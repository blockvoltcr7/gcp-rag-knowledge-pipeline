# rag-gcs-handler/main.py

import json
import os
import uuid
from typing import TypedDict, cast

import functions_framework
import psycopg2
import psycopg2.extras
import structlog
from cloudevents.http.event import CloudEvent
from google.cloud import tasks_v2 as tasks
from psycopg2.extensions import connection

# Initialize structured logging
logger = structlog.get_logger(__name__)

# --- Environment loading with sane defaults ---
DB_CONNECTION_STRING = os.getenv("DATABASE_URL")
if not DB_CONNECTION_STRING:
    logger.error("DATABASE_URL is not set.")
    raise ValueError("DATABASE_URL environment variable must be set.")

PROJECT_ID = (
    os.getenv("GOOGLE_CLOUD_PROJECT_ID")
    or os.getenv("GOOGLE_CLOUD_PROJECT")
    or os.getenv("GCP_PROJECT")
)

REGION = (
    os.getenv("GOOGLE_CLOUD_REGION")
    or os.getenv("FUNCTION_REGION")
    or os.getenv("X_GOOGLE_RUN_REGION")
    or "us-central1"
)

QUEUE_NAME = os.getenv("CLOUD_TASKS_QUEUE_NAME", "rag-processing-queue-dev")
TASK_PROCESSOR_FUNCTION_URL = os.getenv("TASK_PROCESSOR_FUNCTION_URL")
GCS_HANDLER_SERVICE_ACCOUNT = os.getenv("GCS_HANDLER_SERVICE_ACCOUNT")

if not GCS_HANDLER_SERVICE_ACCOUNT and PROJECT_ID:
    # Default to development service account - will be overridden by deployment environment variables
    environment_suffix = os.getenv("ENVIRONMENT", "development")
    env_suffix = "dev" if environment_suffix == "development" else "prod"
    GCS_HANDLER_SERVICE_ACCOUNT = (
        f"rag-gcs-handler-{env_suffix}@{PROJECT_ID}.iam.gserviceaccount.com"
    )

# Fallback URL if not provided (will be set by deployment script)
if not TASK_PROCESSOR_FUNCTION_URL and PROJECT_ID:
    environment_suffix = os.getenv("ENVIRONMENT", "development")
    env_suffix = "dev" if environment_suffix == "development" else "prod"
    TASK_PROCESSOR_FUNCTION_URL = f"https://{REGION}-{PROJECT_ID}.cloudfunctions.net/rag-task-processor-{env_suffix}"


def validate_startup_configuration() -> None:
    """Validate all required configuration at startup with detailed error messages."""
    errors = []

    if not PROJECT_ID:
        errors.append("PROJECT_ID is required but not set")
    elif not PROJECT_ID.strip():
        errors.append("PROJECT_ID cannot be empty or whitespace")

    if not DB_CONNECTION_STRING:
        errors.append("DATABASE_URL is required but not set")
    elif not DB_CONNECTION_STRING.strip():
        errors.append("DATABASE_URL cannot be empty or whitespace")

    if not TASK_PROCESSOR_FUNCTION_URL:
        errors.append("TASK_PROCESSOR_FUNCTION_URL is required but not set")
    elif not TASK_PROCESSOR_FUNCTION_URL.strip():
        errors.append("TASK_PROCESSOR_FUNCTION_URL cannot be empty or whitespace")

    if not REGION:
        errors.append("REGION is required but not set")
    elif not REGION.strip():
        errors.append("REGION cannot be empty or whitespace")

    if errors:
        logger.error(
            "Configuration validation failed",
            errors=errors,
            available_env_vars=[
                (
                    "GOOGLE_CLOUD_PROJECT_ID"
                    if os.getenv("GOOGLE_CLOUD_PROJECT_ID")
                    else None
                ),
                "GOOGLE_CLOUD_PROJECT" if os.getenv("GOOGLE_CLOUD_PROJECT") else None,
                "GCP_PROJECT" if os.getenv("GCP_PROJECT") else None,
                "DATABASE_URL" if os.getenv("DATABASE_URL") else None,
                (
                    "TASK_PROCESSOR_FUNCTION_URL"
                    if os.getenv("TASK_PROCESSOR_FUNCTION_URL")
                    else None
                ),
                "GOOGLE_CLOUD_REGION" if os.getenv("GOOGLE_CLOUD_REGION") else None,
            ],
        )
        raise ValueError(f"Configuration validation failed: {'; '.join(errors)}")


