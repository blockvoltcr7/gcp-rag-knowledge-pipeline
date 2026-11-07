"""
Main processing service for RAG processor.

Coordinates file processing, routing, and business logic
with proper error handling and logging.
"""

from datetime import datetime, timezone

import structlog

from ..config import config
from ..models.metadata_models import (
    ContentTypes,
    ProcessingJob,
    ProcessingStatus,
)
from ..utils.content_router import (
    get_content_router,
)
from ..utils.gcs_utils import (
    get_gcs_client,
    parse_gcs_path,
)
from ..utils.retry_utils import (
    JobCancelledError,
    NonRetryableError,
)
from .audio_processing_service import get_audio_processing_service
from .database_service import ChunkData, get_database_service
from .document_service_factory import get_document_service_factory
from .embedding_service import get_embedding_service
from .video_processing_service import get_video_processing_service

logger = structlog.get_logger(__name__)


class ProcessingService:
    """
    Main service for coordinating file processing operations.

    Handles business logic and orchestrates between different processing
    services while delegating all database operations to DatabaseService.
    """

    def __init__(self, project_id: str | None = None):
        """
        Initialize the processing service.

        Args:
            project_id: Google Cloud project ID
        """
        self.project_id = project_id or config.PROJECT_ID
        self.gcs_client = get_gcs_client(project_id)
        self.content_router = get_content_router()
        self.database_service = get_database_service(project_id)

        logger.info("Processing service initialized", project_id=project_id)

    async def _process_file_by_type(self, job: ProcessingJob) -> list[ChunkData]:
        """
        Process file based on its content type.

        Args:
            job: Processing job with file information

        Returns:
            List of processed chunks with embeddings
        """
        gcs_path = job.gcs_path

        # Determine content type using centralized router
        from ..utils.content_router import get_content_router

        content_router = get_content_router()
        content_type_str = content_router.detect_content_type(gcs_path)

        # Convert string to ContentTypes constant
        if content_type_str == "video":
            content_type = ContentTypes.VIDEO
        elif content_type_str == "audio":
            content_type = ContentTypes.AUDIO
        elif content_type_str == "image":
            content_type = ContentTypes.IMAGE
        else:
            content_type = ContentTypes.DOCUMENT

        logger.info(
            "Processing file by type",
            job_id=job.job_id,
            content_type=content_type,
        )

        local_file_path = None

        try:
            # Download file from GCS
            await self.database_service.update_processing_stage(
                job.job_id, "downloading"
            )
            bucket_name, file_path = parse_gcs_path(gcs_path)
            local_file_path = await self.gcs_client.download_file_to_temp(
                bucket_name, file_path
            )

            logger.info(
                "File downloaded successfully",
                job_id=job.job_id,
                local_path=str(local_file_path),
                file_size=local_file_path.stat().st_size,
            )

            # Process based on content type
            if content_type == ContentTypes.DOCUMENT:
                await self.database_service.update_processing_stage(
                    job.job_id, "processing_document"
                )
                chunks = await self._process_document(str(local_file_path), job)
            elif content_type == ContentTypes.VIDEO:
                await self.database_service.update_processing_stage(
                    job.job_id, "processing_video"
                )
                chunks = await self._process_video(str(local_file_path), job)
            elif content_type == ContentTypes.AUDIO:
                await self.database_service.update_processing_stage(
                    job.job_id, "processing_audio"
                )
                chunks = await self._process_audio(str(local_file_path), job)
            elif content_type == ContentTypes.IMAGE:
                await self.database_service.update_processing_stage(
                    job.job_id, "processing_image"
                )
                chunks = await self._process_image(str(local_file_path), job)
            else:
                raise NonRetryableError(f"Unsupported content type: {content_type}")

            logger.info(
                "File processing completed by type",
                job_id=job.job_id,
                content_type=content_type,
                chunk_count=len(chunks),
            )

            return chunks

        finally:
            # Note: Cleanup is now handled by individual processing services
            # to avoid race conditions with ongoing async operations
            pass

    async def _process_document(
        self, file_path: str, job: ProcessingJob
    ) -> list[ChunkData]:
        """Process document file and generate embeddings."""
        # Use factory to get appropriate document processor (LlamaIndex or Docling)
        factory = get_document_service_factory(self.project_id)
        document_service = factory.get_service()

        logger.info(
            "Processing document",
            job_id=job.job_id,
            processor=factory.processor_type.value,
            file_path=file_path,
        )

        document_id = job.custom_metadata.get("document_id")
        chunks = await document_service.process_document_file(
            document_path=file_path,
            user_id=job.user_id,
            document_id=document_id,
            contextual_text=f"Document file: {job.file_name}",
        )

        # Get embedding service for generating embeddings if not already present
        # (Docling generates embeddings internally, LlamaIndex does not)
        embedding_service = get_embedding_service(self.project_id)

        # Convert to ChunkData format and generate embeddings if missing
        processed_chunks = []
        for chunk in chunks:
            text_embedding = chunk.text_embedding

            # Generate text embedding if not already present
            if text_embedding is None and chunk.text.strip():
                logger.debug(
                    "Generating text embedding for chunk",
                    job_id=job.job_id,
                    chunk_index=getattr(chunk.metadata, "chunk_index", None),
                )
                text_embedding = await embedding_service.generate_text_embedding(
                    text=chunk.text
                )

            chunk_data = ChunkData(
                text=chunk.text,
                metadata=chunk.metadata,
                text_embedding=text_embedding,
                multimodal_embedding=chunk.multimodal_embedding,
            )
            processed_chunks.append(chunk_data)

        logger.info(
            "Document processing completed",
            job_id=job.job_id,
            chunk_count=len(processed_chunks),
            chunks_with_embeddings=sum(
                1 for c in processed_chunks if c.text_embedding is not None
            ),
        )

        return processed_chunks

    async def _process_video(
        self, file_path: str, job: ProcessingJob
    ) -> list[ChunkData]:
        """Process video file and generate embeddings."""
        video_service = get_video_processing_service(self.project_id)
        document_id = job.custom_metadata.get("document_id")
        chunks = await video_service.process_video_file(
            video_path=file_path,
            user_id=job.user_id,
            document_id=document_id,
            contextual_text=f"Video file: {job.file_name}",
            job_id=job.job_id,
        )

        # Convert to ChunkData format
        processed_chunks = []
        for chunk in chunks:
            chunk_data = ChunkData(
                text=chunk.text,
                metadata=chunk.metadata,
                context=chunk.context,
                text_embedding=chunk.text_embedding,
                multimodal_embedding=chunk.multimodal_embedding,
            )
            processed_chunks.append(chunk_data)

        return processed_chunks

    async def _process_audio(
        self, file_path: str, job: ProcessingJob
    ) -> list[ChunkData]:
        """Process audio file and generate embeddings."""
        audio_service = get_audio_processing_service(self.project_id)
        document_id = job.custom_metadata.get("document_id")
        chunks = await audio_service.process_audio_file(
            audio_path=file_path,
            user_id=job.user_id,
            document_id=document_id,
            contextual_text=f"Audio file: {job.file_name}",
            job_id=job.job_id,
        )

        # Convert to ChunkData format
        processed_chunks = []
        for chunk in chunks:
            chunk_data = ChunkData(
                text=chunk.text,
                metadata=chunk.metadata,
                context=chunk.context,
                text_embedding=chunk.text_embedding,
                multimodal_embedding=chunk.multimodal_embedding,
            )
            processed_chunks.append(chunk_data)

        return processed_chunks

    async def _process_image(
        self, file_path: str, job: ProcessingJob
    ) -> list[ChunkData]:
        """Process image file and generate embeddings with AI-powered analysis."""
        # Initialize basic content and context as fallback
        basic_content = f"Image file: {job.file_name}"
        content = basic_content
        context = None

        # Declare analysis metadata type once at the top
        analysis_metadata: dict[str, bool | str] = {}

        # Try to perform AI-powered dual image analysis
        try:
            await self.database_service.update_processing_stage(
                job.job_id, "analyzing_image"
            )

            # Import and use the dual image analysis service
            from ..services.image_processing_service import get_image_processing_service

            image_processing_service = get_image_processing_service(
                project_id=self.project_id
            )

            # Analyze the image to get comprehensive content, concept-focused context, and text embedding
            (
                content,
                context,
                text_embedding,
            ) = await image_processing_service.analyze_image(
                image_path=file_path, contextual_text=f"File: {job.file_name}"
            )

            # Set success metadata
            analysis_metadata = {
                "ai_analysis_performed": True,
                "fallback_used": False,
            }

            logger.info(
                "Dual image analysis with text embeddings completed successfully",
                job_id=job.job_id,
                filename=job.file_name,
                content_bytes=len(content.encode("utf-8")),
                context_bytes=len(context.encode("utf-8")) if context else 0,
                content_chars=len(content),
                context_chars=len(context) if context else 0,
                text_embedding_dimension=len(text_embedding) if text_embedding else 0,
            )

        except Exception as e:
            # Log the error and propagate as NonRetryableError to mark the job as error
            logger.error(
                "Image analysis failed",
                job_id=job.job_id,
                filename=job.file_name,
                error=str(e),
                error_type=type(e).__name__,
            )

            # Raise NonRetryableError so callers record failure without infinite retries
            raise NonRetryableError(
                f"Image analysis failed for {job.file_name}: {str(e)}"
            ) from e

        # Create chunk metadata with concept-focused contextual text
        from ..models.metadata_models import create_image_metadata

        # Use the context field for contextual text (optimized for embeddings)
        # Fall back to content if context is unavailable
        enhanced_contextual_text = context if context else content

        metadata = create_image_metadata(
            filename=job.file_name,
            media_path=job.gcs_path,
            contextual_text=enhanced_contextual_text,
        )

        # Log simple analysis metadata for monitoring
        if analysis_metadata:
            logger.info(
                "Image processing completed with analysis metadata",
                job_id=job.job_id,
                filename=job.file_name,
                analysis_performed=analysis_metadata.get(
                    "ai_analysis_performed", False
                ),
                fallback_used=analysis_metadata.get("fallback_used", False),
            )

        # Generate multimodal embedding using the concept-focused context for optimal embedding quality
        embedding_service = get_embedding_service(self.project_id)
        embedding_text = (
            context if context else content
        )  # Fallback to content if context unavailable
        multimodal_embedding = await embedding_service.generate_multimodal_embedding(
            media_file_path=file_path,
            contextual_text=embedding_text,
        )

        logger.debug(
            "Generated multimodal embedding",
            job_id=job.job_id,
            embedding_text_source="context" if context else "content",
            embedding_text_bytes=len(embedding_text.encode("utf-8")),
            embedding_text_chars=len(embedding_text),
        )

        # Create a single chunk with both text and multimodal embeddings
        chunk_data = ChunkData(
            text=content,  # Full content for the chunk
            metadata=metadata,
            context=context,  # Concept-focused analysis for multimodal embedding
            text_embedding=text_embedding,  # ✅ Single text embedding
            multimodal_embedding=multimodal_embedding,  # Keep existing multimodal embedding
        )

        logger.debug(
            "Created image chunk with both embedding types",
            job_id=job.job_id,
            text_embedding_dimension=len(text_embedding) if text_embedding else 0,
            multimodal_embedding_dimension=len(multimodal_embedding),
        )

        logger.info(
            "Image processing completed with dual embeddings",
            job_id=job.job_id,
            has_text_embedding=text_embedding is not None,
            has_multimodal_embedding=True,
        )

        return [chunk_data]

    async def get_processing_status(self, job_id: str) -> ProcessingJob | None:
        """
        Get the status of a processing job.

        Args:
            job_id: ID of the processing job

        Returns:
            ProcessingJob if found, None otherwise
        """
        return await self.database_service.get_processing_job(job_id)

    async def list_processing_jobs(
        self,
        user_id: str,
        status_filter: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ProcessingJob]:
        """
        List processing jobs for a user.

        Args:
            user_id: User ID to filter by
            status_filter: Optional status filter
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            List of ProcessingJob objects
        """
        return await self.database_service.list_processing_jobs(
            user_id, status_filter, limit, offset
        )


