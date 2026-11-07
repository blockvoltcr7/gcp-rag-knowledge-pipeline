#!/usr/bin/env python3
"""
Google Cloud Platform Shared Utilities
Common functions for GCP setup and deployment scripts

This module provides shared utilities for:
- Command execution with error handling
- Parallel command execution
- API enabling and verification
- Service account readiness checks
- Consistent logging and colors
"""

import shlex
import subprocess
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from shutil import which
from typing import Any, TypedDict

# Import lightweight utility modules from scripts directory
from .error_handling import ErrorContext, ServiceError

# =============================================================================
# CROSS-PLATFORM COMMAND HELPERS
# =============================================================================


def get_gcloud_path() -> str:
    """Get the full path to gcloud command for cross-platform compatibility.

    On Windows, gcloud is a .CMD file which subprocess can't find without
    the full path. This helper ensures gcloud works on Windows, Mac, and Linux.

    Returns:
        Full path to gcloud command

    Raises:
        RuntimeError: If gcloud is not found in PATH
    """
    gcloud_path = which("gcloud")
    if not gcloud_path:
        raise RuntimeError(
            "gcloud command not found in PATH. "
            "Please install Google Cloud SDK: https://cloud.google.com/sdk/docs/install"
        )
    return gcloud_path


# =============================================================================
# CONFIGURATION TYPES
# =============================================================================


class DeploymentConfig(TypedDict):
    """Typed configuration for deployment operations.

    Required fields are typed as str (never None).
    Optional fields are typed as str | None.
    """

    project_id: str  # Required - validated during environment loading
    region: str  # Required - has default value
    service_name: str  # Required - from CONFIG
    image_name: str  # Required - built during deployment
    rag_service_account: str  # Required - validated to exist
    bucket_name: str | None  # Optional - can be None if not configured


# =============================================================================
# STANDARDIZED ERROR HANDLING
# =============================================================================


class DeploymentError(Exception):
    """Errors during deployment operations"""

    pass


class ResourceNotFoundError(Exception):
    """Resource doesn't exist (expected in some cases)"""

    pass


class ConfigurationError(Exception):
    """Configuration validation errors"""

    pass


class ErrorHandlingStrategy:
    """Base class for different error handling approaches"""

    def handle_error(self, error: Exception, context: str, operation: str) -> None:
        raise NotImplementedError

    def should_log_error(self, error: Exception) -> bool:
        """Determine if error should be logged"""
        return True


class LoggedErrorHandler(ErrorHandlingStrategy):
    """Use ErrorContext for operations that should be logged"""

    def handle_error(self, error: Exception, context: str, operation: str) -> None:
        with ErrorContext(f"{context} - {operation}"):
            raise error


class SilentErrorHandler(ErrorHandlingStrategy):
    """For operations where errors are expected (e.g., checking existence)"""

    def handle_error(self, error: Exception, context: str, operation: str) -> None:
        # Log at debug level only for expected errors
        if isinstance(error, subprocess.CalledProcessError) and error.returncode != 0:
            # Expected failure (e.g., resource doesn't exist)
            pass
        else:
            # Unexpected error - still log it
            log_error(f"Unexpected error in {operation}: {error}")
        raise error

    def should_log_error(self, error: Exception) -> bool:
        """Silent handler typically doesn't log expected errors"""
        return False


class RetryErrorHandler(ErrorHandlingStrategy):
    """For operations that should retry on failure"""

    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries

    def handle_error(self, error: Exception, context: str, operation: str) -> None:
        # This will be used by subprocess strategy for retry logic
        raise error


# =============================================================================
# STANDARDIZED SUBPROCESS EXECUTION
# =============================================================================


