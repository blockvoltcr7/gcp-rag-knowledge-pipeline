"""
Video processing service for handling video files with ffmpeg.

Handles video chunking, transcription, embedding generation, and storage
with proper error handling and optimized workflow.

For video embedding best practices, see:
https://cloud.google.com/vertex-ai/generative-ai/docs/embeddings/get-multimodal-embeddings#video-best-practices
"""

import asyncio
import math
import subprocess
import tempfile
from pathlib import Path
from typing import Any, TypedDict

import google.genai as genai
import structlog

from ..config import config
from ..models.metadata_models import TranscriptMetadata, VideoChunkMetadata
from ..utils.gcs_utils import cleanup_temp_file
from ..utils.retry_utils import (
    JobCancelledError,
    NonRetryableError,
    RetryConfig,
    retry_genai_operation,
)
from ..utils.token_utils import create_google_tokenizer, truncate_text_to_tokens
from .audio_transcription import AudioTranscriptionService
from .database_service import ChunkData, get_database_service
from .embedding_service import get_embedding_service
from .genai_utils import create_file_manager

logger = structlog.get_logger(__name__)


class ChunkFileData(TypedDict):
    """Type definition for chunk file data structure."""

    chunk_file: str
    start_sec: float
    end_sec: float
    chunk_index: int


class VideoProcessingServiceError(NonRetryableError):
    """Base exception for video processing service errors."""

    pass


