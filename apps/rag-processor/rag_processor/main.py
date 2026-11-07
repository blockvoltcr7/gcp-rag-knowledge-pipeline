#!/usr/bin/env python3
"""
RAG Processor - Cloud Run Job Entry Point

Processes a single file from GCS and exits.
Environment variables provide job parameters.
"""

import asyncio
import os
import sys
from typing import cast

import httpx
import structlog

from .config import config
from .services.processing_service import process_file_from_gcs
from .utils.logging import setup_logging
from .utils.retry_utils import NonRetryableError

logger = structlog.get_logger(__name__)


async def validate_program_ownership(
    program_id: str, creator_id: str
) -> bool:
    """
    Validate program ownership via Edge Function.

    This prevents direct cross-domain database access by the RAG processor.
    """
    edge_function_url = os.getenv("EDGE_FUNCTION_BASE_URL")
    if not edge_function_url:
        logger.error(
            "EDGE_FUNCTION_BASE_URL not configured",
            hint="Set EDGE_FUNCTION_BASE_URL to the Supabase functions endpoint",
        )
        raise NonRetryableError("Program validation service not configured")

    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not service_role_key:
        logger.error("SUPABASE_SERVICE_ROLE_KEY not configured")
        raise NonRetryableError("Service authentication not configured")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{edge_function_url}/validate-program-ownership",
                json={"program_id": program_id, "creator_id": creator_id},
                headers={
                    "Authorization": f"Bearer {service_role_key}",
                    "Content-Type": "application/json",
                },
                timeout=10.0,
            )
            response.raise_for_status()
            result = response.json()
            return result.get("is_owner", False)
    except httpx.TimeoutException:
        logger.error(
            "Program ownership validation timeout",
            program_id=program_id,
            creator_id=creator_id,
        )
        raise NonRetryableError("Program validation service timeout")
    except httpx.HTTPStatusError as e:
        logger.error(
            "Program ownership validation failed",
            program_id=program_id,
            creator_id=creator_id,
            status_code=e.response.status_code,
        )
        raise NonRetryableError(
            f"Program validation failed: {e.response.status_code}"
        ) from e
    except Exception as e:
        logger.error(
            "Program ownership validation error",
            program_id=program_id,
            creator_id=creator_id,
            error=str(e),
        )
        raise NonRetryableError(f"Program validation error: {e}") from e


async def main() -> None:
    """Main job processing function."""
    setup_logging()

    # Get job parameters from environment variables
    job_id = os.environ.get("PROCESSING_JOB_ID")
    gcs_path = os.environ.get("GCS_FILE_PATH")
    user_id = os.environ.get("USER_ID")
    program_id = os.environ.get("PROGRAM_ID")
    organization_id = os.environ.get("ORGANIZATION_ID")
    document_id = os.environ.get("DOCUMENT_ID")

    if not all([job_id, gcs_path, user_id, program_id]):
        logger.error("Missing required environment variables")
        logger.error("Required: PROCESSING_JOB_ID, GCS_FILE_PATH, USER_ID, PROGRAM_ID")
        logger.error(f"Got: job_id={job_id}, gcs_path={gcs_path}, user_id={user_id}, program_id={program_id}")
        sys.exit(1)

    job_id = cast(str, job_id)
    gcs_path = cast(str, gcs_path)
    user_id = cast(str, user_id)
    program_id = cast(str, program_id)

    logger.info(
        "Starting Cloud Run Job processing",
        job_id=job_id,
        gcs_path=gcs_path,
        user_id=user_id,
        program_id=program_id,
        organization_id=organization_id,
        document_id=document_id,
    )

    custom_metadata = {}
    if document_id:
        custom_metadata["document_id"] = document_id
    if program_id:
        custom_metadata["program_id"] = program_id
    if organization_id:
        custom_metadata["organization_id"] = organization_id

    # Validate program ownership before processing
    try:
        is_owner = await validate_program_ownership(program_id, user_id)
        if not is_owner:
            logger.error(
                "Program ownership validation failed",
                program_id=program_id,
                user_id=user_id,
            )
            raise NonRetryableError(
                f"Creator {user_id} does not own program {program_id}"
            )

        logger.info(
            "Program ownership validated",
            program_id=program_id,
            user_id=user_id,
        )

    except NonRetryableError:
        # Re-raise non-retryable errors
        raise
    except Exception as e:
        logger.error(
            "Failed to validate program ownership",
            program_id=program_id,
            user_id=user_id,
            error=str(e),
        )
        raise NonRetryableError(f"Program ownership validation failed: {e}") from e

    try:
        # Process the file using existing processing logic
        job = await process_file_from_gcs(
            job_id=job_id,
            gcs_path=gcs_path,
            user_id=user_id,
            organization_id=organization_id,
            custom_metadata=custom_metadata,
            project_id=config.PROJECT_ID,
        )

        logger.info(
            "Cloud Run Job completed successfully",
            job_id=job_id,
            processing_status=job.status.value,
        )

    except Exception as e:
        logger.error(
            "Cloud Run Job failed",
            job_id=job_id,
            error=str(e),
            error_type=type(e).__name__,
        )

        # Use different exit codes based on error type
        if isinstance(e, NonRetryableError):
            logger.info(
                "Non-retryable error detected, exiting without Cloud Run retry",
                job_id=job_id,
                error_type=type(e).__name__,
            )
            sys.exit(2)  # Signal permanent failure to Cloud Run (no retry)
        else:
            logger.info(
                "Retryable error detected, allowing Cloud Run retry",
                job_id=job_id,
                error_type=type(e).__name__,
            )
            sys.exit(1)  # Signal transient failure to Cloud Run (allow retry)


if __name__ == "__main__":
    asyncio.run(main())
