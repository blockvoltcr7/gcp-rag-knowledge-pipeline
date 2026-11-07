"""
Retry utilities for RAG processor.

Simple retry logic using built-in Python functionality for error recovery
and graceful degradation without external dependencies.
"""

import asyncio
import functools
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import structlog

logger = structlog.get_logger(__name__)

# TypeVar for preserving return types in retry functions
T = TypeVar("T")


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_backoff: bool = True,
        jitter: bool = True,
    ):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_backoff = exponential_backoff
        self.jitter = jitter


class RetryableError(Exception):
    """Base class for errors that should trigger retries."""

    pass


class NonRetryableError(Exception):
    """Base class for errors that should NOT trigger retries."""

    pass


def is_rate_limit_error(exception: Exception) -> bool:
    """
    Check if an exception is due to rate limiting.

    Args:
        exception: The exception to check

    Returns:
        True if the exception indicates rate limiting
    """
    error_msg = str(exception).lower()
    return (
        "429" in error_msg
        or "resource_exhausted" in error_msg
        or "quota" in error_msg
        or "rate limit" in error_msg
        or "too many requests" in error_msg
    )


def create_rate_limit_retry_config() -> RetryConfig:
    """
    Create a retry configuration optimized for rate limiting scenarios.

    Returns:
        RetryConfig with settings appropriate for API rate limits
    """
    from ..config import config

    return RetryConfig(
        max_attempts=config.API_RETRY_MAX_ATTEMPTS,
        base_delay=config.API_RETRY_BASE_DELAY,
        max_delay=300.0,  # Cap at 5 minutes for rate limits
        exponential_backoff=True,
        jitter=True,
    )


class JobCancelledError(NonRetryableError):
    """
    Exception raised when a processing job has been cancelled or deleted.

    This exception is used to signal that a processing job no longer exists
    in the database and processing should be gracefully terminated.
    It inherits from NonRetryableError to prevent retry attempts.
    """

    pass


# Default retry configurations for different operations
DEFAULT_CONFIGS = {
    "gcs_download": RetryConfig(max_attempts=3, base_delay=1.0),
    "database_operation": RetryConfig(max_attempts=3, base_delay=2.0),
    "api_call": RetryConfig(max_attempts=5, base_delay=1.0),
    "transcription": RetryConfig(max_attempts=3, base_delay=5.0),
    "embedding_generation": RetryConfig(max_attempts=3, base_delay=2.0),
}


def calculate_delay(attempt: int, config: RetryConfig) -> float:
    """Calculate delay for retry attempt."""
    if config.exponential_backoff:
        delay: float = config.base_delay * (2 ** (attempt - 1))
    else:
        delay = config.base_delay

    delay = min(delay, config.max_delay)

    if config.jitter:
        jitter_factor: float = 0.5 + random.random() * 0.5  # Add ±50% jitter
        delay *= jitter_factor

    return delay


