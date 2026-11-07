# rag-task-processor/main.py

import os
from typing import TypedDict

import flask
import functions_framework
import structlog
from google.cloud import run_v2 as run

# Initialize structured logging
logger = structlog.get_logger(__name__)

# --- Environment loading with sane defaults ---
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

PROCESSOR_JOB_NAME = os.getenv("PROCESSOR_JOB_NAME", "rag-processor-job-dev")
TASK_SERVICE_ACCOUNT = os.getenv("TASK_SERVICE_ACCOUNT")

if not TASK_SERVICE_ACCOUNT and PROJECT_ID:
    # Default to development service account
    environment_suffix = os.getenv("ENVIRONMENT", "development")
    env_suffix = "dev" if environment_suffix == "development" else "prod"
    TASK_SERVICE_ACCOUNT = (
        f"rag-processor-{env_suffix}@{PROJECT_ID}.iam.gserviceaccount.com"
    )


def validate_startup_configuration() -> None:
    """Validate all required configuration at startup with detailed error messages."""
    errors = []

    if not PROJECT_ID:
        errors.append("PROJECT_ID is required but not set")
    elif not PROJECT_ID.strip():
        errors.append("PROJECT_ID cannot be empty or whitespace")

    if not PROCESSOR_JOB_NAME:
        errors.append("PROCESSOR_JOB_NAME is required but not set")
    elif not PROCESSOR_JOB_NAME.strip():
        errors.append("PROCESSOR_JOB_NAME cannot be empty or whitespace")

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
                "PROCESSOR_JOB_NAME" if os.getenv("PROCESSOR_JOB_NAME") else None,
                "GOOGLE_CLOUD_REGION" if os.getenv("GOOGLE_CLOUD_REGION") else None,
            ],
        )
        raise ValueError(f"Configuration validation failed: {'; '.join(errors)}")


# Validate configuration at startup
validate_startup_configuration()

# Type assertions - after validation, we know these are not None
assert PROJECT_ID is not None, "PROJECT_ID validated above"
assert PROCESSOR_JOB_NAME is not None, "PROCESSOR_JOB_NAME validated above"
assert REGION is not None, "REGION validated above"

logger.info(
    "Task processor configuration validated and loaded successfully",
    project_id=PROJECT_ID,
    region=REGION,
    processor_job_name=PROCESSOR_JOB_NAME,
    task_service_account=TASK_SERVICE_ACCOUNT,
)

# Initialize Cloud Run Jobs client
try:
    run_jobs_client = run.JobsClient()
    logger.info("Cloud Run Jobs client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Cloud Run Jobs client: {e}")
    raise RuntimeError("Cloud Run Jobs client initialization failed") from e


# --- Typed structures ---
class TaskPayload(TypedDict):
    document_id: str
    job_id: str | None
    gcs_path: str
    user_id: str
    program_id: str
    organization_id: str | None


def execute_cloud_run_job(task_data: TaskPayload) -> None:
    """Execute a Cloud Run Job with the given task data.

    This function handles the actual execution of the Cloud Run Job
    with proper environment variables and configuration.
    """
    # Input validation
    required_fields = ["document_id", "gcs_path", "user_id", "program_id"]
    missing_fields = [field for field in required_fields if not task_data.get(field)]

    if missing_fields:
        logger.error(
            "Missing required fields in task payload", missing_fields=missing_fields
        )
        raise ValueError(f"Missing required fields: {missing_fields}")

    # Build environment variables for the job
    env_vars = [
        {"name": "PROCESSING_JOB_ID", "value": task_data.get("job_id") or ""},
        {"name": "GCS_FILE_PATH", "value": task_data["gcs_path"]},
        {"name": "USER_ID", "value": task_data["user_id"]},
        {"name": "DOCUMENT_ID", "value": task_data["document_id"]},
        {"name": "PROGRAM_ID", "value": task_data.get("program_id") or ""},
    ]

    # Add organization_id if present
    if task_data.get("organization_id"):
        env_vars.append(
            {"name": "ORGANIZATION_ID", "value": str(task_data["organization_id"])}
        )

    logger.info(
        "Executing Cloud Run Job",
        document_id=task_data["document_id"],
        job_id=task_data.get("job_id"),
        gcs_path=task_data["gcs_path"],
        user_id=task_data["user_id"],
        processor_job_name=PROCESSOR_JOB_NAME,
    )

    try:
        # Construct the job resource name
        job_resource_name = (
            f"projects/{PROJECT_ID}/locations/{REGION}/jobs/{PROCESSOR_JOB_NAME}"
        )

        # Create execution request
        # Note: Service account is set during job deployment, no need to override
        request = run.RunJobRequest(
            name=job_resource_name,
            overrides=run.RunJobRequest.Overrides(
                container_overrides=[
                    run.RunJobRequest.Overrides.ContainerOverride(
                        env=[
                            run.EnvVar(name=env_var["name"], value=env_var["value"])
                            for env_var in env_vars
                        ]
                    )
                ]
            ),
        )

        # Execute the job
        operation = run_jobs_client.run_job(request=request)

        logger.info(
            "Cloud Run Job execution initiated successfully",
            document_id=task_data["document_id"],
            job_id=task_data.get("job_id"),
            operation_type=type(operation).__name__,
        )

    except Exception as e:
        logger.error(
            "Failed to execute Cloud Run Job",
            document_id=task_data["document_id"],
            job_id=task_data.get("job_id"),
            error_type=type(e).__name__,
            error_message=str(e),
        )
        raise


