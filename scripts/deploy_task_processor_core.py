#!/usr/bin/env python3
"""
Core Task Processor deployment logic - Environment-agnostic implementation.

This module deploys the Task Processor function (Consumer) that receives Cloud Tasks
and executes Cloud Run Jobs.

Features:
- Environment-aware service naming and configuration
- HTTP trigger for Cloud Tasks
- Cloud Run Jobs integration
- Proper IAM permissions setup
"""

import os
import subprocess
import time
from pathlib import Path

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


def deploy_task_processor_function(
    project_id: str,
    region: str,
    processor_job_name: str,
    environment: str,
) -> bool:
    """Deploy the Task Processor as a Cloud Function Gen 2 with environment-specific configuration."""
    log_step("Deploy", "Deploying RAG Task Processor Cloud Function Gen 2")

    env_suffix = "dev" if environment == "development" else "prod"
    function_name = f"rag-task-processor-{env_suffix}"
    task_processor_service_account = (
        f"rag-task-processor-{env_suffix}@{project_id}.iam.gserviceaccount.com"
    )

    source_dir = Path(__file__).parent.parent / "apps/rag-task-processor"

    # Verify source directory exists
    if not source_dir.exists():
        log(f"   ❌ Source directory not found: {source_dir}", Colors.RED)
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

    # Environment variables for Task Processor
    # CRITICAL: TASK_SERVICE_ACCOUNT should be the rag-processor SA (what the job runs as)
    # NOT the task-processor SA (what the function runs as)
    processor_service_account = (
        f"rag-processor-{env_suffix}@{project_id}.iam.gserviceaccount.com"
    )

    env_vars = {
        "GOOGLE_CLOUD_PROJECT_ID": project_id,
        "GOOGLE_CLOUD_REGION": region,
        "PROCESSOR_JOB_NAME": processor_job_name,
        "TASK_SERVICE_ACCOUNT": processor_service_account,  # What the Cloud Run Job runs as
        "ENVIRONMENT": environment,
    }

    env_vars_str = ",".join([f"{k}={v}" for k, v in env_vars.items()])

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
        "--entry-point=handle_cloud_task",
        "--trigger-http",
        f"--service-account={task_processor_service_account}",
        f"--set-env-vars={env_vars_str}",
        "--memory=512MiB",
        "--timeout=540s",
        "--max-instances=100",
        "--min-instances=0",
        f"--project={project_id}",
        "--no-allow-unauthenticated",  # Require authentication for security
        "--quiet",
    ]

    log(f"   🔧 Deploying function: {function_name}")

    try:
        result = subprocess.run(
            deploy_args,
            capture_output=True,
            text=True,
            timeout=900,  # 15 minutes timeout
        )

        if result.returncode == 0:
            log(
                f"   ✅ Task Processor function deployed successfully: {function_name}",
                Colors.GREEN,
            )

            # Configure IAM permissions for Cloud Tasks to invoke this function
            log("   🔐 Configuring Cloud Tasks invoke permissions...")
            gcs_handler_service_account = (
                f"rag-gcs-handler-{env_suffix}@{project_id}.iam.gserviceaccount.com"
            )

            try:
                # Grant GCS Handler service account permission to invoke Task Processor
                # For Gen2 Cloud Functions, use Cloud Run IAM commands since they're Cloud Run services
                log("   🔐 Granting GCS Handler permission to invoke Task Processor (Gen2)...")

                invoke_cmd = [
                    gcloud_cmd,
                    "run",
                    "services",
                    "add-iam-policy-binding",
                    function_name,
                    f"--region={region}",
                    f"--member=serviceAccount:{gcs_handler_service_account}",
                    "--role=roles/run.invoker",
                    f"--project={project_id}",
                    "--quiet",
                ]

                invoke_result = subprocess.run(
                    invoke_cmd,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )

                if invoke_result.returncode == 0:
                    log(
                        "   ✅ GCS Handler can now invoke Task Processor function",
                        Colors.GREEN,
                    )
                else:
                    log(
                        f"   ⚠️  Could not grant invoke permission: {invoke_result.stderr}",
                        Colors.YELLOW,
                    )
                    log("   💡 You may need to grant this permission manually:")
                    log(
                        f"      gcloud run services add-iam-policy-binding {function_name} \\"
                    )
                    log(f"        --region={region} \\")
                    log(
                        f"        --member=serviceAccount:{gcs_handler_service_account} \\"
                    )
                    log("        --role=roles/run.invoker")

            except Exception as iam_error:
                log(f"   ⚠️  IAM configuration failed: {iam_error}", Colors.YELLOW)

            return True
        else:
            log(f"   ❌ Task Processor deployment failed: {result.stderr}", Colors.RED)
            return False

    except subprocess.TimeoutExpired:
        log("   ❌ Task Processor deployment timed out after 15 minutes", Colors.RED)
        return False
    except Exception as e:
        log(f"   ❌ Error during Task Processor deployment: {e}", Colors.RED)
        return False


