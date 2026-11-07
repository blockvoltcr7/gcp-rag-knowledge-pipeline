"""
API models for RAG processor.

Pydantic models for FastAPI request/response handling
and HTTP API endpoints.
"""

from pydantic import BaseModel


class HealthCheckResponse(BaseModel):
    """Response model for health check endpoint."""

    status: str
    service: str
    version: str
    environment: str | None = None
    health: dict | None = None


class CloudEventResponse(BaseModel):
    """Response model for CloudEvent processing."""

    status: str
    result: dict | None = None
    error: str | None = None


class TaskQueueResponse(BaseModel):
    """Response model for task queue operations."""

    status: str
    task_id: str | None = None
    message: str
