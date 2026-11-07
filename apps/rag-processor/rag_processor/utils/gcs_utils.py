"""
Enhanced GCS utilities for RAG processor.

Provides robust Google Cloud Storage integration with proper error handling,
retry logic, and resource management.
"""

import asyncio
import tempfile
from pathlib import Path
from typing import Any, cast

import structlog
from google.cloud.exceptions import Forbidden, NotFound, TooManyRequests
from google.cloud.storage import Client as StorageClient

from .retry_utils import NonRetryableError, retry_gcs_operation

logger = structlog.get_logger(__name__)


class GCSError(NonRetryableError):
    """Base exception for GCS operations."""

    pass


class GCSFileNotFoundError(NonRetryableError):
    """File not found in GCS."""

    pass


class GCSPermissionError(NonRetryableError):
    """Permission denied for GCS operation."""

    pass


class GCSTemporaryError(Exception):
    """Temporary GCS error that should trigger retries."""

    pass


class EnhancedGCSClient:
    """Enhanced GCS client with retry logic and error handling."""

    def __init__(self, project_id: str | None = None):
        """
        Initialize the enhanced GCS client.

        Args:
            project_id: Google Cloud project ID (optional)
        """
        try:
            self.client = StorageClient(project=project_id)
            self.project_id = project_id or self.client.project
            logger.info("GCS client initialized", project_id=self.project_id)
        except Exception as e:
            logger.error("Failed to initialize GCS client", error=str(e))
            raise GCSError(f"Failed to initialize GCS client: {e}") from e

    def _handle_gcs_error(
        self, error: Exception, operation: str, bucket: str, blob_name: str
    ) -> Exception:
        """
        Handle and classify GCS errors for proper retry behavior.

        Args:
            error: Original exception
            operation: Name of the operation that failed
            bucket: Bucket name
            blob_name: Blob name

        Returns:
            Appropriate exception type for retry logic
        """
        error_str = str(error).lower()

        # Classify errors
        if isinstance(error, NotFound):
            logger.error(
                "GCS file not found",
                operation=operation,
                bucket=bucket,
                blob_name=blob_name,
                error=str(error),
            )
            return GCSFileNotFoundError(f"File not found: gs://{bucket}/{blob_name}")

        elif isinstance(error, Forbidden):
            logger.error(
                "GCS permission denied",
                operation=operation,
                bucket=bucket,
                blob_name=blob_name,
                error=str(error),
            )
            return GCSPermissionError(f"Permission denied: gs://{bucket}/{blob_name}")

        elif (
            isinstance(error, TooManyRequests)
            or "429" in error_str
            or "rate limit" in error_str
        ):
            logger.warning(
                "GCS rate limit exceeded",
                operation=operation,
                bucket=bucket,
                blob_name=blob_name,
                error=str(error),
            )
            return GCSTemporaryError(f"Rate limit exceeded: {error}")

        elif any(
            pattern in error_str
            for pattern in ["timeout", "connection", "network", "temporary"]
        ):
            logger.warning(
                "GCS temporary error",
                operation=operation,
                bucket=bucket,
                blob_name=blob_name,
                error=str(error),
            )
            return GCSTemporaryError(f"Temporary error: {error}")

        else:
            logger.error(
                "GCS unknown error",
                operation=operation,
                bucket=bucket,
                blob_name=blob_name,
                error=str(error),
                error_type=type(error).__name__,
            )
            return GCSError(f"GCS operation failed: {error}")

    async def download_file_to_temp(
        self, bucket_name: str, blob_name: str, custom_temp_dir: str | None = None
    ) -> Path:
        """
        Download a file from GCS to a temporary location with retry logic.

        Args:
            bucket_name: Name of the GCS bucket
            blob_name: Name of the blob (file) in the bucket
            custom_temp_dir: Optional custom temporary directory

        Returns:
            Path to the downloaded temporary file

        Raises:
            GCSFileNotFoundError: If file doesn't exist
            GCSPermissionError: If permission denied
            GCSError: For other GCS errors
        """

        async def _download_operation() -> Path:
            try:
                # Get bucket and blob
                bucket = self.client.bucket(bucket_name)
                blob = bucket.blob(blob_name)

                # Check if file exists
                if not blob.exists():
                    raise GCSFileNotFoundError(
                        f"File not found: gs://{bucket_name}/{blob_name}"
                    )

                # Create temporary file
                if custom_temp_dir:
                    temp_dir = Path(custom_temp_dir)
                    temp_dir.mkdir(parents=True, exist_ok=True)
                else:
                    temp_dir = Path(tempfile.mkdtemp())

                # Use original filename or blob name
                filename = Path(blob_name).name
                temp_file_path = temp_dir / filename

                # Download file
                logger.info(
                    "Starting GCS file download",
                    bucket=bucket_name,
                    blob=blob_name,
                    temp_path=str(temp_file_path),
                )

                blob.download_to_filename(str(temp_file_path))

                # Verify download
                if not temp_file_path.exists():
                    raise GCSError(f"Downloaded file not found at {temp_file_path}")

                file_size = temp_file_path.stat().st_size
                logger.info(
                    "GCS file download completed",
                    bucket=bucket_name,
                    blob=blob_name,
                    temp_path=str(temp_file_path),
                    file_size_bytes=file_size,
                )

                return temp_file_path

            except (GCSFileNotFoundError, GCSPermissionError):
                # Re-raise non-retryable errors as-is
                raise
            except Exception as e:
                # Classify and re-raise with appropriate type
                raise self._handle_gcs_error(
                    e, "download", bucket_name, blob_name
                ) from e

        return await retry_gcs_operation(_download_operation, "gcs_download")

    async def get_file_metadata(
        self, bucket_name: str, blob_name: str
    ) -> dict[str, Any]:
        """
        Get metadata for a file in GCS with retry logic.

        Args:
            bucket_name: Name of the GCS bucket
            blob_name: Name of the blob (file) in the bucket

        Returns:
            Dictionary containing file metadata

        Raises:
            GCSFileNotFoundError: If file doesn't exist
            GCSError: For other GCS errors
        """

        async def _metadata_operation() -> dict[str, Any]:
            try:
                bucket = self.client.bucket(bucket_name)
                blob = bucket.blob(blob_name)

                # Reload to get fresh metadata
                blob.reload()

                metadata = {
                    "name": blob.name,
                    "bucket": blob.bucket.name,
                    "size": blob.size,
                    "content_type": blob.content_type,
                    "created": (
                        blob.time_created.isoformat() if blob.time_created else None
                    ),
                    "updated": blob.updated.isoformat() if blob.updated else None,
                    "md5_hash": blob.md5_hash,
                    "crc32c": blob.crc32c,
                    "etag": blob.etag,
                }

                logger.debug(
                    "Retrieved GCS file metadata",
                    bucket=bucket_name,
                    blob=blob_name,
                    size=blob.size,
                    content_type=blob.content_type,
                )

                return metadata

            except NotFound:
                raise GCSFileNotFoundError(
                    f"File not found: gs://{bucket_name}/{blob_name}"
                ) from None
            except Exception as e:
                raise self._handle_gcs_error(
                    e, "get_metadata", bucket_name, blob_name
                ) from e

        return await retry_gcs_operation(_metadata_operation, "gcs_get_metadata")

    async def file_exists(self, bucket_name: str, blob_name: str) -> bool:
        """
        Check if a file exists in GCS with retry logic.

        Args:
            bucket_name: Name of the GCS bucket
            blob_name: Name of the blob (file) in the bucket

        Returns:
            True if file exists, False otherwise
        """

        async def _exists_operation() -> bool:
            try:
                bucket = self.client.bucket(bucket_name)
                blob = bucket.blob(blob_name)
                # Cast needed: google-cloud-storage lacks return type annotations
                return cast(bool, blob.exists())
            except Exception as e:
                # For exists check, only retry on temporary errors
                if any(
                    pattern in str(e).lower()
                    for pattern in ["timeout", "connection", "network"]
                ):
                    raise GCSTemporaryError(
                        f"Temporary error checking file existence: {e}"
                    ) from e
                else:
                    # For other errors, assume file doesn't exist
                    logger.warning(
                        "Error checking file existence, assuming false",
                        bucket=bucket_name,
                        blob=blob_name,
                        error=str(e),
                    )
                    return False

        try:
            result = await retry_gcs_operation(_exists_operation, "gcs_file_exists")
            return result
        except Exception:
            # If all retries fail, assume file doesn't exist
            return False

    async def get_file_size(self, bucket_name: str, blob_name: str) -> int:
        """
        Get the size of a file in GCS.

        Args:
            bucket_name: Name of the GCS bucket
            blob_name: Name of the blob (file) in the bucket

        Returns:
            File size in bytes

        Raises:
            GCSFileNotFoundError: If file doesn't exist
        """
        try:
            metadata = await asyncio.wait_for(
                self.get_file_metadata(bucket_name, blob_name),
                timeout=5.0,  # 5 second timeout for GCS metadata operations
            )
            size = metadata["size"]
            if not isinstance(size, int):
                raise ValueError(f"Invalid size value from metadata: {size}")
            return size
        except asyncio.TimeoutError:
            raise GCSFileNotFoundError(
                f"File size check timeout: gs://{bucket_name}/{blob_name}"
            ) from None


