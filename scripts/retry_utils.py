"""
Lightweight retry utilities for deployment scripts.

Provides essential retry functionality without heavy ML dependencies.
"""

import time
from collections.abc import Callable
from typing import Any, TypedDict


class RetryConfig(TypedDict):
    """Configuration for retry operations."""

    max_attempts: int
    base_delay: float
    max_delay: float
    exponential_backoff: bool
    jitter: bool


class RetryableError(Exception):
    """Base class for errors that should be retried."""

    pass


class NonRetryableError(Exception):
    """Base class for errors that should not be retried."""

    pass


def retry_sync(
    operation: Callable[[], Any],
    config: RetryConfig,
    retryable_exceptions: tuple[type[Exception], ...],
    operation_name: str,
) -> Any:
    """Execute operation with retry logic."""
    last_exception = None

    for attempt in range(config["max_attempts"]):
        try:
            return operation()
        except retryable_exceptions as e:
            last_exception = e
            if attempt < config["max_attempts"] - 1:
                delay = config["base_delay"]
                if config["exponential_backoff"]:
                    delay *= 2**attempt
                delay = min(delay, config["max_delay"])

                if config["jitter"]:
                    import random

                    delay *= 0.5 + random.random() * 0.5

                time.sleep(delay)
                continue
            else:
                break
        except Exception:
            # Non-retryable exception - re-raise immediately
            raise

    # All retries exhausted
    if last_exception:
        raise last_exception
    else:
        raise RuntimeError(
            f"Operation '{operation_name}' failed after {config['max_attempts']} attempts"
        )
