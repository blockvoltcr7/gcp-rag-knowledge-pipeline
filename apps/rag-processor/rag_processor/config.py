"""
Configuration settings for the RAG processor service.
"""

import os
from typing import Any

from .utils.retry_utils import NonRetryableError


class Config:
    """Configuration settings for the RAG Processor service.

    This service handles document processing with ML models.
    The queue handler is a separate Cloud Function (not part of this service).

    Processor Service Environment Variables:
    - DOCLING_ARTIFACTS_PATH: Path for document processing artifacts

    Shared Environment Variables:
    - DATABASE_URL: PostgreSQL connection string
    - GEMINI_API_KEY: Google AI API key
    - GOOGLE_CLOUD_PROJECT_ID: Google Cloud project ID
    - GOOGLE_CLOUD_STORAGE_BUCKET: GCS bucket for document storage
    """

    # Google Cloud settings
    GOOGLE_CLOUD_PROJECT_ID: str | None = os.getenv(
        "GOOGLE_CLOUD_PROJECT_ID"
    )  # Required - no default
    GOOGLE_CLOUD_REGION: str = os.getenv("GOOGLE_CLOUD_REGION", "us-central1")
    GOOGLE_CLOUD_STORAGE_BUCKET: str = os.getenv("GOOGLE_CLOUD_STORAGE_BUCKET", "")

    # Aliases for consistency with vertexai.init()
    PROJECT_ID: str | None = GOOGLE_CLOUD_PROJECT_ID
    VERTEX_AI_LOCATION: str = GOOGLE_CLOUD_REGION

    # Server settings
    PORT: int = int(os.getenv("PORT", "8080"))
    HOST: str = os.getenv("HOST", "0.0.0.0")

    # Document processing settings
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200

    # LlamaIndex document processor settings
    DOCUMENT_PROCESSOR: str = os.getenv("DOCUMENT_PROCESSOR", "llamaindex")
    USE_LLAMAPARSE: bool = os.getenv("USE_LLAMAPARSE", "false").lower() == "true"
    LLAMAPARSE_API_KEY: str | None = os.getenv("LLAMAPARSE_API_KEY")
    LLAMAINDEX_FALLBACK_ENABLED: bool = (
        os.getenv("LLAMAINDEX_FALLBACK_ENABLED", "true").lower() == "true"
    )

    # AI/ML settings for text embeddings (Gemini)
    TEXT_EMBEDDING_MODEL: str = "gemini-embedding-001"
    TEXT_EMBEDDING_DIMENSIONS: int = 3072

    # AI/ML settings for multimodal embeddings
    MULTIMODAL_EMBEDDING_MODEL: str = "multimodalembedding@001"
    MULTIMODAL_EMBEDDING_DIMENSIONS: int = 1408

    # Video processing settings
    VIDEO_CHUNK_DURATION_SECONDS: int = 15  # Duration of each video chunk
    VIDEO_CONTEXT_MAX_BYTES: int = 1023  # Maximum bytes for context field
    VIDEO_DEFAULT_LANGUAGE: str = "en-US"  # Default language for transcription
    VIDEO_PROCESSING_BATCH_SIZE: int = int(
        os.getenv("VIDEO_PROCESSING_BATCH_SIZE", "10")
    )

    # Video compression and validation settings
    MAX_VIDEO_CHUNK_SIZE_MB: int = int(
        os.getenv("MAX_VIDEO_CHUNK_SIZE_MB", "20")
    )  # Maximum chunk size in MB (stay under 27MB API limit)
    VIDEO_SUCCESS_THRESHOLD: float = float(
        os.getenv("VIDEO_SUCCESS_THRESHOLD", "0.0")
    )  # Chunk failure tolerance (0.0 = fail-fast on any chunk failure)

    # API retry settings for rate limiting
    API_RETRY_MAX_ATTEMPTS: int = int(
        os.getenv("API_RETRY_MAX_ATTEMPTS", "5")
    )  # Maximum retry attempts for rate limiting
    API_RETRY_BASE_DELAY: float = float(
        os.getenv("API_RETRY_BASE_DELAY", "2.0")
    )  # Base delay for exponential backoff (seconds)

    # Database settings
    DATABASE_URL: str | None = os.getenv("DATABASE_URL")  # Required - no default
    DATABASE_POOL_SIZE: int = int(os.getenv("DATABASE_POOL_SIZE", "1"))
    DATABASE_MAX_OVERFLOW: int = int(os.getenv("DATABASE_MAX_OVERFLOW", "0"))
    DATABASE_TIMEOUT: int = int(os.getenv("DATABASE_TIMEOUT", "60"))

    # Logging settings
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT: str = os.getenv("LOG_FORMAT", "json")

    # Processor settings
    DOCLING_ARTIFACTS_PATH: str = os.getenv(
        "DOCLING_ARTIFACTS_PATH", "/app/models/docling"
    )

    # Resource management settings
    MAX_CONCURRENT_JOBS: int = int(
        os.getenv("MAX_CONCURRENT_JOBS", "1")
    )  # Max background jobs per instance

    # Environment settings
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    GOOGLE_APPLICATION_CREDENTIALS: str = os.getenv(
        "GOOGLE_APPLICATION_CREDENTIALS", ""
    )

    # Processing job environment variables (passed by task processor)
    PROGRAM_ID: str | None = os.getenv("PROGRAM_ID")  # Required - program isolation

    # Audio Transcription Settings (using Gemini Developer API)
    TRANSCRIPTION_MODEL: str = "gemini-2.5-flash"
    TRANSCRIPTION_MAX_TOKENS: int = int(
        os.getenv("TRANSCRIPTION_MAX_TOKENS", "4000")
    )  # Max tokens for transcription output
    GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY")

    @classmethod
    def get_database_url(cls) -> str:
        """Get PostgreSQL database URL from environment variable."""
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise ValueError(
                "DATABASE_URL environment variable is required. "
                "Please set it to your PostgreSQL connection string."
            )
        return database_url

    @classmethod
    def validate(cls) -> dict[str, Any]:
        """
        Validate the current Config class attributes and return a structured status summary.

        Performs required/optional checks and mode-specific validations, and enforces numeric constraints that are critical for runtime behavior.

        Returns:
            dict: A summary with these keys:
                - valid (bool): True if no required variables are missing.
                - missing (list[str]): Names or descriptions of required configuration items that are missing or invalid.
                - warnings (list[str]): Non-fatal issues or recommended settings that are absent.
                - processor_config (dict): Processor configuration:
                    - artifacts_path (str): DOCLING_ARTIFACTS_PATH.
                - models (dict): Human-readable descriptions of configured models and related settings.

        Raises:
            NonRetryableError: If any numeric constraint is violated (e.g., CHUNK_SIZE <= 0, CHUNK_OVERLAP < 0 or >= CHUNK_SIZE, VIDEO_CHUNK_DURATION_SECONDS <= 0, VIDEO_CONTEXT_MAX_BYTES <= 0).
        """
        missing: list[str] = []
        warnings: list[str] = []

        # Required settings for processor service
        if not cls.DATABASE_URL:
            missing.append("DATABASE_URL")

        if not cls.GEMINI_API_KEY:
            missing.append("GEMINI_API_KEY")

        if not cls.GOOGLE_CLOUD_PROJECT_ID:
            missing.append("GOOGLE_CLOUD_PROJECT_ID")

        if not cls.PROGRAM_ID:
            missing.append("PROGRAM_ID")

        # Warn about missing optional but important settings
        if not cls.GOOGLE_CLOUD_STORAGE_BUCKET:
            warnings.append(
                "GOOGLE_CLOUD_STORAGE_BUCKET not set - file processing may not work"
            )

        if cls.CHUNK_SIZE <= 0:
            raise NonRetryableError("CHUNK_SIZE must be greater than 0")

        if cls.CHUNK_OVERLAP < 0:
            raise NonRetryableError("CHUNK_OVERLAP must be non-negative")

        if cls.CHUNK_OVERLAP >= cls.CHUNK_SIZE:
            raise NonRetryableError("CHUNK_OVERLAP must be less than CHUNK_SIZE")

        # Video processing validation
        if cls.VIDEO_CHUNK_DURATION_SECONDS <= 0:
            raise NonRetryableError(
                "VIDEO_CHUNK_DURATION_SECONDS must be greater than 0"
            )

        if cls.VIDEO_CONTEXT_MAX_BYTES <= 0:
            raise NonRetryableError("VIDEO_CONTEXT_MAX_BYTES must be greater than 0")

        # Video compression and validation settings validation
        if cls.MAX_VIDEO_CHUNK_SIZE_MB <= 0:
            raise NonRetryableError("MAX_VIDEO_CHUNK_SIZE_MB must be greater than 0")

        if cls.VIDEO_SUCCESS_THRESHOLD < 0.0 or cls.VIDEO_SUCCESS_THRESHOLD > 1.0:
            raise NonRetryableError(
                "VIDEO_SUCCESS_THRESHOLD must be between 0.0 and 1.0"
            )

        if cls.API_RETRY_MAX_ATTEMPTS <= 0:
            raise NonRetryableError("API_RETRY_MAX_ATTEMPTS must be greater than 0")

        if cls.API_RETRY_BASE_DELAY < 0:
            raise NonRetryableError("API_RETRY_BASE_DELAY must be non-negative")

        return {
            "valid": len(missing) == 0,
            "missing": missing,
            "warnings": warnings,
            "processor_config": {
                "artifacts_path": cls.DOCLING_ARTIFACTS_PATH,
            },
            "models": {
                "text": f"{cls.TEXT_EMBEDDING_MODEL} ({cls.TEXT_EMBEDDING_DIMENSIONS}d)",
                "multimodal": f"{cls.MULTIMODAL_EMBEDDING_MODEL} ({cls.MULTIMODAL_EMBEDDING_DIMENSIONS}d)",
                "video": f"{cls.VIDEO_CHUNK_DURATION_SECONDS}s chunks, unlimited duration",
            },
        }

    @classmethod
    def get_database_config(cls) -> dict[str, Any]:
        """Get database-specific configuration."""
        return {
            "url": cls.DATABASE_URL,
            "pool_size": cls.DATABASE_POOL_SIZE,
            "max_overflow": cls.DATABASE_MAX_OVERFLOW,
            "timeout": cls.DATABASE_TIMEOUT,
        }

    @classmethod
    def is_production(cls) -> bool:
        """Check if running in production environment."""
        # Check explicit ENVIRONMENT setting first
        if cls.ENVIRONMENT.lower() == "production":
            return True

        # Check for Cloud Run environment variables
        if os.getenv("K_SERVICE") or os.getenv("CLOUD_RUN_SERVICE"):
            return True

        # Check for other production indicators
        if os.getenv("GAE_ENV") == "standard":  # Google App Engine
            return True

        # Check for common production environment variables
        if os.getenv("NODE_ENV") == "production":
            return True

        # Default to development
        return False

    @classmethod
    def is_debug(cls) -> bool:
        """Check if debug mode is enabled."""
        return cls.DEBUG

    @classmethod
    def get_temp_dir(cls) -> str:
        """Get temporary directory path."""
        return "/tmp/rag-processor"

    @classmethod
    def fail_fast_validation(cls) -> None:
        """Validate required configuration and fail immediately if missing.

        This should be called early in application startup to catch
        configuration issues before they cause confusing runtime errors.

        Raises:
            ValueError: If any required configuration values are missing.
        """
        validation_result = cls.validate()

        if not validation_result["valid"]:
            missing_vars = validation_result["missing"]
            error_msg = (
                f"CRITICAL: Missing required environment variables: {', '.join(missing_vars)}\n\n"
                "These values are required for the RAG processor to function:\n"
            )

            for var in missing_vars:
                if var == "DATABASE_URL":
                    error_msg += f"  • {var}: PostgreSQL connection string\n"
                elif var == "GEMINI_API_KEY":
                    error_msg += f"  • {var}: API key from https://aistudio.google.com/app/apikey\n"

                elif var == "GOOGLE_CLOUD_PROJECT_ID":
                    error_msg += f"  • {var}: Google Cloud project ID\n"
                elif var == "PROGRAM_ID":
                    error_msg += f"  • {var}: Program ID for document isolation (passed by task processor)\n"
                else:
                    error_msg += f"  • {var}: Required configuration value\n"

            error_msg += (
                "\nPlease set these environment variables and restart the service."
            )
            raise NonRetryableError(error_msg)

        # Log warnings for optional but important settings
        if validation_result["warnings"]:
            import logging

            logger = logging.getLogger(__name__)
            for warning in validation_result["warnings"]:
                logger.warning(f"Configuration warning: {warning}")


# Global config instance
config = Config()