class SubprocessStrategy:
    """Standardized subprocess execution with consistent error handling"""

    def __init__(self, timeout: int = 300, use_shell: bool = False):
        self.timeout = timeout
        self.use_shell = use_shell
        self.default_handler = LoggedErrorHandler()

    def run_command(
        self,
        command: str | list[str],
        input_data: str | None = None,
        error_handler: ErrorHandlingStrategy | None = None,
    ) -> str:
        """Execute command with standardized error handling

        Cross-platform gcloud handling: Automatically uses full gcloud path
        for Windows .CMD compatibility and proper quote handling.
        """
        handler = error_handler or self.default_handler

        try:
            if isinstance(command, str) and not self.use_shell:
                # CROSS-PLATFORM FIX: Handle gcloud commands for Windows
                if command.strip().startswith("gcloud"):
                    # Parse and replace gcloud with full path
                    gcloud_cmd = get_gcloud_path()
                    command = shlex.split(command)
                    command[0] = gcloud_cmd
                else:
                    # Use shlex.split() for proper cross-platform parsing
                    # Handles quotes, spaces, and escape characters correctly
                    command = shlex.split(command)

            result = subprocess.run(
                command,
                input=input_data,
                text=True,
                check=True,
                capture_output=True,
                timeout=self.timeout,
                shell=self.use_shell,
            )
            return result.stdout.strip()

        except subprocess.CalledProcessError as e:
            operation = f"Command: {' '.join(command) if isinstance(command, list) else command}"
            handler.handle_error(e, "Subprocess execution", operation)
            raise
        except subprocess.TimeoutExpired as e:
            operation = f"Command timeout: {' '.join(command) if isinstance(command, list) else command}"
            handler.handle_error(e, "Subprocess timeout", operation)
            raise
        except Exception as e:
            operation = f"Command error: {' '.join(command) if isinstance(command, list) else command}"
            handler.handle_error(e, "Subprocess error", operation)
            raise

    def run_silent(self, command: str | list[str]) -> bool:
        """Execute command silently (for existence checks)"""
        try:
            self.run_command(command, error_handler=SilentErrorHandler())
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False

    def run_with_retry(
        self,
        command: str | list[str],
        max_retries: int = 3,
        input_data: str | None = None,
    ) -> str:
        """Execute command with retry logic"""
        last_error = None

        for attempt in range(max_retries):
            try:
                return self.run_command(command, input_data=input_data)
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait_time = 2**attempt  # Exponential backoff
                    log_warning(
                        f"Command failed (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)
                else:
                    log_error(f"Command failed after {max_retries} attempts")

        # Re-raise the last error
        if last_error:
            raise last_error

        # Should never reach here, but satisfy type checker
        raise RuntimeError("Unexpected error: no exception to re-raise")


# Global subprocess strategy instances
default_subprocess = SubprocessStrategy()
shell_subprocess = SubprocessStrategy(use_shell=True)
silent_subprocess = SubprocessStrategy()


# =============================================================================
# STANDARDIZED COMMAND PATTERNS
# =============================================================================


def run_deployment_command(cmd: str | list[str]) -> str:
    """For deployment operations - use ErrorContext"""
    return default_subprocess.run_command(cmd, error_handler=LoggedErrorHandler())


def check_resource_exists(cmd: str | list[str]) -> bool:
    """For existence checks - silent failures"""
    return default_subprocess.run_silent(cmd)


def run_with_user_input(cmd: list[str], input_data: str) -> str:
    """For commands with sensitive input"""
    return default_subprocess.run_command(cmd, input_data=input_data)


def run_gcp_command(
    cmd: list[str] | str, capture_output: bool = False, **kwargs: Any
) -> subprocess.CompletedProcess[str]:
    """Execute GCP command and return subprocess result (for compatibility with test scripts)"""
    try:
        if isinstance(cmd, list):
            result = subprocess.run(
                cmd, capture_output=capture_output, text=True, timeout=300, **kwargs
            )
        else:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=capture_output,
                text=True,
                timeout=300,
                **kwargs,
            )
        return result
    except subprocess.TimeoutExpired as e:
        raise ServiceError(f"Command timed out: {cmd}") from e
    except Exception as e:
        raise ServiceError(f"Command failed: {cmd}") from e


def run_gcloud_command(cmd: str, project_id: str | None = None) -> str:
    """Standardized gcloud command execution"""
    # Add gcloud prefix if not present
    if not cmd.startswith("gcloud "):
        cmd = f"gcloud {cmd}"

    if project_id:
        # Special case: gcloud config set project uses positional argument
        if "gcloud config set project" in cmd:
            cmd = f"{cmd} {project_id}"
        else:
            # Standard case: most gcloud commands use --project flag
            cmd = f"{cmd} --project={project_id}"
    return run_deployment_command(cmd)


def run_shell_command(cmd: str) -> str:
    """For shell commands that need pipes or complex syntax"""
    return shell_subprocess.run_command(cmd, error_handler=LoggedErrorHandler())


class Colors:
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    RED = "\033[0;31m"
    BLUE = "\033[0;34m"
    CYAN = "\033[0;36m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


