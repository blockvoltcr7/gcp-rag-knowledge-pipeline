#!/usr/bin/env python3
"""
Core GCS Handler deployment logic - Environment-agnostic implementation.

This module deploys the GCS Handler function (Producer) that receives GCS events
and creates Cloud Tasks for the queue architecture.

Features:
- Environment-aware service naming and configuration
- EventArc trigger setup for GCS finalized events
- Database secret management
- Cloud Tasks queue creation
"""

import os
import subprocess
import time
from pathlib import Path

from .deployment_config import get_config
from .gcp_utils import Colors, get_gcloud_path, log, log_step
from .utils.env_loader import load_env_file


def get_environment_file_path(environment: str) -> Path:
    """Get the appropriate environment file path for the environment.
    Args:
        environment: Environment name ("development" or "production")
    Returns:
        Path to the environment file
    """
    if environment == "development":
        env_file = (
            Path(__file__).parent.parent / "apps" / "rag-processor" / ".env.local"
        )
    elif environment == "production":
        env_file = Path(__file__).parent.parent / "apps" / "rag-processor" / ".env.prod"
    else:
        raise ValueError(f"Unknown environment: {environment}")
    return env_file


def get_env_value(key: str, default: str = "") -> str:
    """Get environment variable value."""
    return os.getenv(key, default)


