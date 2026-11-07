"""
LlamaIndex Document Processing Service.

Replaces Docling for document processing (DOCX, MD, PDF) using LlamaIndex
readers and node parsers for improved reliability and performance.
"""

import os
import re
from pathlib import Path
from typing import Any

import structlog

from ..config import config
from ..models.metadata_models import (
    ChunkMetadata,
    create_document_metadata,
)
from ..utils.retry_utils import NonRetryableError, retry_async

logger = structlog.get_logger(__name__)


class LlamaIndexDocumentServiceError(NonRetryableError):
    """Exception for LlamaIndex document service errors."""

    pass


class ProcessedChunk:
    """
    Data structure for a processed document chunk.

    Compatible with existing ChunkData structure used by database service.
    """

    def __init__(
        self,
        text: str,
        metadata: ChunkMetadata,
        text_embedding: list[float] | None = None,
        multimodal_embedding: list[float] | None = None,
    ):
        self.text = text
        self.metadata = metadata
        self.text_embedding = text_embedding
        self.multimodal_embedding = multimodal_embedding


def normalize_text(text: str) -> str:
    """
    Normalize text by fixing common PDF/DOCX extraction issues.

    This fixes the problem where PDF/DOCX readers extract text with
    line breaks at word-wrap boundaries, resulting in word-per-line output.

    Args:
        text: Raw text from document extraction

    Returns:
        Normalized text with proper paragraph structure
    """
    if not text:
        return text

    # Step 0: Normalize tabs to spaces
    text = text.replace("\t", " ")

    # Step 1: Normalize line endings to \n
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Step 2: Preserve intentional paragraph breaks (2+ newlines)
    # Replace them with a placeholder
    paragraph_placeholder = "<<<PARAGRAPH_BREAK>>>"
    text = re.sub(r"\n{2,}", paragraph_placeholder, text)

    # Step 3: Preserve bullet points and list items
    # Common patterns: lines starting with •, -, *, numbers, or letters
    # Mark these so we don't merge them
    list_placeholder = "<<<LIST_ITEM>>>"
    # Match newline followed by list marker
    text = re.sub(
        r"\n([•●○◦\-\*]|\d+[\.\)]|[a-zA-Z][\.\)])\s*",
        f"{list_placeholder}\\1 ",
        text,
    )

    # Step 4: Replace single newlines with spaces (these are soft wraps)
    text = re.sub(r"\n", " ", text)

    # Step 5: Restore paragraph breaks
    text = text.replace(paragraph_placeholder, "\n\n")

    # Step 6: Restore list items with proper newlines
    text = text.replace(list_placeholder, "\n")

    # Step 7: Collapse multiple spaces into single space
    text = re.sub(r" +", " ", text)

    # Step 8: Clean up spaces around paragraph breaks
    text = re.sub(r" *\n\n *", "\n\n", text)

    # Step 9: Strip leading/trailing whitespace from each line
    lines = text.split("\n")
    lines = [line.strip() for line in lines]
    text = "\n".join(lines)

    # Step 10: Final cleanup - remove empty lines at start/end
    text = text.strip()

    return text