def log(message: str, color: str = Colors.RESET) -> None:
    """Print colored log message"""
    print(f"{color}{message}{Colors.RESET}")


def log_step(step: str, message: str) -> None:
    """Log a step with consistent formatting"""
    log(f"{Colors.BLUE}[{step}]{Colors.RESET} {message}")


def log_success(message: str) -> None:
    """Log success message"""
    log(f"✅ {message}", Colors.GREEN)


def log_warning(message: str) -> None:
    """Log warning message"""
    log(f"⚠️  {message}", Colors.YELLOW)


def log_error(message: str) -> None:
    """Log error message"""
    log(f"❌ {message}", Colors.RED)


def run_command(
    cmd: str,
    check: bool = True,
    capture_output: bool = True,
    cwd: str | None = None,
    show_output: bool = False,
    timeout: int = 600,  # 10 minutes default
) -> str:
    """Execute shell command with proper error handling using ErrorContext

    Cross-platform gcloud handling: Automatically uses full gcloud path and list format
    for Windows compatibility (handles .CMD files and quote issues).
    """
    # Auto-handle gcloud commands for Windows compatibility
    if isinstance(cmd, str) and cmd.strip().startswith("gcloud"):
        try:
            gcloud_cmd = get_gcloud_path()
            # Parse command with shlex (handles quotes, spaces, escape chars properly)
            cmd_parts = shlex.split(cmd)
            # Replace "gcloud" with full path for Windows .CMD compatibility
            cmd_parts[0] = gcloud_cmd

            # Execute with list format (cross-platform, avoids cmd.exe quote issues)
            with ErrorContext(f"gcloud command: {cmd[:50]}..."):
                result = subprocess.run(
                    cmd_parts,
                    capture_output=capture_output,
                    text=True,
                    check=check,
                    cwd=cwd,
                    timeout=timeout,
                )
                if show_output:
                    return ""
                return result.stdout.strip() if capture_output else ""
        except subprocess.TimeoutExpired as e:
            raise ServiceError(
                f"Command timed out after {timeout} seconds: {cmd}"
            ) from e
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.strip() if e.stderr else "Unknown error"
            raise ServiceError(
                f"gcloud command failed: {cmd}\nError: {error_msg}"
            ) from e
        except Exception as e:
            raise ServiceError(f"Failed to execute gcloud command: {cmd}") from e

    # For non-gcloud commands, use existing shell strategy
    strategy = SubprocessStrategy(timeout=timeout, use_shell=True)

    if show_output:
        # For show_output, we need to handle it differently
        try:
            with ErrorContext(f"Command execution: {cmd[:50]}..."):
                subprocess.run(
                    cmd, shell=True, check=check, cwd=cwd, text=True, timeout=timeout
                )
                return ""  # Return empty string when showing output
        except subprocess.TimeoutExpired as e:
            raise ServiceError(
                f"Command timed out after {timeout} seconds: {cmd}"
            ) from e
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.strip() if e.stderr else "Unknown error"
            raise ServiceError(f"Command failed: {cmd}\nError: {error_msg}") from e
    else:
        # Use standardized error handling for regular commands
        try:
            return strategy.run_command(cmd, error_handler=LoggedErrorHandler())
        except subprocess.TimeoutExpired as e:
            raise ServiceError(
                f"Command timed out after {timeout} seconds: {cmd}"
            ) from e
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.strip() if e.stderr else "Unknown error"
            raise ServiceError(f"Command failed: {cmd}\nError: {error_msg}") from e

    # This should never be reached due to exception handling above
    return ""


def run_commands_parallel(
    commands: list[tuple[str, str]], max_workers: int = 5
) -> list[tuple[str, bool, str]]:
    """
    Execute multiple shell commands in parallel with proper error handling.

    Args:
        commands: List of tuples (description, command)
        max_workers: Maximum number of concurrent workers

    Returns:
        List of tuples (description, success, error_message)
    """
    results = []

    def execute_command(desc_cmd: tuple[str, str]) -> tuple[str, bool, str]:
        description, cmd = desc_cmd
        try:
            with ErrorContext(f"Parallel command: {description}"):
                result = run_command(cmd)
                return (description, True, result)
        except Exception as e:
            return (description, False, str(e))

        # This should never be reached due to exception handling above
        return (description, False, "Unknown error")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all commands
        future_to_desc = {
            executor.submit(execute_command, desc_cmd): desc_cmd[0]
            for desc_cmd in commands
        }

        # Collect results as they complete
        for future in as_completed(future_to_desc):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                desc = future_to_desc[future]
                results.append((desc, False, str(e)))

    return results


