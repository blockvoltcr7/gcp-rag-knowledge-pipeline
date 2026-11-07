"""
Logging configuration utilities for RAG processor.

Provides structured logging setup for production deployment.
"""

import logging
import os

import structlog

from ..config import config


def _is_cloud_environment() -> bool:
    """
    Detect if running in a cloud environment where colors should be disabled.

    Returns:
        True if running in cloud environment, False otherwise
    """
    # Cloud Run environment variables (Jobs and Services)
    if os.getenv("K_SERVICE") or os.getenv("CLOUD_RUN_SERVICE"):
        return True

    # Cloud Run Jobs specifically
    if os.getenv("CLOUD_RUN_JOB") or os.getenv("CLOUD_RUN_TASK_INDEX"):
        return True

    # Additional Cloud Run detection
    if os.getenv("K_CONFIGURATION") or os.getenv("K_REVISION"):
        return True

    # Google App Engine
    if os.getenv("GAE_ENV"):
        return True

    # Google Cloud Functions
    if os.getenv("FUNCTION_NAME") or os.getenv("FUNCTION_TARGET"):
        return True

    # Other cloud platforms
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):  # AWS Lambda
        return True

    if os.getenv("AZURE_FUNCTIONS_ENVIRONMENT"):  # Azure Functions
        return True

    return False


def setup_logging() -> None:
    """Configure structured logging for production."""
    # Check environment states
    is_cloud = _is_cloud_environment()
    is_prod = config.is_production()

    # Allow explicit override via environment variable
    force_json = os.getenv("FORCE_JSON_LOGGING", "").lower() in ("true", "1", "yes")

    # Additional fallback detection for any Google Cloud environment
    # Check for any environment variable starting with GOOGLE_, K_, or CLOUD_
    google_cloud_indicators = [
        key
        for key in os.environ.keys()
        if key.startswith(("GOOGLE_", "K_", "CLOUD_", "GCP_"))
    ]
    has_gcp_env_vars = len(google_cloud_indicators) > 0

    # Force JSON logging in cloud environments to prevent ANSI escape codes
    # Cloud environments don't support terminal colors and they show as raw escape codes
    use_json_logging = force_json or is_cloud or is_prod or has_gcp_env_vars

    # Choose the appropriate renderer
    renderer: structlog.processors.JSONRenderer | structlog.dev.ConsoleRenderer
    if use_json_logging:
        renderer = structlog.processors.JSONRenderer()
    else:
        # Only use colors for local development
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            min_level=getattr(logging, str(config.LOG_LEVEL).upper(), logging.INFO)
        ),
        logger_factory=structlog.WriteLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logger = structlog.get_logger(__name__)
    logger.info(
        "Logging configured",
        environment=config.ENVIRONMENT,
        log_level=config.LOG_LEVEL,
        is_production=is_prod,
        is_cloud_environment=is_cloud,
        force_json_override=force_json,
        has_gcp_env_vars=has_gcp_env_vars,
        gcp_env_var_count=len(google_cloud_indicators),
        json_logging_enabled=use_json_logging,
        renderer_type="JSONRenderer" if use_json_logging else "ConsoleRenderer",
    )
