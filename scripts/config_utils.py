"""
Lightweight configuration utilities for deployment scripts.

Provides essential configuration functions without heavy ML dependencies.
"""

import os
from typing import Any


def get_config_value(key: str, default: Any = None) -> Any:
    """Get configuration value from environment variables."""
    return os.getenv(key, default)


def get_env_var(key: str, default: str = "") -> str:
    """Get environment variable as string."""
    return os.getenv(key, default)