def check_commands_parallel(
    commands: list[tuple[str, str]], max_workers: int = 5
) -> list[tuple[str, bool, str]]:
    """
    Execute multiple existence check commands in parallel without error logging.

    This is for commands like 'gcloud secrets describe' where failure is expected
    when the resource doesn't exist, and we don't want to log these as errors.

    Args:
        commands: List of tuples (description, command)
        max_workers: Maximum number of concurrent workers

    Returns:
        List of tuples (description, success, output_or_error)
    """
    results = []

    def execute_check_command(desc_cmd: tuple[str, str]) -> tuple[str, bool, str]:
        description, cmd = desc_cmd
        try:
            # Use the new silent subprocess strategy
            result = silent_subprocess.run_command(
                cmd, error_handler=SilentErrorHandler()
            )
            return (description, True, result)
        except subprocess.CalledProcessError as e:
            return (
                description,
                False,
                e.stderr.strip() if e.stderr else "Command failed",
            )
        except Exception as e:
            return (description, False, str(e))

        # This should never be reached due to exception handling above
        return (description, False, "Unknown error")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all commands
        future_to_desc = {
            executor.submit(execute_check_command, desc_cmd): desc_cmd[0]
            for desc_cmd in commands
        }

        # Collect results as they complete
        for future in as_completed(future_to_desc):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                desc = future_to_desc[future]
                results.append((desc, False, str(e)))

    return results


def wait_for_service_account_readiness(
    check_function: Callable[[], bool],
    description: str,
    max_wait_minutes: int = 5,
    check_interval_seconds: int = 5,
    initial_wait_seconds: int = 5,
) -> bool:
    """
    Wait for service account permissions to propagate and become ready.

    This function handles the common issue where GCP service account permissions
    need time to propagate across Google's infrastructure.

    Args:
        check_function: Function that returns True when the service account is ready
        description: Human-readable description of what we're waiting for
        max_wait_minutes: Maximum time to wait in minutes (default: 5)
        check_interval_seconds: How often to check in seconds (default: 15)
        initial_wait_seconds: Initial wait before first check (default: 10)

    Returns:
        True if service account is ready, False if timeout exceeded

    Example:
        if wait_for_service_account_readiness(
            lambda: check_eventarc_service_agent_permissions(project_id, eventarc_service_account),
            "EventArc service agent permissions",
            max_wait_minutes=5
        ):
            log_success("EventArc service agent is ready")
        else:
            log_error("EventArc service agent not ready after 5 minutes")
    """
    log(f"⏳ Waiting for {description} to be ready...", Colors.YELLOW)
    log(f"   Initial wait: {initial_wait_seconds}s (allows for immediate propagation)")

    # Initial wait to allow for immediate propagation
    time.sleep(initial_wait_seconds)

    max_checks = (max_wait_minutes * 60) // check_interval_seconds
    start_time = time.time()

    for attempt in range(max_checks):
        try:
            if check_function():
                elapsed_time = time.time() - start_time
                log_success(f"{description} is ready (took {elapsed_time:.1f}s)")
                return True
        except Exception as e:
            log(f"   Check attempt {attempt + 1} failed: {e}", Colors.YELLOW)

        if attempt < max_checks - 1:  # Don't wait after the last attempt
            elapsed_time = time.time() - start_time
            remaining_time = (max_wait_minutes * 60) - elapsed_time
            log(
                f"   Not ready yet, retrying in {check_interval_seconds}s... (attempt {attempt + 1}/{max_checks}, {remaining_time:.0f}s remaining)"
            )
            time.sleep(check_interval_seconds)

    elapsed_time = time.time() - start_time
    log_error(
        f"{description} not ready after {elapsed_time:.1f}s (max: {max_wait_minutes}m)"
    )
    return False


