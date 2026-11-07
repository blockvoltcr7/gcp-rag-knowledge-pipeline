#!/usr/bin/env python3
"""
Deployment Configuration - Single Source of Truth
Shared configuration for RAG SaaS deployment across all environments

This module provides consistent configuration values for:
- Setup scripts (setup-gcp-dev.py, setup-gcp-prod.py)
- Deployment scripts (deploy-dev.py, deploy-prod.py)
- Resource allocation and scaling settings
- Environment variable integration

Usage:
    from deployment_config import ENVIRONMENTS, get_config

    config = get_config("development")
    print(config.service_name)  # "rag-processor-dev"
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

# No sys.path manipulation needed - using local imports
# Import lightweight configuration utilities from scripts directory
from .config_utils import get_env_var
from .error_handling import ConfigurationError
from .validation_utils import (
    validate_and_raise,
    validate_cpu_count,
    validate_environment_name,
    validate_memory_specification,
    validate_timeout_seconds,
)


@dataclass
class EnvironmentConfig:
    """Configuration for a specific deployment environment with validation"""

    # Core service configuration (required fields first)
    service_name: str
    environment: str
    cpu: int
    memory: str
    database_pool_size: int
    database_max_overflow: int
    database_timeout: int

    # Processing configuration
    max_concurrent_jobs: int = 1

    # Google Cloud settings (fields with defaults last)
    region: str = "us-central1"
    location: str = "us-central1"  # Same as region for most services
    timeout: int = 3600  # 1 hour

    # Cloud Run Service parameters (for queue handlers only)
    min_instances: int = 0  # Scale-to-zero for services
    max_instances: int = 10  # Max instances for services
    concurrency: int = 10  # Concurrent requests per instance for services

    # Cloud Run Jobs parameters (for processors only)
    parallelism: int = 1  # Max concurrent job tasks (for jobs only)
    max_retries: int = 3  # Job retry attempts on failure

    def __post_init__(self) -> None:
        """Validate configuration after initialization"""
        self._validate_configuration()

    def _validate_configuration(self) -> None:
        """Validate all configuration values"""
        # Validate environment name
        validate_and_raise(
            validate_environment_name(self.environment),
            f"Invalid environment: '{self.environment}'. Must be development, production, or staging.",
        )

        # Validate memory specification
        validate_and_raise(
            validate_memory_specification(self.memory),
            f"Invalid memory: '{self.memory}'. Must be like 512Mi, 2Gi, 4Gi, 8Gi.",
        )

        # Validate CPU count
        validate_and_raise(
            validate_cpu_count(self.cpu),
            f"Invalid CPU: '{self.cpu}'. Must be 1, 2, 4, 6, or 8.",
        )

        # Validate timeout
        validate_and_raise(
            validate_timeout_seconds(self.timeout),
            f"Invalid timeout: '{self.timeout}'. Must be 1-7200 seconds.",
        )

        # Validate instance counts (Cloud Run Services)
        if self.min_instances < 0:
            raise ConfigurationError(
                f"min_instances must be >= 0, got {self.min_instances}"
            )
        if self.max_instances < 1:
            raise ConfigurationError(
                f"max_instances must be >= 1, got {self.max_instances}"
            )
        if self.min_instances > self.max_instances:
            raise ConfigurationError(
                f"min_instances ({self.min_instances}) cannot exceed max_instances ({self.max_instances})"
            )

        # Validate parallelism (Cloud Run Jobs)
        if self.parallelism < 1:
            raise ConfigurationError(
                f"parallelism must be >= 1, got {self.parallelism}"
            )

        # Validate database settings
        if self.database_pool_size < 1:
            raise ConfigurationError(
                f"database_pool_size must be >= 1, got {self.database_pool_size}"
            )
        if self.database_timeout < 1:
            raise ConfigurationError(
                f"database_timeout must be >= 1, got {self.database_timeout}"
            )

    # Computed properties for consistent resource naming
    @property
    def bucket_name_suffix(self) -> str:
        """Suffix for storage bucket name: project-id-{suffix}"""
        if self.environment == "development":
            return "rag-documents-dev"
        elif self.environment == "production":
            return "rag-documents-prod"
        else:
            return f"rag-documents-{self.environment}"

    @property
    def bucket_suffix(self) -> str:
        """Legacy bucket suffix for compatibility with setup scripts"""
        if self.environment == "development":
            return "-dev"
        elif self.environment == "production":
            return "-prod"
        else:
            return f"-{self.environment}"

    @property
    def description(self) -> str:
        """Environment description for setup scripts"""
        if self.environment == "development":
            return "Development environment - cost-effective for testing"
        elif self.environment == "production":
            return "Production environment - optimized for performance"
        else:
            return f"{self.environment.title()} environment"

    @property
    def service_account_name(self) -> str:
        """Service account name (without @project.iam.gserviceaccount.com)"""
        if self.environment == "development":
            return "rag-processor-dev"
        elif self.environment == "production":
            return "rag-processor-prod"
        else:
            return f"rag-processor-{self.environment}"

    @property
    def trigger_name(self) -> str:
        """EventArc trigger name"""
        return f"{self.service_name}-trigger"

    @property
    def database_secret_name(self) -> str:
        """Secret Manager secret name for database URL"""
        if self.environment == "development":
            return "database-url-dev"
        elif self.environment == "production":
            return "database-url-prod"
        else:
            return f"database-url-{self.environment}"

    @property
    def gemini_api_key_secret_name(self) -> str:
        """Secret Manager secret name for Gemini API key"""
        if self.environment == "development":
            return "gemini-api-key-dev"
        elif self.environment == "production":
            return "gemini-api-key-prod"
        else:
            return f"gemini-api-key-{self.environment}"

    @property
    def llamaparse_api_key_secret_name(self) -> str:
        """Secret Manager secret name for LlamaParse API key"""
        if self.environment == "development":
            return "llamaparse-api-key-dev"
        elif self.environment == "production":
            return "llamaparse-api-key-prod"
        else:
            return f"llamaparse-api-key-{self.environment}"

    @property
    def image_name(self) -> str:
        """Docker image name for Cloud Run"""
        return (
            self.service_name
        )  # Use service name directly for both processor and queue

    @property
    def log_level(self) -> str:
        """Logging level for the environment"""
        if self.environment == "development":
            return "DEBUG"
        else:
            return "INFO"


# Service-specific configurations for DECOUPLED architecture
# CRITICAL: Queue handler and processor have DIFFERENT resource requirements!

# Queue Handler Configurations (Lightweight - EventArc to Cloud Tasks routing)
QUEUE_HANDLER_ENVIRONMENTS: dict[str, EnvironmentConfig] = {
    "development": EnvironmentConfig(
        service_name="rag-queue",
        environment="development",
        # Queue Handler: Lightweight, high-concurrency for simple routing
        cpu=1,  # Minimal CPU for event routing
        memory="512Mi",  # Small memory footprint - no models loaded
        min_instances=0,  # Scale-to-zero for cost optimization
        max_instances=10,
        concurrency=80,  # HIGH concurrency - just routing tasks
        database_pool_size=1,  # Queue handler doesn't need DB pool
        database_max_overflow=1,
        database_timeout=30,
        max_concurrent_jobs=80,  # Can handle many routing operations
        timeout=60,  # Quick timeout - just enqueuing
    ),
    "production": EnvironmentConfig(
        service_name="rag-queue",
        environment="production",
        # Queue Handler: Lightweight, high-concurrency for simple routing
        cpu=1,  # Minimal CPU for event routing
        memory="1Gi",  # Slightly more memory for production stability
        min_instances=0,  # Scale-to-zero (set to 1 for zero cold starts)
        max_instances=10,
        concurrency=80,  # HIGH concurrency - just routing tasks
        database_pool_size=1,  # Queue handler doesn't need DB pool
        database_max_overflow=1,
        database_timeout=30,
        max_concurrent_jobs=80,  # Can handle many routing operations
        timeout=60,  # Quick timeout - just enqueuing
    ),
}

# Processor Jobs Configurations (Heavy - Document processing with models as Cloud Run Jobs)
PROCESSOR_ENVIRONMENTS: dict[str, EnvironmentConfig] = {
    "development": EnvironmentConfig(
        service_name="rag-processor-job",  # Updated for jobs (deployment adds "-dev" suffix)
        environment="development",
        # Processor Job: Heavy resources for long-running batch processing
        cpu=6,  # 6 vCPUs for optimal processing performance
        memory="8Gi",  # 8Gi memory for standard Docling models + large PDFs
        # Cloud Run Jobs parameters (NOT service parameters)
        parallelism=1,  # Process 1 file per job execution (each file gets dedicated resources)
        max_retries=3,  # Retry failed jobs up to 3 times
        timeout=7200,  # 2 hours per job execution (jobs support longer timeouts)
        # Database settings (optimized for single-file processing)
        database_pool_size=1,  # Single connection per job
        database_max_overflow=1,
        database_timeout=60,
        max_concurrent_jobs=10,  # Max parallel job executions (queue scaling)
        # Service parameters (unused for jobs but required by base class)
        min_instances=0,  # Not applicable to jobs
        max_instances=10,  # Not applicable to jobs
        concurrency=1,  # Not applicable to jobs
    ),
    "production": EnvironmentConfig(
        service_name="rag-processor-job",  # Updated for jobs (deployment adds "-prod" suffix)
        environment="production",
        # Processor Job: Heavy resources for long-running batch processing
        cpu=6,  # 6 CPU for optimal processing performance
        memory="8Gi",  # 8Gi memory for standard Docling models + large PDFs
        # Cloud Run Jobs parameters (NOT service parameters)
        parallelism=1,  # Process 1 file per job execution (each file gets dedicated resources)
        max_retries=3,  # Retry failed jobs up to 3 times
        timeout=7200,  # 2 hours per job execution (jobs support longer timeouts)
        # Database settings (optimized for single-file processing)
        database_pool_size=1,  # Single connection per job
        database_max_overflow=1,
        database_timeout=45,
        max_concurrent_jobs=20,  # Higher max parallel job executions for production
        # Service parameters (unused for jobs but required by base class)
        min_instances=0,  # Not applicable to jobs
        max_instances=20,  # Not applicable to jobs
        concurrency=1,  # Not applicable to jobs
    ),
}

# Agno Multi-Agent Service Configurations (Cloud Run Services)
AGNO_ENVIRONMENTS: dict[str, EnvironmentConfig] = {
    "development": EnvironmentConfig(
        service_name="agno-multi-agent-dev",
        environment="development",
        # Development: Cost-optimized with scale-to-zero
        cpu=1,  # 1 vCPU sufficient for dev testing
        memory="1Gi",  # 1GB memory for agent operations
        min_instances=0,  # Scale to zero when idle (save costs)
        max_instances=5,  # Max 5 instances for dev traffic
        concurrency=80,  # 80 concurrent requests per instance
        timeout=60,  # 60 seconds max request time (agent responses)
        # Database settings (connection pooling per instance)
        database_pool_size=5,  # Base connections for agent database queries
        database_max_overflow=10,  # Additional connections during spikes
        database_timeout=30,  # 30s timeout for connection acquisition
        max_concurrent_jobs=80,  # Max concurrent agent conversations
    ),
    "production": EnvironmentConfig(
        service_name="agno-multi-agent-prod",
        environment="production",
        # Production: Performance-optimized with no cold starts
        cpu=2,  # 2 vCPUs for faster agent processing
        memory="2Gi",  # 2GB memory for concurrent conversations
        min_instances=1,  # Always-on to eliminate cold starts (~$80/month)
        max_instances=10,  # Max 10 instances for peak traffic (800 concurrent requests)
        concurrency=80,  # 80 concurrent requests per instance
        timeout=60,  # 60 seconds max request time (agent responses)
        # Database settings (connection pooling per instance)
        database_pool_size=5,  # Base connections for agent database queries
        database_max_overflow=10,  # Additional connections during spikes
        database_timeout=30,  # 30s timeout for connection acquisition
        max_concurrent_jobs=80,  # Max concurrent agent conversations
    ),
}

# Legacy monolithic configuration - DEPRECATED
# Kept for backward compatibility but should NOT be used
ENVIRONMENTS: dict[str, EnvironmentConfig] = {
    "development": PROCESSOR_ENVIRONMENTS["development"],  # Default to processor config
    "production": PROCESSOR_ENVIRONMENTS["production"],  # Default to processor config
}


def create_environment_config_with_overrides(
    base_config: EnvironmentConfig,
    env_var_prefix: str = "RAG_PROCESSOR",
) -> EnvironmentConfig:
    """Create environment config with environment variable overrides"""
    # Get environment variable overrides
    overrides = {}

    # Check for CPU override
    cpu_override_str = get_env_var(f"{env_var_prefix}_CPU", default="")
    if cpu_override_str:
        try:
            overrides["cpu"] = int(cpu_override_str)
        except ValueError:
            pass

    # Check for memory override
    memory_override = get_env_var(f"{env_var_prefix}_MEMORY", default="")
    if memory_override:
        overrides["memory"] = memory_override

    # Check for instance count overrides
    min_instances_str = get_env_var(f"{env_var_prefix}_MIN_INSTANCES", default="")
    if min_instances_str:
        try:
            overrides["min_instances"] = int(min_instances_str)
        except ValueError:
            pass

    max_instances_str = get_env_var(f"{env_var_prefix}_MAX_INSTANCES", default="")
    if max_instances_str:
        try:
            overrides["max_instances"] = int(max_instances_str)
        except ValueError:
            pass

    # Check for timeout override
    timeout_str = get_env_var(f"{env_var_prefix}_TIMEOUT", default="")
    if timeout_str:
        try:
            overrides["timeout"] = int(timeout_str)
        except ValueError:
            pass

    # Create new config with overrides
    if overrides:
        # Convert base config to dict
        config_dict = base_config.__dict__.copy()
        config_dict.update(overrides)

        # Create new config with overrides
        return EnvironmentConfig(**config_dict)

    return base_config


def get_config(environment: str, service_type: str = "processor") -> EnvironmentConfig:
    """Get configuration for specified environment and service type with optional overrides

    Args:
        environment: Environment name ("development" or "production")
        service_type: Service type ("queue-handler" or "processor"), defaults to "processor"

    Returns:
        EnvironmentConfig for the specified environment and service with any env var overrides applied

    Raises:
        ValueError: If environment or service_type is not found
    """
    # Select appropriate configuration based on service type
    if service_type == "queue-handler":
        configs = QUEUE_HANDLER_ENVIRONMENTS
    elif service_type == "processor":
        configs = PROCESSOR_ENVIRONMENTS
    else:
        # Legacy support - default to processor
        configs = ENVIRONMENTS

    if environment not in configs:
        available = ", ".join(configs.keys())
        raise ValueError(f"Unknown environment '{environment}'. Available: {available}")

    base_config = configs[environment]

    # Apply environment variable overrides if any exist
    config_with_overrides = create_environment_config_with_overrides(base_config)

    return config_with_overrides


def get_config_dict(environment: str) -> dict[str, Any]:
    """Get configuration as dict for setup scripts compatibility with overrides

    Args:
        environment: Environment name ("development" or "production")

    Returns:
        Dictionary with all config fields including computed properties and overrides

    Raises:
        ValueError: If environment is not found
    """
    config = get_config(environment)  # This now includes overrides

    # Convert dataclass to dict and add computed properties
    config_dict = config.__dict__.copy()

    # Add computed properties that setup scripts expect
    config_dict["bucket_suffix"] = config.bucket_suffix
    config_dict["description"] = config.description
    config_dict["log_level"] = config.log_level
    config_dict["bucket_name_suffix"] = config.bucket_name_suffix
    config_dict["service_account_name"] = config.service_account_name
    config_dict["trigger_name"] = config.trigger_name

    config_dict["database_secret_name"] = config.database_secret_name
    config_dict["gemini_api_key_secret_name"] = config.gemini_api_key_secret_name
    config_dict["image_name"] = config.image_name

    return config_dict


def list_environments() -> list[str]:
    """List all available environment names"""
    return list(ENVIRONMENTS.keys())


def get_bucket_name(project_id: str, environment: str) -> str:
    """Generate complete bucket name for environment

    Args:
        project_id: Google Cloud project ID
        environment: Environment name

    Returns:
        Complete bucket name: {project_id}-{suffix}
    """
    config = get_config(environment)
    return f"{project_id}-{config.bucket_name_suffix}"


def get_service_account_email(project_id: str, environment: str) -> str:
    """Generate complete service account email for environment

    Args:
        project_id: Google Cloud project ID
        environment: Environment name

    Returns:
        Complete service account email
    """
    config = get_config(environment)
    return f"{config.service_account_name}@{project_id}.iam.gserviceaccount.com"


def get_agno_config(environment: str) -> EnvironmentConfig:
    """Get Agno multi-agent service configuration for specified environment

    Args:
        environment: Environment name ("development" or "production")

    Returns:
        EnvironmentConfig for Agno service

    Raises:
        ValueError: If environment is not found
    """
    if environment not in AGNO_ENVIRONMENTS:
        available = ", ".join(AGNO_ENVIRONMENTS.keys())
        raise ValueError(
            f"Unknown Agno environment '{environment}'. Available: {available}"
        )
    return AGNO_ENVIRONMENTS[environment]


def _load_env_file(env_file: Path) -> dict[str, str]:
    """Helper to load environment variables from file"""
    if not env_file.exists():
        raise FileNotFoundError(f"Environment file not found: {env_file}")

    env_vars = {}
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                if "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key.strip()] = value.strip()

    return env_vars


def _validate_required_vars(
    env_vars: dict[str, str], env_file: Path, required_vars: list[str]
) -> None:
    """Helper to validate required environment variables"""
    missing_vars = [var for var in required_vars if not env_vars.get(var)]

    if missing_vars:
        raise ConfigurationError(
            f"Missing required variables in {env_file}: {', '.join(missing_vars)}\n"
            f"Required variables: {', '.join(required_vars)}"
        )


def load_and_validate_environment(
    env_file: Path, environment: str, required_vars: list[str] | None = None
) -> dict[str, str]:
    """Load and validate environment file for deployment

    Args:
        env_file: Path to environment file (.env.local, .env.prod, etc.)
        environment: Environment name for validation context
        required_vars: List of required environment variables (uses defaults if None)

    Returns:
        Dictionary of environment variables

    Raises:
        FileNotFoundError: If environment file doesn't exist
        ConfigurationError: If required variables are missing
    """
    if required_vars is None:
        required_vars = [
            "GOOGLE_CLOUD_PROJECT_ID",
            "DATABASE_URL",
            "GEMINI_API_KEY",
        ]

    # Load environment variables
    env_vars = _load_env_file(env_file)

    # Validate required variables
    _validate_required_vars(env_vars, env_file, required_vars)

    return env_vars


# Export commonly used configurations for easy imports
DEV_CONFIG = ENVIRONMENTS["development"]
PROD_CONFIG = ENVIRONMENTS["production"]


if __name__ == "__main__":
    """Demo/testing of configuration"""
    print("🔧 Deployment Configuration Demo")
    print("=" * 40)

    for env_name in list_environments():
        config = get_config(env_name)
        print(f"\n{env_name.upper()} Environment:")
        print(f"  Service Name: {config.service_name}")
        print(f"  Resources: {config.cpu} CPU, {config.memory}")
        print(f"  Scaling: {config.min_instances}-{config.max_instances} instances")
        print(f"  Bucket Suffix: {config.bucket_name_suffix}")
        print(f"  Service Account: {config.service_account_name}")
        print(f"  Log Level: {config.log_level}")
