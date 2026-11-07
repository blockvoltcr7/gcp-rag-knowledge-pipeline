#!/usr/bin/env python3
"""
Deploy Task Processor to Production Environment

This script deploys the Task Processor function (Consumer) to the production environment.
"""

import sys

from .deploy_task_processor_core import deploy_task_processor_pipeline

if __name__ == "__main__":
    exit_code = deploy_task_processor_pipeline("production")
    sys.exit(exit_code)