@functions_framework.http
def handle_cloud_task(
    request: flask.Request,
) -> tuple[flask.Response, int] | flask.Response:
    """Handle HTTP requests from Cloud Tasks.

    This function receives task payloads from Cloud Tasks and executes
    the corresponding Cloud Run Jobs. This is the proper "consumer" in
    our queue architecture.
    """
    logger.info("Received Cloud Task request", method=request.method)

    # Validate HTTP method
    if request.method != "POST":
        logger.error(f"Invalid HTTP method: {request.method}")
        return flask.jsonify({"error": "Only POST method allowed"}), 405

    try:
        # Parse request body
        request_json = request.get_json()
        if not request_json:
            logger.error("Empty request body")
            return flask.jsonify({"error": "Request body is required"}), 400

        logger.debug("Task payload received", payload=request_json)

        # Convert to our typed structure
        task_data: TaskPayload = {
            "document_id": request_json.get("document_id", ""),
            "job_id": request_json.get("job_id"),
            "gcs_path": request_json.get("gcs_path", ""),
            "user_id": request_json.get("user_id", ""),
            "program_id": request_json.get("program_id", ""),
            "organization_id": request_json.get("organization_id"),
        }

        # Execute the Cloud Run Job
        try:
            execute_cloud_run_job(task_data)

            logger.info(
                "Task processed successfully",
                document_id=task_data["document_id"],
                job_id=task_data["job_id"],
            )

            return (
                flask.jsonify(
                    {
                        "status": "success",
                        "message": "Cloud Run Job executed successfully",
                        "document_id": task_data["document_id"],
                        "job_id": task_data["job_id"],
                    }
                ),
                200,
            )

        except Exception as job_error:
            logger.error(
                "Cloud Run Job execution failed",
                document_id=task_data["document_id"],
                job_id=task_data["job_id"],
                error_type=type(job_error).__name__,
                error_message=str(job_error),
            )

            # Check if this is a non-retriable error (document deleted, job not found, etc.)
            error_message = str(job_error).lower()
            is_non_retriable = any(
                phrase in error_message
                for phrase in [
                    "processing job not found",
                    "document not found",
                    "file does not exist",
                    "document was deleted",
                    "permission denied",
                    "invalid document id",
                ]
            )

            if is_non_retriable:
                logger.info(
                    "Non-retriable error detected - document likely deleted",
                    document_id=task_data["document_id"],
                    job_id=task_data["job_id"],
                    error_type=type(job_error).__name__,
                )
                # Return 400 so Cloud Tasks will NOT retry
                return (
                    flask.jsonify(
                        {
                            "status": "failed_permanently",
                            "message": "Document no longer exists or invalid",
                            "document_id": task_data["document_id"],
                            "error": str(job_error),
                        }
                    ),
                    400,
                )
            else:
                # Return 500 so Cloud Tasks will retry for infrastructure errors
                return (
                    flask.jsonify(
                        {
                            "status": "error",
                            "message": "Cloud Run Job execution failed",
                            "document_id": task_data["document_id"],
                            "error": str(job_error),
                        }
                    ),
                    500,
                )

    except Exception as parse_error:
        logger.error(
            "Failed to parse task request",
            error_type=type(parse_error).__name__,
            error_message=str(parse_error),
        )

        # Return 400 for parsing errors (don't retry)
        return (
            flask.jsonify(
                {
                    "status": "error",
                    "message": "Invalid request format",
                    "error": str(parse_error),
                }
            ),
            400,
        )


# Entry point for Cloud Functions