def ensure_database_secret(project_id: str, database_url: str, secret_id: str) -> bool:
    """Ensure DATABASE_URL is stored in Secret Manager with environment-specific name."""
    log_step(
        "Secret", f"Ensuring DATABASE_URL is stored in Secret Manager as '{secret_id}'"
    )

    try:
        # Check if secret exists
        gcloud_cmd = get_gcloud_path()
        check_cmd = [
            gcloud_cmd,
            "secrets",
            "describe",
            secret_id,
            f"--project={project_id}",
            "--format=json",
        ]

        result = subprocess.run(check_cmd, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            # Create secret if it doesn't exist
            log(f"   📝 Creating secret '{secret_id}'...")
            create_cmd = [
                gcloud_cmd,
                "secrets",
                "create",
                secret_id,
                f"--project={project_id}",
                "--replication-policy=automatic",
            ]

            result = subprocess.run(
                create_cmd, capture_output=True, text=True, check=False
            )

            if result.returncode != 0:
                log(f"   ❌ Failed to create secret: {result.stderr}", Colors.RED)
                return False
            log(f"   ✅ Secret '{secret_id}' created", Colors.GREEN)
        else:
            log(f"   ✅ Secret '{secret_id}' already exists", Colors.GREEN)

        # Add new version with the DATABASE_URL
        log("   🔄 Updating secret version...")

        add_version_cmd = [
            gcloud_cmd,
            "secrets",
            "versions",
            "add",
            secret_id,
            f"--project={project_id}",
            "--data-file=-",
        ]

        result = subprocess.run(
            add_version_cmd,
            input=database_url,
            text=True,
            capture_output=True,
            check=False,
        )

        if result.returncode != 0:
            log(f"   ❌ Failed to add secret version: {result.stderr}", Colors.RED)
            return False

        log("   ✅ Secret version updated successfully", Colors.GREEN)
        return True

    except Exception as e:
        log(f"   ❌ Error managing secret: {e}", Colors.RED)
        return False


def ensure_artifact_registry(project_id: str, region: str) -> bool:
    """Ensure Artifact Registry repository exists for Cloud Functions."""
    log_step("Registry", "Ensuring Artifact Registry for Cloud Functions exists")

    repository_name = "cloud-functions"

    try:
        # Check if repository exists
        gcloud_cmd = get_gcloud_path()
        check_cmd = [
            gcloud_cmd,
            "artifacts",
            "repositories",
            "describe",
            repository_name,
            f"--location={region}",
            f"--project={project_id}",
            "--format=json",
        ]

        result = subprocess.run(check_cmd, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            # Repository doesn't exist, create it
            log(f"   📝 Creating Artifact Registry repository '{repository_name}'...")

            create_cmd = [
                gcloud_cmd,
                "artifacts",
                "repositories",
                "create",
                repository_name,
                "--repository-format=docker",
                f"--location={region}",
                f"--project={project_id}",
                "--description=Repository for Cloud Functions container images",
            ]

            result = subprocess.run(
                create_cmd, capture_output=True, text=True, check=False
            )

            if result.returncode != 0:
                log(
                    f"   ❌ Failed to create Artifact Registry: {result.stderr}",
                    Colors.RED,
                )
                return False

            log(f"   ✅ Artifact Registry '{repository_name}' created", Colors.GREEN)
        else:
            log(
                f"   ✅ Artifact Registry '{repository_name}' already exists",
                Colors.GREEN,
            )

        return True

    except Exception as e:
        log(f"   ❌ Error managing Artifact Registry: {e}", Colors.RED)
        return False


def prepare_requirements_file(source_dir: Path) -> bool:
    """Ensure a pinned requirements.txt exists for Cloud Functions deployment."""
    requirements_file = source_dir / "requirements.txt"
    pyproject_file = source_dir / "pyproject.toml"

    if requirements_file.exists():
        return True

    if not pyproject_file.exists():
        log("   ❌ No pyproject.toml found for requirements generation", Colors.RED)
        return False

    try:
        log("   📝 Generating requirements.txt from pyproject.toml...")

        # Generate requirements from pyproject.toml using uv
        result = subprocess.run(
            [
                "uv",
                "export",
                "--format",
                "requirements-txt",
                "--output-file",
                str(requirements_file),
            ],
            cwd=source_dir,
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            log(
                f"   ❌ Failed to generate requirements.txt: {result.stderr}",
                Colors.RED,
            )
            return False

        log("   ✅ requirements.txt generated successfully", Colors.GREEN)
        return True

    except Exception as e:
        log(f"   ❌ Error generating requirements.txt: {e}", Colors.RED)
        return False


def ensure_cloud_tasks_queue(project_id: str, region: str, environment: str) -> bool:
    """Ensure Cloud Tasks queue exists with environment-specific naming."""
    env_suffix = "dev" if environment == "development" else "prod"
    queue_name = f"rag-processing-queue-{env_suffix}"

    log_step("Queue", f"Ensuring Cloud Tasks queue '{queue_name}' exists")

    try:
        # Check if queue exists
        gcloud_cmd = get_gcloud_path()
        check_cmd = [
            gcloud_cmd,
            "tasks",
            "queues",
            "describe",
            queue_name,
            f"--location={region}",
            f"--project={project_id}",
        ]

        result = subprocess.run(check_cmd, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            # Queue doesn't exist, create it
            log(f"   📝 Creating Cloud Tasks queue '{queue_name}'...")

            create_cmd = [
                gcloud_cmd,
                "tasks",
                "queues",
                "create",
                queue_name,
                f"--location={region}",
                f"--project={project_id}",
                "--max-dispatches-per-second=10",
                "--max-concurrent-dispatches=100",
                "--max-attempts=3",
            ]

            result = subprocess.run(
                create_cmd, capture_output=True, text=True, check=False
            )

            if result.returncode == 0:
                log(f"   ✅ Cloud Tasks queue '{queue_name}' created", Colors.GREEN)
                return True
            else:
                log(f"   ❌ Failed to create queue: {result.stderr}", Colors.RED)
                return False
        else:
            log(f"   ✅ Cloud Tasks queue '{queue_name}' already exists", Colors.GREEN)
            return True

    except Exception as e:
        log(f"   ❌ Error managing Cloud Tasks queue: {e}", Colors.RED)
        return False


def deploy_gcs_handler_function(
    project_id: str,
    region: str,
    bucket_name: str,
    database_url: str,
    environment: str,
) -> bool:
    """Deploy the GCS handler as a Cloud Function Gen 2 with environment-specific configuration."""
    log_step("Deploy", "Deploying RAG GCS Handler Cloud Function Gen 2")

    # Get environment-specific configuration
    config = get_config(environment, service_type="queue-handler")
    env_suffix = "dev" if environment == "development" else "prod"
    function_name = f"rag-gcs-handler-{env_suffix}"
    gcs_handler_service_account = (
        f"rag-gcs-handler-{env_suffix}@{project_id}.iam.gserviceaccount.com"
    )
    task_processor_function_url = f"https://{region}-{project_id}.cloudfunctions.net/rag-task-processor-{env_suffix}"

    source_dir = Path(__file__).parent.parent / "apps/rag-gcs-handler"

    # Verify source directory exists
    if not source_dir.exists():
        log(f"   ❌ Source directory not found: {source_dir}", Colors.RED)
        return False

    # Store DATABASE_URL in Secret Manager with environment-specific name
    if not ensure_database_secret(
        project_id, database_url, config.database_secret_name
    ):
        log("   ❌ Failed to store DATABASE_URL in Secret Manager", Colors.RED)
        return False

    # Ensure Artifact Registry is set up
    if not ensure_artifact_registry(project_id, region):
        log(
            "   ⚠️  Could not ensure Artifact Registry, continuing anyway...",
            Colors.YELLOW,
        )

    time.sleep(2)

    # Ensure a pinned requirements.txt exists for Cloud Functions build
    if not prepare_requirements_file(source_dir):
        log("   ❌ Could not prepare requirements.txt for deployment", Colors.RED)
        return False

    # Environment-specific Cloud Tasks queue name
    queue_name = f"rag-processing-queue-{env_suffix}"

    # Separate secrets from regular environment variables
    env_vars = {
        "GOOGLE_CLOUD_PROJECT_ID": project_id,
        "GOOGLE_CLOUD_REGION": region,
        "CLOUD_TASKS_QUEUE_NAME": queue_name,
        "TASK_PROCESSOR_FUNCTION_URL": task_processor_function_url,
        "GCS_HANDLER_SERVICE_ACCOUNT": gcs_handler_service_account,
        "ENVIRONMENT": environment,
        "DATABASE_POOL_SIZE": str(config.database_pool_size),
        "DATABASE_MAX_OVERFLOW": str(config.database_max_overflow),
        "DATABASE_TIMEOUT": str(config.database_timeout),
    }

    env_vars_str = ",".join([f"{k}={v}" for k, v in env_vars.items()])
    secret_mapping = f"DATABASE_URL={config.database_secret_name}:latest"

    gcloud_cmd = get_gcloud_path()
    deploy_args = [
        gcloud_cmd,
        "functions",
        "deploy",
        function_name,
        "--gen2",
        "--runtime=python311",
        f"--region={region}",
        f"--source={source_dir}",
        "--trigger-event-filters=type=google.cloud.storage.object.v1.finalized",
        f"--trigger-event-filters=bucket={bucket_name}",
        f"--service-account={gcs_handler_service_account}",
        "--entry-point=handle_gcs_event",
        f"--memory={config.memory}",
        f"--cpu={config.cpu}",
        f"--max-instances={config.max_instances}",
        f"--min-instances={config.min_instances}",
        f"--concurrency={config.concurrency}",
        f"--timeout={config.timeout}s",
        "--allow-unauthenticated",
        f"--docker-repository=projects/{project_id}/locations/{region}/repositories/cloud-functions",
        f"--set-env-vars={env_vars_str}",
        f"--set-secrets={secret_mapping}",
    ]

    log(f"   📦 Deploying Cloud Function Gen 2: {function_name}")
    log(f"   📁 Source: {source_dir}")
    log(f"   🪣 Trigger bucket: {bucket_name}")
    log(f"   ⚙️  Queue: {queue_name} ")
    log(f"   🏷️  Environment: {environment}")

    try:
        # Deploy the function
        result = subprocess.run(
            deploy_args,
            capture_output=True,
            text=True,
            timeout=900,  # 15 minutes timeout
        )

        if result.returncode == 0:
            log(
                f"   ✅ GCS Handler function deployed successfully: {function_name}",
                Colors.GREEN,
            )
            return True
        else:
            log("   ❌ GCS Handler deployment failed", Colors.RED)
            if result.stderr:
                log(result.stderr, Colors.RED)
            return False

    except subprocess.TimeoutExpired:
        log("   ❌ GCS Handler deployment timed out after 15 minutes", Colors.RED)
        return False
    except Exception as e:
        log(f"   ❌ Error during deployment: {e}", Colors.RED)
        return False


def deploy_gcs_handler_pipeline(environment: str) -> int:
    """Main deployment function for GCS Handler with environment-specific configuration."""
    log(
        f"🚀 GCS Handler Deployment - {environment.upper()}",
        Colors.CYAN + Colors.BOLD,
    )
    log("=" * 50)

    # Load environment variables from environment-specific file
    env_file = get_environment_file_path(environment)
    if env_file.exists():
        log(f"📋 Loading environment from {env_file}")
        load_env_file(env_file)
    else:
        log(f"❌ Environment file not found: {env_file}", Colors.RED)
        log("Please run the setup script first:")
        if environment == "development":
            log("  npm run setup:gcp:dev")
        else:
            log("  npm run setup:gcp:prod")
        return 1

    # Get configuration from environment variables
    project_id = get_env_value("GOOGLE_CLOUD_PROJECT_ID")
    region = get_env_value("GOOGLE_CLOUD_REGION", "us-central1")
    bucket_name = get_env_value("GOOGLE_CLOUD_STORAGE_BUCKET")
    database_url = get_env_value("DATABASE_URL")

    # Validate required configuration
    missing_config = []
    if not project_id:
        missing_config.append("GOOGLE_CLOUD_PROJECT_ID")
    if not bucket_name:
        missing_config.append("GOOGLE_CLOUD_STORAGE_BUCKET")
    if not database_url:
        missing_config.append("DATABASE_URL")

    if missing_config:
        log(
            f"❌ Missing required configuration: {', '.join(missing_config)}",
            Colors.RED,
        )
        log(f"💡 Please set these in your {env_file.name} file", Colors.YELLOW)
        return 1

    log(f"📍 Project: {project_id}")
    log(f"📍 Region: {region}")
    log(f"📍 Bucket: {bucket_name}")
    log(f"📍 Environment: {environment}")
    log("")

    # Ensure environment-specific Cloud Tasks queue exists
    if not ensure_cloud_tasks_queue(project_id, region, environment):
        log("❌ Failed to ensure Cloud Tasks queue exists", Colors.RED)
        return 1

    # Deploy GCS Handler function
    if not deploy_gcs_handler_function(
        project_id,
        region,
        bucket_name,
        database_url,
        environment,
    ):
        log("❌ GCS Handler deployment failed", Colors.RED)
        log("")
        log("💡 Troubleshooting tips:", Colors.YELLOW)
        log("   1. Ensure all required APIs are enabled:", Colors.YELLOW)
        log("      - Cloud Functions API", Colors.YELLOW)
        log("      - Artifact Registry API", Colors.YELLOW)
        log("      - EventArc API", Colors.YELLOW)
        log("   2. Run: gcloud components update", Colors.YELLOW)
        env_suffix = "dev" if environment == "development" else "prod"
        log(
            f"   3. Try the deployment again: npm run deploy:gcs-handler:{env_suffix}",
            Colors.YELLOW,
        )
        return 1

    log("")
    log(
        f"🎉 GCS Handler for {environment.upper()} deployed successfully!",
        Colors.GREEN + Colors.BOLD,
    )
    log("")
    log("Next steps:", Colors.YELLOW)
    env_suffix = "dev" if environment == "development" else "prod"
    log(
        f"1. Deploy the Task Processor: npm run deploy:task-processor:{env_suffix}",
        Colors.YELLOW,
    )
    log("2. Test by uploading a file to your GCS bucket", Colors.YELLOW)
    log(
        f"3. Monitor logs: gcloud functions logs read rag-gcs-handler-{env_suffix} --gen2",
        Colors.YELLOW,
    )

    return 0
