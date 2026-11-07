"""
Lightweight validation utilities for deployment scripts.

Provides essential validation functions without heavy ML dependencies.
"""

import re
import urllib.parse
from typing import Any

# Input validation patterns
GCP_PROJECT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
GCS_BUCKET_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-_.]{1,61}[a-z0-9]$")

# Valid GCP regions
VALID_GCP_REGIONS = {
    # Americas
    "us-central1",
    "us-east1",
    "us-east4",
    "us-west1",
    "us-west2",
    "us-west3",
    "us-west4",
    "northamerica-northeast1",
    "northamerica-northeast2",
    "southamerica-east1",
    # Europe
    "europe-central2",
    "europe-north1",
    "europe-west1",
    "europe-west2",
    "europe-west3",
    "europe-west4",
    "europe-west6",
    "europe-west8",
    "europe-west9",
    # Asia Pacific
    "asia-east1",
    "asia-east2",
    "asia-northeast1",
    "asia-northeast2",
    "asia-northeast3",
    "asia-south1",
    "asia-south2",
    "asia-southeast1",
    "asia-southeast2",
    "australia-southeast1",
    "australia-southeast2",
}


def validate_gcp_project_id(project_id: str) -> bool:
    """Validate GCP project ID format."""
    if not project_id:
        return False
    return bool(GCP_PROJECT_ID_PATTERN.match(project_id))


def validate_gcp_project_id_strict(project_id: str) -> None:
    """Validate GCP project ID format with exception on failure."""
    if not validate_gcp_project_id(project_id):
        raise ValueError(
            f"Invalid GCP project ID: '{project_id}'. "
            f"Project IDs must be 6-30 characters, start with a letter, "
            f"and contain only lowercase letters, numbers, and hyphens."
        )


def validate_gcp_region(region: str) -> bool:
    """Validate GCP region name."""
    return region in VALID_GCP_REGIONS


def validate_gcs_bucket_name_strict(bucket_name: str) -> None:
    """Validate GCS bucket name format with exception on failure."""
    if not bucket_name:
        raise ValueError("Bucket name cannot be empty")

    if not GCS_BUCKET_NAME_PATTERN.match(bucket_name):
        raise ValueError(
            f"Invalid GCS bucket name: '{bucket_name}'. "
            f"Bucket names must be 3-63 characters, start and end with alphanumeric, "
            f"and contain only lowercase letters, numbers, hyphens, periods, and underscores."
        )


def validate_database_url(database_url: str) -> bool:
    """Validate database URL format."""
    if not database_url:
        return False

    try:
        parsed = urllib.parse.urlparse(database_url)
        return (
            parsed.scheme in ("postgresql", "postgres")
            and bool(parsed.hostname)
            and bool(parsed.username)
        )
    except Exception:
        return False


def validate_required_fields(
    config: dict[str, Any], required_fields: list[str]
) -> list[str]:
    """Validate that all required fields are present and non-empty."""
    missing_fields = []
    for field in required_fields:
        value = config.get(field)
        if not value or (isinstance(value, str) and not value.strip()):
            missing_fields.append(field)
    return missing_fields


def validate_environment_name(environment: str) -> bool:
    """Validate environment name."""
    return environment in ("development", "production", "staging")


def validate_memory_specification(memory: str) -> bool:
    """Validate memory specification format."""
    if not memory:
        return False
    return memory.endswith(("Mi", "Gi")) and memory[:-2].isdigit()


def validate_timeout_seconds(timeout: int) -> bool:
    """Validate timeout value."""
    return 1 <= timeout <= 7200  # 1 second to 2 hours


def validate_cpu_count(cpu: int) -> bool:
    """Validate CPU count."""
    return cpu in (1, 2, 4, 6, 8)


def validate_and_raise(condition: bool, message: str) -> None:
    """Validate condition and raise ValueError if false."""
    if not condition:
        raise ValueError(message)


def validate_gcs_bucket_name(bucket_name: str) -> bool:
    """Validate GCS bucket name format."""
    if not bucket_name:
        return False
    return bool(GCS_BUCKET_NAME_PATTERN.match(bucket_name))


def validate_api_key(api_key: str) -> bool:
    """Validate API key format."""
    if not api_key:
        return False
    return len(api_key) >= 32 and api_key.replace("-", "").replace("_", "").isalnum()
