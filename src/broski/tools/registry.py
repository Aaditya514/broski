"""Central registry and dispatch engine for broski tools."""

from __future__ import annotations

import logging
from typing import Any

from broski.tools.base import BaseTool, RiskLevel, ToolResult
from broski.tools.security import ConfirmationStatus, SecurityConfirmationManager

logger = logging.getLogger("broski.tools.registry")


class ToolRegistry:
    """Registry maintaining active tools and enforcing risk-level gating before dispatch."""

    def __init__(self, confirmation_manager: SecurityConfirmationManager | None = None) -> None:
        self._tools: dict[str, BaseTool] = {}
        self.confirmation_manager = confirmation_manager or SecurityConfirmationManager()

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance in the registry."""
        if tool.name in self._tools:
            logger.warning("Overwriting previously registered tool: %s", tool.name)
        self._tools[tool.name] = tool
        logger.debug("Registered tool '%s' with risk level '%s'", tool.name, tool.risk_level.value)

    def get(self, name: str) -> BaseTool | None:
        """Retrieve a registered tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def get_gemini_declarations(self) -> list[dict[str, Any]]:
        """Return OpenAPI/Gemini function calling schema declarations for all registered tools."""
        return [tool.to_gemini_declaration() for tool in self._tools.values()]

    async def execute(
        self,
        tool_name: str,
        args: dict[str, Any] | None = None,
        *,
        confirmed: bool = False,
        confirmation_id: str | None = None,
    ) -> ToolResult:
        """Dispatch and execute a tool with 3-tier risk gating.

        Args:
            tool_name: Registered name of the tool.
            args: Keyword arguments for tool execution.
            confirmed: Whether the caller explicitly pre-confirmed this critical execution.
            confirmation_id: Optional ID of an existing approved confirmation request.
        """
        tool_args = args or {}
        tool = self.get(tool_name)
        if not tool:
            logger.error("Attempted to execute unregistered tool: '%s'", tool_name)
            return ToolResult(
                success=False,
                error=f"Tool '{tool_name}' is not registered.",
                message=f"I couldn't find a tool called '{tool_name}' in my registry, bro.",
            )

        # 3-Tier Security Gating for CRITICAL operations
        if tool.risk_level == RiskLevel.CRITICAL and self.confirmation_manager.require_critical:
            # Check if valid pre-approval exists via confirmation_id
            if confirmation_id:
                req = self.confirmation_manager.get_request(confirmation_id)
                if not req or req.status != ConfirmationStatus.APPROVED:
                    return ToolResult(
                        success=False,
                        error=f"Confirmation '{confirmation_id}' was not approved or has expired.",
                        message="That action was not confirmed or expired, bro. Aborted.",
                    )
            elif not confirmed:
                # Need to request confirmation
                req = self.confirmation_manager.request_confirmation(
                    tool_name=tool.name,
                    args=tool_args,
                    reason=f"Action '{tool.name}' is categorized as CRITICAL.",
                )
                return ToolResult(
                    success=False,
                    output={"confirmation_id": req.request_id, "status": "pending_confirmation"},
                    error="Confirmation required",
                    message=(
                        f"Yo bro, '{tool.name}' is a critical action. "
                        f"Say 'confirm' or approve request [{req.request_id}] to run it."
                    ),
                )

        # Execute tool
        try:
            logger.info("Executing tool '%s' with args %s", tool.name, tool_args)
            result = await tool.execute(**tool_args)
            return result
        except Exception as exc:
            logger.exception("Error executing tool '%s'", tool.name)
            return ToolResult(
                success=False,
                error=str(exc),
                message=f"Sorry bro, running '{tool.name}' ran into an error: {exc}",
            )