# Global service instance
_processing_service: ProcessingService | None = None


def get_processing_service(project_id: str | None = None) -> ProcessingService:
    """
    Get a global processing service instance.

    Args:
        project_id: Google Cloud project ID

    Returns:
        ProcessingService instance
    """
    global _processing_service

    if _processing_service is None:
        _processing_service = ProcessingService(project_id=project_id)

    return _processing_service


async def process_file_from_gcs(
    job_id: str,
    gcs_path: str,
    user_id: str,
    organization_id: str | None = None,
    custom_metadata: dict | None = None,
    project_id: str | None = None,
) -> ProcessingJob:
    """
    Process a file from GCS using an existing processing job.

    This function processes files through the queue handler workflow where
    jobs are created by the queue handler and updated by the rag-processor.

    Args:
        job_id: ID of existing processing job from queue handler
        gcs_path: GCS path to the file
        user_id: User ID who owns the file
        organization_id: Optional organization ID
        custom_metadata: Optional custom metadata
        project_id: Google Cloud project ID

    Returns:
        Updated ProcessingJob instance

    Raises:
        ValueError: If job_id doesn't exist or belongs to different user
    """
    logger.info(
        "Processing file from GCS using existing job",
        job_id=job_id,
        gcs_path=gcs_path,
        user_id=user_id,
        organization_id=organization_id,
    )

    # Get processing service and database service
    processing_service = get_processing_service(project_id)
    database_service = processing_service.database_service

    # Find existing job instead of creating new one
    existing_job = await database_service.get_processing_job(job_id)

    if not existing_job:
        error_msg = f"Processing job not found: {job_id}"
        logger.error(error_msg, job_id=job_id, gcs_path=gcs_path)
        raise ValueError(error_msg)

    # Security: Verify job belongs to correct user
    if existing_job.user_id != user_id:
        error_msg = f"Job {job_id} belongs to different user"
        logger.error(
            error_msg,
            job_id=job_id,
            job_user=existing_job.user_id,
            request_user=user_id,
        )
        raise ValueError(error_msg)

    logger.info(
        "Found existing job for processing",
        job_id=job_id,
        current_status=existing_job.status.value,
        document_id=existing_job.custom_metadata.get("document_id"),
    )

    try:
        # Update job status to processing
        existing_job.status = ProcessingStatus.PROCESSING
        existing_job.started_at = datetime.now(timezone.utc)
        await database_service.update_processing_job(existing_job)

        logger.info(
            "Updated existing job status to processing",
            job_id=job_id,
            status=existing_job.status.value,
        )

        # Update processing stage
        await database_service.update_processing_stage(
            existing_job.job_id, "downloading"
        )

        # Process the file based on content type using existing logic
        chunks = await processing_service._process_file_by_type(existing_job)

        # Update processing stage
        await database_service.update_processing_stage(existing_job.job_id, "storing")

        # Store chunks and embeddings
        document_id = existing_job.custom_metadata.get("document_id")
        program_id = existing_job.custom_metadata.get("program_id")
        await database_service.store_chunks(chunks, user_id, document_id, program_id)

        # Update document chunk count
        if document_id:
            await database_service.update_document_chunk_count(document_id, len(chunks))

        # Mark job as completed
        existing_job.status = ProcessingStatus.PROCESSED
        existing_job.completed_at = datetime.now(timezone.utc)
        await database_service.update_processing_job(existing_job)

        logger.info(
            "Existing job processing completed successfully",
            job_id=existing_job.job_id,
            gcs_path=gcs_path,
            chunk_count=len(chunks),
        )

        return existing_job

    except JobCancelledError as e:
        # Job was cancelled/deleted - clean up gracefully without updating job status
        logger.info(
            "Processing job was cancelled or deleted - terminating processing gracefully",
            job_id=existing_job.job_id,
            gcs_path=gcs_path,
            error=str(e),
        )
        # Don't try to update the job status since the job no longer exists
        # Just re-raise the exception to signal cancellation to caller
        raise
    except Exception as e:
        # Update existing job with error status
        logger.error(
            "Error processing existing job",
            job_id=existing_job.job_id,
            error=str(e),
        )
        existing_job.status = ProcessingStatus.ERROR
        existing_job.error_message = str(e)
        existing_job.completed_at = datetime.now(timezone.utc)
        await database_service.update_processing_job(existing_job)

        raise  # Re-raise to maintain error propagation