def parse_gcs_path(gcs_path: str) -> tuple[str, str]:
    """
    Parse a GCS path into bucket and blob components.

    Args:
        gcs_path: GCS path in format 'gs://bucket/path/to/file' or 'bucket/path/to/file'

    Returns:
        Tuple of (bucket_name, blob_name)

    Raises:
        ValueError: If path format is invalid
    """
    if gcs_path.startswith("gs://"):
        gcs_path = gcs_path[5:]  # Remove 'gs://' prefix

    if "/" not in gcs_path:
        raise ValueError(f"Invalid GCS path format: {gcs_path}")

    parts = gcs_path.split("/", 1)
    bucket_name = parts[0]
    blob_name = parts[1]

    if not bucket_name or not blob_name:
        raise ValueError(f"Invalid GCS path format: {gcs_path}")

    return bucket_name, blob_name


def cleanup_temp_file(file_path: str | Path) -> None:
    """
    Safely clean up a temporary file - ONLY deletes files in temp directories.

    Args:
        file_path: Path to the temporary file to clean up
    """
    try:
        path = Path(file_path)
        if not path.exists():
            return

        # SAFETY CHECK: Only delete files in temporary locations
        tmpdir = Path(tempfile.gettempdir())
        is_in_temp = tmpdir in path.parents or path.parent.name.startswith("tmp")

        if not is_in_temp:
            logger.warning(
                "Skipped cleanup for non-temp file - SAFETY PROTECTION",
                path=str(path),
                tmpdir=str(tmpdir),
                parent=str(path.parent),
            )
            return

        # Safe to delete - confirmed temporary file
        path.unlink()
        logger.debug("Cleaned up temporary file", path=str(path))

        # Also try to remove parent directory if it's empty
        try:
            parent_dir = path.parent
            if parent_dir.name.startswith("tmp") and not any(parent_dir.iterdir()):
                parent_dir.rmdir()
                logger.debug("Cleaned up temporary directory", path=str(parent_dir))
        except OSError:
            # Directory not empty or other issue, ignore
            pass

    except Exception as e:
        logger.warning(
            "Failed to clean up temporary file", path=str(file_path), error=str(e)
        )


# Global instance for convenience
_gcs_client: EnhancedGCSClient | None = None


def get_gcs_client(project_id: str | None = None) -> EnhancedGCSClient:
    """
    Get a global GCS client instance.

    Args:
        project_id: Google Cloud project ID (optional)

    Returns:
        Enhanced GCS client instance
    """
    global _gcs_client

    if _gcs_client is None:
        _gcs_client = EnhancedGCSClient(project_id=project_id)

    return _gcs_client
