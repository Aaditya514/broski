"""Unit tests for the tools registry and 3-tier security confirmation gating."""

from __future__ import annotations

import time
from typing import Any, ClassVar

import pytest

from broski.tools.base import BaseTool, RiskLevel, ToolResult
from broski.tools.registry import ToolRegistry
from broski.tools.security import (
    ConfirmationStatus,
    SecurityConfirmationManager,
)


class DummySafeTool(BaseTool):
    name = "dummy_safe_tool"
    description = "A safe read-only tool."
    risk_level = RiskLevel.SAFE
    parameters_schema: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}, "required": []}

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(success=True, output="safe_output", message="Safe complete.")


class DummyModerateTool(BaseTool):
    name = "dummy_moderate_tool"
    description = "A moderate non-destructive mutating tool."
    risk_level = RiskLevel.MODERATE
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(
            success=True,
            output=f"moderate_{kwargs.get('value')}",
            message="Moderate complete.",
        )


class DummyCriticalTool(BaseTool):
    name = "dummy_critical_tool"
    description = "A critical destructive tool."
    risk_level = RiskLevel.CRITICAL
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"target": {"type": "string"}},
        "required": ["target"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(
            success=True,
            output=f"deleted_{kwargs.get('target')}",
            message="Critical complete.",
        )


# --- SecurityConfirmationManager Tests ---


def test_confirmation_manager_request_lifecycle() -> None:
    """Verify request creation, approval, and query by ID."""
    manager = SecurityConfirmationManager(require_critical=True, timeout_seconds=30)
    req = manager.request_confirmation("delete_file", {"path": "secrets.txt"}, "Sensitive deletion")

    assert req.tool_name == "delete_file"
    assert req.status == ConfirmationStatus.PENDING
    assert req.args == {"path": "secrets.txt"}
    assert not req.is_expired

    fetched = manager.get_request(req.request_id)
    assert fetched is not None
    assert fetched.request_id == req.request_id

    # Approve request
    assert manager.confirm(req.request_id, approved=True) is True
    assert fetched.status == ConfirmationStatus.APPROVED

    # Subsequent confirmation attempts fail
    assert manager.confirm(req.request_id, approved=False) is False


def test_confirmation_manager_deny() -> None:
    """Verify explicit denial of a request."""
    manager = SecurityConfirmationManager()
    req = manager.request_confirmation("kill_process", {"pid": 1234})

    assert manager.confirm(req.request_id, approved=False) is True
    assert req.status == ConfirmationStatus.DENIED


def test_confirmation_manager_timeout_expiration() -> None:
    """Verify timed-out requests automatically transition to EXPIRED."""
    manager = SecurityConfirmationManager(timeout_seconds=0)  # Immediate timeout
    req = manager.request_confirmation("format_disk", {})

    time.sleep(0.01)  # Ensure delta > 0
    assert req.is_expired is True

    fetched = manager.get_request(req.request_id)
    assert fetched is not None
    assert fetched.status == ConfirmationStatus.EXPIRED

    assert len(manager.get_pending_requests()) == 0


def test_confirmation_manager_cleanup() -> None:
    """Verify expired and resolved requests are purged."""
    manager = SecurityConfirmationManager(timeout_seconds=0)
    manager.request_confirmation("action1", {})
    time.sleep(0.01)

    manager2 = SecurityConfirmationManager(timeout_seconds=60)
    req2 = manager2.request_confirmation("action2", {})
    manager2.confirm(req2.request_id, approved=False)  # Denied

    cleaned1 = manager.cleanup_expired()
    assert cleaned1 >= 1

    cleaned2 = manager2.cleanup_expired()
    assert cleaned2 >= 1


# --- ToolRegistry Tests ---


@pytest.mark.asyncio
async def test_registry_safe_and_moderate_auto_execute() -> None:
    """Verify SAFE and MODERATE tools execute without confirmation prompts."""
    registry = ToolRegistry()
    registry.register(DummySafeTool())
    registry.register(DummyModerateTool())

    res_safe = await registry.execute("dummy_safe_tool")
    assert res_safe.success is True
    assert res_safe.output == "safe_output"

    res_mod = await registry.execute("dummy_moderate_tool", {"value": "test"})
    assert res_mod.success is True
    assert res_mod.output == "moderate_test"


@pytest.mark.asyncio
async def test_registry_critical_tool_unconfirmed_blocks() -> None:
    """Verify CRITICAL tool returns pending_confirmation when not confirmed."""
    manager = SecurityConfirmationManager(require_critical=True, timeout_seconds=30)
    registry = ToolRegistry(confirmation_manager=manager)
    registry.register(DummyCriticalTool())

    res = await registry.execute("dummy_critical_tool", {"target": "database.sqlite"})
    assert res.success is False
    assert "pending_confirmation" in res.output.get("status", "")
    assert "critical action" in res.message.lower()

    # Verify confirmation request was registered in manager
    conf_id = res.output["confirmation_id"]
    req = manager.get_request(conf_id)
    assert req is not None
    assert req.tool_name == "dummy_critical_tool"


@pytest.mark.asyncio
async def test_registry_critical_tool_confirmed_executes() -> None:
    """Verify CRITICAL tool executes when confirmed=True."""
    registry = ToolRegistry()
    registry.register(DummyCriticalTool())

    res = await registry.execute(
        "dummy_critical_tool",
        {"target": "temp_dir"},
        confirmed=True,
    )
    assert res.success is True
    assert res.output == "deleted_temp_dir"


@pytest.mark.asyncio
async def test_registry_critical_tool_with_approved_id_executes() -> None:
    """Verify CRITICAL tool executes when valid approved confirmation_id is provided."""
    manager = SecurityConfirmationManager(require_critical=True)
    registry = ToolRegistry(confirmation_manager=manager)
    registry.register(DummyCriticalTool())

    req = manager.request_confirmation("dummy_critical_tool", {"target": "cache"})
    manager.confirm(req.request_id, approved=True)

    res = await registry.execute(
        "dummy_critical_tool",
        {"target": "cache"},
        confirmation_id=req.request_id,
    )
    assert res.success is True
    assert res.output == "deleted_cache"


@pytest.mark.asyncio
async def test_registry_critical_tool_with_denied_id_fails() -> None:
    """Verify CRITICAL tool rejects execution when confirmation_id was denied."""
    manager = SecurityConfirmationManager(require_critical=True)
    registry = ToolRegistry(confirmation_manager=manager)
    registry.register(DummyCriticalTool())

    req = manager.request_confirmation("dummy_critical_tool", {"target": "cache"})
    manager.confirm(req.request_id, approved=False)  # Denied

    res = await registry.execute(
        "dummy_critical_tool",
        {"target": "cache"},
        confirmation_id=req.request_id,
    )
    assert res.success is False
    assert "was not approved" in (res.error or "")


def test_registry_gemini_declarations() -> None:
    """Verify OpenAPI function calling schema generation for Gemini."""
    registry = ToolRegistry()
    registry.register(DummySafeTool())
    registry.register(DummyModerateTool())

    declarations = registry.get_gemini_declarations()
    assert len(declarations) == 2
    names = {d["name"] for d in declarations}
    assert "dummy_safe_tool" in names
    assert "dummy_moderate_tool" in names
