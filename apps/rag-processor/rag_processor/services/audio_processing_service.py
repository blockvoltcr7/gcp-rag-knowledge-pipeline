"""
Audio processing service for handling audio files with transcription.

Handles audio transcription, embedding generation, and storage
with proper error handling and optimized workflow.
"""

from pathlib import Path

import structlog

from ..models.metadata_models import AudioChunkMetadata, TranscriptMetadata
from ..utils.retry_utils import JobCancelledError, NonRetryableError
from ..utils.token_utils import create_google_tokenizer, truncate_text_to_tokens
from .audio_transcription import AudioTranscriptionService
from .database_service import ChunkData, get_database_service
from .embedding_service import get_embedding_service

logger = structlog.get_logger(__name__)


class AudioProcessingServiceError(NonRetryableError):
    """Base exception for audio processing service errors."""

    pass


class AudioProcessingService:
    """
    Service for processing audio files.

    Handles audio transcription, embedding generation, and storage
    using the existing AudioTranscriptionService and text embedding models.
    """

    def __init__(
        self,
        max_chunk_duration: int = 300,  # 5 minutes
        chunk_size: int = 60,  # 1 minute per segment
        project_id: str | None = None,
    ):
        """
        Initialize the audio processing service.

        Args:
            max_chunk_duration: Maximum duration in seconds before chunking
            chunk_size: Size of each chunk in seconds
            project_id: Google Cloud project ID
        """
        self.max_chunk_duration = max_chunk_duration
        self.chunk_size = chunk_size

        # Initialize dependencies
        self.embedding_service = get_embedding_service(project_id)
        self.database_service = get_database_service(project_id)

        # Initialize the existing audio transcription service
        self.transcription_service = AudioTranscriptionService()

        # Initialize tokenizer for transcript text chunking
        self.tokenizer = create_google_tokenizer(
            genai_client=self.embedding_service.genai_client
        )

        logger.info(
            "Audio processing service initialized",
            max_chunk_duration=max_chunk_duration,
            chunk_size=chunk_size,
            project_id=project_id,
        )

    async def process_audio_file(
        self,
        audio_path: str,
        user_id: str,
        document_id: str | None = None,
        contextual_text: str = "",
        job_id: str | None = None,
    ) -> list[ChunkData]:
        """
        Process a complete audio file.

        Args:
            audio_path: Path to the audio file
            user_id: ID of the user who owns the audio
            document_id: Optional document ID to associate chunks with
            contextual_text: Optional contextual text for embedding
            job_id: Optional job ID for stage tracking

        Returns:
            List of processed chunks ready for storage

        Raises:
            AudioProcessingServiceError: If processing fails
        """
        logger.info(
            "Starting audio processing",
            audio_path=audio_path,
            user_id=user_id,
            document_id=document_id,
            job_id=job_id,
        )

        try:
            # Update stage: analyzing audio
            if job_id:
                await self.database_service.update_processing_stage(
                    job_id, "analyzing_audio"
                )

            # Get audio duration using the transcription service's helper method
            audio_duration = await self.transcription_service.get_audio_duration(
                audio_path
            )

            # Update stage: transcribing audio
            if job_id:
                await self.database_service.update_processing_stage(
                    job_id, "transcribing_audio"
                )

            # Use the existing AudioTranscriptionService to transcribe the audio
            transcription_result = (
                await self.transcription_service.transcribe_audio_with_genai(
                    audio_path=audio_path,
                    language_hint="en-US",  # Default to English, could be parameterized
                )
            )

            # Extract transcript text and metadata
            transcript_text = transcription_result.get("text", "").strip()

            # Handle silent audio files (no transcript text)
            if not transcript_text:
                logger.info(
                    "Silent audio file - creating chunk without text embedding",
                    audio_path=audio_path,
                    job_id=job_id,
                )

                # Create metadata for silent audio
                metadata = AudioChunkMetadata(
                    media_path=audio_path,
                    contextual_text=contextual_text,
                    segment_index=0,
                    start_offset_sec=0.0,
                    end_offset_sec=audio_duration,
                    duration_sec=audio_duration,
                    total_segments=1,
                    transcript=TranscriptMetadata(
                        language="unknown",
                        model=transcription_result.get("model", "vertex-ai"),
                        transcript_timestamp=transcription_result.get(
                            "transcript_timestamp", ""
                        ),
                        has_audio=False,  # No audio content detected
                        error=transcription_result.get("error"),
                    ),
                )

                # Create ChunkData for silent audio file
                chunk_data = ChunkData(
                    text=f"Silent audio file: {Path(audio_path).stem}",
                    metadata=metadata,
                    context=None,
                    text_embedding=None,  # No text embedding for silent audio
                    multimodal_embedding=None,  # Audio files don't have multimodal embeddings
                )

                return [chunk_data]

            # Truncate transcript text if it exceeds token limits (simple approach)
            truncated_transcript = truncate_text_to_tokens(
                text=transcript_text, tokenizer=self.tokenizer, max_tokens=2047
            )

            logger.info(
                "Processing audio transcript with truncation",
                audio_path=audio_path,
                original_transcript_tokens=self.tokenizer.count_tokens(transcript_text),
                truncated_transcript_tokens=self.tokenizer.count_tokens(
                    truncated_transcript
                ),
                original_char_length=len(transcript_text),
                truncated_char_length=len(truncated_transcript),
            )

            # Generate text embedding for truncated transcript
            embedding = await self.embedding_service.generate_text_embedding(
                text=truncated_transcript,
            )

            # Create metadata for the audio file
            metadata = AudioChunkMetadata(
                media_path=audio_path,
                contextual_text=contextual_text,
                segment_index=0,
                start_offset_sec=0.0,
                end_offset_sec=audio_duration,
                duration_sec=audio_duration,
                total_segments=1,  # Single chunk for entire audio file
                transcript=TranscriptMetadata(
                    language=transcription_result.get("language", "en-US"),
                    model=transcription_result.get("model", "vertex-ai"),
                    transcript_timestamp=transcription_result.get(
                        "transcript_timestamp", ""
                    ),
                    has_audio=len(transcript_text) > 0,
                    error=transcription_result.get("error"),
                ),
            )

            # Create single ChunkData for the audio file
            chunk_data = ChunkData(
                text=truncated_transcript,
                metadata=metadata,
                context=None,
                text_embedding=embedding,
                multimodal_embedding=None,  # Audio files don't have multimodal embeddings
            )

            logger.info(
                "Audio processing completed",
                audio_path=audio_path,
                job_id=job_id,
                original_transcript_length=len(transcript_text),
                truncated_transcript_length=len(truncated_transcript),
                audio_duration=audio_duration,
                transcription_language=transcription_result.get("language", "unknown"),
            )

            return [chunk_data]

        except JobCancelledError as e:
            logger.info(
                "Audio processing cancelled - job was deleted during processing",
                audio_path=audio_path,
                user_id=user_id,
                job_id=job_id,
                error=str(e),
            )
            # Re-raise to signal cancellation to caller
            raise
        except Exception as e:
            logger.error(
                "Audio processing failed",
                audio_path=audio_path,
                user_id=user_id,
                job_id=job_id,
                error=str(e),
            )
            raise AudioProcessingServiceError(f"Audio processing failed: {e}") from e
        finally:
            # Clean up the main audio file AND any temporary files created by the transcription service
            try:
                # Clean up the main audio file that was passed to us
                from ..utils.gcs_utils import cleanup_temp_file

                cleanup_temp_file(audio_path)
                logger.debug("Cleaned up main audio file", audio_path=audio_path)

                # Clean up any additional temporary files created by the transcription service
                self.transcription_service.cleanup_temp_files()
            except Exception as cleanup_error:
                logger.warning(
                    "Failed to cleanup audio processing temp files",
                    audio_path=audio_path,
                    error=str(cleanup_error),
                )


# Global service instance
_audio_processing_service: AudioProcessingService | None = None


def get_audio_processing_service(
    project_id: str | None = None,
) -> AudioProcessingService:
    """
    Get a global audio processing service instance.

    Args:
        project_id: Google Cloud project ID

    Returns:
        AudioProcessingService instance
    """
    global _audio_processing_service

    if _audio_processing_service is None:
        _audio_processing_service = AudioProcessingService(project_id=project_id)

    return _audio_processing_service
