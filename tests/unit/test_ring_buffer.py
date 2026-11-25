"""Unit tests for broski AudioRingBuffer."""

import numpy as np

from broski.audio.ring_buffer import AudioRingBuffer


def test_ring_buffer_write_and_read() -> None:
    """Verify basic write and read operations maintain audio data integrity."""
    buffer = AudioRingBuffer(capacity_bytes=1000)

    # Generate 100 samples of 16-bit audio (200 bytes)
    samples = np.array([i * 100 for i in range(100)], dtype=np.int16)
    written = buffer.write(samples)
    assert written == 200
    assert buffer.available_bytes == 200
    assert buffer.available_samples == 100

    # Read back 50 samples (100 bytes)
    read_samples = buffer.read_samples(50)
    assert len(read_samples) == 50
    assert np.array_equal(read_samples, samples[:50])
    assert buffer.available_bytes == 100

    # Read remaining 50 samples
    remaining = buffer.read_samples(50)
    assert np.array_equal(remaining, samples[50:])
    assert buffer.available_bytes == 0


def test_ring_buffer_peek() -> None:
    """Verify peek retrieves data without advancing the read pointer."""
    buffer = AudioRingBuffer(capacity_bytes=500)
    samples = np.array([1, 2, 3, 4, 5], dtype=np.int16)
    buffer.write(samples)

    # Peek 3 samples
    peeked = buffer.peek_samples(3)
    assert len(peeked) == 3
    assert np.array_equal(peeked, np.array([1, 2, 3], dtype=np.int16))
    assert buffer.available_samples == 5  # Still 5 available

    # Read all samples
    read_data = buffer.read_samples(5)
    assert len(read_data) == 5
    assert buffer.available_samples == 0


def test_ring_buffer_overflow_circular() -> None:
    """Verify buffer overwrites oldest data on overflow to preserve freshest audio."""
    # Buffer capacity for 5 samples (10 bytes)
    buffer = AudioRingBuffer(capacity_bytes=10)

    # Write 4 samples: [10, 20, 30, 40]
    buffer.write(np.array([10, 20, 30, 40], dtype=np.int16))
    assert buffer.available_samples == 4

    # Write 3 more samples: [50, 60, 70] (total 7 > capacity 5)
    # Oldest 2 samples (10, 20) should be dropped; buffer should hold [30, 40, 50, 60, 70]
    buffer.write(np.array([50, 60, 70], dtype=np.int16))
    assert buffer.available_samples == 5

    res = buffer.read_samples(5)
    assert np.array_equal(res, np.array([30, 40, 50, 60, 70], dtype=np.int16))


def test_ring_buffer_float32_conversion() -> None:
    """Verify float32 audio arrays in range [-1.0, 1.0] are converted to int16."""
    buffer = AudioRingBuffer(capacity_bytes=100)
    float_audio = np.array([-1.0, 0.0, 0.5, 1.0], dtype=np.float32)
    buffer.write(float_audio)

    int_samples = buffer.read_samples(4)
    assert int_samples[0] <= -32767
    assert int_samples[1] == 0
    assert abs(int_samples[2] - 16383) <= 1
    assert int_samples[3] >= 32767


def test_ring_buffer_clear() -> None:
    """Verify clear resets buffer size and pointers."""
    buffer = AudioRingBuffer(capacity_bytes=500)
    buffer.write(np.array([1, 2, 3], dtype=np.int16))
    assert buffer.available_bytes > 0

    buffer.clear()
    assert buffer.available_bytes == 0
    assert len(buffer.read(100)) == 0


def test_ring_buffer_read_timeout() -> None:
    """Verify read with timeout exits gracefully when empty."""
    buffer = AudioRingBuffer(capacity_bytes=100)
    data = buffer.read(10, timeout=0.05)
    assert data == b""
