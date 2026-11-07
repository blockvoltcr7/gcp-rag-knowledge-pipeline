"""
Shared utilities for Google GenAI operations.

Provides common functionality used across multiple AI services,
including file state management and polling utilities.
"""

import asyncio
from typing import Any

import google.genai as genai
import structlog
from google.genai import types

from ..utils.retry_utils import NonRetryableError, retry_genai_operation

logger = structlog.get_logger(__name__)


class GenAIFileManager:
    """Utility class for managing GenAI file uploads and state polling."""

    def __init__(self, genai_client: genai.Client):
        """
        Initialize the file manager.

        Args:
            genai_client: Configured GenAI client instance
        """
        self.genai_client = genai_client

    async def wait_for_file_active(
        self, file_name: str, max_wait_time: int = 180
    ) -> bool:
        """
        Wait for uploaded file to reach ACTIVE state before using it.

        This is critical because GenAI files go through states:
        PROCESSING -> ACTIVE -> (ready for use)

        Using files in PROCESSING state causes AI generation to fail.

        Args:
            file_name: Name of the uploaded file
            max_wait_time: Maximum time to wait in seconds (default: 3 minutes)

        Returns:
            True if file reached ACTIVE state, False otherwise
        """
        start_time = asyncio.get_event_loop().time()
        logger.debug(f"Waiting for file {file_name} to reach ACTIVE state...")

        while True:
            try:
                # Direct file state check (no retry wrapper to avoid missing rapid state transitions)
                file_info = await self.genai_client.aio.files.get(name=file_name)

                logger.debug(f"File {file_name} current state: {file_info.state}")

                if file_info.state == types.FileState.ACTIVE:
                    elapsed_time = asyncio.get_event_loop().time() - start_time
                    logger.info(
                        f"File {file_name} reached ACTIVE state after {elapsed_time:.1f}s"
                    )
                    return True
                elif file_info.state == types.FileState.FAILED:
                    elapsed_time = asyncio.get_event_loop().time() - start_time

                    # Capture all available attributes from the file_info object
                    file_attrs = {}
                    for attr in dir(file_info):
                        if not attr.startswith("_"):
                            try:
                                value = getattr(file_info, attr)
                                # Only include non-callable attributes
                                if not callable(value):
                                    file_attrs[attr] = str(value)
                            except Exception:
                                pass

                    logger.error(
                        f"File {file_name} failed to process after {elapsed_time:.1f}s - Google GenAI file details",
                        state="FAILED",
                        file_attributes=file_attrs,
                    )
                    return False

                # Check timeout
                elapsed_time = asyncio.get_event_loop().time() - start_time
                if elapsed_time > max_wait_time:
                    logger.error(
                        f"Timeout waiting for file {file_name} to become active "
                        f"after {elapsed_time:.1f} seconds (current state: {file_info.state})"
                    )
                    return False

                # Wait 2 seconds before checking again
                await asyncio.sleep(2)

            except Exception as e:
                elapsed_time = asyncio.get_event_loop().time() - start_time
                logger.error(
                    f"Error checking file state for {file_name} after retries and {elapsed_time:.1f}s: {e}"
                )
                return False

    async def upload_and_wait(
        self, file_path: str, mime_type: str | None = None, max_wait_time: int = 180
    ) -> Any:
        """
        Upload a file and wait for it to reach ACTIVE state.

        Args:
            file_path: Path to the file to upload
            mime_type: MIME type of the file (e.g., 'video/mp4', 'audio/wav')
            max_wait_time: Maximum time to wait for file to become active

        Returns:
            The uploaded GenAI file object

        Raises:
            Exception: If upload fails or file doesn't reach ACTIVE state
        """
        # Upload the file with mime_type if provided
        logger.debug(f"Uploading file to GenAI: {file_path}, mime_type: {mime_type}")

        # Extract just the filename for cleaner naming
        filename = file_path.split("/")[-1] if "/" in file_path else file_path

        # Use retry logic for GenAI upload to handle 500 errors gracefully

        async def _upload_file() -> Any:
            with open(file_path, "rb") as f:
                if mime_type:
                    return await self.genai_client.aio.files.upload(
                        file=f,
                        config={
                            "mime_type": mime_type,
                            "display_name": filename,
                        },
                    )
                else:
                    return await self.genai_client.aio.files.upload(file=f)

        uploaded_file = await retry_genai_operation(
            _upload_file, operation_name=f"upload_file({filename})"
        )

        logger.info(f"File uploaded with name: {uploaded_file.name}")

        # Validate file name
        if not uploaded_file.name:
            raise NonRetryableError("Uploaded file name is None")

        # Wait for file to be ready using simple direct polling
        start_time = asyncio.get_event_loop().time()
        logger.debug(f"Waiting for file {uploaded_file.name} to reach ACTIVE state...")

        while True:
            try:
                # Direct file state check (same as working local test)
                file_info = await self.genai_client.aio.files.get(
                    name=uploaded_file.name
                )
                elapsed_time = asyncio.get_event_loop().time() - start_time

                logger.debug(
                    f"File {uploaded_file.name} current state: {file_info.state} after {elapsed_time:.1f}s"
                )

                if file_info.state == types.FileState.ACTIVE:
                    logger.info(
                        f"File {uploaded_file.name} reached ACTIVE state after {elapsed_time:.1f}s"
                    )
                    return uploaded_file

                elif file_info.state == types.FileState.FAILED:
                    # Capture all available attributes from the file_info object
                    file_attrs = {}
                    for attr in dir(file_info):
                        if not attr.startswith("_"):
                            try:
                                value = getattr(file_info, attr)
                                if not callable(value):
                                    file_attrs[attr] = str(value)
                            except Exception:
                                pass

                    logger.error(
                        f"File {uploaded_file.name} failed to process after {elapsed_time:.1f}s - Google GenAI file details",
                        state="FAILED",
                        file_attributes=file_attrs,
                    )

                    # Clean up failed upload
                    await self.cleanup_file(uploaded_file)
                    raise NonRetryableError(
                        f"File {uploaded_file.name} failed to reach ACTIVE state after {elapsed_time:.1f}s. "
                        f"This may indicate a Google GenAI API processing issue."
                    )

                # Check timeout
                if elapsed_time > max_wait_time:
                    logger.error(
                        f"Timeout waiting for file {uploaded_file.name} to become active "
                        f"after {elapsed_time:.1f} seconds (current state: {file_info.state})"
                    )
                    await self.cleanup_file(uploaded_file)
                    raise NonRetryableError(
                        f"File {uploaded_file.name} timed out after {max_wait_time}s (state: {file_info.state})"
                    )

                # Wait 2 seconds before checking again
                await asyncio.sleep(2)

            except NonRetryableError:
                # Re-raise our own errors
                raise
            except Exception as e:
                elapsed_time = asyncio.get_event_loop().time() - start_time
                logger.error(
                    f"Error checking file state for {uploaded_file.name} after {elapsed_time:.1f}s: {e}"
                )
                await self.cleanup_file(uploaded_file)
                raise NonRetryableError(f"File state check failed: {e}") from e

    async def upload_and_wait_with_retry(
        self,
        file_path: str,
        mime_type: str | None = None,
        max_wait_time: int = 180,
        max_retries: int = 5,
        base_delay: float = 5.0,
    ) -> Any:
        """
        Upload a file and wait for it to reach ACTIVE state with retry logic.

        This method handles temporary GenAI API processing issues by retrying
        uploads that fail due to files not reaching ACTIVE state quickly.
        Uses exponential backoff to avoid overwhelming the API during issues.

        Args:
            file_path: Path to the file to upload
            mime_type: MIME type of the file (e.g., 'video/mp4', 'audio/wav')
            max_wait_time: Maximum time to wait for file to become active per attempt
            max_retries: Maximum number of retry attempts (default: 5)
            base_delay: Base delay in seconds for exponential backoff (default: 5.0)

        Returns:
            The uploaded GenAI file object

        Raises:
            Exception: If upload fails after all retry attempts or encounters non-retryable error
        """
        last_error = None

        for attempt in range(max_retries):
            try:
                logger.debug(
                    f"Upload attempt {attempt + 1}/{max_retries} for file: {file_path}"
                )

                # Attempt the upload using existing logic
                result = await self.upload_and_wait(file_path, mime_type, max_wait_time)

                # Success - log and return
                if attempt > 0:
                    logger.info(
                        f"Upload succeeded on attempt {attempt + 1}/{max_retries} for file: {file_path}"
                    )

                return result

            except Exception as error:
                last_error = error

                # Check if this failure should be retried
                if not self._is_retryable_failure(error):
                    logger.error(
                        f"Non-retryable error on attempt {attempt + 1}/{max_retries} for {file_path}: {error}"
                    )
                    raise error

                # Check if we have more attempts remaining
                if attempt == max_retries - 1:
                    logger.error(
                        f"Upload failed after {max_retries} attempts for {file_path}. Final error: {error}"
                    )
                    break

                # Calculate delay with exponential backoff: 5s, 10s, 20s, 40s, 80s
                delay = base_delay * (2**attempt)

                logger.warning(
                    f"Retryable error on attempt {attempt + 1}/{max_retries} for {file_path}: {error}. "
                    f"Retrying in {delay}s..."
                )

                # Wait before retry
                await asyncio.sleep(delay)

        # All retry attempts exhausted
        if last_error is not None:
            raise last_error
        else:
            raise RuntimeError(
                "Upload failed after all retry attempts with no recorded error"
            )

    def _is_retryable_failure(self, error: Exception) -> bool:
        """
        Determine if a file upload failure should be retried.

        Retryable failures are typically temporary GenAI API processing issues
        where files upload successfully but fail to reach ACTIVE state quickly.

        Args:
            error: The exception that occurred during upload

        Returns:
            True if the failure should be retried, False otherwise
        """
        if isinstance(error, NonRetryableError):
            error_message = str(error).lower()
            # Check for the specific failure pattern indicating GenAI API processing issues
            return "failed to reach active state" in error_message
        return False

    async def cleanup_file(self, uploaded_file: Any) -> None:
        """
        Clean up an uploaded file from GenAI.

        Args:
            uploaded_file: The uploaded file object to clean up
        """
        if uploaded_file and uploaded_file.name:
            try:
                # Use retry logic for GenAI delete to handle 500 errors gracefully
                async def _delete_file() -> Any:
                    return await self.genai_client.aio.files.delete(
                        name=uploaded_file.name
                    )

                await retry_genai_operation(
                    _delete_file, operation_name=f"delete_file({uploaded_file.name})"
                )
                logger.debug(f"Cleaned up uploaded file: {uploaded_file.name}")
            except Exception as cleanup_error:
                logger.warning(
                    f"Failed to delete uploaded file {uploaded_file.name} after retries: {cleanup_error}"
                )


def create_file_manager(genai_client: genai.Client) -> GenAIFileManager:
    """
    Create a GenAI file manager instance.

    Args:
        genai_client: Configured GenAI client

    Returns:
        GenAIFileManager instance
    """
    return GenAIFileManager(genai_client)