def wait_for_cloud_run_service_ready(
    service_name: str,
    region: str,
    project_id: str,
    max_wait_minutes: int = 3,
    check_interval_seconds: int = 10,
    initial_wait_seconds: int = 5,
) -> str | None:
    """
    Wait for a Cloud Run service to be ready and return its URL.

    This function handles the common issue where Cloud Run services
    need time to be fully deployed and accessible after the gcloud deploy command.

    Args:
        service_name: Name of the Cloud Run service
        region: GCP region where the service is deployed
        project_id: GCP project ID
        max_wait_minutes: Maximum time to wait in minutes (default: 3)
        check_interval_seconds: How often to check in seconds (default: 10)
        initial_wait_seconds: Initial wait before first check (default: 5)

    Returns:
        Service URL if ready, None if timeout exceeded

    Example:
        service_url = wait_for_cloud_run_service_ready(
            "my-service", "us-central1", "my-project"
        )
        if service_url:
            log_success(f"Service ready at: {service_url}")
        else:
            log_error("Service not ready after timeout")
    """
    description = f"Cloud Run service {service_name}"
    log(f"⏳ Waiting for {description} to be ready...", Colors.YELLOW)
    log(f"   Initial wait: {initial_wait_seconds}s (allows for deployment propagation)")

    # Initial wait to allow for deployment propagation
    time.sleep(initial_wait_seconds)

    max_checks = (max_wait_minutes * 60) // check_interval_seconds
    start_time = time.time()

    for attempt in range(max_checks):
        try:
            # Use list format for cross-platform compatibility (Windows, Mac, Linux)
            gcloud_cmd = get_gcloud_path()
            result = subprocess.run(
                [
                    gcloud_cmd,
                    "run",
                    "services",
                    "describe",
                    service_name,
                    f"--region={region}",
                    f"--project={project_id}",
                    "--format=value(status.url)",  # No quotes needed in list format
                    "--quiet",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0 and result.stdout.strip():
                service_url = result.stdout.strip()
                elapsed_time = time.time() - start_time
                log_success(f"{description} is ready (took {elapsed_time:.1f}s)")
                return service_url

        except Exception as e:
            log(f"   Check attempt {attempt + 1} failed: {e}", Colors.YELLOW)

        if attempt < max_checks - 1:  # Don't wait after the last attempt
            elapsed_time = time.time() - start_time
            remaining_time = (max_wait_minutes * 60) - elapsed_time
            log(
                f"   Not ready yet, retrying in {check_interval_seconds}s... (attempt {attempt + 1}/{max_checks}, {remaining_time:.0f}s remaining)"
            )
            time.sleep(check_interval_seconds)

    elapsed_time = time.time() - start_time
    log_error(
        f"{description} not ready after {elapsed_time:.1f}s (max: {max_wait_minutes}m)"
    )
    return None


def get_project_number(project_id: str) -> str:
    """Get the project number for a given project ID."""
    try:
        result = run_command(
            f"gcloud projects describe {project_id} --format='value(projectNumber)'",
            capture_output=True,
        )
        return result.strip()
    except Exception as e:
        raise Exception(f"Failed to get project number for {project_id}: {e}") from e


def ensure_service_agent_exists(
    project_id: str, service_type: str, region: str = "us-central1"
) -> str:
    """
    Ensure a GCP service agent exists and return its email.

    Args:
        project_id: GCP project ID
        service_type: Type of service agent ('eventarc' or 'cloudstorage')
        region: GCP region (required for EventArc operations)

    Returns:
        Service agent email address

    Raises:
        Exception: If service agent creation fails
    """
    # Get project number first
    project_number = get_project_number(project_id)

    # Construct service agent email based on type
    if service_type == "eventarc":
        service_agent_email = (
            f"service-{project_number}@gcp-sa-eventarc.iam.gserviceaccount.com"
        )
    elif service_type == "cloudstorage":
        service_agent_email = (
            f"service-{project_number}@gs-project-accounts.iam.gserviceaccount.com"
        )
    else:
        raise ValueError(f"Unsupported service type: {service_type}")

    # Check if service agent exists - use subprocess directly to avoid ErrorContext logging
    gcloud_cmd = get_gcloud_path()
    result = subprocess.run(
        [
            gcloud_cmd,
            "iam",
            "service-accounts",
            "describe",
            service_agent_email,
            f"--project={project_id}",
            "--quiet",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        log(f"✅ {service_type} service agent already exists", Colors.GREEN)
        return service_agent_email
    else:
        log(f"🔧 Creating {service_type} service agent...", Colors.YELLOW)
        log(
            f"   💡 {service_type.title()} service agent is created automatically when {service_type.title()} API is used"
        )

    # For EventArc, try to trigger service agent creation by using the API
    if service_type == "eventarc":
        log("   🔄 Attempting to trigger service agent creation...")
        try:
            # Try to list triggers to trigger service agent creation
            run_command(
                f"gcloud eventarc triggers list --location={region} --project={project_id}",
                capture_output=True,
            )
        except Exception as e:
            log(f"⚠️  Could not create {service_type} service agent: {e}")
            log("   💡 This is normal if the service hasn't been used yet")
            log("   🔄 Service agent will be created automatically when needed")

    # For Cloud Storage, the service agent is created when the API is used
    elif service_type == "cloudstorage":
        log("   🔄 Cloud Storage service agent is created automatically")
        log("   💡 It will be available when Cloud Storage API is first used")

    # Return the email even if we couldn't verify creation
    # The service agent will be created when needed by GCP
    return service_agent_email


def check_eventarc_service_agent_permissions(project_id: str) -> bool:
    """
    Check if EventArc service agent has the required permissions.

    Args:
        project_id: GCP project ID

    Returns:
        True if permissions are properly configured, False otherwise
    """
    try:
        # Ensure EventArc service agent exists
        eventarc_service_agent = ensure_service_agent_exists(project_id, "eventarc")

        # Check if the service agent has the eventarc.serviceAgent role
        result = run_command(
            f"gcloud projects get-iam-policy {project_id} --flatten='bindings[].members' "
            f"--format='table(bindings.role)' --filter='bindings.members:serviceAccount:{eventarc_service_agent}'",
            capture_output=True,
        )

        return "roles/eventarc.serviceAgent" in result

    except Exception as e:
        log(f"Error checking EventArc service agent permissions: {e}", Colors.RED)
        return False


def check_cloud_storage_service_agent_permissions(project_id: str) -> bool:
    """
    Check if Cloud Storage service agent has the required Pub/Sub permissions.

    Args:
        project_id: GCP project ID

    Returns:
        True if permissions are properly configured, False otherwise
    """
    try:
        # Ensure Cloud Storage service agent exists
        storage_service_agent = ensure_service_agent_exists(project_id, "cloudstorage")

        # Check if the service agent has the pubsub.publisher role
        result = run_command(
            f"gcloud projects get-iam-policy {project_id} --flatten='bindings[].members' "
            f"--format='table(bindings.role)' --filter='bindings.members:serviceAccount:{storage_service_agent}'",
            capture_output=True,
        )

        return "roles/pubsub.publisher" in result

    except Exception as e:
        log(f"Error checking Cloud Storage service agent permissions: {e}", Colors.RED)
        return False


def check_service_account_secret_access(
    project_id: str, service_account: str, secret_name: str
) -> bool:
    """
    Check if a service account has access to a specific secret.

    Args:
        project_id: Google Cloud project ID
        service_account: Service account email
        secret_name: Name of the secret

    Returns:
        True if service account can access the secret, False otherwise
    """
    try:
        # Check if service account has secret accessor role for the specific secret
        gcloud_cmd = get_gcloud_path()
        result = subprocess.run(
            [
                gcloud_cmd,
                "secrets",
                "get-iam-policy",
                secret_name,
                f"--project={project_id}",
                "--flatten=bindings[].members",
                "--format=table(bindings.role)",
                f"--filter=bindings.members:serviceAccount:{service_account}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return False

        # Check if the secret accessor role is present
        return "roles/secretmanager.secretAccessor" in result.stdout

    except Exception:
        return False


def check_cloud_run_invoke_permissions(
    project_id: str, region: str, service_name: str, service_account: str
) -> bool:
    """
    Check if a service account has permission to invoke a Cloud Run service.

    Args:
        project_id: Google Cloud project ID
        region: Cloud Run service region
        service_name: Cloud Run service name
        service_account: Service account email

    Returns:
        True if service account can invoke the service, False otherwise
    """
    try:
        # Check if service account has run.invoker role for the specific service
        gcloud_cmd = get_gcloud_path()
        result = subprocess.run(
            [
                gcloud_cmd,
                "run",
                "services",
                "get-iam-policy",
                service_name,
                f"--region={region}",
                f"--project={project_id}",
                "--flatten=bindings[].members",
                "--format=table(bindings.role)",
                f"--filter=bindings.members:serviceAccount:{service_account}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return False

        # Check if the run.invoker role is present
        return "roles/run.invoker" in result.stdout

    except Exception:
        return False


# =============================================================================
# API READINESS TESTING
# =============================================================================


class APITester:
    """Strategy pattern for testing different API readiness"""

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.timeout = 30

    def test_api(self, api: str) -> bool:
        """Test if an API is ready for use"""
        try:
            tester_func = self._get_api_tester(api)
            return tester_func()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False

    def _get_api_tester(self, api: str) -> Callable[[], bool]:
        """Get the appropriate tester function for an API"""
        testers = {
            "run.googleapis.com": self._test_cloud_run,
            "cloudbuild.googleapis.com": self._test_cloud_build,
            "secretmanager.googleapis.com": self._test_secret_manager,
        }
        return testers.get(api, lambda: self._test_generic_api(api))

    def _test_cloud_run(self) -> bool:
        """Test Cloud Run API by listing services"""
        run_gcloud_command("gcloud run services list --quiet", self.project_id)
        return True

    def _test_cloud_build(self) -> bool:
        """Test Cloud Build API by listing builds"""
        run_gcloud_command("gcloud builds list --limit=1 --quiet", self.project_id)
        return True

    def _test_secret_manager(self) -> bool:
        """Test Secret Manager API by listing secrets"""
        run_gcloud_command("gcloud secrets list --limit=1 --quiet", self.project_id)
        return True

    def _test_generic_api(self, api: str) -> bool:
        """Test generic API by verifying it's enabled"""
        result = run_gcloud_command(
            f"gcloud services list --enabled --filter=name:{api} --quiet",
            self.project_id,
        )
        if api not in result:
            raise subprocess.CalledProcessError(
                1, f"API {api} not found in enabled services"
            )
        return True


def check_api_readiness(project_id: str, apis: list[str], max_retries: int = 5) -> bool:
    """
    Verify that APIs are actually ready for use, not just enabled.

    Args:
        project_id: Google Cloud project ID
        apis: List of API service names to check
        max_retries: Maximum number of retry attempts

    Returns:
        True if all APIs are ready, False otherwise
    """
    log("   🔍 Verifying APIs are ready for use...")

    api_tester = APITester(project_id)

    for attempt in range(max_retries):
        all_ready = True
        failed_apis = []

        for api in apis:
            if not api_tester.test_api(api):
                all_ready = False
                failed_apis.append(api)

        if all_ready:
            log_success("All APIs are ready for use")
            return True

        if attempt < max_retries - 1:
            wait_time = min(
                10 + (attempt * 5), 30
            )  # Progressive backoff: 10s, 15s, 20s, 25s, 30s
            log(
                f"   ⏳ APIs not ready yet ({', '.join(failed_apis)}), retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})"
            )
            time.sleep(wait_time)
        else:
            log_error(
                f"APIs still not ready after {max_retries} attempts: {', '.join(failed_apis)}"
            )
            return False

    return False


def enable_and_verify_apis(project_id: str, environment: str = "development") -> None:
    """Enable required Google Cloud APIs and verify they're ready for use"""
    log_step("APIs", "Enabling and verifying Google Cloud APIs...")
    log("   💡 This may take a few minutes...")

    # Base APIs required for all environments
    apis = BASE_REQUIRED_APIS.copy()

    # Add production-specific APIs
    if environment.lower() == "production":
        apis.extend(PRODUCTION_ADDITIONAL_APIS)

    # Prepare commands for parallel execution
    commands = []
    for api in apis:
        cmd = f"gcloud services enable {api} --project={project_id}"
        commands.append((api, cmd))

    # Execute APIs in parallel (saves ~50-60 seconds vs sequential)
    log("   💨 Enabling APIs in parallel...")
    results = run_commands_parallel(commands, max_workers=8)

    # Process results
    success_count = 0
    failed_apis = []
    for api, success, error in results:
        if success:
            log(f"  ✓ {api}")
            success_count += 1
        else:
            log_warning(f"Could not enable {api}: {error}")
            failed_apis.append(api)

    if failed_apis:
        log_error(f"Failed to enable APIs: {', '.join(failed_apis)}")
        log("This will likely cause deployment failures. Please check:")
        log("  • Project billing is enabled")
        log("  • You have proper permissions")
        log("  • Project exists and is accessible")
        raise ServiceError(f"Failed to enable required APIs: {', '.join(failed_apis)}")

    log_success(
        f"All Google Cloud APIs enabled successfully ({success_count}/{len(apis)})"
    )

    # Verify APIs are actually ready for use
    if not check_api_readiness(project_id, apis):
        log_error("APIs were enabled but are not ready for use")
        log("This can happen when:")
        log("  • APIs are still propagating (usually takes 1-2 minutes)")
        log("  • There are permission issues")
        log("  • Project billing is not properly configured")
        raise ServiceError("APIs not ready for use after enabling")

    log_success("APIs enabled and verified ready for use")


# =============================================================================
# SECRET MANAGEMENT
# =============================================================================


def create_or_update_secret(
    secret_name: str, secret_value: str, project_id: str
) -> None:
    """Create or update secret in Google Secret Manager"""
    # Check if secret exists - use silent check to avoid logging expected failures
    exists = check_resource_exists(
        f"gcloud secrets describe {secret_name} --project={project_id} --quiet"
    )

    gcloud_cmd = get_gcloud_path()

    if exists:
        log(f"   Updating secret: {secret_name}")
        # Use standardized secure input method
        run_with_user_input(
            [
                gcloud_cmd,
                "secrets",
                "versions",
                "add",
                secret_name,
                "--data-file=-",
                f"--project={project_id}",
            ],
            secret_value,
        )
    else:
        log(f"   Creating secret: {secret_name}")
        try:
            # Use standardized secure input method
            run_with_user_input(
                [
                    gcloud_cmd,
                    "secrets",
                    "create",
                    secret_name,
                    "--data-file=-",
                    f"--project={project_id}",
                ],
                secret_value,
            )
        except Exception:
            # Fallback: secret might have been created by another process
            log(f"   Secret creation failed, attempting update: {secret_name}")
            run_with_user_input(
                [
                    gcloud_cmd,
                    "secrets",
                    "versions",
                    "add",
                    secret_name,
                    "--data-file=-",
                    f"--project={project_id}",
                ],
                secret_value,
            )


def grant_secret_permissions(
    secret_names: list[str], service_account: str, project_id: str
) -> None:
    """Grant secret access permissions to a service account"""
    log(f"   Service account: {service_account}")

    for secret_name in secret_names:
        log(f"   Granting access to {secret_name}...")
        run_gcloud_command(
            f"gcloud secrets add-iam-policy-binding {secret_name} "
            f"--member=serviceAccount:{service_account} "
            f"--role=roles/secretmanager.secretAccessor",
            project_id,
        )


# =============================================================================
# API CONFIGURATION
# =============================================================================

# Base APIs required for all environments
BASE_REQUIRED_APIS = [
    "cloudbuild.googleapis.com",
    "run.googleapis.com",
    "storage.googleapis.com",
    "secretmanager.googleapis.com",
    "eventarc.googleapis.com",
    "aiplatform.googleapis.com",
    "visionai.googleapis.com",  # Vision AI API for multimodal embeddings
    "speech.googleapis.com",
    "pubsub.googleapis.com",
    "cloudtasks.googleapis.com",  # Cloud Tasks for queue-based processing
    "artifactregistry.googleapis.com",  # Artifact Registry for Docker images
]

# Production-specific APIs
PRODUCTION_ADDITIONAL_APIS = [
    "billingbudgets.googleapis.com",
    "monitoring.googleapis.com",
    "logging.googleapis.com",
]


def enable_apis_only(project_id: str, environment: str = "development") -> None:
    """Enable required Google Cloud APIs without verification (for setup scripts)"""
    log_step("APIs", "Enabling required Google Cloud APIs (parallel)...")

    # Base APIs required for all environments
    apis = BASE_REQUIRED_APIS.copy()

    # Add production-specific APIs
    if environment.lower() == "production":
        apis.extend(
            [
                "billingbudgets.googleapis.com",
                "monitoring.googleapis.com",
                "logging.googleapis.com",
            ]
        )

    # Prepare commands for parallel execution
    commands = []
    for api in apis:
        cmd = f"gcloud services enable {api} --project={project_id}"
        commands.append((api, cmd))

    # Execute APIs in parallel (saves ~50-60 seconds vs sequential)
    log("   💨 Enabling APIs in parallel (saves ~50-60 seconds)...")
    results = run_commands_parallel(commands, max_workers=8)

    # Process results
    success_count = 0
    for api, success, error in results:
        if success:
            log(f"  ✓ {api}")
            success_count += 1
        else:
            log_warning(f"Could not enable {api}: {error}")

    if success_count == len(apis):
        log_success("All Google Cloud APIs enabled successfully")
    else:
        log_success(
            f"Google Cloud APIs enabled ({success_count}/{len(apis)} successful)"
        )
