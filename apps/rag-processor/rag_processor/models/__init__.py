"""
Models package for RAG processor.

Contains Pydantic models that match the TypeScript interfaces
from the web application for type-safe metadata handling.
"""

# Export API models
from .api_models import (
    HealthCheckResponse,
    TaskQueueResponse,
)

# Export metadata models
from .metadata_models import (
    AudioChunkMetadata,
    ChunkMetadata,
    ContentType,
    ContentTypes,
    DocumentChunkMetadata,
    ImageChunkMetadata,
    ProcessingJob,
    ProcessingStatus,
    VideoChunkMetadata,
)

__all__ = [
    # API models
    "HealthCheckResponse",
    "TaskQueueResponse",
    # Metadata models
    "ChunkMetadata",
    "AudioChunkMetadata",
    "VideoChunkMetadata",
    "ImageChunkMetadata",
    "DocumentChunkMetadata",
    "ProcessingJob",
    "ProcessingStatus",
    "ContentType",
    "ContentTypes",
]