# Validate configuration at startup
validate_startup_configuration()

# Type assertions - after validation, we know these are not None
assert PROJECT_ID is not None, "PROJECT_ID validated above"
assert DB_CONNECTION_STRING is not None, "DB_CONNECTION_STRING validated above"
assert (
    TASK_PROCESSOR_FUNCTION_URL is not None
), "TASK_PROCESSOR_FUNCTION_URL validated above"
assert REGION is not None, "REGION validated above"

logger.info(
    "GCS handler configuration validated and loaded successfully",
    project_id=PROJECT_ID,
    region=REGION,
    queue_name=QUEUE_NAME,
    task_processor_function_url=TASK_PROCESSOR_FUNCTION_URL,
    gcs_handler_service_account=GCS_HANDLER_SERVICE_ACCOUNT,
)

# Cloud Tasks will be sent to Task Processor function for proper queue consumption

# Initialize Cloud Tasks client with proper configuration
try:
    tasks_client = tasks.CloudTasksClient()
    logger.info("Cloud Tasks client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Cloud Tasks client: {e}")
    raise RuntimeError("Cloud Tasks client initialization failed") from e


# --- Typed structures ---
class GcsObjectFinalizedData(TypedDict, total=False):
    bucket: str
    name: str
    contentType: str
    size: str  # GCS provides size as a string in event payloads


class TaskMetadata(TypedDict, total=False):
    bucket: str
    name: str
    contentType: str
    size: str
    original_event_data: GcsObjectFinalizedData


class ProcessTaskPayload(TypedDict):
    document_id: str
    job_id: str | None
    gcs_path: str
    user_id: str
    status_was_updated: bool
    metadata: TaskMetadata


# --- Database Operations ---
def get_db_connection() -> connection:
    """
    Establishes a new database connection.
    This connects to the Supabase pooler endpoint, which handles pooling.
    """
    conn = None
    # We add a connection timeout to prevent the function from hanging
    try:
        conn = psycopg2.connect(DB_CONNECTION_STRING, connect_timeout=10)
        logger.debug("Database connection established successfully")
        return conn
    except psycopg2.OperationalError as e:
        logger.exception(
            "Database connection failed",
            error=str(e),
        )
        raise


def extract_user_id(file_path: str) -> str:
    """Extracts creator ID from a file path.

    Path format: documents/{creator_id}/{program_id}/{filename}
    The creator_id is at index 1 after splitting by '/'.
    """
    parts = file_path.split("/")
    if len(parts) >= 3:  # Changed from >= 2 to >= 3 for 3-level path
        return parts[1]  # creator_id is at index 1
    return "anonymous"


def extract_program_id(file_path: str) -> str:
    """Extracts program ID from a file path.

    Path format: gs://bucket/documents/{creator_id}/{program_id}/{filename}
    The program_id is at index 5 after splitting by '/' (accounting for gs:// prefix).
    """
    parts = file_path.split("/")
    if len(parts) >= 6:
        return parts[5]  # program_id is at index 5 (gs://bucket/documents/creator_id/program_id/filename)
    logger.warning("Failed to extract program_id from path", file_path=file_path)
    return ""  # Return empty string if path format is invalid


def derive_file_category(mime_type: str) -> str:
    """Derives file category from MIME type."""
    if mime_type.startswith("video/"):
        return "videos"
    elif mime_type.startswith("audio/"):
        return "audio"
    elif mime_type.startswith("image/"):
        return "images"
    else:
        return "documents"


def extract_gcs_bucket(gcs_path: str) -> str:
    """Extracts bucket name from GCS path (gs://bucket/path format)."""
    if gcs_path.startswith("gs://"):
        return gcs_path[5:].split("/")[0]
    return ""


