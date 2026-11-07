"""
Metadata models for RAG processor.

Pydantic models that match the TypeScript interfaces from the web application
for type-safe metadata handling across video, audio, image, and document content.
"""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# Content type constants (matching TypeScript)
class ContentTypes:
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"
    DOCUMENT = "document"


# Processing status enumeration
class ProcessingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    ERROR = "error"


# Type aliases for better type hints
ContentType = Literal["video", "audio", "image", "document"]


class TranscriptMetadata(BaseModel):
    """
    Transcript metadata shared between video and audio content.

    Matches TypeScript TranscriptMetadata interface.
    """

    language: str = Field(..., description="Language code (e.g., 'en-US')")
    model: str = Field(
        ..., description="Model used for transcription (e.g., 'gemini-2.5-flash')"
    )
    transcript_timestamp: str = Field(..., description="ISO timestamp of transcription")
    has_audio: bool = Field(..., description="Whether audio content was detected")
    error: str | None = Field(None, description="Error message if transcription failed")


class BaseChunkMetadata(BaseModel):
    """
    Base metadata interface for all content types.

    Matches TypeScript BaseChunkMetadata interface.
    """

    media_path: str | None = Field(None, description="Path to media file in GCS")
    contextual_text: str | None = Field(
        None, description="Additional context for embeddings"
    )


class VideoChunkMetadata(BaseChunkMetadata):
    """
    Video-specific metadata for video segments.

    Matches TypeScript VideoChunkMetadata interface.
    """

    content_type: Literal["video"] = Field(
        default="video", description="Content type discriminator"
    )
    segment_index: int = Field(
        ..., ge=0, description="Index of this segment within the video"
    )
    start_offset_sec: float = Field(
        ..., ge=0.0, description="Start time of segment in seconds"
    )
    end_offset_sec: float = Field(
        ..., gt=0.0, description="End time of segment in seconds"
    )
    duration_sec: float = Field(
        ..., gt=0.0, description="Duration of segment in seconds"
    )
    total_segments: int = Field(
        ..., gt=0, description="Total number of segments in the video"
    )
    transcript: TranscriptMetadata = Field(..., description="Transcription metadata")

    def model_post_init(self, __context: str | None = None) -> None:
        """Validate that duration matches start/end times."""
        calculated_duration = self.end_offset_sec - self.start_offset_sec
        if abs(self.duration_sec - calculated_duration) > 0.1:  # Allow 0.1s tolerance
            raise ValueError(
                f"Duration {self.duration_sec} doesn't match calculated duration {calculated_duration}"
            )


class AudioChunkMetadata(BaseChunkMetadata):
    """
    Audio-specific metadata for audio segments.

    Matches TypeScript AudioChunkMetadata interface.
    """

    content_type: Literal["audio"] = Field(
        default="audio", description="Content type discriminator"
    )
    segment_index: int = Field(
        ..., ge=0, description="Index of this segment within the audio"
    )
    start_offset_sec: float = Field(
        ..., ge=0.0, description="Start time of segment in seconds"
    )
    end_offset_sec: float = Field(
        ..., gt=0.0, description="End time of segment in seconds"
    )
    duration_sec: float = Field(
        ..., gt=0.0, description="Duration of segment in seconds"
    )
    total_segments: int = Field(
        ..., gt=0, description="Total number of segments in the audio"
    )
    transcript: TranscriptMetadata = Field(..., description="Transcription metadata")

    def model_post_init(self, __context: str | None = None) -> None:
        """Validate that duration matches start/end times."""
        calculated_duration = self.end_offset_sec - self.start_offset_sec
        if abs(self.duration_sec - calculated_duration) > 0.1:  # Allow 0.1s tolerance
            raise ValueError(
                f"Duration {self.duration_sec} doesn't match calculated duration {calculated_duration}"
            )


class ImageChunkMetadata(BaseChunkMetadata):
    """
    Image-specific metadata for image content.

    Matches TypeScript ImageChunkMetadata interface.
    """

    content_type: Literal["image"] = Field(
        default="image", description="Content type discriminator"
    )
    filename: str = Field(..., description="Original filename of the image")


class DocumentChunkMetadata(BaseChunkMetadata):
    """
    Document-specific metadata for document chunks.

    Matches TypeScript DocumentChunkMetadata interface.
    """

    content_type: Literal["document"] = Field(
        default="document", description="Content type discriminator"
    )
    page_number: int | None = Field(None, gt=0, description="Page number in document")
    chunk_index: int = Field(
        ..., ge=0, description="Index of this chunk within the document"
    )
    doc_type: str = Field(..., description="Document type (pdf, docx, etc.)")