def deploy_task_processor_pipeline(environment: str) -> int:
    """Main deployment function for Task Processor with environment-specific configuration."""
    log(
        f"🚀 Task Processor Deployment - {environment.upper()}",
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
    processor_job_name = get_env_value("PROCESSOR_JOB_NAME")

    # Validate required configuration
    missing_config = []
    if not project_id:
        missing_config.append("GOOGLE_CLOUD_PROJECT_ID")
    if not processor_job_name:
        missing_config.append("PROCESSOR_JOB_NAME")

    if missing_config:
        log(
            f"❌ Missing required configuration: {', '.join(missing_config)}",
            Colors.RED,
        )
        log(f"💡 Please set these in your {env_file.name} file", Colors.YELLOW)
        return 1

    log(f"📍 Project: {project_id}")
    log(f"📍 Region: {region}")
    log(f"📍 Processor Job: {processor_job_name}")
    log(f"📍 Environment: {environment}")
    log("")

    # Deploy Task Processor function
    if not deploy_task_processor_function(
        project_id,
        region,
        processor_job_name,
        environment,
    ):
        log("❌ Task Processor deployment failed", Colors.RED)
        log("")
        log("💡 Troubleshooting tips:", Colors.YELLOW)
        log("   1. Ensure all required APIs are enabled:", Colors.YELLOW)
        log("      - Cloud Functions API", Colors.YELLOW)
        log("      - Artifact Registry API", Colors.YELLOW)
        log("      - Cloud Run API", Colors.YELLOW)
        log("   2. Run: gcloud components update", Colors.YELLOW)
        env_suffix = "dev" if environment == "development" else "prod"
        log(
            f"   3. Try the deployment again: npm run deploy:task-processor:{env_suffix}",
            Colors.YELLOW,
        )
        return 1

    log("")
    log(
        f"🎉 Task Processor for {environment.upper()} deployed successfully!",
        Colors.GREEN + Colors.BOLD,
    )
    log("")
    log("🎯 Deployment Complete!", Colors.GREEN + Colors.BOLD)
    log("")
    log("Your complete RAG processing pipeline is now deployed:", Colors.YELLOW)
    log("  ✅ RAG Processor service (Cloud Run job)", Colors.GREEN)
    log("  ✅ GCS Handler (Cloud Function)", Colors.GREEN)
    log("  ✅ Task Processor (Cloud Function)", Colors.GREEN)
    log("")
    log("Next steps:", Colors.YELLOW)
    env_suffix = "dev" if environment == "development" else "prod"
    log("1. Test by uploading a file in your documents page in the web app", Colors.YELLOW)
    log(
        f"2. Monitor logs: gcloud functions logs read rag-task-processor-{env_suffix} --gen2",
        Colors.YELLOW,
    )

    return 0
