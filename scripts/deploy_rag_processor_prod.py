#!/usr/bin/env python3
"""
RAG Processor deployment for PRODUCTION environment.

This script is a thin wrapper around the core deployment logic,
configured specifically for the production environment.

Features:
- Uses .env.prod for environment variables
- Deploys to production-specific service name (rag-processor-prod)
- Uses production service account and secrets
- Performance-optimized scaling configuration

Usage:
    npm run deploy:processor:prod
"""

from .deploy_rag_processor_core import deploy_processor_complete_pipeline


def main() -> None:
    """Deploy RAG processor for production environment."""
    deploy_processor_complete_pipeline(environment="production")


if __name__ == "__main__":
    main()
