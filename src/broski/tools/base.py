"""Base interfaces and risk-level categorization for broski desktop tools.

Adheres to the core safety architecture: 'No unrestricted LLM-generated terminal execution'.
Every tool explicitly declares its RiskLevel and parameters schema.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, ClassVar

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    """Categorized risk tiers for tool execution.
    
    SAFE:
        Read-only inspection (note reading, search, git status, active window inspection).
        Automatically permitted without interrupting the user.
    MODERATE:
        Non-destructive or safe mutation (appending to daily notes, launching approved apps,
        copying to clipboard). Allowed with logging and conversational affirmation.
    CRITICAL:
        Destructive or system-modifying actions (deleting files, git commit/push, running
        system commands, killing processes, submitting browser forms).
        STRICTLY requires explicit user confirmation before execution.
    """

    SAFE = "safe"
    MODERATE = "moderate"
    CRITICAL = "critical"


class ToolResult(BaseModel):
    """Normalized structured result returned by all tools."""

    success: bool = Field(description="Whether the tool executed without error.")
    output: Any = Field(default=None, description="Structured payload or data produced by the tool.")
    error: str | None = Field(default=None, description="Error message if execution failed.")
    message: str = Field(
        default="",
        description="Conversational, speech-friendly summary of the outcome for Piper TTS.",
    )


class BaseTool(ABC):
    """Abstract base class for all callable tools in broski."""

    name: str
    description: str
    risk_level: RiskLevel = RiskLevel.SAFE
    parameters_schema: ClassVar[dict[str, Any]]

    def to_gemini_declaration(self) -> dict[str, Any]:
        """Export tool metadata in OpenAPI / Gemini function declaration format."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters_schema,
        }

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool asynchronously with validated arguments."""
        raise NotImplementedError