class VideoProcessingService:
    """
    Service for processing video files.

    Handles video chunking, transcription, embedding generation, and storage
    using ffmpeg, the existing AudioTranscriptionService, and Google's multimodal embedding models.
    """

    def __init__(self, project_id: str | None = None) -> None:
        """
        Initialize the video processing service.

        Args:
            project_id: Google Cloud project ID
        """
        self.project_id = project_id or config.PROJECT_ID

        # Initialize dependencies
        self.embedding_service = get_embedding_service(project_id)
        self.database_service = get_database_service(project_id)
        self.transcription_service = AudioTranscriptionService()

        # Initialize GenAI client for context generation using API key
        self.genai_client = genai.Client(
            vertexai=False,
            api_key=config.GEMINI_API_KEY,
        )

        # Initialize file manager for GenAI file operations
        self.file_manager = create_file_manager(self.genai_client)

        # Initialize tokenizer for transcript text chunking
        self.tokenizer = create_google_tokenizer(
            genai_client=self.embedding_service.genai_client
        )

        # Initialize retry configuration for AI API calls
        self.retry_config = RetryConfig(
            max_attempts=3,  # Retry failed AI calls up to 3 times
            base_delay=2.0,  # Start with 2 second delay
            max_delay=30.0,  # Cap delay at 30 seconds
            exponential_backoff=True,  # Use exponential backoff
            jitter=True,  # Add jitter to prevent thundering herd
        )

        logger.info(
            "Video processing service initialized",
            chunk_duration_seconds=config.VIDEO_CHUNK_DURATION_SECONDS,
            project_id=self.project_id,
            retry_max_attempts=self.retry_config.max_attempts,
        )

    def clean_and_normalize_video(self, video_path: str) -> str:
        """
        Clean and normalize video file to ensure Vertex AI multimodal embedding compatibility.

        Applies error detection, timestamp fixing, and re-encoding to eliminate corruption
        or codec issues that might cause Vertex AI embedding API failures. Processes ALL
        video formats (not just MOV) to ensure consistent quality.

        Args:
            video_path: Path to the original video file

        Returns:
            Path to the cleaned video file.
            If cleaning fails, returns the original path (no exception).
        """
        try:
            video_stem = Path(video_path).stem
            temp_dir = Path(tempfile.mkdtemp(prefix="tmp_video_clean_"))
            cleaned_path = temp_dir / f"{video_stem}_cleaned.mp4"

            logger.info(
                "Cleaning and normalizing video for Vertex AI compatibility",
                original_path=video_path,
                cleaned_path=str(cleaned_path),
            )

            # Force re-encoding with aggressive error detection and repair
            subprocess.run(
                [
                    "ffmpeg",
                    "-err_detect",
                    "ignore_err",  # Ignore errors and salvage corrupted data
                    "-i",
                    video_path,
                    "-c:v",
                    "libx264",  # Force H.264 re-encoding
                    "-profile:v",
                    "baseline",  # Use baseline profile for maximum compatibility
                    "-level",
                    "3.1",  # H.264 level for broad compatibility
                    "-r",
                    "30",  # Standardize to 30fps
                    "-vsync",
                    "cfr",  # Force constant frame rate (deprecated but works in 5.1.7)
                    "-c:a",
                    "aac",  # Standard AAC audio codec
                    "-ar",
                    "48000",  # Standard audio sample rate
                    "-ac",
                    "2",  # Stereo audio
                    "-map_metadata",
                    "-1",  # Strip ALL metadata
                    "-map_chapters",
                    "-1",  # Remove chapter information
                    "-movflags",
                    "+faststart",  # Optimize for streaming
                    "-avoid_negative_ts",
                    "make_zero",  # Fix timestamp issues
                    "-fflags",
                    "+genpts+igndts+flush_packets",  # Generate PTS, ignore DTS issues, flush packets
                    "-force_key_frames",
                    "expr:gte(t,n_forced*2)",  # Force keyframes every 2 seconds
                    "-f",
                    "mp4",  # Force MP4 container format
                    "-y",  # Overwrite output file if exists
                    str(cleaned_path),
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=600,
            )

            original_size = Path(video_path).stat().st_size
            cleaned_size = cleaned_path.stat().st_size
            size_change = ((cleaned_size - original_size) / original_size) * 100

            logger.info(
                "Video cleaning completed",
                original_path=video_path,
                cleaned_path=str(cleaned_path),
                original_size_mb=round(original_size / (1024 * 1024), 1),
                cleaned_size_mb=round(cleaned_size / (1024 * 1024), 1),
                size_change_percent=round(size_change, 1),
            )

            return str(cleaned_path)

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.error(
                "Video cleaning failed",
                video_path=video_path,
                error=str(e),
                stderr=getattr(e, "stderr", None),
            )
            logger.warning("Falling back to original video file")
            return video_path
        except Exception as e:
            logger.error(
                "Unexpected error during video cleaning",
                video_path=video_path,
                error=str(e),
                error_type=type(e).__name__,
            )
            return video_path

    def get_video_duration(self, video_path: str) -> float:
        """
        Get video duration in seconds using ffprobe.

        Args:
            video_path: Path to the video file

        Returns:
            Video duration in seconds

        Raises:
            VideoProcessingServiceError: If duration cannot be determined
        """
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "quiet",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    video_path,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            duration = float(result.stdout.strip())

            logger.debug(
                "Determined video duration",
                video_path=video_path,
                duration_seconds=duration,
            )

            return duration

        except (subprocess.CalledProcessError, ValueError) as e:
            logger.warning(
                "Could not determine video duration, using default",
                video_path=video_path,
                error=str(e),
            )
            # Default to 2 minutes if we can't determine duration
            return 120.0

    async def _transcribe_video_segment_with_retry(
        self,
        chunk_file: str,
        start_time: float,
        end_time: float,
        chunk_index: int,
    ) -> dict[str, Any]:
        """
        Transcribe video segment with retry logic.

        Args:
            chunk_file: Path to the video chunk file
            start_time: Start time within the chunk (usually 0.0)
            end_time: End time within the chunk
            chunk_index: Index of this chunk for unique ID generation

        Returns:
            Transcription data with text and metadata

        Raises:
            VideoProcessingServiceError: If transcription fails after all retries
        """

        async def _transcribe_operation() -> dict[str, Any]:
            return await self.transcribe_video_segment(
                chunk_file, start_time, end_time, chunk_index
            )

        try:
            return await retry_genai_operation(
                func=_transcribe_operation,
                operation_name=f"transcribe_video_segment({Path(chunk_file).name})",
            )
        except Exception as e:
            logger.error(
                "Video transcription failed after all retries",
                chunk_file=chunk_file,
                start_time=start_time,
                end_time=end_time,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise VideoProcessingServiceError(
                f"Video transcription failed: {str(e)}"
            ) from e

    async def _generate_context_with_retry(
        self,
        video_chunk_path: str,
        start_sec: float,
        end_sec: float,
        transcript_text: str,
        media_resolution: str,
    ) -> str:
        """
        Generate context for video chunk with retry logic.

        Args:
            video_chunk_path: Path to the video chunk file
            start_sec: Start time of the chunk
            end_sec: End time of the chunk
            transcript_text: Transcribed text from the chunk
            media_resolution: The resolution setting to use for video analysis ('low' or 'default')

        Returns:
            Generated context string

        Raises:
            VideoProcessingServiceError: If context generation fails after all retries
        """

        async def _context_operation() -> str:
            return await self._generate_context_for_video_chunk(
                video_chunk_path, start_sec, end_sec, transcript_text, media_resolution
            )

        try:
            return await retry_genai_operation(
                func=_context_operation,
                operation_name=f"generate_context({Path(video_chunk_path).name})",
            )
        except Exception as e:
            logger.error(
                "Video context generation failed after all retries",
                video_chunk_path=video_chunk_path,
                start_sec=start_sec,
                end_sec=end_sec,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise VideoProcessingServiceError(
                f"Video context generation failed: {str(e)}"
            ) from e

    def create_video_chunk(
        self,
        video_path: str,
        start_sec: float,
        end_sec: float,
        chunk_index: int,
    ) -> str:
        """
        Create a compressed video chunk file using ffmpeg with adaptive compression.

        Tries multiple compression levels to keep chunk under the size limit while
        maintaining best possible quality.

        Args:
            video_path: Path to the original video
            start_sec: Start time in seconds
            end_sec: End time in seconds
            chunk_index: Index of the chunk

        Returns:
            Path to the created chunk file

        Raises:
            VideoProcessingServiceError: If chunk creation fails or size cannot be reduced
        """
        try:
            video_dir = Path(video_path).parent
            video_name = Path(video_path).stem
            chunk_file = video_dir / f"{video_name}_chunk_{chunk_index:03d}.mp4"
            duration = end_sec - start_sec

            # Try progressive compression levels with error detection
            compression_levels = [
                {"crf": "28", "preset": "medium", "description": "light compression"},
                {"crf": "32", "preset": "fast", "description": "medium compression"},
                {"crf": "36", "preset": "veryfast", "description": "heavy compression"},
                {
                    "crf": "40",
                    "preset": "veryfast",
                    "description": "very heavy compression",
                },
                {
                    "crf": "44",
                    "preset": "veryfast",
                    "description": "maximum compression",
                },
            ]

            for level in compression_levels:
                success = self._create_chunk_with_compression(
                    video_path, start_sec, duration, chunk_file, level
                )
                if success:
                    return str(chunk_file)

            # Last resort: Multiple levels of resolution scaling
            logger.warning(
                "Trying resolution scaling as last resort",
                chunk_index=chunk_index,
            )

            # Try multiple resolution levels - progressively more aggressive
            scaling_levels = [
                {"resolution": "1280:720", "description": "720p scaling"},
                {"resolution": "854:480", "description": "480p scaling"},
                {"resolution": "640:360", "description": "360p scaling"},
            ]

            for scaling in scaling_levels:
                success = self._create_chunk_with_aggressive_scaling(
                    video_path, start_sec, duration, chunk_file, scaling
                )
                if success:
                    return str(chunk_file)

            raise VideoProcessingServiceError(
                f"Could not create chunk {chunk_index} under {config.MAX_VIDEO_CHUNK_SIZE_MB}MB "
                f"even with maximum compression and scaling"
            )

        except subprocess.CalledProcessError as e:
            logger.error(
                "Failed to create video chunk",
                video_path=video_path,
                start_sec=start_sec,
                end_sec=end_sec,
                chunk_index=chunk_index,
                error=str(e),
                stderr=e.stderr,
            )
            raise VideoProcessingServiceError(
                f"Video chunk creation failed: {e}"
            ) from e

    def _create_chunk_with_compression(
        self,
        video_path: str,
        start_sec: float,
        duration: float,
        chunk_file: Path,
        compression_settings: dict[str, str],
    ) -> bool:
        """Try creating chunk with specific compression settings and error detection."""
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-err_detect",
                    "ignore_err",  # Ignore errors and salvage corrupted segments
                    "-i",
                    video_path,
                    "-ss",
                    str(start_sec),
                    "-t",
                    str(duration),
                    "-c:v",
                    "libx264",
                    "-crf",
                    compression_settings["crf"],
                    "-preset",
                    compression_settings["preset"],
                    "-c:a",
                    "aac",
                    "-b:a",
                    "64k",  # Lower audio bitrate for 30-second chunks
                    "-avoid_negative_ts",
                    "make_zero",  # Fix timestamp issues for GenAI compatibility
                    "-fflags",
                    "+genpts",  # Generate presentation timestamps
                    str(chunk_file),
                    "-y",
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            if self._is_chunk_size_acceptable(chunk_file):
                logger.info(
                    "Chunk compressed successfully",
                    compression=compression_settings["description"],
                    crf=compression_settings["crf"],
                    size_mb=self._get_chunk_size_mb(chunk_file),
                )
                return True
            return False
        except subprocess.CalledProcessError:
            return False

    def _create_chunk_with_aggressive_scaling(
        self,
        video_path: str,
        start_sec: float,
        duration: float,
        chunk_file: Path,
        scaling_settings: dict[str, str],
    ) -> bool:
        """Create chunk with aggressive resolution scaling, compression, and error detection."""
        try:
            width, height = scaling_settings["resolution"].split(":")
            scale_filter = f"scale=min({width}\\,iw):min({height}\\,ih):force_original_aspect_ratio=decrease"

            subprocess.run(
                [
                    "ffmpeg",
                    "-err_detect",
                    "ignore_err",  # Ignore errors and salvage corrupted segments
                    "-i",
                    video_path,
                    "-ss",
                    str(start_sec),
                    "-t",
                    str(duration),
                    "-c:v",
                    "libx264",
                    "-crf",
                    "44",  # Very aggressive compression for 30-second chunks
                    "-preset",
                    "veryfast",
                    "-vf",
                    scale_filter,
                    "-c:a",
                    "aac",
                    "-b:a",
                    "48k",  # Very low audio bitrate for size reduction
                    "-avoid_negative_ts",
                    "make_zero",  # Fix timestamp issues for GenAI compatibility
                    "-fflags",
                    "+genpts",  # Generate presentation timestamps
                    str(chunk_file),
                    "-y",
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            if self._is_chunk_size_acceptable(chunk_file):
                logger.warning(
                    "Chunk created with aggressive scaling",
                    size_mb=self._get_chunk_size_mb(chunk_file),
                    scaling=scaling_settings["description"],
                    crf="44",
                    audio_bitrate="48k",
                )
                return True
            return False
        except subprocess.CalledProcessError:
            return False

    def _is_chunk_size_acceptable(self, chunk_file: Path) -> bool:
        """Check if chunk file is under the size limit."""
        size_mb = self._get_chunk_size_mb(chunk_file)
        return size_mb <= config.MAX_VIDEO_CHUNK_SIZE_MB

    def _get_chunk_size_mb(self, chunk_file: Path) -> float:
        """Get file size in MB."""
        if not chunk_file.exists():
            return float("inf")
        size_bytes = chunk_file.stat().st_size
        return size_bytes / (1024 * 1024)

    async def transcribe_video_segment(
        self,
        video_path: str,
        start_sec: float,
        end_sec: float,
        chunk_index: int,
    ) -> dict[str, Any]:
        """
        Transcribe a video segment using the existing AudioTranscriptionService.

        Args:
            video_path: Path to the video file
            start_sec: Start time in seconds
            end_sec: End time in seconds
            chunk_index: Index of this chunk for unique ID generation

        Returns:
            Transcription data with text and metadata
        """
        try:
            # Use the existing AudioTranscriptionService to transcribe the video chunk
            transcription_result = await self.transcription_service.transcribe_video_chunk(
                video_chunk_path=video_path,
                chunk_index=chunk_index,  # Use actual chunk index for unique audio file naming
                start_time=start_sec,
                end_time=end_sec,
                language_hint=config.VIDEO_DEFAULT_LANGUAGE,
            )

            # Extract transcript text and metadata from the result
            transcript_dict = transcription_result.get("transcript", {})
            transcript_text = transcript_dict.get("text", "").strip()

            # Handle silent video segments - empty transcript is valid for silent segments
            if not transcript_text:
                logger.info(
                    "Silent video segment detected - no speech to transcribe",
                    video_path=video_path,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    transcription_result=transcription_result,
                )
                # Continue processing - empty transcript is valid for silent segments

            # Convert the transcription result to the expected format
            duration = end_sec - start_sec
            result = {
                "text": transcript_text,
                "language": transcript_dict.get("language", "en-US"),
                "model": transcript_dict.get("model", "vertex-ai"),
                "timestamp": transcript_dict.get("transcript_timestamp", ""),
                "duration": str(duration),
                "has_audio": len(transcript_text) > 0,
                "error": transcript_dict.get("error"),
            }

            logger.info(
                "Video segment transcription completed",
                video_path=video_path,
                start_sec=start_sec,
                end_sec=end_sec,
                transcript_length=len(transcript_text),
                transcription_language=result["language"],
            )

            return result

        except Exception as e:
            logger.error(
                "Video transcription failed",
                video_path=video_path,
                start_sec=start_sec,
                end_sec=end_sec,
                error=str(e),
            )

            # Re-raise the exception to trigger retry instead of returning fallback
            raise VideoProcessingServiceError(
                f"Video transcription failed for segment {start_sec:.1f}s - {end_sec:.1f}s: {str(e)}"
            ) from e

    async def _generate_context_for_video_chunk(
        self,
        video_chunk_path: str,
        start_sec: float,
        end_sec: float,
        transcript_text: str,
        media_resolution: str,
    ) -> str:
        """
        Generate context for a video chunk using AI analysis.

        Combines visual analysis (what's shown on screen) with audio context
        (speaker identification, tonality) to provide comprehensive context
        that complements the transcription.

        Args:
            video_chunk_path: Path to the video chunk file
            start_sec: Start time of the chunk
            end_sec: End time of the chunk
            transcript_text: Transcribed text from the chunk
            media_resolution: The resolution setting to use for video analysis ('low' or 'default')

        Returns:
            Generated context string describing visual and audio elements

        Raises:
            VideoProcessingServiceError: If context generation fails critically
        """
        try:
            logger.info(
                "Starting context generation for video chunk",
                video_chunk_path=video_chunk_path,
                start_sec=start_sec,
                end_sec=end_sec,
                transcript_length=len(transcript_text),
                media_resolution=media_resolution,
            )

            # All video chunks are created as MP4 files by create_video_chunk()
            mime_type = "video/mp4"

            # Upload video chunk and wait for it to be ready using the file manager with retry logic
            uploaded_video = await self.file_manager.upload_and_wait_with_retry(
                video_chunk_path, mime_type=mime_type
            )

            try:
                # Create comprehensive prompt for full video analysis
                prompt = self._create_comprehensive_video_analysis_prompt(
                    transcript_text, start_sec, end_sec
                )

                # Generate comprehensive video context analysis
                contents: Any = [prompt, uploaded_video]

                response = await self.genai_client.aio.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=contents,
                )

                # Extract context from response
                context = (response.text or "").strip()

                # Fail if context generation returned empty - this will trigger a retry
                if not context:
                    raise VideoProcessingServiceError(
                        f"AI context generation failed for video chunk {start_sec:.1f}s-{end_sec:.1f}s: empty response from AI model"
                    )

                # Truncate context if it exceeds configured limit for embedding compatibility
                original_byte_length = len(context.encode("utf-8"))
                original_char_length = len(context)

                if original_byte_length > config.VIDEO_CONTEXT_MAX_BYTES:
                    # Truncate based on UTF-8 byte length, not character count
                    context_bytes = context.encode("utf-8")
                    truncated_bytes = context_bytes[: config.VIDEO_CONTEXT_MAX_BYTES]

                    # Ensure we don't cut in the middle of a multi-byte character
                    # by decoding with 'ignore' to handle partial characters
                    context = truncated_bytes.decode("utf-8", errors="ignore")

                    # Verify the result is actually within limits
                    final_byte_length = len(context.encode("utf-8"))

                    logger.warning(
                        "Context truncated for embedding compatibility",
                        video_chunk_path=video_chunk_path,
                        original_byte_length=original_byte_length,
                        original_char_length=original_char_length,
                        truncated_byte_length=final_byte_length,
                        truncated_char_length=len(context),
                        bytes_removed=original_byte_length - final_byte_length,
                    )

                logger.info(
                    "Video context generation completed",
                    video_chunk_path=video_chunk_path,
                    context_length=len(context),
                    mime_type=mime_type,
                )

                return context

            finally:
                # Always clean up uploaded video using file manager
                await self.file_manager.cleanup_file(uploaded_video)

        except Exception as e:
            logger.error(
                "Context generation failed",
                video_chunk_path=video_chunk_path,
                error=str(e),
                error_type=type(e).__name__,
            )
            # Re-raise the exception to trigger retry instead of using fallback
            raise VideoProcessingServiceError(
                f"AI context generation failed for video chunk {start_sec:.1f}s-{end_sec:.1f}s: {str(e)}"
            ) from e

    def _create_comprehensive_video_analysis_prompt(
        self, transcript_text: str, start_sec: float, end_sec: float
    ) -> str:
        """
        Create a comprehensive prompt for full video analysis.

        Args:
            transcript_text: Transcribed audio text
            start_sec: Start time of the chunk
            end_sec: End time of the chunk

        Returns:
            Formatted prompt for comprehensive video analysis
        """
        return f"""Analyze this entire {end_sec - start_sec:.1f}-second video segment comprehensively. Watch the full video from beginning to end and provide detailed context that complements the audio transcript for comprehensive video search and understanding.

            **TIME RANGE:** {start_sec:.1f}s - {end_sec:.1f}s (Original video timestamps)

            **AUDIO TRANSCRIPT:**
            {transcript_text}

            **COMPREHENSIVE ANALYSIS REQUIRED:**

            1. **COMPLETE VISUAL INVENTORY:**
            - All text content visible on screen (exact words, error messages, titles, labels, data values)
            - UI elements and interface components (buttons, menus, forms, dialogs, alerts)
            - Visual data presentations (charts, graphs, tables, numbers, metrics)
            - Scene changes and transitions throughout the video duration
            - People, faces, gestures, and body language
            - Objects, backgrounds, and environmental context
            - Any visual indicators of state changes (loading, errors, success states)

            2. **TEMPORAL PROGRESSION:**
            - Key moments and scene changes throughout the video duration
            - Actions and interactions that occur over time
            - Visual narrative flow and progression of events
            - Beginning state vs ending state of the video segment

            3. **AUDIO CHARACTERISTICS:**
            - Speaker demographics and characteristics (gender, accent, speaking style)
            - Emotional tone and sentiment (confident, frustrated, excited, neutral)
            - Speech patterns (pace, pauses, emphasis, clarity)
            - Background sounds, music, or environmental audio
            - Audio quality and technical characteristics

            4. **CONTENT DISCONNECTS & RELATIONSHIPS:**
            - Areas where visual content contradicts or differs from spoken content
            - Visual information that adds context not mentioned in audio
            - Demonstrations or examples shown visually while discussing concepts
            - Data or specifics shown on screen while audio discusses general topics

            5. **SEARCHABLE KEYWORDS & PHRASES:**
            - Specific technical terms, product names, or identifiers visible on screen
            - Error codes, version numbers, or technical specifications
            - Names of people, companies, or products mentioned or shown
            - Key concepts that someone might search for to find this content

            **CRITICAL DETECTION PRIORITIES:**
            - Error messages, warnings, or alerts visible on screen
            - Specific numerical data, metrics, or measurements displayed
            - Software interfaces, debugging screens, or technical demonstrations
            - Tutorial steps, click-by-click actions, or procedural demonstrations
            - Charts, graphs, or data visualizations with specific values
            - Text content that appears on screen (documents, code, UI text)

            **OUTPUT FORMAT:**
            Visual Summary: [Comprehensive description of all visual elements, changes, and content throughout the video]
            Audio Analysis: [Speaker characteristics, tone, delivery style, and background audio]
            Key Moments: [Chronological description of important visual changes or events during the video]
            Content Relationships: [How visual and audio content complement, contradict, or enhance each other]
            Search Keywords: [Specific terms, phrases, and identifiers that would help someone find this segment]

            **CRITICAL OUTPUT CONSTRAINT:**
            Your entire response must be 1024 characters or fewer. Be concise while capturing the most important details.
            Focus on the most searchable and distinctive elements. Prioritize specific text content, technical details,
            and unique identifiers over general descriptions.

            Be extremely detailed and specific within the character limit. Include exact text content, specific UI elements,
            numerical values, and any technical details visible. This analysis will be used for precise video search and retrieval.
        """

    async def process_video_file(
        self,
        video_path: str,
        user_id: str,
        document_id: str | None = None,
        contextual_text: str = "",
        job_id: str | None = None,
        media_resolution: str = "low",  # New parameter for controlling video resolution
    ) -> list[ChunkData]:
        """
        Process a complete video file.

        Args:
            video_path: Path to the video file
            user_id: ID of the user who owns the video
            document_id: Optional document ID to associate chunks with
            contextual_text: Optional contextual text for embedding
            job_id: Optional job ID for stage tracking
            media_resolution: The resolution setting to use for video analysis ('low' or 'default')

        Returns:
            List of processed chunks ready for storage

        Raises:
            VideoProcessingServiceError: If processing fails
        """
        logger.info(
            "Starting video processing",
            video_path=video_path,
            user_id=user_id,
            document_id=document_id,
            job_id=job_id,
            media_resolution=media_resolution,
        )

        # Variables to track original vs cleaned paths for cleanup
        original_video_path = video_path
        cleaned_video_path = None

        try:
            # Update stage: cleaning video
            if job_id:
                await self.database_service.update_processing_stage(
                    job_id, "cleaning_video"
                )

            # Clean and normalize video for Vertex AI compatibility
            video_path = self.clean_and_normalize_video(video_path)

            # Track if we created a cleaned file for cleanup
            if video_path != original_video_path:
                cleaned_video_path = video_path
                logger.info(
                    "Using cleaned video file for processing",
                    original_path=original_video_path,
                    cleaned_path=video_path,
                )

            # Update stage: analyzing video
            if job_id:
                await self.database_service.update_processing_stage(
                    job_id, "analyzing_video"
                )

            # Get video duration
            duration = self.get_video_duration(video_path)

            # Update stage: processing video content
            if job_id:
                await self.database_service.update_processing_stage(
                    job_id, "processing_video"
                )

            # Process video in batches for improved performance
            chunks = await self._process_chunks_in_batches(
                video_path=video_path,
                duration=duration,
                contextual_text=contextual_text,
                job_id=job_id,
                media_resolution=media_resolution,
            )

            logger.info(
                "Video processing completed",
                video_path=video_path,
                chunk_count=len(chunks),
                duration_seconds=duration,
                job_id=job_id,
            )

            return chunks

        except JobCancelledError as e:
            logger.info(
                "Video processing cancelled - job was deleted during processing",
                video_path=video_path,
                user_id=user_id,
                job_id=job_id,
                error=str(e),
            )
            # Re-raise to signal cancellation to caller
            raise
        except Exception as e:
            logger.error(
                "Video processing failed",
                video_path=video_path,
                user_id=user_id,
                job_id=job_id,
                error=str(e),
            )
            raise VideoProcessingServiceError(f"Video processing failed: {e}") from e
        finally:
            # Clean up video files AND any temporary files created by the transcription service
            try:
                # Clean up the original video file that was passed to us
                cleanup_temp_file(original_video_path)
                logger.debug(
                    "Cleaned up original video file", video_path=original_video_path
                )

                # Clean up cleaned MP4 file if we created one
                if cleaned_video_path and cleaned_video_path != original_video_path:
                    cleanup_temp_file(cleaned_video_path)
                    logger.debug(
                        "Cleaned up cleaned video file",
                        video_path=cleaned_video_path,
                    )

                # Clean up any additional temporary files created by the transcription service
                self.transcription_service.cleanup_temp_files()
            except Exception as cleanup_error:
                logger.warning(
                    "Failed to cleanup video processing temp files",
                    original_path=original_video_path,
                    cleaned_path=cleaned_video_path,
                    error=str(cleanup_error),
                )

    def _create_chunk_metadata(
        self,
        video_path: str,
        contextual_text: str,
        chunk_index: int,
        start_sec: float,
        end_sec: float,
        total_chunks: int,
        transcript_data: dict[str, Any],
    ) -> VideoChunkMetadata:
        """
        Create metadata for a video chunk.

        Args:
            video_path: Path to the original video
            contextual_text: Contextual text for embedding
            chunk_index: Index of this chunk
            start_sec: Start time of chunk in seconds
            end_sec: End time of chunk in seconds
            total_chunks: Total number of chunks
            transcript_data: Transcription results

        Returns:
            VideoChunkMetadata object
        """
        return VideoChunkMetadata(
            media_path=video_path,
            contextual_text=contextual_text,
            segment_index=chunk_index,
            start_offset_sec=start_sec,
            end_offset_sec=end_sec,
            duration_sec=end_sec - start_sec,
            total_segments=total_chunks,
            transcript=TranscriptMetadata(
                language=transcript_data.get("language", "unknown"),
                model=transcript_data.get("model", "unknown"),
                transcript_timestamp=transcript_data.get("timestamp", ""),
                has_audio=transcript_data.get("has_audio", False),
                error=transcript_data.get("error"),
            ),
        )

    async def _process_chunks_in_batches(
        self,
        video_path: str,
        duration: float,
        contextual_text: str = "",
        job_id: str | None = None,
        media_resolution: str = "low",
    ) -> list[ChunkData]:
        """
        Process video chunks in batches for improved performance.

        Uses hybrid approach: sequential chunk file creation followed by
        parallel batch processing of transcription/AI operations.

        Args:
            video_path: Path to the video file
            duration: Video duration in seconds
            contextual_text: Contextual text for embedding
            job_id: Optional job ID for progress tracking
            media_resolution: The resolution setting to use for video analysis

        Returns:
            List of processed chunks ready for storage

        Raises:
            VideoProcessingServiceError: If no chunks are successfully processed
        """
        total_chunks = math.ceil(duration / config.VIDEO_CHUNK_DURATION_SECONDS)
        batch_size = config.VIDEO_PROCESSING_BATCH_SIZE
        total_batches = math.ceil(total_chunks / batch_size)

        logger.info(
            "Starting batch video processing",
            video_path=video_path,
            total_chunks=total_chunks,
            batch_size=batch_size,
            total_batches=total_batches,
            media_resolution=media_resolution,
        )

        # Phase 1: Create all chunk files sequentially (preserves stability)
        if job_id:
            await self.database_service.update_processing_stage(
                job_id, "creating_video_chunks"
            )

        chunk_files: list[ChunkFileData] = []
        for chunk_index in range(total_chunks):
            start_sec = chunk_index * config.VIDEO_CHUNK_DURATION_SECONDS
            end_sec = min(start_sec + config.VIDEO_CHUNK_DURATION_SECONDS, duration)

            # Skip chunks shorter than minimum duration (prevents micro-chunk processing issues)
            chunk_duration = end_sec - start_sec
            if chunk_duration < 5.0:
                logger.info(
                    "Skipping short video chunk (< 5 seconds)",
                    chunk_index=chunk_index,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    duration=chunk_duration,
                    reason="below_minimum_duration",
                )
                continue

            chunk_file = self.create_video_chunk(
                video_path, start_sec, end_sec, chunk_index
            )
            chunk_files.append(
                ChunkFileData(
                    chunk_file=chunk_file,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    chunk_index=chunk_index,
                )
            )

        # Phase 2: Process chunks in batches
        # Recalculate batch counts based on actual chunks after filtering
        actual_chunk_count = len(chunk_files)
        if actual_chunk_count == 0:
            logger.warning("No chunks to process after filtering short segments")
            return []

        actual_batches = math.ceil(actual_chunk_count / batch_size)
        all_chunks: list[ChunkData] = []
        failed_chunks = 0
        max_failed_chunks = int(
            actual_chunk_count * config.VIDEO_SUCCESS_THRESHOLD
        )  # Use actual chunk count for threshold

        logger.info(
            "Processing filtered chunks in batches",
            original_chunks=total_chunks,
            actual_chunks=actual_chunk_count,
            skipped_chunks=total_chunks - actual_chunk_count,
            actual_batches=actual_batches,
        )

        for batch_num in range(actual_batches):
            if job_id:
                await self.database_service.update_processing_stage(
                    job_id, f"processing_batch_{batch_num + 1}_of_{actual_batches}"
                )

            # Get batch of chunk files
            batch_start = batch_num * batch_size
            batch_end = min(batch_start + batch_size, actual_chunk_count)
            batch = chunk_files[batch_start:batch_end]

            # Create parallel tasks for this batch
            batch_tasks = []
            for chunk_data in batch:
                task = self._process_single_chunk_content(
                    chunk_file=chunk_data["chunk_file"],
                    video_path=video_path,
                    start_sec=chunk_data["start_sec"],
                    end_sec=chunk_data["end_sec"],
                    chunk_index=chunk_data["chunk_index"],
                    total_chunks=actual_chunk_count,
                    contextual_text=contextual_text,
                    media_resolution=media_resolution,
                )
                batch_tasks.append(task)

            # Process batch in parallel with timeout
            try:
                batch_results = await asyncio.gather(
                    *batch_tasks, return_exceptions=True
                )

                # Handle batch results - separate successful results from exceptions
                for i, result in enumerate(batch_results):
                    if isinstance(result, Exception):
                        failed_chunks += 1
                        chunk_info = batch[i]
                        logger.error(
                            "Batch chunk processing failed",
                            chunk_index=chunk_info["chunk_index"],
                            batch_num=batch_num + 1,
                            error=str(result),
                        )

                        # Fail-fast logic: fail entire video if too many chunks fail
                        if failed_chunks > max_failed_chunks:
                            raise NonRetryableError(
                                f"Too many video chunks failed: {failed_chunks}/{actual_chunk_count}. "
                                f"Video processing cannot continue."
                            ) from result
                    elif isinstance(result, ChunkData):
                        # Only add successful ChunkData results
                        all_chunks.append(result)
                    else:
                        # This should not happen, but handle unexpected types
                        logger.error(
                            "Unexpected result type in batch processing",
                            result_type=type(result),
                            batch_num=batch_num + 1,
                        )

            except asyncio.TimeoutError as e:
                logger.error(
                    f"Batch {batch_num + 1} timed out",
                    batch_size=len(batch),
                    total_batches=total_batches,
                )
                raise VideoProcessingServiceError(
                    f"Batch processing timeout: {e}"
                ) from e

            # Clean up chunk files for this batch
            for chunk_data in batch:
                cleanup_temp_file(Path(chunk_data["chunk_file"]))

        # Ensure we processed at least some chunks
        if not all_chunks:
            raise VideoProcessingServiceError("No chunks were successfully processed")

        logger.info(
            "Batch video processing completed",
            video_path=video_path,
            original_chunks=total_chunks,
            actual_chunks=actual_chunk_count,
            successful_chunks=len(all_chunks),
            failed_chunks=failed_chunks,
            actual_batches=actual_batches,
        )

        return all_chunks

    async def _process_single_chunk_content(
        self,
        chunk_file: str,
        video_path: str,
        start_sec: float,
        end_sec: float,
        chunk_index: int,
        total_chunks: int,
        contextual_text: str,
        media_resolution: str = "low",
    ) -> ChunkData:
        """
        Process the content of a single video chunk (no progress tracking).

        This is the core chunk processing logic extracted from _process_single_chunk
        for use in batch processing where progress is tracked at batch level.

        Args:
            chunk_file: Path to the chunk file (already created)
            video_path: Path to the original video file
            start_sec: Start time of chunk in seconds
            end_sec: End time of chunk in seconds
            chunk_index: Index of this chunk
            total_chunks: Total number of chunks
            contextual_text: Contextual text for embedding
            media_resolution: The resolution setting to use for video analysis

        Returns:
            Single ChunkData object with processed content

        Raises:
            VideoProcessingServiceError: If chunk processing fails
        """
        try:
            # Start transcription and visual analysis in parallel
            transcript_task = asyncio.create_task(
                self._transcribe_video_segment_with_retry(
                    chunk_file, start_sec, end_sec, chunk_index
                )
            )

            context_task = asyncio.create_task(
                self._generate_context_with_retry(
                    video_chunk_path=chunk_file,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    transcript_text="",
                    media_resolution=media_resolution,
                )
            )

            # Wait for both to complete
            transcript_data, context = await asyncio.gather(
                transcript_task, context_task
            )

            # Extract transcript text
            transcript_text = transcript_data.get("text", "").strip()
            logger.info(
                "Extracted transcript from batch chunk processing",
                chunk_index=chunk_index,
                chunk_file=Path(chunk_file).name,
                start_sec=start_sec,
                end_sec=end_sec,
                transcript_length=len(transcript_text),
                transcript_preview=(
                    transcript_text[:100].replace("\n", " ")
                    if transcript_text
                    else "EMPTY"
                ),
                has_audio=transcript_data.get("has_audio", False),
            )

            # Generate multimodal embedding (no text context needed - video content is sufficient)
            multimodal_embedding = (
                await self.embedding_service.generate_multimodal_embedding(
                    media_file_path=chunk_file,
                )
            )

            # Handle silent vs non-silent segments
            if not transcript_text:
                truncated_transcript = ""
                text_embedding = None
                chunk_text = f"Silent video segment {start_sec:.1f}s-{end_sec:.1f}s"
            else:
                # Truncate transcript if needed
                truncated_transcript = truncate_text_to_tokens(
                    text=transcript_text, tokenizer=self.tokenizer, max_tokens=2047
                )

                # Generate text embedding
                text_embedding = await self.embedding_service.generate_text_embedding(
                    truncated_transcript
                )
                chunk_text = truncated_transcript

            # Create chunk metadata
            metadata = self._create_chunk_metadata(
                video_path=video_path,
                contextual_text=contextual_text,
                chunk_index=chunk_index,
                start_sec=start_sec,
                end_sec=end_sec,
                total_chunks=total_chunks,
                transcript_data=transcript_data,
            )

            return ChunkData(
                text=chunk_text,
                metadata=metadata,
                context=context,
                text_embedding=text_embedding,
                multimodal_embedding=multimodal_embedding,
            )

        except Exception as e:
            logger.error(
                "Chunk content processing failed",
                chunk_index=chunk_index,
                start_sec=start_sec,
                end_sec=end_sec,
                error=str(e),
            )
            raise VideoProcessingServiceError(
                f"Chunk processing failed for segment {start_sec:.1f}s-{end_sec:.1f}s: {str(e)}"
            ) from e


# Global service instance
_video_processing_service: VideoProcessingService | None = None


def get_video_processing_service(
    project_id: str | None = None,
) -> VideoProcessingService:
    """
    Get a singleton video processing service instance.

    Since there's only one project, this ensures we reuse the same service
    instance across the application for efficiency and resource management.

    Args:
        project_id: Google Cloud project ID (used only on first initialization)

    Returns:
        VideoProcessingService singleton instance
    """
    global _video_processing_service

    if _video_processing_service is None:
        _video_processing_service = VideoProcessingService(project_id=project_id)

    return _video_processing_service
