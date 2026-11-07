"""
Lightweight error handling utilities for deployment scripts.

Provides essential error handling without heavy ML dependencies.
"""

from datetime import datetime, timezone
from typing import Any


class ScriptError(Exception):
    """Base exception for script errors with user-friendly messages."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.timestamp = datetime.now(timezone.utc)

    def __str__(self) -> str:
        return self.message


class ValidationError(ScriptError):
    """Input validation errors that should not be retried."""

    pass


class ConfigurationError(ScriptError):
    """Configuration-related errors that should not be retried."""

    pass


class PrerequisiteError(ScriptError):
    """Missing prerequisite errors that should not be retried."""

    pass


class ServiceError(ScriptError):
    """Google Cloud service operation errors."""

    pass


class ErrorContext:
    """Context manager for standardized error handling."""

    def __init__(self, operation_name: str) -> None:
        self.operation_name = operation_name

    def __enter__(self) -> "ErrorContext":
        return self

    def __exit__(
        self, exc_type: type[Exception] | None, exc_val: Exception | None, exc_tb: Any
    ) -> None:
        # Let exceptions propagate - this is just for context tracking
        pass


def handle_script_error(error: Exception, context: str) -> str:
    """Handle script errors and return user-friendly message."""
    if isinstance(error, ValidationError | ConfigurationError | PrerequisiteError):
        return str(error)
    elif isinstance(error, ServiceError):
        return f"Google Cloud operation failed in {context}: {error}"
    else:
        return f"Unexpected error in {context}: {error}"
