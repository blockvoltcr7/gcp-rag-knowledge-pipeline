"""
Audio Transcription Service using Google GenAI

This module provides video transcription capabilities by using Google GenAI
to transcribe audio content directly through Gemini models with proper authentication.
"""

import asyncio
import logging
import mimetypes
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import google.genai as genai
from google.genai import types

from ..config import config
from ..utils.content_router import get_content_router
from ..utils.retry_utils import NonRetryableError

logger = logging.getLogger(__name__)


class AudioTranscriptionError(NonRetryableError):
    """Base exception for audio transcription errors."""

    pass


class NoAudioTrackError(AudioTranscriptionError):
    """Raised when a video file has no audio track."""

    pass


class AudioTranscriptionService:
    """Service for transcribing audio from video chunks using Google GenAI."""

    def __init__(self) -> None:
        """Initialize the audio transcription service."""
        # Initialize Google GenAI client with Vertex AI backend
        self.genai_client = genai.Client(
            vertexai=False,
            api_key=config.GEMINI_API_KEY,
        )

        self.temp_dir = Path(tempfile.gettempdir()) / "rag_transcription"
        self.temp_dir.mkdir(exist_ok=True)

        logger.info("AudioTranscriptionService initialized with Google GenAI")

    async def extract_audio_from_video(
        self, video_path: str, output_format: str = "mp3", unique_id: str | None = None
    ) -> tuple[str, dict[str, Any]]:
        """
        Extract audio from video file using ffmpeg.

        Args:
            video_path: Path to the video file
            output_format: Output audio format (mp3, wav, etc.)
            unique_id: Optional unique identifier to avoid filename collisions in parallel processing

        Returns:
            Tuple of (audio_file_path, metadata)

        Raises:
            NoAudioTrackError: If video has no audio track
            AudioTranscriptionError: If extraction fails
        """
        try:
            # Create temporary file for extracted audio with unique naming to prevent batch processing collisions
            if unique_id:
                temp_audio_file = self.temp_dir / f"audio_{unique_id}.{output_format}"
            else:
                # Generate unique ID using UUID for guaranteed collision safety
                import uuid

                unique_suffix = str(uuid.uuid4())[
                    :8
                ]  # Short UUID for readable filenames
                temp_audio_file = (
                    self.temp_dir / f"audio_{unique_suffix}.{output_format}"
                )

            # Build ffmpeg command for audio extraction with timestamp compatibility
            ffmpeg_cmd = [
                "ffmpeg",
                "-i",
                video_path,
                "-vn",  # No video
                "-acodec",
                "libmp3lame" if output_format == "mp3" else "pcm_s16le",
                "-ar",
                "16000",  # 16kHz sample rate for compatibility
                "-ac",
                "1",  # Mono channel
                "-avoid_negative_ts",
                "make_zero",  # Fix timestamp issues for consistency with video processing
                "-fflags",
                "+genpts",  # Generate presentation timestamps
                "-y",  # Overwrite output file
                str(temp_audio_file),
            ]

            logger.info(
                "Extracting audio from video: video_path=%s, output_file=%s, format=%s, unique_id=%s",
                video_path,
                str(temp_audio_file),
                output_format,
                unique_id or "generated",
            )

            # Run ffmpeg
            process = await asyncio.create_subprocess_exec(
                *ffmpeg_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode("utf-8") if stderr else "Unknown ffmpeg error"

                # Check if video has no audio track
                if (
                    "does not contain any stream" in error_msg
                    or "No audio" in error_msg
                ):
                    raise NoAudioTrackError(f"Video has no audio track: {video_path}")

                raise AudioTranscriptionError(f"Audio extraction failed: {error_msg}")

            # Verify the output file was created and has content
            if not temp_audio_file.exists() or temp_audio_file.stat().st_size == 0:
                raise AudioTranscriptionError(
                    f"Audio extraction produced empty file: {temp_audio_file}"
                )

            # Get basic metadata
            metadata = {
                "duration_seconds": await self._get_audio_duration(
                    str(temp_audio_file)
                ),
                "file_size_bytes": temp_audio_file.stat().st_size,
                "format": output_format,
            }

            logger.info(
                "Audio extraction successful: audio_file=%s, duration_seconds=%s, file_size_bytes=%d",
                str(temp_audio_file),
                metadata.get("duration_seconds", "unknown"),
                temp_audio_file.stat().st_size,
            )

            return str(temp_audio_file), metadata

        except (NoAudioTrackError, AudioTranscriptionError):
            raise
        except Exception as e:
            logger.error(
                "Unexpected error during audio extraction: video_path=%s, error=%s, error_type=%s",
                video_path,
                str(e),
                type(e).__name__,
            )
            raise AudioTranscriptionError(
                f"Unexpected error during audio extraction: {e}"
            ) from e

    async def get_audio_duration(self, audio_path: str) -> float:
        """Get audio duration using ffprobe."""
        try:
            ffprobe_cmd = [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                audio_path,
            ]

            process = await asyncio.create_subprocess_exec(
                *ffprobe_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                logger.warning(
                    "Failed to get audio duration: audio_path=%s", audio_path
                )
                return 0.0

            import json

            probe_data = json.loads(stdout.decode("utf-8"))

            if "format" in probe_data:
                return float(probe_data["format"].get("duration", 0))

            return 0.0

        except Exception as e:
            logger.warning(
                "Error getting audio duration: audio_path=%s, error=%s",
                audio_path,
                str(e),
            )
            return 0.0

    async def _get_audio_duration(self, audio_path: str) -> float:
        """Get audio duration using ffprobe (deprecated - use get_audio_duration)."""
        return await self.get_audio_duration(audio_path)

    async def transcribe_audio_with_genai(
        self, audio_path: str, language_hint: str | None = None
    ) -> dict[str, Any]:
        """
        Transcribe audio using Google GenAI Gemini models.

        Args:
            audio_path: Path to the audio file
            language_hint: Optional language hint for transcription

        Returns:
            Dictionary containing transcription results

        Raises:
            AudioTranscriptionError: If transcription fails
        """
        try:
            logger.info(
                "Starting audio transcription with Google GenAI: audio_path=%s, language_hint=%s",
                audio_path,
                language_hint,
            )

            # Upload audio file to GenAI using async API
            # First, determine the MIME type for the file
            # Determine the MIME type using centralized router
            content_router = get_content_router()
            mime_type = content_router.get_mime_type_for_extension(audio_path)

            # Fallback to mimetypes.guess_type if not found in router
            if not mime_type:
                mime_type, _ = mimetypes.guess_type(audio_path)

            # Throw error if MIME type cannot be determined
            if not mime_type:
                raise AudioTranscriptionError(
                    f"Cannot determine MIME type for audio file: {audio_path}. "
                    f"Unsupported audio format."
                )

            logger.info(
                "Processing audio file with MIME type: audio_path=%s, mime_type=%s",
                audio_path,
                mime_type,
            )

            # Read the audio file and create a Part with explicit MIME type
            with open(audio_path, "rb") as f:
                audio_data = f.read()

            # Create a Part with the audio data and explicit MIME type
            audio_part = types.Part.from_bytes(data=audio_data, mime_type=mime_type)

            logger.info(
                "Audio file prepared for transcription: size=%d bytes, mime_type=%s",
                len(audio_data),
                mime_type,
            )

            # Create transcription prompt
            base_prompt = "Generate a transcript of the speech."

            if language_hint:
                base_prompt += f" The audio is likely in {language_hint}."

            base_prompt += (
                " Only return the transcribed text, no additional commentary."
            )

            # Generate transcription using GenAI async API
            # The Google GenAI library accepts this format as documented
            response = await self.genai_client.aio.models.generate_content(
                model=config.TRANSCRIPTION_MODEL,
                contents=[base_prompt, audio_part],  # type: ignore[arg-type]
                config={"max_output_tokens": config.TRANSCRIPTION_MAX_TOKENS},
            )

            # Process response
            transcript_text = (response.text or "").strip()

            if not transcript_text:
                logger.warning(
                    "Empty transcription received: audio_path=%s", audio_path
                )
                transcript_text = ""

            # Create response structure
            transcript_data: dict[str, Any] = {
                "text": transcript_text,
                "language": language_hint or "auto-detected",
                "model": config.TRANSCRIPTION_MODEL,
                "transcript_timestamp": datetime.now(timezone.utc).isoformat(),
                "words": [],  # GenAI doesn't provide word-level timing
            }

            logger.info(
                "Audio transcription completed: audio_path=%s, transcript_length=%d, model=%s",
                audio_path,
                len(transcript_text),
                config.TRANSCRIPTION_MODEL,
            )

            return transcript_data

        except Exception as e:
            error_msg = str(e)
            is_rate_limit = self._is_rate_limit_error(e)

            logger.error(
                "Audio transcription failed: audio_path=%s, error=%s, error_type=%s, is_rate_limit=%s",
                audio_path,
                error_msg,
                type(e).__name__,
                is_rate_limit,
            )

            if is_rate_limit:
                raise AudioTranscriptionError(
                    f"Transcription failed due to API rate limiting: {error_msg}. "
                    "This indicates API quota exhaustion - check your Gemini API usage limits."
                ) from e
            else:
                raise AudioTranscriptionError(
                    f"Transcription failed: {error_msg}"
                ) from e

    def _is_rate_limit_error(self, exception: Exception) -> bool:
        """Check if an exception is due to rate limiting."""
        error_msg = str(exception).lower()
        return (
            "429" in error_msg
            or "resource_exhausted" in error_msg
            or "quota" in error_msg
            or "rate limit" in error_msg
            or "too many requests" in error_msg
        )

    async def transcribe_video_chunk(
        self,
        video_chunk_path: str,
        chunk_index: int,
        start_time: float,
        end_time: float,
        language_hint: str | None = None,
    ) -> dict[str, Any]:
        """
        Extract audio from video chunk and transcribe it.

        Args:
            video_chunk_path: Path to the video chunk file
            chunk_index: Index of the chunk in the sequence
            start_time: Start time of the chunk in seconds
            end_time: End time of the chunk in seconds
            language_hint: Optional language hint for transcription

        Returns:
            Dictionary containing chunk metadata and transcription
        """
        audio_file_path = None

        try:
            logger.info(
                "Starting video chunk transcription: video_chunk=%s, chunk_index=%d, start_time=%f, end_time=%f",
                video_chunk_path,
                chunk_index,
                start_time,
                end_time,
            )

            # Step 1: Extract audio from video chunk with unique ID to prevent batch processing collisions
            # Use chunk-specific unique ID that includes actual time boundaries
            unique_id = f"chunk_{chunk_index}_{start_time:.1f}_{end_time:.1f}"
            audio_file_path, audio_metadata = await self.extract_audio_from_video(
                video_chunk_path, unique_id=unique_id
            )

            # Step 2: Transcribe the extracted audio
            transcript_data = await self.transcribe_audio_with_genai(
                audio_file_path, language_hint
            )

            # Step 3: Combine results
            result = {
                "chunk_metadata": {
                    "chunk_index": chunk_index,
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration": end_time - start_time,
                    "audio_metadata": audio_metadata,
                },
                "transcript": transcript_data,
            }

            logger.info(
                "Video chunk transcription completed: video_chunk=%s, chunk_index=%d, transcript_length=%d, unique_id=%s, transcript_preview=%s",
                video_chunk_path,
                chunk_index,
                len(transcript_data.get("text", "")),
                unique_id,
                (transcript_data.get("text", "") or "")[:100].replace("\n", " "),
            )

            return result

        except NoAudioTrackError:
            logger.warning(
                "Video chunk has no audio track, storing empty transcript: video_chunk=%s, chunk_index=%d",
                video_chunk_path,
                chunk_index,
            )

            return {
                "chunk_metadata": {
                    "chunk_index": chunk_index,
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration": end_time - start_time,
                },
                "transcript": {
                    "text": "",
                    "language": language_hint or "unknown",
                    "model": config.TRANSCRIPTION_MODEL,
                    "transcript_timestamp": datetime.now(timezone.utc).isoformat(),
                    "words": [],
                    "error": "No audio track found",
                },
            }

        except Exception as e:
            logger.error(
                "Video chunk transcription failed: video_chunk=%s, chunk_index=%d, error=%s, error_type=%s",
                video_chunk_path,
                chunk_index,
                str(e),
                type(e).__name__,
            )

            return {
                "chunk_metadata": {
                    "chunk_index": chunk_index,
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration": end_time - start_time,
                },
                "transcript": {
                    "text": "",
                    "language": language_hint or "unknown",
                    "model": config.TRANSCRIPTION_MODEL,
                    "transcript_timestamp": datetime.now(timezone.utc).isoformat(),
                    "words": [],
                    "error": str(e),
                },
            }

        finally:
            # Clean up temporary audio file
            if audio_file_path and os.path.exists(audio_file_path):
                try:
                    os.remove(audio_file_path)
                    logger.debug(
                        "Cleaned up temporary audio file: audio_file=%s",
                        audio_file_path,
                    )
                except Exception as cleanup_error:
                    logger.warning(
                        "Failed to clean up temporary audio file: audio_file=%s, error=%s",
                        audio_file_path,
                        str(cleanup_error),
                    )

    def cleanup_temp_files(self) -> None:
        """Clean up any orphaned temporary files."""
        try:
            for temp_file in self.temp_dir.glob("audio_*"):
                if temp_file.is_file():
                    try:
                        temp_file.unlink()
                        logger.debug(
                            "Cleaned up orphaned temp file: file=%s", str(temp_file)
                        )
                    except Exception as e:
                        logger.warning(
                            "Failed to clean up temp file: file=%s, error=%s",
                            str(temp_file),
                            str(e),
                        )
        except Exception as e:
            logger.warning("Error during temp file cleanup: error=%s", str(e))
