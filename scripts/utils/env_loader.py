"""Environment variable loading utilities."""

import os
from pathlib import Path


def load_env_file(env_file_path: Path) -> dict[str, str]:
    """
    Load environment variables from a .env file.

    Args:
        env_file_path: Path to the .env file

    Returns:
        Dictionary of environment variables
    """
    env_vars: dict[str, str] = {}
    if env_file_path.exists():
        with open(env_file_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")  # Remove quotes
                    env_vars[key] = value
                    os.environ[key] = value  # Also set in current environment
    return env_vars