# Discriminated union of all metadata types (matching TypeScript)
ChunkMetadata = (
    VideoChunkMetadata | AudioChunkMetadata | ImageChunkMetadata | DocumentChunkMetadata
)


# Type guards for metadata discrimination (matching TypeScript functions)
def is_video_metadata(metadata: ChunkMetadata) -> bool:
    """Check if metadata is for video content."""
    return metadata.content_type == ContentTypes.VIDEO


def is_audio_metadata(metadata: ChunkMetadata) -> bool:
    """Check if metadata is for audio content."""
    return metadata.content_type == ContentTypes.AUDIO


def is_image_metadata(metadata: ChunkMetadata) -> bool:
    """Check if metadata is for image content."""
    return metadata.content_type == ContentTypes.IMAGE


def is_document_metadata(metadata: ChunkMetadata) -> bool:
    """Check if metadata is for document content."""
    return metadata.content_type == ContentTypes.DOCUMENT


# Factory functions for creating metadata
def create_video_metadata(
    segment_index: int,
    start_offset_sec: float,
    end_offset_sec: float,
    total_segments: int,
    transcript: TranscriptMetadata,
    media_path: str | None = None,
    contextual_text: str | None = None,
) -> VideoChunkMetadata:
    """Create video metadata with calculated duration."""
    duration_sec = end_offset_sec - start_offset_sec

    return VideoChunkMetadata(
        segment_index=segment_index,
        start_offset_sec=start_offset_sec,
        end_offset_sec=end_offset_sec,
        duration_sec=duration_sec,
        total_segments=total_segments,
        transcript=transcript,
        media_path=media_path,
        contextual_text=contextual_text,
    )


def create_audio_metadata(
    segment_index: int,
    start_offset_sec: float,
    end_offset_sec: float,
    total_segments: int,
    transcript: TranscriptMetadata,
    media_path: str | None = None,
    contextual_text: str | None = None,
) -> AudioChunkMetadata:
    """Create audio metadata with calculated duration."""
    duration_sec = end_offset_sec - start_offset_sec

    return AudioChunkMetadata(
        segment_index=segment_index,
        start_offset_sec=start_offset_sec,
        end_offset_sec=end_offset_sec,
        duration_sec=duration_sec,
        total_segments=total_segments,
        transcript=transcript,
        media_path=media_path,
        contextual_text=contextual_text,
    )


def create_image_metadata(
    filename: str,
    media_path: str | None = None,
    contextual_text: str | None = None,
) -> ImageChunkMetadata:
    """Create image metadata."""
    return ImageChunkMetadata(
        filename=filename,
        media_path=media_path,
        contextual_text=contextual_text,
    )


def create_document_metadata(
    chunk_index: int,
    doc_type: str,
    media_path: str | None = None,
    contextual_text: str | None = None,
    page_number: int | None = None,
) -> DocumentChunkMetadata:
    """Create document metadata."""
    return DocumentChunkMetadata(
        chunk_index=chunk_index,
        doc_type=doc_type,
        media_path=media_path,
        contextual_text=contextual_text,
        page_number=page_number,
    )


# Processing result models
class ProcessingResult(BaseModel):
    """Result of processing a content chunk."""

    content: str = Field(..., description="Processed content text")
    metadata: ChunkMetadata = Field(..., description="Typed metadata for the chunk")
    embedding: list[float] | None = Field(
        None, description="Generated embedding vector"
    )


class ProcessingError(BaseModel):
    """Error information from processing."""

    error_type: str = Field(..., description="Type of error")
    error_message: str = Field(..., description="Human-readable error message")
    file_path: str | None = Field(None, description="Path of file that caused error")
    chunk_index: int | None = Field(
        None, description="Index of chunk that caused error"
    )
    stack_trace: str | None = Field(None, description="Stack trace if available")


class ProcessingJob(BaseModel):
    """Processing job tracking for file processing operations."""

    job_id: str = Field(..., description="Unique job identifier")
    user_id: str = Field(..., description="ID of the user who uploaded the file")
    organization_id: str | None = Field(
        default=None, description="Optional organization ID"
    )
    gcs_path: str = Field(..., description="GCS path to the file")
    file_name: str = Field(..., description="Original filename")
    file_size: int = Field(..., gt=0, description="File size in bytes")
    status: ProcessingStatus = Field(..., description="Current processing status")
    created_at: datetime = Field(..., description="When the job was created")
    started_at: datetime | None = Field(
        default=None, description="When processing started"
    )
    completed_at: datetime | None = Field(
        default=None, description="When processing completed"
    )
    failed_at: datetime | None = Field(
        default=None, description="When processing failed"
    )
    error_message: str | None = Field(
        default=None, description="Error message if failed"
    )
    custom_metadata: dict[str, str] = Field(
        default_factory=dict, description="Custom metadata from user"
    )
