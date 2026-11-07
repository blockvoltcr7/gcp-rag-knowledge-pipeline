"""
Database service for storing document chunks and embeddings.

Handles storage of both text and multimodal embeddings with proper
error handling, logging, and connection pooling.
"""

import json
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, cast

import psycopg2
import psycopg2.extras
import psycopg2.pool
import structlog
from google.cloud import secretmanager
from pgvector.psycopg2 import register_vector

from ..config import config
from ..models.metadata_models import (
    ChunkMetadata,
    ContentType,
    ProcessingJob,
    ProcessingStatus,
)
from ..utils.retry_utils import (
    JobCancelledError,
    NonRetryableError,
    retry_database_operation,
)

logger = structlog.get_logger(__name__)


class DatabaseServiceError(NonRetryableError):
    """Base exception for database service errors."""

    pass


class ChunkData:
    """
    Data structure for document chunk information.

    Contains text content, embeddings, metadata, and optional context for a document chunk.
    Supports dual embeddings for video chunks (text + multimodal).
    """

    def __init__(
        self,
        text: str,
        metadata: ChunkMetadata,
        context: str | None = None,
        text_embedding: list[float] | None = None,
        multimodal_embedding: list[float] | None = None,
    ):
        self.text = text
        self.metadata = metadata
        self.context = context
        self.text_embedding = text_embedding
        self.multimodal_embedding = multimodal_embedding


