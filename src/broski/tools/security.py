"""Security confirmation manager and gating for critical system tools.

Enforces 3-tier risk gating:
- SAFE: Auto-executed.
- MODERATE: Executed with affirmation.
- CRITICAL: Requires explicit user approval before execution.
"""

from __future__ import annotations

import logging
import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("broski.tools.security")


class ConfirmationStatus(str, Enum):
    """Lifecycle state of a security confirmation request."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


class ConfirmationRequest(BaseModel):
    """Request for explicit user authorization before running a CRITICAL tool."""

    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(default="This tool performs potentially destructive or permanent changes.")
    status: ConfirmationStatus = ConfirmationStatus.PENDING
    created_at: float = Field(default_factory=time.time)
    timeout_seconds: int = 30

    @property
    def is_expired(self) -> bool:
        """Check whether the confirmation request has exceeded its timeout."""
        return (time.time() - self.created_at) > self.timeout_seconds


class SecurityConfirmationManager:
    """Tracks and resolves confirmation requests for critical operations."""

    def __init__(self, require_critical: bool = True, timeout_seconds: int = 30) -> None:
        self.require_critical = require_critical
        self.timeout_seconds = timeout_seconds
        self._requests: dict[str, ConfirmationRequest] = {}

    def request_confirmation(
        self,
        tool_name: str,
        args: dict[str, Any],
        reason: str | None = None,
    ) -> ConfirmationRequest:
        """Create and register a pending confirmation request."""
        req_reason = reason or f"Executing '{tool_name}' requires explicit user authorization."
        req = ConfirmationRequest(
            tool_name=tool_name,
            args=args,
            reason=req_reason,
            timeout_seconds=self.timeout_seconds,
        )
        self._requests[req.request_id] = req
        logger.warning(
            "Security Confirmation Requested: [%s] Tool: %s (Args: %s) Reason: %s",
            req.request_id,
            tool_name,
            args,
            req_reason,
        )
        return req

    def get_request(self, request_id: str) -> ConfirmationRequest | None:
        """Retrieve confirmation request by ID, marking expired if timed out."""
        req = self._requests.get(request_id)
        if req and req.status == ConfirmationStatus.PENDING and req.is_expired:
            req.status = ConfirmationStatus.EXPIRED
        return req

    def get_pending_requests(self) -> list[ConfirmationRequest]:
        """List all unexpired pending confirmation requests."""
        now = time.time()
        pending: list[ConfirmationRequest] = []
        for req in self._requests.values():
            if req.status == ConfirmationStatus.PENDING:
                if (now - req.created_at) > req.timeout_seconds:
                    req.status = ConfirmationStatus.EXPIRED
                else:
                    pending.append(req)
        return pending

    def confirm(self, request_id: str, approved: bool) -> bool:
        """Authorize or reject a pending request. Returns True if status changed."""
        req = self.get_request(request_id)
        if not req:
            logger.warning("Confirmation request '%s' not found.", request_id)
            return False

        if req.status != ConfirmationStatus.PENDING:
            logger.warning("Confirmation request '%s' is already %s.", request_id, req.status.value)
            return False

        req.status = ConfirmationStatus.APPROVED if approved else ConfirmationStatus.DENIED
        logger.info(
            "Confirmation request '%s' %s by user.",
            request_id,
            "APPROVED" if approved else "DENIED",
        )
        return True

    def cleanup_expired(self) -> int:
        """Purge expired requests from memory."""
        now = time.time()
        expired_ids = [
            req_id
            for req_id, req in self._requests.items()
            if req.status in (ConfirmationStatus.EXPIRED, ConfirmationStatus.DENIED)
            or (req.status == ConfirmationStatus.PENDING and (now - req.created_at) > req.timeout_seconds)
        ]
        for req_id in expired_ids:
            del self._requests[req_id]
        return len(expired_ids)
