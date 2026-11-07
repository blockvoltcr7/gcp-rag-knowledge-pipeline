"""
Processing Service Changes for LlamaIndex Integration.

This file shows the modifications needed to processing_service.py
to integrate the LlamaIndex document service.

INSTRUCTIONS:
1. Replace the _process_document method in processing_service.py
2. Update imports at the top of the file
3. Add the document service factory initialization
"""

# =============================================================================
# ADD THESE IMPORTS at the top of processing_service.py
# =============================================================================

# Add this import
from .document_service_factory import get_document_service_factory, DocumentProcessor


# =============================================================================
# REPLACE the __init__ method to include factory initialization
# =============================================================================

class ProcessingService:
    """
    Main service for coordinating file processing operations.
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

        # NEW: Initialize document service factory for processor selection
        self.document_service_factory = get_document_service_factory(project_id)

        logger.info(
            "Processing service initialized",
            project_id=project_id,
            document_processor=self.document_service_factory.processor_type.value,
        )


# =============================================================================
# REPLACE the _process_document method with this implementation
# =============================================================================

    async def _process_document(
        self, file_path: str, job: ProcessingJob
    ) -> list[ChunkData]:
        """
        Process document file and generate embeddings.

        Uses the configured document processor (LlamaIndex or Docling)
        based on environment configuration.
        """
        document_id = job.custom_metadata.get("document_id")

        # Get the configured document service
        document_service = self.document_service_factory.get_service()

        logger.info(
            "Processing document",
            job_id=job.job_id,
            processor=self.document_service_factory.processor_type.value,
            document_path=file_path,
        )

        try:
            # Process document using selected service
            if self.document_service_factory.is_llamaindex():
                # LlamaIndex path
                chunks = await document_service.process_document_file(
                    document_path=file_path,
                    user_id=job.user_id,
                    document_id=document_id,
                    contextual_text=f"Document file: {job.file_name}",
                )

                # Generate embeddings for LlamaIndex chunks
                # (LlamaIndex service returns chunks without embeddings by default)
                embedding_service = get_embedding_service(self.project_id)

                processed_chunks = []
                for chunk in chunks:
                    # Generate text embedding
                    text_embedding = await embedding_service.generate_text_embedding(
                        chunk.text
                    )

                    chunk_data = ChunkData(
                        text=chunk.text,
                        metadata=chunk.metadata,
                        text_embedding=text_embedding,
                        multimodal_embedding=None,  # Documents don't need multimodal
                    )
                    processed_chunks.append(chunk_data)

                logger.info(
                    "LlamaIndex document processing completed",
                    job_id=job.job_id,
                    chunk_count=len(processed_chunks),
                )

                return processed_chunks

            else:
                # Docling path (existing implementation)
                chunks = await document_service.process_document_file(
                    document_path=file_path,
                    user_id=job.user_id,
                    document_id=document_id,
                    contextual_text=f"Document file: {job.file_name}",
                )

                # Convert to ChunkData format (existing code)
                processed_chunks = []
                for chunk in chunks:
                    chunk_data = ChunkData(
                        text=chunk.text,
                        metadata=chunk.metadata,
                        text_embedding=chunk.text_embedding,
                        multimodal_embedding=chunk.multimodal_embedding,
                    )
                    processed_chunks.append(chunk_data)

                logger.info(
                    "Docling document processing completed",
                    job_id=job.job_id,
                    chunk_count=len(processed_chunks),
                )

                return processed_chunks

        except Exception as e:
            logger.error(
                "Document processing failed",
                job_id=job.job_id,
                processor=self.document_service_factory.processor_type.value,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise


# =============================================================================
# OPTIONAL: Add fallback logic for automatic processor switching
# =============================================================================

    async def _process_document_with_fallback(
        self, file_path: str, job: ProcessingJob
    ) -> list[ChunkData]:
        """
        Process document with automatic fallback to secondary processor.

        Tries the primary processor first, falls back to secondary on failure.
        """
        document_id = job.custom_metadata.get("document_id")
        primary_processor = self.document_service_factory.processor_type

        try:
            # Try primary processor
            return await self._process_document(file_path, job)

        except Exception as primary_error:
            logger.warning(
                "Primary processor failed, attempting fallback",
                job_id=job.job_id,
                primary_processor=primary_processor.value,
                error=str(primary_error),
            )

            # Determine fallback processor
            if primary_processor == DocumentProcessor.LLAMAINDEX:
                # Fallback to Docling
                from .document_processing_service import get_document_processing_service

                fallback_service = get_document_processing_service(self.project_id)
                fallback_name = "docling"
            else:
                # Fallback to LlamaIndex
                from .llamaindex_document_service import get_llamaindex_document_service

                fallback_service = get_llamaindex_document_service(self.project_id)
                fallback_name = "llamaindex"

            try:
                logger.info(
                    "Attempting fallback processor",
                    job_id=job.job_id,
                    fallback_processor=fallback_name,
                )

                chunks = await fallback_service.process_document_file(
                    document_path=file_path,
                    user_id=job.user_id,
                    document_id=document_id,
                    contextual_text=f"Document file: {job.file_name}",
                )

                # Generate embeddings if needed
                embedding_service = get_embedding_service(self.project_id)

                processed_chunks = []
                for chunk in chunks:
                    text_embedding = chunk.text_embedding
                    if text_embedding is None:
                        text_embedding = await embedding_service.generate_text_embedding(
                            chunk.text
                        )

                    chunk_data = ChunkData(
                        text=chunk.text,
                        metadata=chunk.metadata,
                        text_embedding=text_embedding,
                        multimodal_embedding=getattr(chunk, 'multimodal_embedding', None),
                    )
                    processed_chunks.append(chunk_data)

                logger.info(
                    "Fallback processor succeeded",
                    job_id=job.job_id,
                    fallback_processor=fallback_name,
                    chunk_count=len(processed_chunks),
                )

                return processed_chunks

            except Exception as fallback_error:
                logger.error(
                    "Fallback processor also failed",
                    job_id=job.job_id,
                    primary_processor=primary_processor.value,
                    primary_error=str(primary_error),
                    fallback_processor=fallback_name,
                    fallback_error=str(fallback_error),
                )
                # Re-raise original error
                raise primary_error from fallback_error