async def retry_async(
    func: Callable[[], Awaitable[T]],
    config: RetryConfig | None = None,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    non_retryable_exceptions: tuple[type[Exception], ...] = (NonRetryableError,),
    operation_name: str = "operation",
) -> T:
    """
    Retry an async function with configurable backoff.

    Args:
        func: Async function to retry
        config: Retry configuration
        retryable_exceptions: Tuple of exception types that should trigger retries
        non_retryable_exceptions: Tuple of exception types that should NOT trigger retries
        operation_name: Name of operation for logging

    Returns:
        Result of the function call

    Raises:
        Last exception if all retries are exhausted
    """
    if config is None:
        config = RetryConfig()

    last_exception = None

    for attempt in range(1, config.max_attempts + 1):
        try:
            logger.debug(
                "Attempting operation",
                operation=operation_name,
                attempt=attempt,
                max_attempts=config.max_attempts,
            )

            result = await func()

            if attempt > 1:
                logger.info(
                    "Operation succeeded after retry",
                    operation=operation_name,
                    attempt=attempt,
                    total_attempts=config.max_attempts,
                )

            return result

        except non_retryable_exceptions as e:
            logger.error(
                "Operation failed with non-retryable error",
                operation=operation_name,
                attempt=attempt,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise e

        except retryable_exceptions as e:
            last_exception = e

            logger.warning(
                "Operation failed, will retry",
                operation=operation_name,
                attempt=attempt,
                max_attempts=config.max_attempts,
                error=str(e),
                error_type=type(e).__name__,
            )

            if attempt < config.max_attempts:
                delay = calculate_delay(attempt, config)
                logger.debug(
                    "Waiting before retry",
                    operation=operation_name,
                    delay_seconds=delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "Operation failed after all retries exhausted",
                    operation=operation_name,
                    total_attempts=config.max_attempts,
                    final_error=str(e),
                    error_type=type(e).__name__,
                )

    # This should never happen, but just in case
    if last_exception is None:
        raise RuntimeError(
            f"Operation '{operation_name}' failed after {config.max_attempts} attempts with no recorded exception"
        )

    raise last_exception


def retry_sync(
    func: Callable,
    config: RetryConfig | None = None,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    non_retryable_exceptions: tuple[type[Exception], ...] = (NonRetryableError,),
    operation_name: str = "operation",
) -> Any:
    """
    Retry a synchronous function with configurable backoff.

    Args:
        func: Synchronous function to retry
        config: Retry configuration
        retryable_exceptions: Tuple of exception types that should trigger retries
        non_retryable_exceptions: Tuple of exception types that should NOT trigger retries
        operation_name: Name of operation for logging

    Returns:
        Result of the function call

    Raises:
        Last exception if all retries are exhausted
    """
    if config is None:
        config = RetryConfig()

    last_exception = None

    for attempt in range(1, config.max_attempts + 1):
        try:
            logger.debug(
                "Attempting operation",
                operation=operation_name,
                attempt=attempt,
                max_attempts=config.max_attempts,
            )

            result = func()

            if attempt > 1:
                logger.info(
                    "Operation succeeded after retry",
                    operation=operation_name,
                    attempt=attempt,
                    total_attempts=config.max_attempts,
                )

            return result

        except non_retryable_exceptions as e:
            logger.error(
                "Operation failed with non-retryable error",
                operation=operation_name,
                attempt=attempt,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise e

        except retryable_exceptions as e:
            last_exception = e

            logger.warning(
                "Operation failed, will retry",
                operation=operation_name,
                attempt=attempt,
                max_attempts=config.max_attempts,
                error=str(e),
                error_type=type(e).__name__,
            )

            if attempt < config.max_attempts:
                delay = calculate_delay(attempt, config)
                logger.debug(
                    "Waiting before retry",
                    operation=operation_name,
                    delay_seconds=delay,
                )
                time.sleep(delay)
            else:
                logger.error(
                    "Operation failed after all retries exhausted",
                    operation=operation_name,
                    total_attempts=config.max_attempts,
                    final_error=str(e),
                    error_type=type(e).__name__,
                )

    # This should never happen, but just in case
    if last_exception is None:
        raise RuntimeError(
            f"Operation '{operation_name}' failed after {config.max_attempts} attempts with no recorded exception"
        )

    raise last_exception


def with_retry(
    config: RetryConfig | None = None,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    non_retryable_exceptions: tuple[type[Exception], ...] = (NonRetryableError,),
    operation_name: str | None = None,
) -> Callable:
    """
    Decorator for adding retry logic to async functions.

    Args:
        config: Retry configuration
        retryable_exceptions: Tuple of exception types that should trigger retries
        non_retryable_exceptions: Tuple of exception types that should NOT trigger retries
        operation_name: Name of operation for logging (defaults to function name)
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            nonlocal operation_name
            if operation_name is None:
                operation_name = func.__name__

            async def call_func() -> Any:
                return await func(*args, **kwargs)

            return await retry_async(
                call_func,
                config=config,
                retryable_exceptions=retryable_exceptions,
                non_retryable_exceptions=non_retryable_exceptions,
                operation_name=operation_name,
            )

        return wrapper

    return decorator


# Common error classification functions
def is_retryable_genai_error(error: Exception) -> bool:
    """Check if a GenAI API error should trigger a retry."""
    error_str = str(error).lower()

    # Non-retryable conditions (authentication, authorization, quota, etc.)
    non_retryable_patterns = [
        "api key not valid",
        "invalid_argument",
        "invalid api key",
        "authentication",
        "authorization",
        "permission denied",
        "quota exceeded",
        "resource_exhausted",
        "400",  # Bad Request
        "401",  # Unauthorized
        "403",  # Forbidden
        "404",  # Not Found
    ]

    # If it matches non-retryable patterns, don't retry
    if any(pattern in error_str for pattern in non_retryable_patterns):
        return False

    # Retryable conditions (temporary issues)
    retryable_patterns = [
        "timeout",
        "connection",
        "network",
        "temporary",
        "rate limit",
        "429",  # Too Many Requests
        "503",  # Service Unavailable
        "502",  # Bad Gateway
        "500",  # Internal Server Error
    ]

    return any(pattern in error_str for pattern in retryable_patterns)


def is_retryable_gcs_error(error: Exception) -> bool:
    """Check if a GCS error should trigger a retry."""
    error_str = str(error).lower()

    # Retryable conditions
    retryable_patterns = [
        "timeout",
        "connection",
        "network",
        "temporary",
        "rate limit",
        "429",  # Too Many Requests
        "503",  # Service Unavailable
        "502",  # Bad Gateway
        "500",  # Internal Server Error
    ]

    return any(pattern in error_str for pattern in retryable_patterns)


def is_retryable_database_error(error: Exception) -> bool:
    """Check if a database error should trigger a retry."""
    error_str = str(error).lower()

    # Retryable conditions
    retryable_patterns = [
        "connection",
        "timeout",
        "temporary",
        "deadlock",
        "lock",
        "busy",
    ]

    return any(pattern in error_str for pattern in retryable_patterns)


def is_retryable_api_error(error: Exception) -> bool:
    """Check if an API error should trigger a retry."""
    error_str = str(error).lower()

    # Retryable conditions
    retryable_patterns = [
        "timeout",
        "connection",
        "network",
        "rate limit",
        "429",  # Too Many Requests
        "503",  # Service Unavailable
        "502",  # Bad Gateway
        "500",  # Internal Server Error
    ]

    return any(pattern in error_str for pattern in retryable_patterns)


# Convenience functions for common operations
async def retry_gcs_operation(
    func: Callable[[], Awaitable[T]], operation_name: str = "gcs_operation"
) -> T:
    """Retry a GCS operation with appropriate configuration."""

    # Create a wrapper function to use with retry_async
    async def _wrapped_func() -> T:
        try:
            return await func()
        except Exception as e:
            # If it's a retryable GCS error, convert to RetryableError
            if is_retryable_gcs_error(e):
                raise RetryableError(str(e)) from e
            else:
                # For non-retryable errors, convert to NonRetryableError
                raise NonRetryableError(str(e)) from e

    # Use the existing retry_async function for proper type inference
    return await retry_async(
        func=_wrapped_func,
        config=DEFAULT_CONFIGS["gcs_download"],
        retryable_exceptions=(RetryableError,),
        non_retryable_exceptions=(NonRetryableError,),
        operation_name=operation_name,
    )


async def retry_database_operation(
    func: Callable[[], Awaitable[T]], operation_name: str = "database_operation"
) -> T:
    """Retry a database operation with appropriate configuration."""

    # Create a wrapper function to use with retry_async
    async def _wrapped_func() -> T:
        try:
            return await func()
        except Exception as e:
            # If it's a retryable database error, convert to RetryableError
            if is_retryable_database_error(e):
                raise RetryableError(str(e)) from e
            else:
                # For non-retryable errors, convert to NonRetryableError
                raise NonRetryableError(str(e)) from e

    # Use the existing retry_async function for proper type inference
    return await retry_async(
        func=_wrapped_func,
        config=DEFAULT_CONFIGS["database_operation"],
        retryable_exceptions=(RetryableError,),
        non_retryable_exceptions=(NonRetryableError,),
        operation_name=operation_name,
    )


async def retry_genai_operation(
    func: Callable[[], Awaitable[T]], operation_name: str = "genai_operation"
) -> T:
    """Retry a GenAI API operation with appropriate configuration."""

    # Create a wrapper function to use with retry_async
    async def _wrapped_func() -> T:
        try:
            return await func()
        except Exception as e:
            # If it's a retryable GenAI error, convert to RetryableError
            if is_retryable_genai_error(e):
                raise RetryableError(str(e)) from e
            else:
                # For non-retryable errors, convert to NonRetryableError
                raise NonRetryableError(str(e)) from e

    # Use the existing retry_async function for proper type inference
    return await retry_async(
        func=_wrapped_func,
        config=DEFAULT_CONFIGS["api_call"],
        retryable_exceptions=(RetryableError,),
        non_retryable_exceptions=(NonRetryableError,),
        operation_name=operation_name,
    )
