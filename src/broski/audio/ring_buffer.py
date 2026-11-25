"""Thread-safe circular audio ring buffer for real-time audio streams.

Allows continuous streaming audio from PortAudio/sounddevice callbacks
to be consumed by VAD, wake word, and speech-to-text models without
dropping frames or allocating memory in the audio thread.
"""

import threading

import numpy as np


class AudioRingBuffer:
    """Thread-safe circular ring buffer for 16-bit mono PCM audio (16,000 Hz)."""

    def __init__(
        self,
        capacity_bytes: int = 320_000,  # 10 seconds of 16kHz 16-bit mono PCM (16000 * 2 * 10)
        sample_rate: int = 16000,
        channels: int = 1,
    ) -> None:
        self.capacity_bytes = capacity_bytes
        self.sample_rate = sample_rate
        self.channels = channels
        self.bytes_per_sample = 2  # 16-bit PCM = 2 bytes per sample

        # Pre-allocated circular storage
        self._buffer = bytearray(capacity_bytes)
        self._write_pos = 0
        self._read_pos = 0
        self._size = 0  # Number of unread bytes currently in buffer

        self._lock = threading.Lock()
        self._data_available = threading.Condition(self._lock)

    @property
    def available_bytes(self) -> int:
        """Return the number of unread bytes currently available."""
        with self._lock:
            return self._size

    @property
    def available_samples(self) -> int:
        """Return the number of unread audio samples available."""
        with self._lock:
            return self._size // self.bytes_per_sample

    def write(self, data: bytes | bytearray | np.ndarray) -> int:
        """Write incoming audio data into the circular ring buffer.

        If incoming data exceeds remaining capacity, overwrites oldest data
        so real-time consumers always have the freshest speech audio.
        """
        if isinstance(data, np.ndarray):
            if data.dtype != np.int16:
                # Convert float32 [-1.0, 1.0] to int16 [-32768, 32767]
                if np.issubdtype(data.dtype, np.floating):
                    data = np.clip(data, -1.0, 1.0)
                    data = (data * 32767.0).astype(np.int16)
                else:
                    data = data.astype(np.int16)
            raw_bytes = data.tobytes()
        else:
            raw_bytes = bytes(data)

        num_bytes = len(raw_bytes)
        if num_bytes == 0:
            return 0

        with self._lock:
            # If incoming data is larger than whole buffer, keep only newest slice
            if num_bytes >= self.capacity_bytes:
                raw_bytes = raw_bytes[-self.capacity_bytes :]
                num_bytes = len(raw_bytes)
                self._buffer[:] = raw_bytes
                self._write_pos = 0
                self._read_pos = 0
                self._size = self.capacity_bytes
                self._data_available.notify_all()
                return num_bytes

            # Check if writing will overwrite unread bytes
            free_space = self.capacity_bytes - self._size
            if num_bytes > free_space:
                # Advance read position to drop oldest unread bytes
                overflow = num_bytes - free_space
                self._read_pos = (self._read_pos + overflow) % self.capacity_bytes
                self._size -= overflow

            # Copy raw_bytes into circular buffer (handling wrap-around)
            end_space = self.capacity_bytes - self._write_pos
            if num_bytes <= end_space:
                self._buffer[self._write_pos : self._write_pos + num_bytes] = raw_bytes
            else:
                self._buffer[self._write_pos :] = raw_bytes[:end_space]
                self._buffer[: num_bytes - end_space] = raw_bytes[end_space:]

            self._write_pos = (self._write_pos + num_bytes) % self.capacity_bytes
            self._size += num_bytes
            self._data_available.notify_all()
            return num_bytes

    def read(self, num_bytes: int, timeout: float | None = None) -> bytes:
        """Read and remove up to `num_bytes` from the buffer.

        If buffer has fewer bytes than requested, waits up to `timeout` seconds.
        """
        with self._data_available:
            if timeout is not None and self._size < num_bytes:
                self._data_available.wait_for(lambda: self._size >= num_bytes, timeout=timeout)

            to_read = min(num_bytes, self._size)
            if to_read == 0:
                return b""

            end_space = self.capacity_bytes - self._read_pos
            if to_read <= end_space:
                data = bytes(self._buffer[self._read_pos : self._read_pos + to_read])
            else:
                part1 = self._buffer[self._read_pos :]
                part2 = self._buffer[: to_read - end_space]
                data = bytes(part1 + part2)

            self._read_pos = (self._read_pos + to_read) % self.capacity_bytes
            self._size -= to_read
            return data

    def peek(self, num_bytes: int) -> bytes:
        """Read up to `num_bytes` without advancing the read position."""
        with self._lock:
            to_peek = min(num_bytes, self._size)
            if to_peek == 0:
                return b""

            end_space = self.capacity_bytes - self._read_pos
            if to_peek <= end_space:
                return bytes(self._buffer[self._read_pos : self._read_pos + to_peek])
            else:
                part1 = self._buffer[self._read_pos :]
                part2 = self._buffer[: to_peek - end_space]
                return bytes(part1 + part2)

    def read_samples(self, num_samples: int, timeout: float | None = None) -> np.ndarray:
        """Read up to `num_samples` as a numpy int16 array."""
        num_bytes = num_samples * self.bytes_per_sample
        raw_bytes = self.read(num_bytes, timeout=timeout)
        if not raw_bytes:
            return np.empty(0, dtype=np.int16)
        return np.frombuffer(raw_bytes, dtype=np.int16)

    def peek_samples(self, num_samples: int) -> np.ndarray:
        """Peek up to `num_samples` as a numpy int16 array without advancing."""
        num_bytes = num_samples * self.bytes_per_sample
        raw_bytes = self.peek(num_bytes)
        if not raw_bytes:
            return np.empty(0, dtype=np.int16)
        return np.frombuffer(raw_bytes, dtype=np.int16)

    def clear(self) -> None:
        """Reset the buffer pointers and discard all unread data."""
        with self._lock:
            self._write_pos = 0
            self._read_pos = 0
            self._size = 0
