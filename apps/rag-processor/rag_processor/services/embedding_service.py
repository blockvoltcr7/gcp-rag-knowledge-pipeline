"""
Embedding service for generating embeddings using Google Gemini.

Handles both text and multimodal embeddings with proper error handling,
logging, and retry logic.
"""

from pathlib import Path

import google.genai as genai
import structlog
import vertexai
from google.genai.types import EmbedContentConfig
from vertexai.vision_models import Image, MultiModalEmbeddingModel, Video

from ..config import config
from ..utils.retry_utils import NonRetryableError, is_retryable_genai_error, retry_async
from ..utils.token_utils import create_google_tokenizer

logger = structlog.get_logger(__name__)


class EmbeddingServiceError(NonRetryableError):
    """
    Base exception for embedding service errors.

    Inherits from NonRetryableError to prevent infinite retry loops
    when embedding generation fails permanently (e.g., contextual text too long,
    unsupported file format, API quota exceeded).

    For temporary service failures (503, 502, 500), the original exception
    is re-raised to allow retry logic to handle them properly.
    """

    pass


class EmbeddingService:
    """
    Service for generating embeddings using Google AI services.

    Uses google-genai as primary choice for text embeddings and vertexai only
    for multimodal embeddings (since genai doesn't support them yet).
    """

    def __init__(
        self,
        text_model: str = "gemini-embedding-001",
        multimodal_model: str = "multimodalembedding@001",
        text_dimensions: int = 3072,
        multimodal_dimensions: int = 1408,
        project_id: str | None = None,
    ):
        """
        Initialize the embedding service.

        Args:
            text_model: Model name for text embeddings
            multimodal_model: Model name for multimodal embeddings
            text_dimensions: Dimensions for text embeddings
            multimodal_dimensions: Dimensions for multimodal embeddings
            project_id: Google Cloud project ID
        """
        self.text_model = text_model
        self.multimodal_model = multimodal_model
        self.text_dimensions = text_dimensions
        self.multimodal_dimensions = multimodal_dimensions

        # Initialize new genai client for text embeddings with Vertex AI
        self.genai_client = genai.Client(
            vertexai=True,
            project=project_id,
            location=config.VERTEX_AI_LOCATION,  # Use configured location
        )

        # Initialize Vertex AI for multimodal embeddings (genai doesn't support these yet)
        vertexai.init(project=project_id, location=config.VERTEX_AI_LOCATION)
        self.multimodal_embedding_model = MultiModalEmbeddingModel.from_pretrained(
            multimodal_model
        )

        # Initialize tokenizer for contextual text truncation
        self.tokenizer = create_google_tokenizer(genai_client=self.genai_client)

        logger.info(
            "Embedding service initialized",
            text_model=text_model,
            multimodal_model=multimodal_model,
            text_dimensions=text_dimensions,
            multimodal_dimensions=multimodal_dimensions,
        )

    async def generate_text_embedding(
        self,
        text: str,
    ) -> list[float]:
        """
        Generate text embedding using Google's gemini-embedding-001 model.

        Args:
            text: Text to embed

        Returns:
            Embedding vector as list of floats

        Raises:
            EmbeddingServiceError: If embedding generation fails
        """
        if not text.strip():
            raise EmbeddingServiceError("Cannot generate embedding for empty text")

        async def _generate_embedding() -> list[float]:
            try:
                logger.info(
                    "Generating text embedding",
                    text_length=len(text),
                    model=self.text_model,
                )

                response = self.genai_client.models.embed_content(
                    model=self.text_model,
                    contents=text,
                    config=EmbedContentConfig(
                        task_type="RETRIEVAL_DOCUMENT",
                        output_dimensionality=self.text_dimensions,
                    ),
                )

                if not response.embeddings or not response.embeddings[0].values:
                    raise EmbeddingServiceError(
                        "No embedding returned from Google GenAI"
                    )

                embedding = list(response.embeddings[0].values)

                logger.info(
                    "Text embedding generated successfully",
                    embedding_dimension=len(embedding),
                    text_length=len(text),
                )

                return embedding

            except Exception as e:
                error_msg = str(e)
                is_retryable = is_retryable_genai_error(e)

                logger.error(
                    "Text embedding generation failed",
                    error=error_msg,
                    error_type=type(e).__name__,
                    text_length=len(text),
                    is_retryable=is_retryable,
                )

                if is_retryable:
                    # Let retry logic handle retryable errors (503, 502, 500, temporary rate limits)
                    raise e
                else:
                    # Wrap permanent failures (quota exhaustion, invalid input, etc.)
                    raise EmbeddingServiceError(
                        f"Text embedding generation failed: {error_msg}"
                    ) from e

        return list(
            await retry_async(
                _generate_embedding, operation_name="generate_text_embedding"
            )
        )

    async def generate_multimodal_embedding(
        self,
        media_file_path: str,
        contextual_text: str = "",
    ) -> list[float]:
        """
        Generate multimodal embedding using Vertex AI SDK.

        Note: Uses vertexai because google-genai doesn't support multimodal embeddings yet.

        Args:
            media_file_path: Path to media file
            contextual_text: Optional contextual text to include

        Returns:
            List of float values representing the embedding

        Raises:
            EmbeddingServiceError: If embedding generation fails
        """

        async def _generate_embedding() -> list[float]:
            try:
                # Truncate contextual text for multimodal embedding (1024 character limit)
                truncated_contextual_text = contextual_text
                if contextual_text and len(contextual_text) > 1023:
                    truncated_contextual_text = contextual_text[:1023]
                    logger.info(
                        "Truncated contextual text for multimodal embedding",
                        original_length=len(contextual_text),
                        truncated_length=len(truncated_contextual_text),
                        original_chars=len(contextual_text),
                        truncated_chars=1023,
                    )

                # Determine file type and load accordingly
                file_ext = media_file_path.lower().split(".")[-1]
                image_formats = ["jpg", "jpeg", "png", "webp"]
                video_formats = ["mp4", "mov", "avi", "mkv", "webm", "flv", "m4v"]

                embedding: list[float] = []  # Initialize to avoid unbound variable

                if file_ext in image_formats:
                    media_obj = Image.load_from_file(media_file_path)

                    # Handle image files
                    if truncated_contextual_text.strip():
                        embeddings = self.multimodal_embedding_model.get_embeddings(
                            image=media_obj,
                            contextual_text=truncated_contextual_text,
                            dimension=self.multimodal_dimensions,
                        )
                    else:
                        embeddings = self.multimodal_embedding_model.get_embeddings(
                            image=media_obj,
                            dimension=self.multimodal_dimensions,
                        )

                    # Extract the embedding vector for images
                    if (
                        hasattr(embeddings, "image_embedding")
                        and embeddings.image_embedding
                    ):
                        embedding = list(
                            embeddings.image_embedding
                        )  # Cast to list[float]
                    else:
                        raise EmbeddingServiceError(
                            "No image embedding found in response"
                        )

                elif file_ext in video_formats:
                    if Video is None:
                        raise EmbeddingServiceError(
                            "vertexai Video class is not available"
                        )
                    media_obj = Video.load_from_file(media_file_path)

                    # Log file size before calling API to debug 27MB limit issues
                    file_size_bytes = Path(media_file_path).stat().st_size
                    file_size_mb = round(file_size_bytes / (1024 * 1024), 2)

                    logger.info(
                        "Calling multimodal embedding API",
                        media_file=media_file_path,
                        file_size_mb=file_size_mb,
                        file_size_bytes=file_size_bytes,
                        contextual_text_length=len(truncated_contextual_text),
                        contextual_text_chars=len(truncated_contextual_text),
                        model=self.multimodal_model,
                        file_extension=file_ext,
                    )

                    # Handle video files (do NOT pass dimension for video - fixed at 1408)
                    if truncated_contextual_text.strip():
                        embeddings = self.multimodal_embedding_model.get_embeddings(
                            video=media_obj,
                            contextual_text=truncated_contextual_text,
                        )
                    else:
                        embeddings = self.multimodal_embedding_model.get_embeddings(
                            video=media_obj,
                        )

                    # Extract the first segment embedding for videos (simplified approach)
                    if (
                        hasattr(embeddings, "video_embeddings")
                        and embeddings.video_embeddings
                    ):
                        video_segments = embeddings.video_embeddings
                        if len(video_segments) > 0:
                            embedding = list(
                                video_segments[0].embedding
                            )  # Cast to list[float]
                        else:
                            raise EmbeddingServiceError(
                                "No video segments found in embeddings"
                            )
                    else:
                        raise EmbeddingServiceError(
                            "No video embeddings found in response"
                        )
                else:
                    raise EmbeddingServiceError(
                        f"Unsupported media format: {file_ext}. "
                        f"Supported: {image_formats + video_formats}"
                    )

                # Validate embedding
                if not embedding:
                    raise EmbeddingServiceError("Embedding is empty or None")

                if len(embedding) != self.multimodal_dimensions:
                    raise EmbeddingServiceError(
                        f"Expected {self.multimodal_dimensions} dimensions, got {len(embedding)}"
                    )

                logger.debug(
                    "Generated multimodal embedding",
                    media_file=media_file_path,
                    contextual_text_length=len(contextual_text),
                    embedding_dimensions=len(embedding),
                    model=self.multimodal_model,
                    file_type=file_ext,
                )

                return embedding

            except Exception as e:
                error_msg = str(e)
                is_retryable = is_retryable_genai_error(e)

                logger.error(
                    "Failed to generate multimodal embedding",
                    media_file=media_file_path,
                    contextual_text_length=len(contextual_text),
                    model=self.multimodal_model,
                    error=error_msg,
                    is_retryable=is_retryable,
                )

                if is_retryable:
                    # Let retry logic handle retryable errors (503, 502, 500, temporary rate limits)
                    raise e
                else:
                    # Wrap permanent failures (quota exhaustion, invalid input, etc.)
                    raise EmbeddingServiceError(
                        f"Multimodal embedding generation failed: {error_msg}"
                    ) from e

        return list(
            await retry_async(
                _generate_embedding, operation_name="generate_multimodal_embedding"
            )
        )


# Global service instance
_embedding_service: EmbeddingService | None = None


def get_embedding_service(project_id: str | None = None) -> EmbeddingService:
    """
    Get a global embedding service instance.

    Args:
        project_id: Google Cloud project ID

    Returns:
        EmbeddingService instance
    """
    global _embedding_service

    if _embedding_service is None:
        # Read configuration from config
        text_model = config.TEXT_EMBEDDING_MODEL
        multimodal_model = config.MULTIMODAL_EMBEDDING_MODEL
        text_dimensions = config.TEXT_EMBEDDING_DIMENSIONS
        multimodal_dimensions = config.MULTIMODAL_EMBEDDING_DIMENSIONS

        _embedding_service = EmbeddingService(
            text_model=text_model,
            multimodal_model=multimodal_model,
            text_dimensions=text_dimensions,
            multimodal_dimensions=multimodal_dimensions,
            project_id=project_id,
        )

    return _embedding_service
