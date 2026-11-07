"""
Image processing service for RAG processor.

Handles image analysis and description generation using Google GenAI.
"""

import asyncio
from typing import Any

import google.genai as genai
import structlog

from ..config import config
from ..models.image_analysis_models import ImageAnalysisError
from ..services.genai_utils import create_file_manager
from ..utils.retry_utils import NonRetryableError
from ..utils.token_utils import (
    create_google_tokenizer,
    truncate_text_to_tokens,
)

logger = structlog.get_logger(__name__)


class ImageProcessingService:
    """Service for processing images using Google GenAI with multimodal capabilities."""

    def __init__(
        self,
        project_id: str | None = None,
        location: str | None = None,
        model_name: str = "gemini-2.5-flash",
        timeout_seconds: int = 30,
    ):
        """
        Initialize the image analysis service.

        Args:
            project_id: Google Cloud project ID. If None, will use GOOGLE_CLOUD_PROJECT_ID env var.
            location: Google Cloud location for Vertex AI.
            model_name: The Gemini model to use for analysis.
            timeout_seconds: Timeout for API requests.
        """
        self.project_id = project_id or config.PROJECT_ID
        if not self.project_id:
            raise NonRetryableError("Google Cloud project ID is required")

        self.location = location or config.VERTEX_AI_LOCATION
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds

        # Initialize GenAI client for image analysis using API key
        self.genai_client = genai.Client(
            vertexai=False,
            api_key=config.GEMINI_API_KEY,
        )

        # Initialize file manager for GenAI file operations
        self.file_manager = create_file_manager(self.genai_client)

        logger.info(
            "ImageProcessingService initialized",
            project_id=self.project_id,
            location=self.location,
            model=model_name,
            timeout_seconds=timeout_seconds,
        )

    async def analyze_image(
        self, image_path: str, contextual_text: str | None = None
    ) -> tuple[str, str, list[float]]:
        """
        Analyze an image with dual API calls for comprehensive and concept-focused analysis,
        plus text embedding generation for the comprehensive content.

        Args:
            image_path: Path to the image file
            contextual_text: Optional context about the image

        Returns:
            tuple[str, str, list[float]]: (comprehensive_content, concept_context, single_text_embedding)
        """
        try:
            logger.info(
                "Starting dual image analysis (comprehensive + concept-focused)",
                image_path=image_path,
            )

            # Determine mime type based on file extension
            mime_type = self._get_image_mime_type(image_path)

            # Upload image and wait for it to be ready using the file manager with retry logic
            genai_file = await self.file_manager.upload_and_wait_with_retry(
                image_path, mime_type=mime_type
            )

            try:
                # Execute both API calls in parallel for optimal performance - all or nothing
                logger.debug(
                    "Making parallel API calls for comprehensive and concept-focused analysis"
                )

                # Create tasks for both API calls
                comprehensive_task = self._analyze_comprehensive(
                    genai_file, contextual_text
                )
                context_task = self._analyze_image_for_context(
                    genai_file, contextual_text
                )

                # Execute both calls in parallel - if either fails, both fail (all or nothing)
                content, context = await asyncio.gather(
                    comprehensive_task, context_task
                )

                logger.info(
                    "Parallel dual image analysis completed successfully",
                    image_path=image_path,
                    content_bytes=len(content.encode("utf-8")),
                    context_bytes=len(context.encode("utf-8")),
                    content_chars=len(content),
                    context_chars=len(context),
                )

                # Generate text embeddings for the comprehensive content
                text_embedding = await self.generate_text_embedding_for_content(content)

                logger.info(
                    "Image analysis with text embeddings completed",
                    image_path=image_path,
                    embedding_dimension=len(text_embedding),
                )

                return content, context, text_embedding

            finally:
                # Always clean up the uploaded file using file manager
                await self.file_manager.cleanup_file(genai_file)

        except Exception as e:
            error_msg = str(e)
            is_rate_limit = self._is_rate_limit_error(e)

            logger.error(
                "Image analysis failed",
                image_path=image_path,
                error=error_msg,
                error_type=type(e).__name__,
                is_rate_limit=is_rate_limit,
            )

            if is_rate_limit:
                raise ImageAnalysisError(
                    f"Image analysis failed due to API rate limiting: {error_msg}. "
                    "This indicates API quota exhaustion - check your Gemini API usage limits."
                ) from e
            else:
                raise ImageAnalysisError(f"Analysis failed: {error_msg}") from e

    def _get_image_mime_type(self, image_path: str) -> str:
        """
        Determine the MIME type of an image using centralized router.

        Args:
            image_path: Path to the image file

        Returns:
            MIME type string for the image
        """
        from ..utils.content_router import get_content_router

        content_router = get_content_router()
        mime_type = content_router.get_mime_type_for_extension(image_path)

        # Default to JPEG if not found
        return mime_type or "image/jpeg"

    def _create_comprehensive_image_analysis_prompt(
        self, contextual_text: str | None = None
    ) -> str:
        """
        Create a comprehensive prompt for detailed image analysis.

        Args:
            contextual_text: Optional context about the image

        Returns:
            Formatted prompt for comprehensive image analysis
        """
        context_section = ""
        if contextual_text:
            context_section = f"""
            **PROVIDED CONTEXT:**
            {contextual_text}
            """

        return f"""Analyze this image comprehensively and provide detailed context for image search and understanding. Examine every visual element carefully and describe what you see with specific, searchable information.

            {context_section}

            **COMPREHENSIVE ANALYSIS REQUIRED:**

            1. **VISUAL CONTENT INVENTORY:**
            - All text visible in the image (signs, labels, captions, documents, handwriting, printed text)
            - People (number, age groups, clothing, activities, expressions, poses)
            - Objects and items (furniture, tools, devices, vehicles, food, animals, plants)
            - Settings and environments (indoor/outdoor, rooms, landscapes, buildings, weather)
            - Colors, lighting, and visual style (dominant colors, lighting conditions, artistic style, mood)

            2. **TEXT AND READABLE CONTENT:**
            - Exact transcription of any readable text (even partial or blurry text)
            - Signs, posters, book titles, screen content, labels, or captions
            - Brand names, logos, or identifying marks visible
            - Numbers, dates, prices, or measurements shown
            - Languages used (if text is in non-English languages, note the language)

            3. **SCENE AND CONTEXT:**
            - Type of image (photograph, screenshot, artwork, diagram, document, etc.)
            - Setting or location (home, office, outdoors, restaurant, store, etc.)
            - Time indicators (day/night, season, era/time period if apparent)
            - Activities or events taking place
            - Mood, atmosphere, or emotional tone of the image

            4. **SPECIFIC DETAILS:**
            - Notable features, unique elements, or distinguishing characteristics
            - Spatial relationships and composition (what's in foreground/background)
            - Quality and style (professional photo, casual snapshot, artistic, technical diagram)
            - Any specialized content (medical, scientific, educational, entertainment, etc.)
            - Cultural or regional elements visible

            5. **SEARCHABLE ELEMENTS:**
            - Key concepts someone might search for to find this image
            - Specific names, places, events, or topics depicted
            - Categories this image would fit into (family photo, recipe, tutorial, meme, etc.)
            - Descriptive keywords that capture the essence and details

            **OUTPUT FORMAT:**
            Main Description: [Clear, comprehensive description of what the image shows]
            Text Content: [Exact transcription of any visible text, or "No readable text" if none]
            Setting and Context: [Where/when this appears to be taken and what's happening]
            Notable Details: [Specific, unique, or important elements that stand out]
            Search Keywords: [Terms and phrases that would help someone find this image]

            **OUTPUT REQUIREMENTS:**
            Be thorough and comprehensive while focusing on what's actually visible. Include exact text transcriptions,
            specific details about people/objects/settings, and descriptive keywords. This analysis will be used for
            precise image search and retrieval in a knowledge base system through text-based embeddings.

            Prioritize searchable content: specific text content, technical details, unique identifiers, and distinctive
            features that would help someone find this image through text queries. The more detailed and specific you are,
            the better the search results will be.
        """

    def _create_concept_focused_prompt(self, contextual_text: str | None = None) -> str:
        """
        Create a concept-focused prompt for key concepts and distinctive features.
        Optimized for embedding generation with concise, searchable information.

        Args:
            contextual_text: Optional context about the image

        Returns:
            Formatted prompt for concept-focused analysis
        """
        context_section = ""
        if contextual_text:
            context_section = f"""
            **PROVIDED CONTEXT:**
            {contextual_text}
            """

        return f"""Analyze this image and extract the key concepts and distinctive features that make it unique and searchable. Focus on what makes this image stand out and how someone would search for it.

            {context_section}

            **FOCUS ON KEY CONCEPTS:**

            1. **PRIMARY VISUAL ELEMENTS:**
            - Main subjects, objects, and people (be specific)
            - Key text or readable content (exact transcription)
            - Dominant colors, lighting, and visual style

            2. **DISTINCTIVE FEATURES:**
            - What makes this image unique or memorable
            - Specific brands, logos, or identifying marks
            - Notable technical details or specialized content

            3. **SEARCHABLE CATEGORIES:**
            - Type of image (photo, screenshot, diagram, artwork, etc.)
            - Setting or environment (indoor, outdoor, specific location type)
            - Purpose or context (educational, entertainment, business, personal, etc.)

            4. **KEY SEARCH TERMS:**
            - Specific objects, tools, devices, or items
            - People characteristics (age, clothing, activities)
            - Location indicators and environmental details
            - Any text, numbers, dates, or measurements visible

            **CRITICAL OUTPUT FORMAT:**
            Key Concepts: [Main visual elements, objects, people - be specific]
            Distinctive Features: [What makes this image unique/searchable]
            Categories: [Type classification and setting]
            Search Terms: [Essential keywords for finding this image]

            **CRITICAL OUTPUT CONSTRAINT:**
            Your entire response must be 1023 characters or fewer. Be extremely concise while capturing the most distinctive and searchable elements. Prioritize unique identifiers, specific text content, and key visual concepts that would be used in search queries.

            Focus on what makes this image different from others - the distinctive features that would help someone find this specific image in a large database.
        """

    async def _analyze_comprehensive(
        self, genai_file: Any, contextual_text: str | None = None
    ) -> str:
        """
        Analyze image for comprehensive content using the uploaded GenAI file.

        Args:
            genai_file: Already uploaded GenAI file object
            contextual_text: Optional context about the image

        Returns:
            Comprehensive content text (will be token-chunked for text embeddings)
        """
        try:
            # Create comprehensive prompt
            prompt = self._create_comprehensive_image_analysis_prompt(contextual_text)

            # Get comprehensive analysis from GenAI
            response = await self.genai_client.aio.models.generate_content(
                model=self.model_name,
                contents=[prompt, genai_file],  # type: ignore[arg-type]
            )

            content = (response.text or "").strip()

            logger.info(
                "Comprehensive analysis completed",
                content_length=len(content),
                content_bytes=len(content.encode("utf-8")),
            )

            return content

        except Exception as e:
            logger.error(
                "Comprehensive analysis failed",
                error=str(e),
                error_type=type(e).__name__,
            )
            # Re-raise as the calling method will handle the overall error
            raise

    async def _analyze_image_for_context(
        self, genai_file: Any, contextual_text: str | None = None
    ) -> str:
        """
        Analyze image for concept-focused context using the uploaded GenAI file.

        Args:
            genai_file: Already uploaded GenAI file object
            contextual_text: Optional context about the image

        Returns:
            Concept-focused context text (max 32 tokens for embedding compatibility)
        """
        try:
            # Create concept-focused prompt
            prompt = self._create_concept_focused_prompt(contextual_text)

            # Get concept analysis from GenAI with token limit
            response = await self.genai_client.aio.models.generate_content(
                model=self.model_name,
                contents=[prompt, genai_file],  # type: ignore[arg-type]
                config={"max_output_tokens": 32},  # Limit for embedding compatibility
            )

            context = (response.text or "").strip()

            logger.debug(
                "Generated concept-focused context",
                context_length=len(context),
                context_bytes=len(context.encode("utf-8")),
            )

            return context

        except Exception as e:
            logger.error(
                "Context analysis failed",
                error=str(e),
                error_type=type(e).__name__,
            )
            # Re-raise as the calling method will handle the overall error
            raise

    async def generate_text_embedding_for_content(
        self, content: str, project_id: str | None = None
    ) -> list[float]:
        """
        Generate text embedding for content using token-aware truncation.

        Args:
            content: Comprehensive content text from image analysis
            project_id: Google Cloud project ID

        Returns:
            Single text embedding vector

        Raises:
            ImageAnalysisError: If text embedding generation fails
        """
        try:
            if not content.strip():
                logger.warning("Empty content provided for text embedding generation")
                return []

            # Import and get embedding service
            from .embedding_service import get_embedding_service

            embedding_service = get_embedding_service(project_id or self.project_id)

            # Create tokenizer for truncation
            tokenizer = create_google_tokenizer(embedding_service.genai_client)

            # Truncate content to fit within token limit (2047 tokens for gemini-embedding-001)
            truncated_content = truncate_text_to_tokens(
                text=content,
                tokenizer=tokenizer,
                max_tokens=2047,  # Leave 1 token buffer for safety
            )

            logger.info(
                "Content truncated for text embedding",
                original_length=len(content),
                truncated_length=len(truncated_content),
                original_tokens=tokenizer.count_tokens(content),
                truncated_tokens=tokenizer.count_tokens(truncated_content),
            )

            # Generate text embedding for the truncated content
            text_embedding = await embedding_service.generate_text_embedding(
                truncated_content
            )

            logger.info(
                "Text embedding generated successfully",
                embedding_dimension=len(text_embedding),
                content_length=len(truncated_content),
            )

            return text_embedding

        except Exception as e:
            error_msg = str(e)
            is_rate_limit = self._is_rate_limit_error(e)

            logger.error(
                "Text embedding generation failed",
                content_length=len(content),
                error=error_msg,
                error_type=type(e).__name__,
                is_rate_limit=is_rate_limit,
            )

            if is_rate_limit:
                raise ImageAnalysisError(
                    f"Text embedding generation failed due to API rate limiting: {error_msg}. "
                    "This indicates API quota exhaustion - check your Google AI API usage limits."
                ) from e
            else:
                raise ImageAnalysisError(
                    f"Text embedding generation failed: {error_msg}"
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


# Global service instance
_image_processing_service: ImageProcessingService | None = None


def get_image_processing_service(
    project_id: str | None = None,
    location: str | None = None,
    model_name: str = "gemini-2.5-flash",
    timeout_seconds: int = 30,
) -> ImageProcessingService:
    """Get the global image processing service instance."""
    global _image_processing_service
    if _image_processing_service is None:
        _image_processing_service = ImageProcessingService(
            project_id=project_id,
            location=location,
            model_name=model_name,
            timeout_seconds=timeout_seconds,
        )
    return _image_processing_service
