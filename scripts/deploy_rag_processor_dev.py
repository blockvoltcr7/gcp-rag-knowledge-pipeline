#!/usr/bin/env python3
"""
RAG Processor deployment for DEVELOPMENT environment.

This script is a thin wrapper around the core deployment logic,
configured specifically for the development environment.

Features:
- Uses .env.local for environment variables
- Deploys to development-specific service name (rag-processor-dev)
- Uses development service account and secrets
- Cost-optimized scaling configuration

Usage:
    npm run deploy:processor:dev
"""

from .deploy_rag_processor_core import deploy_processor_complete_pipeline


def main() -> None:
    """Deploy RAG processor for development environment."""
    deploy_processor_complete_pipeline(environment="development")


if __name__ == "__main__":
    main()