class DatabaseService:
    """
    Service for handling all database operations.

    Provides clean interfaces for storing text and multimodal embeddings,
    managing processing jobs, and handling document metadata with proper
    error handling, connection pooling, and transaction management.
    """

    def __init__(self, project_id: str | None = None):
        """
        Initialize the database service.

        Args:
            project_id: Google Cloud project ID
        """
        self.project_id = project_id
        self.secret_client = secretmanager.SecretManagerServiceClient()
        # Config is available as global instance
        self._connection_pool: psycopg2.pool.ThreadedConnectionPool | None = None
        self._connection_string: str | None = None

        logger.info("Database service initialized", project_id=project_id)

    def _get_bucket_name(self) -> str:
        """
        Get the GCS bucket name from configuration.

        Returns:
            GCS bucket name

        Raises:
            DatabaseServiceError: If bucket name is not configured
        """
        bucket_name = config.GOOGLE_CLOUD_STORAGE_BUCKET
        if not bucket_name:
            raise DatabaseServiceError(
                "GOOGLE_CLOUD_STORAGE_BUCKET environment variable not set. "
                "This is required to construct full GCS paths for stored documents."
            )
        return bucket_name

    def _get_connection_pool(self) -> psycopg2.pool.ThreadedConnectionPool:
        """
        Get or create a connection pool.

        Returns:
            PostgreSQL connection pool
        """
        if self._connection_pool is None:
            if self._connection_string is None:
                self._connection_string = self._get_connection_string()

            db_config = config.get_database_config()

            # Create connection pool with proper configuration
            self._connection_pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=db_config["pool_size"],
                dsn=self._connection_string,
                connect_timeout=db_config["timeout"],
            )

            # Register vector extension for all connections in the pool
            # This is needed for pgvector operations
            raw_conn = self._connection_pool.getconn()
            try:
                conn = cast(psycopg2.extensions.connection, raw_conn)
                register_vector(conn)
            finally:
                self._connection_pool.putconn(raw_conn)

            logger.info(
                "Connection pool created",
                pool_size=db_config["pool_size"],
                timeout=db_config["timeout"],
            )

        return self._connection_pool

    def _get_connection_string(self) -> str:
        """Get database connection string from environment variable (mounted by Cloud Run)."""
        try:
            # Get connection string from environment variable (mounted by --set-secrets)
            connection_string = config.DATABASE_URL

            if not connection_string:
                raise ValueError("DATABASE_URL environment variable not set")

            # Validate connection string format
            if not connection_string.startswith("postgresql://"):
                raise ValueError("Invalid connection string format")

            # Ensure SSL is properly configured for connection stability
            if "sslmode=" not in connection_string:
                connection_string += "?sslmode=require"
            elif "sslmode=disable" in connection_string:
                # Replace disable with require for better connection stability
                connection_string = connection_string.replace(
                    "sslmode=disable", "sslmode=require"
                )

            return connection_string

        except Exception as e:
            logger.error("Failed to get database connection string", error=str(e))
            raise DatabaseServiceError(
                f"Connection string retrieval failed: {e}"
            ) from e

    def _validate_connection(self, conn: psycopg2.extensions.connection) -> bool:
        """
        Validate connection by testing a simple query.

        Args:
            conn: Connection to validate

        Returns:
            True if connection is valid, False otherwise
        """
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            return True
        except Exception:
            return False

    async def get_database_connection(self) -> psycopg2.extensions.connection:
        """
        Get database connection from the connection pool with validation.

        Returns:
            PostgreSQL connection from pool
        """
        connection_id = str(uuid.uuid4())
        _acquisition_start = time.time()
        wait_start = time.time()

        try:
            pool = self._get_connection_pool()

            # Update pool metrics before acquisition
            self._update_pool_metrics(pool)

            conn = pool.getconn()

            # Record wait time
            _wait_time = time.time() - wait_start
            # Log wait time if needed

            if conn is None:
                logger.warning("Connection pool exhausted")
                raise DatabaseServiceError("Failed to get connection from pool")

            # Cast to proper type since pool.getconn() returns Any
            typed_conn = cast(psycopg2.extensions.connection, conn)

            # Validate connection before use (implements pool pre-ping equivalent)
            if not self._validate_connection(typed_conn):
                logger.warning(
                    "Invalid connection detected, attempting to get a new one"
                )
                pool.putconn(typed_conn, close=True)  # Close bad connection
                conn = pool.getconn()
                if conn is None:
                    raise DatabaseServiceError(
                        "Failed to get replacement connection from pool"
                    )
                typed_conn = cast(psycopg2.extensions.connection, conn)

                # If still invalid after replacement, raise error
                if not self._validate_connection(typed_conn):
                    raise DatabaseServiceError(
                        "Unable to establish valid database connection"
                    )

            # Ensure vector extension is registered for this connection
            register_vector(typed_conn)

            # Record successful acquisition
            logger.debug("Connection acquired", connection_id=connection_id)

            # Update pool metrics after acquisition
            self._update_pool_metrics(pool)

            return typed_conn

        except Exception as e:
            # Record failed acquisition
            logger.error("Failed to acquire connection", connection_id=connection_id)

            # Categorize and record error type
            error_type = self._categorize_connection_error(e)
            logger.error("Connection error", error_type=error_type)

            logger.error(
                "Failed to get database connection", error=str(e), error_type=error_type
            )
            raise DatabaseServiceError(f"Database connection failed: {e}") from e

    def return_connection(
        self, conn: psycopg2.extensions.connection, close: bool = False
    ) -> None:
        """
        Return connection to the connection pool.

        Args:
            conn: Connection to return to pool
            close: If True, close the connection instead of returning to pool
        """
        try:
            if self._connection_pool and conn:
                if close or conn.closed:
                    # Close bad connections instead of returning to pool
                    self._connection_pool.putconn(conn, close=True)
                    logger.debug("Closed bad connection instead of returning to pool")
                else:
                    self._connection_pool.putconn(conn)

                # Update pool metrics after returning connection
                self._update_pool_metrics(self._connection_pool)
        except Exception as e:
            logger.warning("Failed to return connection to pool", error=str(e))

    @asynccontextmanager
    async def get_connection(self) -> AsyncIterator[psycopg2.extensions.connection]:
        """
        Async context manager for database connections.

        Automatically acquires connection from pool and returns it when done.
        Ensures proper cleanup even if exceptions occur.

        Usage:
            async with db_service.get_connection() as conn:
                # Use connection for database operations
                cursor = conn.cursor()
                # Connection automatically returned to pool

        Yields:
            PostgreSQL connection from pool

        Raises:
            DatabaseServiceError: If connection cannot be acquired
        """
        conn = None
        connection_is_bad = False
        connection_id = str(uuid.uuid4())
        _acquisition_start = time.time()
        wait_start = time.time()
        connection_start_time = None

        try:
            # Acquire connection from pool with validation (like async version)
            pool = self._get_connection_pool()

            # Update pool metrics before acquisition
            self._update_pool_metrics(pool)

            raw_conn = pool.getconn()

            # Record wait time
            _wait_time = time.time() - wait_start
            # Log wait time if needed

            if raw_conn is None:
                logger.warning("Connection pool exhausted")
                raise DatabaseServiceError("Failed to get connection from pool")

            # Cast to proper type
            conn = cast(psycopg2.extensions.connection, raw_conn)

            # Validate connection before use
            if not self._validate_connection(conn):
                logger.warning(
                    "Invalid connection detected, attempting to get a new one"
                )
                pool.putconn(conn, close=True)  # Close bad connection
                raw_conn = pool.getconn()
                if raw_conn is None:
                    raise DatabaseServiceError(
                        "Failed to get replacement connection from pool"
                    )
                conn = cast(psycopg2.extensions.connection, raw_conn)

                # If still invalid after replacement, raise error
                if not self._validate_connection(conn):
                    raise DatabaseServiceError(
                        "Unable to establish valid database connection"
                    )

            # Register vector extension for valid connection
            register_vector(conn)

            # Record successful acquisition
            logger.debug("Connection acquired", connection_id=connection_id)
            connection_start_time = time.time()

            # Update pool metrics after acquisition
            self._update_pool_metrics(pool)

            yield conn

        except Exception as e:
            # Record failed acquisition if not already recorded
            logger.error("Failed to acquire connection", connection_id=connection_id)

            # Categorize and record error type
            error_type = self._categorize_connection_error(e)
            logger.error("Connection error", error_type=error_type)

            logger.error(
                "Database connection error", error=str(e), error_type=error_type
            )
            connection_is_bad = True  # Mark for closure instead of return to pool
            raise DatabaseServiceError(f"Database connection failed: {e}") from e
        finally:
            # Record connection lifetime if we had a successful connection
            if connection_start_time is not None:
                lifetime = time.time() - connection_start_time
                logger.debug("Connection released", lifetime=lifetime)

            # Return connection to pool, closing if it's bad
            if conn is not None:
                self.return_connection(conn, close=connection_is_bad)

    def _update_pool_metrics(self, pool: psycopg2.pool.ThreadedConnectionPool) -> None:
        """
        Update connection pool metrics.

        Args:
            pool: Connection pool to get metrics from
        """
        try:
            if pool:
                # Get pool statistics
                # Note: psycopg2's ThreadedConnectionPool doesn't expose direct stats,
                # so we need to use internal attributes carefully
                active = len(getattr(pool, "_used", []))  # Connections currently in use
                idle = len(getattr(pool, "_pool", []))  # Connections available in pool
                max_size = pool.maxconn  # Maximum pool size

                logger.debug(
                    "Pool metrics", active=active, idle=idle, max_size=max_size
                )

                logger.debug(
                    "Pool metrics updated",
                    active=active,
                    idle=idle,
                    max_size=max_size,
                    utilization_percent=(
                        (active / max_size * 100) if max_size > 0 else 0
                    ),
                )
        except Exception as e:
            logger.warning("Failed to update pool metrics", error=str(e))

    def _categorize_connection_error(self, error: Exception) -> str:
        """
        Categorize connection errors for metrics.

        Args:
            error: Exception to categorize

        Returns:
            Error category string
        """
        error_str = str(error).lower()

        if "timeout" in error_str:
            return "timeout"
        elif "authentication" in error_str or "password" in error_str:
            return "authentication"
        elif "connection refused" in error_str or "could not connect" in error_str:
            return "network"
        elif "pool" in error_str and "exhausted" in error_str:
            return "pool_exhausted"
        elif "ssl" in error_str or "certificate" in error_str:
            return "ssl"
        elif "too many connections" in error_str:
            return "connection_limit"
        elif "database" in error_str and "does not exist" in error_str:
            return "database_not_found"
        else:
            return "unknown"

    def _build_full_gcs_path(self, relative_path: str) -> str:
        """
        Build full GCS path from relative path.

        Args:
            relative_path: Relative GCS path from database

        Returns:
            Full GCS path with bucket name
        """
        if relative_path and not relative_path.startswith("gs://"):
            bucket_name = self._get_bucket_name()
            return f"gs://{bucket_name}/{relative_path}"
        return relative_path or ""

    def _determine_content_type_from_path(self, file_path: str) -> str:
        """
        Determine content type from file path extension using centralized router.

        Args:
            file_path: Path to the file (can be GCS path or filename)

        Returns:
            Content type string
        """
        from ..utils.content_router import get_content_router

        content_router = get_content_router()
        return content_router.detect_content_type(file_path)

    def _validate_and_normalize_content_type(
        self, content_type: str, job_id: str = ""
    ) -> ContentType:
        """
        Validate and normalize content type to ensure it's a valid literal value.

        Args:
            content_type: Content type string to validate
            job_id: Optional job ID for logging

        Returns:
            Validated ContentType literal
        """
        valid_types = ("video", "audio", "image", "document")
        if content_type not in valid_types:
            logger.warning(
                "Invalid content type, defaulting to document",
                content_type=content_type,
                job_id=job_id,
            )
            return "document"
        # Narrow to the ContentType literal union without ignores
        return cast(ContentType, content_type)

    def _convert_db_status_to_processing_status(
        self, db_status: str
    ) -> ProcessingStatus:
        """
        Convert database status string to ProcessingStatus enum.

        Args:
            db_status: Status string from database

        Returns:
            ProcessingStatus enum value
        """
        status_mapping = {
            "pending": ProcessingStatus.PENDING,
            "processing": ProcessingStatus.PROCESSING,
            "processed": ProcessingStatus.PROCESSED,
            "error": ProcessingStatus.ERROR,
        }
        return status_mapping.get(db_status, ProcessingStatus.PENDING)

    def _build_processing_job_from_result(
        self, result: dict[str, Any]
    ) -> ProcessingJob:
        """
        Build ProcessingJob object from database query result.

        Args:
            result: Database query result dictionary

        Returns:
            ProcessingJob object
        """
        # Convert database status
        processing_status = self._convert_db_status_to_processing_status(
            result["status"]
        )

        # Build full GCS path
        full_gcs_path = self._build_full_gcs_path(result["gcs_path"])

        # Determine content type from file path
        content_type_str = self._determine_content_type_from_path(full_gcs_path)

        # Validate and normalize content type
        content_type_str = self._validate_and_normalize_content_type(
            content_type_str, result["id"]
        )

        # Build processing job object
        job = ProcessingJob(
            job_id=result["id"],
            file_name=result["filename"] or "",
            file_size=result["file_size"] or 0,
            gcs_path=full_gcs_path,
            user_id=result["creator_id"] or "",  # Read from creator_id column
            status=processing_status,
            created_at=result["created_at"],
            started_at=result["processing_started_at"],
            completed_at=result["completed_at"],
            error_message=result["error_message"],
        )

        # Add document metadata
        job.custom_metadata["document_id"] = result["document_id"]
        job.custom_metadata["processing_stage"] = result["processing_stage"]
        job.custom_metadata["program_id"] = result.get("program_id")

        return job

    async def store_chunks(
        self,
        chunks: list[ChunkData],
        user_id: str,
        document_id: str | None = None,
        program_id: str | None = None,
    ) -> None:
        """
        Store chunks and embeddings in the database.

        Includes deduplication logic to prevent duplicate chunks for the same document.
        Handles both text-only and multimodal chunks by inserting appropriate embedding fields.

        Args:
            chunks: List of chunk data with text, embeddings, and metadata
            user_id: User ID for the document
            document_id: Optional document ID for association
            program_id: Optional program ID for program-based isolation
        """
        if not chunks:
            logger.warning("No chunks provided for storage")
            return

        # Determine chunk types for logging
        text_chunks = sum(1 for chunk in chunks if chunk.text_embedding is not None)
        multimodal_chunks = sum(
            1 for chunk in chunks if chunk.multimodal_embedding is not None
        )

        if text_chunks > 0 and multimodal_chunks > 0:
            chunk_type = "mixed"
        elif multimodal_chunks > 0:
            chunk_type = "multimodal"
        else:
            chunk_type = "text"

        logger.info(
            f"Storing {len(chunks)} {chunk_type} chunks",
            user_id=user_id,
            document_id=document_id,
            text_chunks=text_chunks,
            multimodal_chunks=multimodal_chunks,
        )

        async def _store_operation() -> None:
            async with self.get_connection() as conn:
                try:
                    with conn.cursor(
                        cursor_factory=psycopg2.extras.RealDictCursor
                    ) as cursor:
                        # First, check if chunks already exist for this document
                        if document_id:
                            cursor.execute(
                                """
                                SELECT COUNT(*) as chunk_count
                                FROM ai.document_chunks
                                WHERE document_id = %s
                                """,
                                (document_id,),
                            )
                            result = cursor.fetchone()
                            existing_count = result["chunk_count"] if result else 0

                            if existing_count > 0:
                                logger.info(
                                    "Removing existing chunks before storing new ones",
                                    document_id=document_id,
                                    existing_count=existing_count,
                                    new_count=len(chunks),
                                )
                                # Delete existing chunks for this document
                                cursor.execute(
                                    """
                                    DELETE FROM ai.document_chunks
                                    WHERE document_id = %s
                                    """,
                                    (document_id,),
                                )

                        # Prepare batch insert data
                        chunk_records = []
                        for idx, chunk in enumerate(chunks):
                            chunk_id = str(uuid.uuid4())
                            chunk_records.append(
                                (
                                    chunk_id,
                                    chunk.text,
                                    idx,
                                    chunk.text_embedding,
                                    chunk.multimodal_embedding,
                                    user_id,
                                    (
                                        json.dumps(chunk.metadata.model_dump())
                                        if chunk.metadata
                                        else "{}"
                                    ),
                                    document_id,
                                    program_id,
                                    datetime.now(timezone.utc),
                                    chunk.context,
                                )
                            )

                        # Batch insert all chunks with dual embedding support
                        cursor.executemany(
                            """
                            INSERT INTO ai.document_chunks (
                                id, content, chunk_index, text_embedding, multimodal_embedding, creator_id, metadata,
                                document_id, program_id, created_at, context
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            chunk_records,
                        )

                        conn.commit()

                        logger.info(
                            f"Successfully stored {len(chunks)} {chunk_type} chunks",
                            user_id=user_id,
                            document_id=document_id,
                        )

                except Exception as e:
                    conn.rollback()
                    logger.error(
                        f"Failed to store {chunk_type} chunks",
                        error=str(e),
                        user_id=user_id,
                        document_id=document_id,
                    )
                    raise DatabaseServiceError(f"Chunk storage failed: {e}") from e

        await retry_database_operation(_store_operation, "store_chunks")

    async def update_document_chunk_count(
        self, document_id: str, chunk_count: int
    ) -> None:
        """
        Update the chunk count for a document.

        Args:
            document_id: Document ID to update
            chunk_count: Number of chunks processed
        """

        async def _update_operation() -> None:
            async with self.get_connection() as conn:
                try:
                    with conn.cursor(
                        cursor_factory=psycopg2.extras.RealDictCursor
                    ) as cursor:
                        cursor.execute(
                            """
                            UPDATE ai.documents
                            SET
                                chunk_count = %s,
                                updated_at = %s
                            WHERE id = %s
                        """,
                            (
                                chunk_count,
                                datetime.now(timezone.utc),
                                document_id,
                            ),
                        )

                        conn.commit()

                        logger.info(
                            "Updated document chunk count",
                            document_id=document_id,
                            chunk_count=chunk_count,
                        )

                except Exception as e:
                    conn.rollback()
                    logger.error(
                        "Failed to update document chunk count",
                        document_id=document_id,
                        chunk_count=chunk_count,
                        error=str(e),
                    )
                    raise DatabaseServiceError(f"Document update failed: {e}") from e

        await retry_database_operation(_update_operation, "update_document_chunk_count")

    def close_pool(self) -> None:
        """Close the connection pool."""
        if self._connection_pool:
            self._connection_pool.closeall()
            self._connection_pool = None
            logger.info("Connection pool closed")

    def __del__(self) -> None:
        """Cleanup connection pool on deletion."""
        self.close_pool()

    async def update_processing_job(self, job: ProcessingJob) -> None:
        """
        Update a processing job in the database.

        Args:
            job: Processing job to update
        """

        async def _update_operation() -> None:
            async with self.get_connection() as conn:
                try:
                    with conn.cursor(
                        cursor_factory=psycopg2.extras.RealDictCursor
                    ) as cursor:
                        # Map ProcessingStatus to document_processing_job_status
                        status_mapping = {
                            "PENDING": "pending",
                            "PROCESSING": "processing",
                            "PROCESSED": "processed",
                            "ERROR": "error",
                        }

                        db_status = status_mapping.get(job.status.name, "pending")

                        # Get appropriate processing stage for the current status
                        processing_stage = self._get_processing_stage_for_status(
                            job.status
                        )

                        # Update the processing job
                        cursor.execute(
                            """
                            UPDATE ai.processing_jobs
                            SET
                                status = %s,
                                processing_stage = %s,
                                processing_started_at = %s,
                                completed_at = %s,
                                error_message = %s,
                                updated_at = %s
                            WHERE id = %s
                        """,
                            (
                                db_status,
                                processing_stage,
                                job.started_at,
                                job.completed_at,
                                job.error_message,
                                datetime.now(timezone.utc),
                                job.job_id,
                            ),
                        )

                        # Also update the document status
                        document_id = job.custom_metadata.get("document_id", None)
                        if document_id:
                            # Map job status to document status
                            doc_status_mapping = {
                                "PENDING": "processing",
                                "PROCESSING": "processing",
                                "PROCESSED": "completed",
                                "ERROR": "error",
                            }
                            doc_status = doc_status_mapping.get(
                                job.status.name, "processing"
                            )

                            cursor.execute(
                                """
                                UPDATE ai.documents
                                SET
                                    status = %s,
                                    processing_error = %s,
                                    processed_at = %s,
                                    updated_at = %s
                                WHERE id = %s
                            """,
                                (
                                    doc_status,
                                    (
                                        job.error_message
                                        if job.status.name == "ERROR"
                                        else None
                                    ),
                                    (
                                        job.completed_at
                                        if job.status.name == "PROCESSED"
                                        else None
                                    ),
                                    datetime.now(timezone.utc),
                                    document_id,
                                ),
                            )

                        conn.commit()

                        logger.info(
                            "Updated processing job and document",
                            job_id=job.job_id,
                            status=job.status.value,
                            document_id=document_id,
                        )

                except Exception as e:
                    conn.rollback()
                    logger.error(
                        "Failed to update processing job",
                        job_id=job.job_id,
                        error=str(e),
                    )
                    raise DatabaseServiceError(
                        f"Processing job update failed: {e}"
                    ) from e

        await retry_database_operation(_update_operation, "update_processing_job")

    def _get_processing_stage_for_status(self, status: ProcessingStatus) -> str:
        """
        Map ProcessingStatus to appropriate processing stage value.

        Args:
            status: Current processing status

        Returns:
            Processing stage string for database storage
        """
        stage_mapping = {
            ProcessingStatus.PENDING: "pending",
            ProcessingStatus.PROCESSING: "processing",
            ProcessingStatus.PROCESSED: "completed",
            ProcessingStatus.ERROR: "error",
        }
        return stage_mapping.get(status, "pending")

    async def update_processing_stage(self, job_id: str, stage: str) -> None:
        """
        Update only the processing stage for a job.

        Args:
            job_id: Processing job ID to update
            stage: New processing stage value

        Raises:
            JobCancelledError: If the processing job no longer exists (was deleted)
        """

        async def _update_stage_operation() -> None:
            async with self.get_connection() as conn:
                try:
                    with conn.cursor(
                        cursor_factory=psycopg2.extras.RealDictCursor
                    ) as cursor:
                        cursor.execute(
                            """
                            UPDATE ai.processing_jobs
                            SET
                                processing_stage = %s,
                                updated_at = %s
                            WHERE id = %s
                        """,
                            (stage, datetime.now(timezone.utc), job_id),
                        )

                        # Check if the job still exists
                        if cursor.rowcount == 0:
                            logger.info(
                                "Processing job no longer exists - job was cancelled or deleted",
                                job_id=job_id,
                                stage=stage,
                            )
                            raise JobCancelledError(
                                f"Processing job {job_id} no longer exists - job was cancelled or deleted"
                            )

                        conn.commit()

                        logger.debug(
                            "Updated processing stage",
                            job_id=job_id,
                            stage=stage,
                        )

                except JobCancelledError:
                    # Re-raise job cancellation without rollback (nothing to rollback)
                    raise
                except Exception as e:
                    conn.rollback()
                    logger.warning(
                        "Failed to update processing stage",
                        job_id=job_id,
                        stage=stage,
                        error=str(e),
                    )
                    # Re-raise the exception so it can be handled by retry logic
                    raise

        await retry_database_operation(
            _update_stage_operation, "update_processing_stage"
        )

    async def get_processing_job(self, job_id: str) -> ProcessingJob | None:
        """
        Get a processing job by ID.

        Args:
            job_id: ID of the processing job

        Returns:
            ProcessingJob if found, None otherwise
        """

        async def _get_operation() -> ProcessingJob | None:
            async with self.get_connection() as conn:
                try:
                    with conn.cursor(
                        cursor_factory=psycopg2.extras.RealDictCursor
                    ) as cursor:
                        # Query processing job details with associated document info
                        cursor.execute(
                            """
                            SELECT
                                dpj.id,
                                dpj.document_id,
                                dpj.status,
                                dpj.processing_stage,
                                dpj.file_size,
                                dpj.file_type,
                                dpj.file_path,
                                dpj.retry_count,
                                dpj.processing_started_at,
                                dpj.completed_at,
                                dpj.error_message,
                                dpj.created_at,
                                dpj.updated_at,
                                d.filename,
                                d.gcs_path,
                                d.creator_id,
                                d.program_id
                            FROM ai.processing_jobs dpj
                            LEFT JOIN ai.documents d ON dpj.document_id = d.id
                            WHERE dpj.id = %s
                        """,
                            (job_id,),
                        )

                        result = cursor.fetchone()
                        if not result:
                            logger.debug("Processing job not found", job_id=job_id)
                            return None

                        job = self._build_processing_job_from_result(result)

                        logger.debug(
                            "Retrieved processing job",
                            job_id=job_id,
                            status=job.status.value,
                            document_id=job.custom_metadata["document_id"],
                        )

                        return job

                except Exception as e:
                    logger.error(
                        "Failed to get processing job", job_id=job_id, error=str(e)
                    )
                    raise DatabaseServiceError(
                        f"Processing job retrieval failed: {e}"
                    ) from e

        return await retry_database_operation(_get_operation, "get_processing_job")

    async def get_latest_processing_job_for_document(
        self, document_id: str
    ) -> ProcessingJob | None:
        """
        Get the most recent processing job for a specific document.

        Args:
            document_id: ID of the document

        Returns:
            ProcessingJob if found, None otherwise
        """

        async def _get_latest_operation() -> ProcessingJob | None:
            async with self.get_connection() as conn:
                try:
                    with conn.cursor(
                        cursor_factory=psycopg2.extras.RealDictCursor
                    ) as cursor:
                        # Query latest processing job for the document
                        cursor.execute(
                            """
                            SELECT
                                dpj.id,
                                dpj.document_id,
                                dpj.status,
                                dpj.processing_stage,
                                dpj.file_size,
                                dpj.file_type,
                                dpj.file_path,
                                dpj.retry_count,
                                dpj.processing_started_at,
                                dpj.completed_at,
                                dpj.error_message,
                                dpj.created_at,
                                dpj.updated_at,
                                d.filename,
                                d.gcs_path,
                                d.creator_id,
                                d.program_id
                            FROM ai.processing_jobs dpj
                            LEFT JOIN ai.documents d ON dpj.document_id = d.id
                            WHERE d.id = %s
                            ORDER BY dpj.created_at DESC
                            LIMIT 1
                        """,
                            (document_id,),
                        )

                        result = cursor.fetchone()
                        if not result:
                            logger.debug(
                                "No processing job found for document",
                                document_id=document_id,
                            )
                            return None

                        job = self._build_processing_job_from_result(result)

                        logger.debug(
                            "Retrieved latest processing job for document",
                            document_id=document_id,
                            job_id=job.job_id,
                            status=job.status.value,
                        )

                        return job

                except Exception as e:
                    logger.error(
                        "Failed to get latest processing job for document",
                        document_id=document_id,
                        error=str(e),
                    )
                    raise DatabaseServiceError(
                        f"Latest processing job retrieval failed: {e}"
                    ) from e

        return await retry_database_operation(
            _get_latest_operation, "get_latest_processing_job_for_document"
        )

    async def list_processing_jobs(
        self,
        user_id: str,
        status_filter: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ProcessingJob]:
        """
        List processing jobs for a user.

        Args:
            user_id: User ID to filter by
            status_filter: Optional status filter
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            List of ProcessingJob objects
        """

        async def _list_operation() -> list[ProcessingJob]:
            async with self.get_connection() as conn:
                try:
                    with conn.cursor(
                        cursor_factory=psycopg2.extras.RealDictCursor
                    ) as cursor:
                        # Build dynamic query based on filters
                        where_clauses = ["d.creator_id = %s"]
                        params: list[str | int] = [user_id]

                        if status_filter:
                            where_clauses.append("dpj.status = %s")
                            params.append(status_filter)

                        where_clause = " AND ".join(where_clauses)

                        query = f"""
                            SELECT
                                dpj.id,
                                dpj.document_id,
                                dpj.status,
                                dpj.processing_stage,
                                dpj.file_size,
                                dpj.file_type,
                                dpj.file_path,
                                dpj.retry_count,
                                dpj.processing_started_at,
                                dpj.completed_at,
                                dpj.error_message,
                                dpj.created_at,
                                dpj.updated_at,
                                d.filename,
                                d.gcs_path,
                                d.creator_id,
                                d.program_id
                            FROM ai.processing_jobs dpj
                            LEFT JOIN ai.documents d ON dpj.document_id = d.id
                            WHERE {where_clause}
                            ORDER BY dpj.created_at DESC
                            LIMIT %s OFFSET %s
                        """

                        params.extend([limit, offset])
                        cursor.execute(query, params)
                        results = cursor.fetchall()

                        jobs = []
                        for result in results:
                            job = self._build_processing_job_from_result(result)
                            jobs.append(job)

                        logger.info(
                            "Retrieved processing jobs list",
                            user_id=user_id,
                            status_filter=status_filter,
                            count=len(jobs),
                            limit=limit,
                            offset=offset,
                        )

                        return jobs

                except Exception as e:
                    logger.error(
                        "Failed to list processing jobs",
                        user_id=user_id,
                        status_filter=status_filter,
                        error=str(e),
                    )
                    raise DatabaseServiceError(
                        f"Processing jobs listing failed: {e}"
                    ) from e

        result = await retry_database_operation(_list_operation, "list_processing_jobs")
        return result if result is not None else []


# Global service instance
_database_service: DatabaseService | None = None


def get_database_service(project_id: str | None = None) -> DatabaseService:
    """
    Get a global database service instance.

    Args:
        project_id: Google Cloud project ID

    Returns:
        DatabaseService instance
    """
    global _database_service

    if _database_service is None:
        _database_service = DatabaseService(project_id=project_id)

    return _database_service