class LlamaIndexDocumentService:
    """
    Document processing service using LlamaIndex.

    Handles DOCX, MD, PDF, TXT, and HTML files with appropriate readers
    and chunking strategies.
    """

    # Supported file extensions and their reader mappings
    SUPPORTED_EXTENSIONS = {
        ".pdf": "pdf",
        ".docx": "docx",
        ".doc": "docx",
        ".md": "markdown",
        ".markdown": "markdown",
        ".txt": "text",
        ".html": "html",
        ".htm": "html",
    }

    def __init__(
        self,
        project_id: str | None = None,
        use_llamaparse: bool = False,
        llamaparse_api_key: str | None = None,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ):
        """
        Initialize the LlamaIndex document service.

        Args:
            project_id: Google Cloud project ID
            use_llamaparse: Whether to use LlamaParse for PDFs (requires API key)
            llamaparse_api_key: LlamaParse API key
            chunk_size: Size of text chunks (default: 1000)
            chunk_overlap: Overlap between chunks (default: 200)
        """
        self.project_id = project_id or config.PROJECT_ID
        self.use_llamaparse = use_llamaparse
        self.llamaparse_api_key = llamaparse_api_key or os.getenv("LLAMAPARSE_API_KEY")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        # Lazy-loaded components
        self._file_extractor: dict[str, Any] | None = None
        self._node_parser: Any = None
        self._initialized = False

        logger.info(
            "LlamaIndex document service created",
            project_id=project_id,
            use_llamaparse=use_llamaparse,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    def _initialize(self) -> None:
        """
        Lazy initialization of LlamaIndex components.

        Called on first use to avoid import overhead at startup.
        """
        if self._initialized:
            return

        try:
            # Import LlamaIndex components (no type stubs available)
            from llama_index.core.node_parser import SentenceSplitter
            from llama_index.readers.file import (  # type: ignore[import-untyped]
                DocxReader,
                HTMLTagReader,
                MarkdownReader,
                PDFReader,
            )

            # Initialize node parser for chunking
            self._node_parser = SentenceSplitter(
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
            )

            # Build file extractor mapping
            self._file_extractor = {
                ".docx": DocxReader(),
                ".doc": DocxReader(),
                ".md": MarkdownReader(),
                ".markdown": MarkdownReader(),
                ".html": HTMLTagReader(),
                ".htm": HTMLTagReader(),
                ".txt": None,  # SimpleDirectoryReader handles txt natively
            }

            # Configure PDF reader
            if self.use_llamaparse and self.llamaparse_api_key:
                try:
                    from llama_parse import LlamaParse  # type: ignore[import-untyped]

                    self._file_extractor[".pdf"] = LlamaParse(
                        api_key=self.llamaparse_api_key,
                        result_type="markdown",
                        verbose=False,
                    )
                    logger.info("LlamaParse initialized for PDF processing")
                except ImportError:
                    logger.warning(
                        "llama-parse not installed, falling back to PDFReader"
                    )
                    self._file_extractor[".pdf"] = PDFReader()
            else:
                self._file_extractor[".pdf"] = PDFReader()
                logger.info("PDFReader initialized for PDF processing")

            self._initialized = True
            logger.info("LlamaIndex document service initialized")

        except ImportError as e:
            raise LlamaIndexDocumentServiceError(
                f"Failed to import LlamaIndex components. "
                f"Install with: pip install llama-index-core llama-index-readers-file. "
                f"Error: {e}"
            ) from e

    def _get_reader_for_extension(self, extension: str) -> Any:
        """
        Get the appropriate reader for a file extension.

        Args:
            extension: File extension (e.g., ".pdf")

        Returns:
            Reader instance or None for native handling
        """
        self._initialize()
        if self._file_extractor is None:
            return None
        return self._file_extractor.get(extension.lower())

    def is_supported(self, file_path: str) -> bool:
        """
        Check if a file type is supported.

        Args:
            file_path: Path to the file

        Returns:
            True if supported, False otherwise
        """
        extension = Path(file_path).suffix.lower()
        return extension in self.SUPPORTED_EXTENSIONS

    async def process_document_file(
        self,
        document_path: str,
        user_id: str,
        document_id: str | None = None,
        contextual_text: str = "",
    ) -> list[ProcessedChunk]:
        """
        Process a document file and return chunks with metadata.

        Args:
            document_path: Path to the document file
            user_id: User ID who owns the document
            document_id: Optional document ID for association
            contextual_text: Optional context for embeddings

        Returns:
            List of ProcessedChunk objects ready for embedding

        Raises:
            LlamaIndexDocumentServiceError: If processing fails
        """
        file_path = Path(document_path)
        extension = file_path.suffix.lower()

        if not self.is_supported(document_path):
            raise LlamaIndexDocumentServiceError(
                f"Unsupported file type: {extension}. "
                f"Supported: {list(self.SUPPORTED_EXTENSIONS.keys())}"
            )

        logger.info(
            "Processing document with LlamaIndex",
            document_path=document_path,
            extension=extension,
            user_id=user_id,
            document_id=document_id,
        )

        async def _process() -> list[ProcessedChunk]:
            self._initialize()

            try:
                # Import SimpleDirectoryReader for loading
                from llama_index.core import SimpleDirectoryReader

                # Get appropriate reader
                reader = self._get_reader_for_extension(extension)

                # Build file extractor dict for this specific file
                file_extractor = {}
                if reader is not None:
                    file_extractor[extension] = reader

                # Load document(s)
                dir_reader = SimpleDirectoryReader(
                    input_files=[str(file_path)],
                    file_extractor=file_extractor if file_extractor else None,
                )

                # Use async loading
                documents = await dir_reader.aload_data()

                if not documents:
                    raise LlamaIndexDocumentServiceError(
                        f"No content extracted from document: {document_path}"
                    )

                # Calculate stats before normalization
                raw_total_chars = sum(len(doc.text) for doc in documents)

                logger.info(
                    "Documents loaded (before normalization)",
                    document_count=len(documents),
                    total_chars=raw_total_chars,
                )

                # Normalize text to fix PDF/DOCX extraction issues
                # (word-per-line, excessive newlines, etc.)
                # Note: LlamaIndex Document objects are immutable, so we create new ones
                from llama_index.core import Document as LlamaDocument

                normalized_documents = []
                for doc in documents:
                    original_len = len(doc.text)
                    normalized_text = normalize_text(doc.text)
                    normalized_len = len(normalized_text)

                    # Create new Document with normalized text, preserving metadata
                    normalized_doc = LlamaDocument(
                        text=normalized_text,
                        metadata=doc.metadata,
                        id_=doc.id_,
                    )
                    normalized_documents.append(normalized_doc)

                    if original_len != normalized_len:
                        logger.debug(
                            "Text normalized",
                            original_chars=original_len,
                            normalized_chars=normalized_len,
                            reduction_pct=round(
                                (1 - normalized_len / original_len) * 100, 1
                            )
                            if original_len > 0
                            else 0,
                        )

                # Replace documents with normalized versions
                documents = normalized_documents
                normalized_total_chars = sum(len(doc.text) for doc in documents)
                logger.info(
                    "Documents normalized",
                    original_chars=raw_total_chars,
                    normalized_chars=normalized_total_chars,
                    reduction_pct=round(
                        (1 - normalized_total_chars / raw_total_chars) * 100, 1
                    )
                    if raw_total_chars > 0
                    else 0,
                )

                # Parse into nodes (chunks)
                nodes = self._node_parser.get_nodes_from_documents(documents)

                if not nodes:
                    raise LlamaIndexDocumentServiceError(
                        f"No chunks generated from document: {document_path}"
                    )

                # Convert nodes to ProcessedChunk format
                chunks = []
                doc_type = extension.lstrip(".")

                for idx, node in enumerate(nodes):
                    # Extract page number if available
                    page_number = None
                    if hasattr(node, "metadata") and node.metadata:
                        page_number = node.metadata.get(
                            "page_label"
                        ) or node.metadata.get("page_number")
                        if page_number:
                            try:
                                page_number = int(page_number)
                            except (ValueError, TypeError):
                                page_number = None

                    # Create metadata
                    metadata = create_document_metadata(
                        chunk_index=idx,
                        doc_type=doc_type,
                        media_path=document_path,
                        contextual_text=contextual_text,
                        page_number=page_number,
                    )

                    chunk = ProcessedChunk(
                        text=node.text,
                        metadata=metadata,
                        text_embedding=None,  # Will be generated by embedding service
                        multimodal_embedding=None,
                    )
                    chunks.append(chunk)

                logger.info(
                    "Document processing completed",
                    document_path=document_path,
                    chunk_count=len(chunks),
                    avg_chunk_size=(
                        sum(len(c.text) for c in chunks) // len(chunks) if chunks else 0
                    ),
                )

                return chunks

            except LlamaIndexDocumentServiceError:
                raise
            except Exception as e:
                logger.error(
                    "Document processing failed",
                    document_path=document_path,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                raise LlamaIndexDocumentServiceError(
                    f"Failed to process document {document_path}: {e}"
                ) from e

        return await retry_async(_process, operation_name="llamaindex_process_document")

    async def process_document_with_embeddings(
        self,
        document_path: str,
        user_id: str,
        document_id: str | None = None,
        contextual_text: str = "",
    ) -> list[ProcessedChunk]:
        """
        Process a document and generate text embeddings for each chunk.

        This is a convenience method that combines document processing
        with embedding generation.

        Args:
            document_path: Path to the document file
            user_id: User ID who owns the document
            document_id: Optional document ID
            contextual_text: Optional context for embeddings

        Returns:
            List of ProcessedChunk objects with embeddings populated
        """
        # Import embedding service
        from .embedding_service import get_embedding_service

        # Process document first
        chunks = await self.process_document_file(
            document_path=document_path,
            user_id=user_id,
            document_id=document_id,
            contextual_text=contextual_text,
        )

        # Generate embeddings for each chunk
        embedding_service = get_embedding_service(self.project_id)

        for chunk in chunks:
            try:
                embedding = await embedding_service.generate_text_embedding(chunk.text)
                chunk.text_embedding = embedding
            except Exception as e:
                logger.warning(
                    "Failed to generate embedding for chunk",
                    chunk_index=(
                        chunk.metadata.chunk_index
                        if hasattr(chunk.metadata, "chunk_index")
                        else "unknown"
                    ),
                    error=str(e),
                )
                # Continue processing other chunks

        embedded_count = sum(1 for c in chunks if c.text_embedding is not None)
        logger.info(
            "Embeddings generated",
            total_chunks=len(chunks),
            embedded_chunks=embedded_count,
        )

        return chunks


# Global service instance
_llamaindex_document_service: LlamaIndexDocumentService | None = None


def get_llamaindex_document_service(
    project_id: str | None = None,
) -> LlamaIndexDocumentService:
    """
    Get a global LlamaIndex document service instance.

    Args:
        project_id: Google Cloud project ID

    Returns:
        LlamaIndexDocumentService instance
    """
    global _llamaindex_document_service

    if _llamaindex_document_service is None:
        # Read configuration
        use_llamaparse = os.getenv("USE_LLAMAPARSE", "false").lower() == "true"
        llamaparse_api_key = os.getenv("LLAMAPARSE_API_KEY")
        chunk_size = int(os.getenv("LLAMAINDEX_CHUNK_SIZE", str(config.CHUNK_SIZE)))
        chunk_overlap = int(
            os.getenv("LLAMAINDEX_CHUNK_OVERLAP", str(config.CHUNK_OVERLAP))
        )

        _llamaindex_document_service = LlamaIndexDocumentService(
            project_id=project_id,
            use_llamaparse=use_llamaparse,
            llamaparse_api_key=llamaparse_api_key,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    return _llamaindex_document_service


def reset_llamaindex_document_service() -> None:
    """Reset the global service instance (useful for testing)."""
    global _llamaindex_document_service
    _llamaindex_document_service = None
