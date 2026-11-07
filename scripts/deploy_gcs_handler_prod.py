#!/usr/bin/env python3
"""
Deploy GCS Handler to Production Environment

This script deploys the GCS Handler function (Producer) to the production environment.
"""

import sys

from .deploy_gcs_handler_core import deploy_gcs_handler_pipeline

if __name__ == "__main__":
    exit_code = deploy_gcs_handler_pipeline("production")
    sys.exit(exit_code)