def revert_document_status(document_id: str) -> None:
    """Revert document status from 'processing' back to 'uploading' if task creation fails."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                UPDATE ai.documents
                SET status = 'uploading', updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND status = 'processing'
                """,
                (document_id,),
            )
            conn.commit()
            logger.info(
                "Document status reverted to 'uploading'", document_id=document_id
            )
    except Exception as e:
        logger.error(
            "Failed to revert document status", document_id=document_id, error=str(e)
        )
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()


def update_existing_document_for_processing(
    event_data: GcsObjectFinalizedData,
) -> ProcessTaskPayload:
    """
    Updates the existing document record to processing status and ensures a processing job exists.
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            bucket = event_data.get("bucket")
            file_path = event_data.get("name")
            content_type = event_data.get("contentType")
            size = event_data.get("size")

            if not all([bucket, file_path, content_type, size]):
                raise ValueError("Missing essential data in GCS event payload")

            assert file_path is not None, "file_path validated above"
            assert bucket is not None, "bucket validated above"
            assert content_type is not None, "content_type validated above"
            assert size is not None, "size validated above"

            user_id = extract_user_id(file_path)
            gcs_path_for_db = f"gs://{bucket}/{file_path}"

            cursor.execute(
                """
                SELECT id, status, filename, original_filename
                FROM ai.documents
                WHERE gcs_path = %s
                LIMIT 1;
                """,
                (gcs_path_for_db,),
            )
            existing_doc = cursor.fetchone()

            if not existing_doc:
                logger.error(
                    "Document not found for GCS path.",
                    gcs_path=gcs_path_for_db,
                    user_id=user_id,
                )
                raise ValueError(
                    f"Document record not found for GCS path: {gcs_path_for_db}"
                )

            document_id = existing_doc["id"]
            logger.info(
                "Found existing document for processing",
                document_id=document_id,
                current_status=existing_doc["status"],
            )

            cursor.execute(
                """
                UPDATE ai.documents
                SET status = 'processing',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                  AND status = 'uploading'
                RETURNING id, status;
                """,
                (document_id,),
            )

            update_result = cursor.fetchone()
            status_was_updated = update_result is not None

            if status_was_updated:
                logger.info(
                    "Document transitioned to processing", document_id=document_id
                )
            else:
                logger.info(
                    "Document not in uploading state, skipping processing transition",
                    document_id=document_id,
                    current_status=existing_doc["status"],
                )

            cursor.execute(
                """
                INSERT INTO ai.processing_jobs (id, document_id, status, processing_stage, file_size, file_type, file_path)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (file_path) DO UPDATE SET
                    status = CASE WHEN ai.processing_jobs.status = 'processed' THEN ai.processing_jobs.status ELSE EXCLUDED.status END,
                    processing_stage = CASE WHEN ai.processing_jobs.status = 'processed' OR ai.processing_jobs.processing_stage = 'completed' THEN ai.processing_jobs.processing_stage ELSE EXCLUDED.processing_stage END,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id;
                """,
                (
                    str(uuid.uuid4()),
                    document_id,
                    "pending",
                    "pending",
                    size,
                    content_type,
                    file_path,
                ),
            )
            result_job = cursor.fetchone()
            actual_job_id = result_job["id"] if result_job else None

            conn.commit()

            logger.info(
                "Document processing transition completed successfully.",
                document_id=document_id,
                job_id=actual_job_id,
            )

            return {
                "document_id": str(document_id),
                "job_id": actual_job_id,
                "gcs_path": f"gs://{bucket}/{file_path}",
                "user_id": user_id,
                "status_was_updated": status_was_updated,
                "metadata": {
                    "bucket": str(bucket),
                    "name": str(file_path),
                    "contentType": str(content_type),
                    "size": str(size),
                    "original_event_data": event_data,
                },
            }

    except (Exception, psycopg2.DatabaseError) as error:
        if conn:
            conn.rollback()
        logger.error("Database operation failed.", error=str(error))
        raise

    finally:
        if conn:
            conn.close()


def generate_task_name(document_id: str, job_id: str | None) -> str:
    """Generate unique task name for deduplication.

    Creates a deterministic task name based on document_id and job_id
    to prevent duplicate processing of the same file.
    """
    # Use job_id if available, otherwise use document_id only
    unique_id = job_id if job_id else document_id
    # Sanitize for Cloud Tasks naming requirements (alphanumeric + hyphens)
    sanitized = "".join(c if c.isalnum() or c == "-" else "-" for c in unique_id)
    return f"rag-task-{sanitized}"


def create_cloud_task(task_payload_data: ProcessTaskPayload) -> None:
    """Create and enqueue a Cloud Task for processing.

    Creates a simple Cloud Task with task data and sends it to the
    Task Processor function for proper queue-based processing.
    """
    # Input validation
    if not task_payload_data.get("job_id"):
        logger.error("Missing job_id in task payload")
        raise ValueError("job_id is required for Cloud Task creation")

    if not task_payload_data.get("gcs_path"):
        logger.error("Missing gcs_path in task payload")
        raise ValueError("gcs_path is required for Cloud Task creation")

    if not task_payload_data.get("user_id"):
        logger.error("Missing user_id in task payload")
        raise ValueError("user_id is required for Cloud Task creation")

    if not task_payload_data.get("document_id"):
        logger.error("Missing document_id in task payload")
        raise ValueError("document_id is required for Cloud Task creation")

    # Generate unique task name for deduplication
    task_name = generate_task_name(
        task_payload_data["document_id"], task_payload_data["job_id"]
    )

    # Construct queue path
    assert PROJECT_ID is not None, "PROJECT_ID validated at startup"
    queue_path = tasks_client.queue_path(PROJECT_ID, REGION, QUEUE_NAME)

    # Extract organization_id if present in metadata
    metadata = task_payload_data.get("metadata", {})
    organization_id = None
    if isinstance(metadata, dict):
        organization_id = metadata.get("organization_id")

    # Extract program_id from GCS path
    gcs_path = task_payload_data["gcs_path"]
    program_id = extract_program_id(gcs_path)

    # Simple task payload for Task Processor function
    task_payload = {
        "document_id": task_payload_data["document_id"],
        "job_id": task_payload_data["job_id"],
        "gcs_path": gcs_path,
        "user_id": task_payload_data["user_id"],
        "program_id": program_id,
        "organization_id": organization_id,
    }

    # Create the task that sends data to Task Processor function
    task = tasks.Task(
        name=f"{queue_path}/tasks/{task_name}",
        http_request=tasks.HttpRequest(
            http_method=tasks.HttpMethod.POST,
            url=TASK_PROCESSOR_FUNCTION_URL,
            headers={"Content-Type": "application/json"},
            body=json.dumps(task_payload).encode("utf-8"),
            oidc_token=tasks.OidcToken(
                service_account_email=GCS_HANDLER_SERVICE_ACCOUNT,
                audience=TASK_PROCESSOR_FUNCTION_URL,
            ),
        ),
    )

    logger.info(
        "Creating Cloud Task for Task Processor function",
        task_name=task_name,
        document_id=task_payload_data["document_id"],
        job_id=task_payload_data["job_id"],
        gcs_path=task_payload_data["gcs_path"],
        user_id=task_payload_data["user_id"],
        program_id=program_id,
        queue_path=queue_path,
        task_processor_url=TASK_PROCESSOR_FUNCTION_URL,
    )

    try:
        # Create the task
        response = tasks_client.create_task(
            parent=queue_path,
            task=task,
        )

        logger.info(
            "Cloud Task created successfully for Task Processor function",
            task_name=task_name,
            response_name=response.name,
            document_id=task_payload_data["document_id"],
            job_id=task_payload_data["job_id"],
        )

    except Exception as e:
        logger.error(
            "Failed to create Cloud Task",
            task_name=task_name,
            document_id=task_payload_data["document_id"],
            job_id=task_payload_data["job_id"],
            error_type=type(e).__name__,
            error_message=str(e),
        )
        # Revert document status on task creation failure
        revert_document_status(task_payload_data.get("document_id", "unknown"))
        raise


# --- Cloud Function Handler ---
@functions_framework.cloud_event
def handle_gcs_event(cloud_event: CloudEvent) -> None:
    """
    Handles a GCS CloudEvent by updating a database record and executing a Cloud Run Job.

    Professional-grade implementation with comprehensive error handling,
    input validation, and detailed logging for production readiness.
    """
    # Validate input event
    if not cloud_event:
        logger.error("Received null or empty CloudEvent")
        raise ValueError("CloudEvent cannot be null or empty")

    if not hasattr(cloud_event, "data") or not cloud_event.data:
        logger.error("CloudEvent missing data payload")
        raise ValueError("CloudEvent must contain data payload")

    event_type = cloud_event.get("type", "unknown")
    event_source = cloud_event.get("source", "unknown")

    logger.info(
        "Processing GCS CloudEvent",
        event_type=event_type,
        event_source=event_source,
        event_id=cloud_event.get("id", "unknown"),
    )

    try:
        # Cast and validate event data
        event_data = cast(GcsObjectFinalizedData, cloud_event.data)

        # Validate essential event data fields
        required_fields = ["bucket", "name", "contentType"]
        missing_fields = [
            field for field in required_fields if not event_data.get(field)
        ]

        if missing_fields:
            logger.error(
                "CloudEvent missing required fields",
                missing_fields=missing_fields,
                event_data_keys=list(event_data.keys()) if event_data else [],
            )
            raise ValueError(f"CloudEvent missing required fields: {missing_fields}")

        logger.debug(
            "CloudEvent data validated successfully",
            bucket=event_data.get("bucket"),
            file_name=event_data.get("name"),
            content_type=event_data.get("contentType"),
            file_size=event_data.get("size", "unknown"),
        )

        # Update document status and create processing job
        try:
            task_payload_data: ProcessTaskPayload = (
                update_existing_document_for_processing(event_data)
            )
        except ValueError as db_error:
            logger.error(
                "Database operation failed during document processing setup",
                error_type=type(db_error).__name__,
                error_message=str(db_error),
                bucket=event_data.get("bucket"),
                file_name=event_data.get("name"),
            )
            # Don't re-raise for document not found - this is expected for some files
            if "Document record not found" in str(db_error):
                logger.info(
                    "Skipping processing - document record not found (likely test upload)"
                )
                return
            else:
                raise
        except Exception as db_error:
            logger.error(
                "Unexpected database error during document processing setup",
                error_type=type(db_error).__name__,
                error_message=str(db_error),
                bucket=event_data.get("bucket"),
                file_name=event_data.get("name"),
            )
            raise

        # Create Cloud Task if document status was successfully updated
        if task_payload_data["status_was_updated"]:
            logger.info(
                "Document status updated successfully, creating Cloud Task",
                document_id=task_payload_data["document_id"],
                job_id=task_payload_data["job_id"],
                gcs_path=task_payload_data["gcs_path"],
            )

            try:
                create_cloud_task(task_payload_data)
                logger.info(
                    "Cloud Task created successfully",
                    document_id=task_payload_data["document_id"],
                    job_id=task_payload_data["job_id"],
                )
            except Exception as task_error:
                logger.error(
                    "Cloud Task creation failed",
                    document_id=task_payload_data["document_id"],
                    job_id=task_payload_data["job_id"],
                    error_type=type(task_error).__name__,
                    error_message=str(task_error),
                )
                raise
        else:
            logger.info(
                "Document status not updated, skipping task creation",
                document_id=task_payload_data["document_id"],
                job_id=task_payload_data["job_id"],
                reason="Document may already be processing or in completed state",
            )

        logger.info(
            "GCS CloudEvent processing completed successfully",
            event_type=event_type,
            document_id=task_payload_data["document_id"],
        )

    except ValueError as validation_error:
        logger.error(
            "Input validation failed for GCS CloudEvent",
            event_type=event_type,
            error_type=type(validation_error).__name__,
            error_message=str(validation_error),
        )
        # Re-raise validation errors - they indicate client/configuration issues
        raise

    except Exception as unexpected_error:
        error_type = type(unexpected_error).__name__
        logger.error(
            "Unexpected error processing GCS CloudEvent",
            event_type=event_type,
            event_source=event_source,
            error_type=error_type,
            error_message=str(unexpected_error),
        )
        # Re-raise all errors to ensure Cloud Functions properly reports failures
        raise


# Entry point for Cloud Functions (no WSGI wrapper needed)
