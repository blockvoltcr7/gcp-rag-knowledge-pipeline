"""
Document processing service for handling document files.

Handles text extraction, chunking, embedding generation, and storage
with proper error handling and support for multiple document formats.
"""

import threading
from pathlib import Path
from typing import TypedDict

import chardet
import structlog
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
from langchain_text_splitters import RecursiveCharacterTextSplitter

from ..models.metadata_models import DocumentChunkMetadata
from ..utils.retry_utils import NonRetryableError
from ..utils.token_utils import create_google_tokenizer
from .database_service import ChunkData, get_database_service
from .embedding_service import get_embedding_service

logger = structlog.get_logger(__name__)


class ChunkWithPages(TypedDict):
    """Structure for document chunks with page information."""

    text: str
    page_numbers: list[int]


class DocumentProcessingServiceError(NonRetryableError):
    """Base exception for document processing service errors."""

    pass


class DocumentProcessingService:
    """
    Service for processing document files using offline standard Docling models with all AI features disabled.

    Handles text extraction, chunking, embedding generation, and storage
    for various document formats (PDF, DOCX, TXT, etc.) using Docling's
    document processing and chunking capabilities in text-only mode.

    Uses pre-downloaded standard Docling models included in Docker image for reliable production
    operation, with all AI features disabled (OCR, table structure, picture processing) to
    avoid model conflicts and ensure maximum performance and reliability.
    Models must be baked into the Docker container during build - no runtime downloads.

    This design ensures fastest, most reliable document processing with offline models while
    avoiding all potential AI model conflicts and dependency issues.
    """

    # Class-level cache for DocumentConverter (shared across all instances)
    _doc_converter: DocumentConverter | None = None
    _converter_lock = threading.Lock()

    def __init__(
        self,
        max_tokens: int = 2047,  # Max tokens for Google gemini-embedding-001
        project_id: str | None = None,
    ):
        """
        Initialize the document processing service.

        Args:
            max_tokens: Maximum tokens per text chunk (2047 for gemini-embedding-001)
            project_id: Google Cloud project ID
        """
        self.max_tokens = max_tokens

        # Initialize dependencies
        self.embedding_service = get_embedding_service(project_id)
        self.database_service = get_database_service(project_id)

        # Initialize Docling components (using cached converter)
        self.doc_converter = self._get_or_create_document_converter()
        self.tokenizer = create_google_tokenizer(
            genai_client=self.embedding_service.genai_client
        )

        logger.info(
            "Document processing service initialized",
            max_tokens=max_tokens,
            project_id=project_id,
        )

    def _get_or_create_document_converter(self) -> DocumentConverter:
        """
        Get cached DocumentConverter or create new one if not exists.
        Thread-safe singleton pattern for DocumentConverter caching.

        Returns:
            Cached DocumentConverter instance
        """
        # Double-checked locking pattern for thread-safe singleton
        if self._doc_converter is None:
            with self._converter_lock:
                if self._doc_converter is None:
                    logger.info("Creating new DocumentConverter (will be cached)")
                    self._doc_converter = self._create_document_converter()
                    logger.info("DocumentConverter cached successfully")
                else:
                    logger.debug(
                        "Using cached DocumentConverter from concurrent thread"
                    )
        else:
            logger.debug("Using cached DocumentConverter")

        return self._doc_converter

    def _create_document_converter(self) -> DocumentConverter:
        """
        Create DocumentConverter with offline standard Docling models, no VLM pipeline, and OCR disabled.

        Uses pre-downloaded standard Docling models included in Docker image for reliable operation
        without VLM pipeline overhead or OCR dependencies for improved performance and reliability.

        Configuration expects DOCLING_ARTIFACTS_PATH environment variable to be set at container level.
        Falls back to default container path (/app/models/docling) if environment variable not set.

        Returns:
            Configured DocumentConverter instance with offline models, basic processing, no OCR

        Raises:
            DocumentProcessingServiceError: If offline standard Docling models are not available
        """
        import os

        # Check for models - environment variable takes precedence, then default container path
        container_artifacts_path = Path("/app/models/docling")
        env_artifacts_path = os.getenv("DOCLING_ARTIFACTS_PATH")

        artifacts_path = None
        if env_artifacts_path:
            artifacts_path = Path(env_artifacts_path)
        elif container_artifacts_path.exists():
            artifacts_path = container_artifacts_path

        try:
            # Check if offline models exist
            if (
                artifacts_path
                and artifacts_path.exists()
                and any(artifacts_path.iterdir())
            ):
                logger.info(
                    "Configuring Docling with offline standard models (no VLM pipeline)",
                    artifacts_path=str(artifacts_path),
                    model_files_count=len(list(artifacts_path.rglob("*"))),
                )

                # Configure PDF pipeline with offline models but without VLM
                # Docling will use DOCLING_ARTIFACTS_PATH environment variable automatically
                # Also pass artifacts_path explicitly as redundant safety measure
                pipeline_options = PdfPipelineOptions(
                    artifacts_path=artifacts_path,
                    # Disable most AI-powered features to avoid model conflicts
                    do_ocr=False,  # No OCR (avoids EasyOCR)
                    do_table_structure=False,  # Disabled - avoids layout model dependency for Docling 2.71.0
                    do_code_enrichment=False,  # No code OCR
                    do_formula_enrichment=False,  # No formula OCR
                    do_picture_classification=False,  # No picture classification
                    do_picture_description=False,  # No picture description
                )

                converter = DocumentConverter(
                    format_options={
                        InputFormat.PDF: PdfFormatOption(
                            pipeline_options=pipeline_options
                        )
                    }
                )

                logger.info(
                    "Document converter initialized with offline standard Docling models, all AI features disabled for fast, reliable text-only processing"
                )
                return converter
            else:
                logger.warning(
                    "Offline standard Docling models not found",
                    container_path=str(container_artifacts_path),
                    env_path=env_artifacts_path,
                    container_exists=container_artifacts_path.exists(),
                )
                raise Exception("Offline standard Docling models not available")

        except Exception as e:
            error_msg = f"Failed to configure offline standard Docling models: {e}"
            logger.error(
                "Critical error: Offline standard Docling models not available",
                error=str(e),
                error_type=type(e).__name__,
                artifacts_path=str(artifacts_path) if artifacts_path else None,
            )
            raise DocumentProcessingServiceError(error_msg) from e

    def _extract_heading_hierarchy_from_markdown(
        self, markdown_text: str
    ) -> dict[str, tuple[list[str], str]]:
        """
        Extract heading hierarchy AND full section text from markdown.

        Parses markdown to create a mapping from text sections to their heading hierarchy
        and complete section content. This preserves ALL content (including prices) that
        Docling's HybridChunker might filter out.

        Args:
            markdown_text: Markdown export from Docling

        Returns:
            Dictionary mapping section text (first 100 chars) to tuple of (hierarchy, full_text)
            Example: {"Operations Handbook": (["File Uploads"], "Upload a document to begin processing.")}
        """
        import re

        heading_map: dict[str, tuple[list[str], str]] = {}
        current_hierarchy: list[str] = []
        current_section_lines: list[str] = []

        lines = markdown_text.split("\n")

        for line in lines:
            # Check if line is a markdown heading (# Heading)
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)

            if heading_match:
                # Update heading hierarchy FIRST (before saving section)
                level = len(heading_match.group(1))  # Count # symbols
                heading_text = heading_match.group(2).strip()

                # Skip price/number headings when building hierarchy
                # This prevents "Upload a document..." from replacing "File Uploads"
                is_price_heading = heading_text.startswith("$") or (
                    heading_text and heading_text[0].isdigit()
                )

                if not is_price_heading:
                    # Save previous section with OLD hierarchy (before this heading)
                    if current_section_lines:
                        section_text = "\n".join(current_section_lines).strip()
                        if section_text:
                            # Use first 100 chars as key for matching
                            key = section_text[:100]
                            # Store BOTH hierarchy AND full section text
                            heading_map[key] = (current_hierarchy.copy(), section_text)
                        current_section_lines = []

                    # Update hierarchy with non-price heading
                    if level == 1:
                        current_hierarchy = [heading_text]
                    elif level == 2:
                        current_hierarchy = current_hierarchy[:1] + [heading_text]
                    elif level == 3:
                        current_hierarchy = current_hierarchy[:2] + [heading_text]
                    else:
                        # For deeper levels, just append
                        current_hierarchy = current_hierarchy[: level - 1] + [
                            heading_text
                        ]

                    logger.debug(
                        "Found markdown heading",
                        level=level,
                        heading=heading_text,
                        hierarchy=current_hierarchy,
                    )
                else:
                    # Price heading - treat as regular text content, not as hierarchy
                    # Add to current section so prices appear in chunk text
                    current_section_lines.append(heading_text)
                    logger.debug(
                        "Price/number heading treated as content",
                        level=level,
                        heading=heading_text,
                    )
            else:
                # Add to current section content
                if line.strip():  # Skip empty lines
                    current_section_lines.append(line)

        # Save last section
        if current_section_lines:
            section_text = "\n".join(current_section_lines).strip()
            if section_text:
                key = section_text[:100]
                # Store BOTH hierarchy AND full section text
                heading_map[key] = (current_hierarchy.copy(), section_text)

        return heading_map

    def _find_best_heading_match(
        self, chunk_text: str, heading_map: dict[str, tuple[list[str], str]]
    ) -> tuple[list[str], str] | None:
        """
        Find the best matching heading hierarchy and full section text for a chunk.

        Uses fuzzy text matching to find which markdown section this chunk belongs to.
        Returns both the heading hierarchy AND the full section text (which includes prices).

        Args:
            chunk_text: The text content of the chunk
            heading_map: Mapping from section text to (hierarchy, full_text) tuple

        Returns:
            Tuple of (hierarchy, full_section_text) or None if no match found
        """
        # Try exact match first (first 100 chars)
        chunk_key = chunk_text[:100].strip()
        if chunk_key in heading_map:
            return heading_map[chunk_key]

        # Try fuzzy matching - find section with most text overlap
        best_match_score = 0.0
        best_match_result: tuple[list[str], str] | None = None

        # Normalize chunk text for comparison
        chunk_normalized = chunk_text.lower().replace("\n", " ")[:200]

        for section_key, (hierarchy, full_text) in heading_map.items():
            section_normalized = section_key.lower().replace("\n", " ")

            # Count common words (simple similarity metric)
            chunk_words = set(chunk_normalized.split())
            section_words = set(section_normalized.split())
            common_words = chunk_words & section_words

            if len(section_words) > 0:
                similarity = len(common_words) / len(section_words)

                if similarity > best_match_score:
                    best_match_score = similarity
                    best_match_result = (hierarchy, full_text)

        # Only return match if similarity is reasonable
        if best_match_score > 0.3:  # 30% word overlap threshold
            return best_match_result

        return None

    async def _split_text_file_with_langchain(
        self, document_path: str
    ) -> list[ChunkWithPages]:
        """
        Split plain text file using LangChain's RecursiveCharacterTextSplitter.

        Handles encoding detection and semantic chunking without Docling overhead.
        Designed for .txt, .md, and other plain text files.

        Args:
            document_path: Path to the text file

        Returns:
            List of chunk dictionaries with text content and page numbers

        Raises:
            DocumentProcessingServiceError: If text file processing fails
        """
        import time

        start_time = time.time()

        try:
            # Step 1: Detect file encoding
            logger.info(
                "Starting text file encoding detection",
                document_path=document_path,
            )

            with open(document_path, "rb") as f:
                raw_data = f.read()
                detected = chardet.detect(raw_data)
                encoding = detected["encoding"] or "utf-8"
                confidence = detected.get("confidence", 0.0)

            logger.info(
                "Text file encoding detected",
                document_path=document_path,
                detected_encoding=encoding,
                confidence=round(confidence, 2),
            )

            # Step 2: Read file with detected encoding
            try:
                with open(document_path, encoding=encoding, errors="replace") as f:
                    text = f.read()

                logger.info(
                    "Text file read successfully",
                    document_path=document_path,
                    text_length=len(text),
                    encoding=encoding,
                )
            except Exception as read_error:
                logger.error(
                    "Failed to read text file with detected encoding",
                    document_path=document_path,
                    encoding=encoding,
                    error=str(read_error),
                    error_type=type(read_error).__name__,
                )
                raise DocumentProcessingServiceError(
                    f"Failed to read text file '{document_path}' with encoding {encoding}: {read_error}"
                ) from read_error

            # Step 3: Initialize LangChain text splitter
            logger.info(
                "Initializing LangChain RecursiveCharacterTextSplitter",
                document_path=document_path,
                max_tokens=self.max_tokens,
            )

            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=self.max_tokens,
                chunk_overlap=200,  # Maintain context between chunks
                length_function=self.tokenizer.count_tokens,
                separators=[
                    "\n\n",  # Paragraphs
                    "\n",  # Lines
                    ". ",  # Sentences ending with period
                    "? ",  # Sentences ending with question mark
                    "! ",  # Sentences ending with exclamation
                    " ",  # Words
                    "",  # Characters (last resort)
                ],
                is_separator_regex=False,
            )

            # Step 4: Split text into chunks
            logger.info(
                "Splitting text with LangChain",
                document_path=document_path,
            )

            chunks = text_splitter.split_text(text)

            total_time = time.time() - start_time

            logger.info(
                "Text file split successfully with LangChain",
                document_path=document_path,
                chunk_count=len(chunks),
                encoding=encoding,
                total_time_seconds=round(total_time, 2),
                average_chunk_length=(
                    sum(len(c) for c in chunks) // len(chunks) if chunks else 0
                ),
            )

            # Step 5: Return in ChunkWithPages format (text files have no pages)
            return [
                ChunkWithPages(text=chunk, page_numbers=[1])
                for chunk in chunks
                if chunk.strip()
            ]

        except DocumentProcessingServiceError:
            # Re-raise our own errors
            raise
        except Exception as e:
            total_time = time.time() - start_time
            logger.error(
                "Text file processing failed",
                document_path=document_path,
                error=str(e),
                error_type=type(e).__name__,
                total_time_seconds=round(total_time, 2),
            )
            raise DocumentProcessingServiceError(
                f"Text file processing failed for {document_path}: {e}"
            ) from e

    async def split_document_into_chunks(
        self, document_path: str
    ) -> list[ChunkWithPages]:
        """
        Split document into chunks using appropriate method.

        Routes plain text files to LangChain's RecursiveCharacterTextSplitter
        for fast, encoding-aware processing. Routes structured documents to
        Docling's HybridChunker for semantic document understanding.

        Args:
            document_path: Path to the document file

        Returns:
            List of chunk dictionaries with text content and page numbers

        Raises:
            DocumentProcessingServiceError: If chunking fails
        """
        import time

        start_time = time.time()

        try:
            # Route plain text files to specialized handler
            if document_path.lower().endswith((".txt", ".md", ".markdown")):
                logger.info(
                    "Routing plain text file to LangChain handler",
                    document_path=document_path,
                    file_extension=Path(document_path).suffix.lower(),
                )
                return await self._split_text_file_with_langchain(document_path)

            # Pre-validate PDFs to surface actionable errors early
            if document_path.lower().endswith(".pdf"):
                try:
                    import pypdfium2 as pdfium  # Lightweight validation

                    pdf = pdfium.PdfDocument(document_path)
                    page_count = len(pdf)
                    # Note: pdfium raises on encrypted or non-openable documents.
                    # We probe page count for visibility and avoid unused variables.
                    # pdfium raises on encrypted/non-openable docs; we log page_count
                    logger.info(
                        "PDF prevalidation passed",
                        document_path=document_path,
                        page_count=page_count,
                    )
                    # Optional guard for extremely large docs to avoid timeouts/memory spikes
                    if page_count > 2000:
                        raise DocumentProcessingServiceError(
                            f"PDF has {page_count} pages; exceeds safe processing limit (2000). "
                            "Please split the document and retry."
                        )
                except Exception as pre_e:
                    # Provide actionable error message for encrypted/corrupt PDFs
                    logger.error(
                        "PDF prevalidation failed",
                        document_path=document_path,
                        error=str(pre_e),
                        error_type=type(pre_e).__name__,
                    )
                    raise DocumentProcessingServiceError(
                        f"PDF validation failed for '{document_path}': {pre_e}"
                    ) from pre_e
            logger.info(
                "Starting document chunking with Docling HybridChunker",
                document_path=document_path,
            )

            # Step 1: Document conversion
            logger.info(
                "Step 1: Starting document conversion with Docling converter",
                document_path=document_path,
            )
            conversion_start = time.time()

            result = self.doc_converter.convert(document_path)

            conversion_time = time.time() - conversion_start
            logger.info(
                "Step 1: Document conversion completed",
                document_path=document_path,
                conversion_time_seconds=round(conversion_time, 2),
                result_type=type(result).__name__,
                has_document=bool(result and hasattr(result, "document")),
            )

            if not result or not result.document:
                logger.error(
                    "Document conversion failed - empty or invalid result",
                    document_path=document_path,
                    result_is_none=result is None,
                    has_document_attr=hasattr(result, "document") if result else False,
                    document_is_none=(
                        result.document is None
                        if result and hasattr(result, "document")
                        else None
                    ),
                )
                raise DocumentProcessingServiceError(
                    f"Failed to extract document content from '{document_path}'. Result was empty or invalid."
                )

            dl_document = result.document
            logger.info(
                "Step 2: Document object extracted successfully",
                document_path=document_path,
                document_type=type(dl_document).__name__,
                has_content=bool(dl_document),
            )

            # Step 2b: Export to markdown to extract proper heading hierarchy
            logger.info(
                "Step 2b: Exporting document to markdown for heading extraction",
                document_path=document_path,
            )
            markdown_export_start = time.time()

            # Export document to markdown (this correctly detects headings)
            markdown_text = dl_document.export_to_markdown()

            # Parse markdown to extract heading hierarchy
            heading_map = self._extract_heading_hierarchy_from_markdown(markdown_text)

            markdown_export_time = time.time() - markdown_export_start
            logger.info(
                "Step 2b: Markdown export and heading extraction completed",
                document_path=document_path,
                export_time_seconds=round(markdown_export_time, 2),
                headings_found=len(heading_map),
                heading_previews=list(heading_map.keys())[:5],
            )

            # Step 3: Initialize HybridChunker
            logger.info(
                "Step 3: Initializing HybridChunker with Google tokenizer",
                document_path=document_path,
                max_tokens=self.max_tokens,
                tokenizer_type=type(self.tokenizer).__name__,
            )
            chunker_init_start = time.time()

            chunker = HybridChunker(
                tokenizer=self.tokenizer,
                merge_peers=True,  # Merge related content sections
                always_emit_headings=True,  # Force heading emission even for weak structure
            )
            # Store chunker instance for use in contextualize()
            self.chunker = chunker

            chunker_init_time = time.time() - chunker_init_start
            logger.info(
                "Step 3: HybridChunker initialized successfully",
                document_path=document_path,
                init_time_seconds=round(chunker_init_time, 2),
                chunker_type=type(chunker).__name__,
            )

            # Step 3: Chunk the document
            logger.info(
                "Step 4: Starting document chunking process",
                document_path=document_path,
            )
            chunking_start = time.time()

            # Add progress logging for chunking since this might be where it hangs
            logger.info(
                "Step 4a: Calling chunker.chunk() method",
                document_path=document_path,
            )

            chunk_objects = list(self.chunker.chunk(dl_doc=dl_document))

            chunking_time = time.time() - chunking_start
            logger.info(
                "Step 4: Document chunking completed",
                document_path=document_path,
                chunking_time_seconds=round(chunking_time, 2),
                chunk_count=len(chunk_objects),
            )

            if not chunk_objects:
                logger.warning(
                    "No chunks generated from document",
                    document_path=document_path,
                )
                return [ChunkWithPages(text="[Empty document]", page_numbers=[])]

            # Step 5: Process chunk objects using contextualize() for header preservation
            logger.info(
                "Step 5a: Processing chunk objects with contextualize() for header enrichment",
                document_path=document_path,
                raw_chunk_count=len(chunk_objects),
            )
            processing_start = time.time()

            # First pass: Convert chunk objects to ChunkWithPages format
            # Using chunker.contextualize() to include heading metadata (Docling best practice)
            raw_chunks = []

            for i, chunk_obj in enumerate(chunk_objects):
                # Log progress every 10 chunks to track processing
                if i % 10 == 0 or i == len(chunk_objects) - 1:
                    logger.info(
                        "Step 5a: Processing chunk batch",
                        document_path=document_path,
                        chunk_index=i,
                        total_chunks=len(chunk_objects),
                        progress_percent=round((i + 1) / len(chunk_objects) * 100, 1),
                    )

                if not chunk_obj.text or not chunk_obj.text.strip():
                    logger.debug(f"Skipping empty or whitespace-only chunk {i + 1}.")
                    continue

                # Extract page numbers from chunk metadata
                page_numbers: list[int] = []

                # Debug logging to understand metadata structure
                logger.debug(
                    f"Chunk {i} metadata analysis",
                    chunk_index=i,
                    has_meta=bool(chunk_obj.meta),
                    meta_type=type(chunk_obj.meta).__name__ if chunk_obj.meta else None,
                    meta_attrs=dir(chunk_obj.meta) if chunk_obj.meta else [],
                    has_doc_items=(
                        hasattr(chunk_obj.meta, "doc_items")
                        if chunk_obj.meta
                        else False
                    ),
                )

                # Try multiple approaches to extract page numbers
                if chunk_obj.meta:
                    # Approach 1: Standard doc_items -> prov -> page_no
                    if hasattr(chunk_obj.meta, "doc_items"):
                        doc_items = getattr(chunk_obj.meta, "doc_items", [])
                        logger.debug(f"Found {len(doc_items)} doc_items in chunk {i}")

                        for j, item in enumerate(doc_items):
                            if hasattr(item, "prov"):
                                logger.debug(
                                    f"Doc item {j} has prov with {len(item.prov)} items"
                                )
                                for prov_item in item.prov:
                                    if (
                                        hasattr(prov_item, "page_no")
                                        and prov_item.page_no is not None
                                    ):
                                        page_numbers.append(prov_item.page_no)
                                        logger.debug(
                                            f"Found page_no: {prov_item.page_no}"
                                        )

                    # Approach 2: Check if page info is directly in meta
                    if hasattr(chunk_obj.meta, "page_no"):
                        page_no = getattr(chunk_obj.meta, "page_no", None)
                        if page_no is not None:
                            page_numbers.append(page_no)
                            logger.debug(f"Found direct page_no in meta: {page_no}")

                    # Approach 3: Check for page_number attribute
                    if hasattr(chunk_obj.meta, "page_number"):
                        page_number = getattr(chunk_obj.meta, "page_number", None)
                        if page_number is not None:
                            page_numbers.append(page_number)
                            logger.debug(f"Found page_number in meta: {page_number}")

                # If no page numbers found, default to chunk index + 1 as fallback
                if not page_numbers:
                    # For documents, assume each chunk represents roughly one page
                    # This is a reasonable fallback for document processing
                    page_numbers = [i + 1]
                    logger.debug(
                        f"No page numbers found, using fallback page number: {i + 1}"
                    )

                page_numbers = sorted(set(page_numbers))

                # Extract raw chunk text from Docling (may be missing prices)
                docling_chunk_text = chunk_obj.text.strip()

                # Find matching section from markdown export (includes ALL content)
                match_result = self._find_best_heading_match(
                    docling_chunk_text, heading_map
                )

                if match_result:
                    markdown_headings, full_section_text = match_result

                    logger.info(
                        f"[DEBUG] Chunk {i} matched to markdown section",
                        chunk_index=i,
                        heading_hierarchy=markdown_headings,
                        docling_text_preview=docling_chunk_text[:100],
                        markdown_text_preview=full_section_text[:100],
                    )

                    # Use full section text from markdown (includes prices that Docling filtered)
                    chunk_text = full_section_text

                    # Filter out price/number headings (start with "$" or digits)
                    # This prevents using "Upload a document..." or "1. Introduction" as section headings
                    non_price_headings = [
                        h
                        for h in markdown_headings
                        if not (h.startswith("$") or (h and h[0].isdigit()))
                    ]

                    # Select the best heading to use
                    heading_to_use = None

                    if len(non_price_headings) > 1:
                        # Multiple non-price headings: prefer the most specific (last in hierarchy)
                        # But skip if the last one is too generic (single word or very short)
                        last_heading = non_price_headings[-1]

                        if len(last_heading.split()) > 1:
                            # Multi-word heading is likely specific enough
                            heading_to_use = last_heading
                        else:
                            # Single word - might be generic, use second-to-last if available
                            heading_to_use = (
                                non_price_headings[-2]
                                if len(non_price_headings) > 2
                                else last_heading
                            )

                    elif len(non_price_headings) == 1:
                        # Only one non-price heading - use it
                        heading_to_use = non_price_headings[0]

                    else:
                        # All headings are prices/numbers - don't prepend anything
                        logger.debug(
                            f"[DEBUG] Chunk {i} only price/number headings found, skipping",
                            chunk_index=i,
                            full_hierarchy=markdown_headings,
                        )

                    if heading_to_use:
                        logger.info(
                            f"[DEBUG] Chunk {i} selected heading",
                            chunk_index=i,
                            selected_heading=heading_to_use,
                            full_hierarchy=markdown_headings,
                            non_price_headings=non_price_headings,
                        )

                        # Only prepend if not already in chunk (avoid duplication)
                        if heading_to_use not in chunk_text[: len(heading_to_use) + 50]:
                            chunk_text = f"{heading_to_use}\n\n{chunk_text}"
                            logger.info(
                                f"[DEBUG] Chunk {i} heading prepended",
                                chunk_index=i,
                                heading=heading_to_use,
                                full_hierarchy=markdown_headings,
                            )
                else:
                    # No match found - fall back to Docling chunk text
                    chunk_text = docling_chunk_text
                    logger.debug(
                        f"[DEBUG] Chunk {i} no markdown heading match found, using Docling text",
                        chunk_index=i,
                        chunk_text_preview=chunk_text[:100],
                    )

                raw_chunks.append(
                    ChunkWithPages(
                        text=chunk_text,
                        page_numbers=page_numbers,
                    )
                )

            logger.info(
                "Step 5a: Chunk processing with heading hierarchy completed",
                document_path=document_path,
                raw_chunk_count=len(raw_chunks),
            )

            logger.info(
                "Step 5b: Enforcing chunk size limits",
                document_path=document_path,
                raw_chunk_count=len(raw_chunks),
            )

            # Second pass: Enforce size limits (NEW)
            chunks = self._enforce_chunk_size_limits(
                raw_chunks, target_size=1000, max_size=1200, overlap=200
            )

            processing_time = time.time() - processing_start
            total_time = time.time() - start_time

            logger.info(
                "Step 5c: Chunk processing complete",
                document_path=document_path,
                processing_time_seconds=round(processing_time, 2),
                final_chunk_count=len(chunks),
                chunks_added_by_splitting=len(chunks) - len(raw_chunks),
            )

            logger.info(
                "Document chunked successfully with HybridChunker",
                document_path=document_path,
                chunk_count=len(chunks),
                total_time_seconds=round(total_time, 2),
                average_chunk_length=(
                    sum(len(c["text"]) for c in chunks) // len(chunks) if chunks else 0
                ),
            )

            return (
                chunks
                if chunks
                else [ChunkWithPages(text="[Empty document]", page_numbers=[])]
            )

        except Exception as e:
            total_time = time.time() - start_time
            logger.error(
                "Document chunking failed",
                document_path=document_path,
                error=str(e),
                error_type=type(e).__name__,
                total_time_seconds=round(total_time, 2),
            )
            raise DocumentProcessingServiceError(
                f"Document chunking failed for {document_path}: {e}"
            ) from e

    def _enforce_chunk_size_limits(
        self,
        chunks: list[ChunkWithPages],
        target_size: int = 1000,
        max_size: int = 1200,
        overlap: int = 200,
    ) -> list[ChunkWithPages]:
        """
        Post-process chunks to enforce character limits.

        Splits oversized chunks using RecursiveCharacterTextSplitter
        while preserving page number metadata from HybridChunker.

        Args:
            chunks: Original chunks from HybridChunker
            target_size: Target characters per chunk (default: 1000)
            max_size: Maximum allowed characters - chunks > this get split (default: 1200)
            overlap: Characters to overlap between split chunks (default: 200)

        Returns:
            List of size-enforced chunks with preserved metadata
        """
        enforced_chunks: list[ChunkWithPages] = []

        # Initialize text splitter for oversized chunks
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=target_size,
            chunk_overlap=overlap,
            length_function=len,  # Character-based
            separators=["\n\n", "\n", ". ", "? ", "! ", " ", ""],
            is_separator_regex=False,
        )

        for chunk in chunks:
            chunk_text = chunk["text"]
            page_numbers = chunk["page_numbers"]

            # If chunk is within size limits, keep as-is
            if len(chunk_text) <= max_size:
                enforced_chunks.append(chunk)
                logger.debug(
                    "Chunk within size limit",
                    size=len(chunk_text),
                    max_size=max_size,
                )
            else:
                # Split oversized chunk
                logger.info(
                    "Splitting oversized chunk",
                    original_size=len(chunk_text),
                    max_size=max_size,
                    page_numbers=page_numbers,
                )

                split_texts = text_splitter.split_text(chunk_text)

                for split_text in split_texts:
                    enforced_chunks.append(
                        ChunkWithPages(
                            text=split_text,
                            page_numbers=page_numbers,  # Preserve original page numbers
                        )
                    )

                logger.info(
                    "Chunk split complete",
                    original_size=len(chunk_text),
                    split_count=len(split_texts),
                    avg_split_size=sum(len(t) for t in split_texts) // len(split_texts),
                )

        logger.info(
            "Chunk size enforcement summary",
            original_count=len(chunks),
            enforced_count=len(enforced_chunks),
            chunks_split=len(enforced_chunks) - len(chunks),
        )

        return enforced_chunks

    async def process_document_file(
        self,
        document_path: str,
        user_id: str,
        document_id: str | None = None,
        contextual_text: str = "",
    ) -> list[ChunkData]:
        """
        Process a complete document file using Docling's HybridChunker.

        Args:
            document_path: Path to the document file
            user_id: ID of the user who owns the document
            document_id: Optional document ID to associate chunks with
            contextual_text: Optional contextual text for embedding

        Returns:
            List of processed chunks ready for storage

        Raises:
            DocumentProcessingServiceError: If processing fails
        """
        logger.info(
            "Starting document processing with Docling HybridChunker",
            document_path=document_path,
            user_id=user_id,
            document_id=document_id,
        )

        try:
            # Split document into chunks using HybridChunker
            text_chunks = await self.split_document_into_chunks(document_path)

            # Process each chunk
            chunks = []
            for i, chunk_data in enumerate(text_chunks):
                # Extract text and page numbers from chunk
                chunk_text = chunk_data["text"]
                page_numbers = chunk_data["page_numbers"]

                # Generate text embedding
                embedding = await self.embedding_service.generate_text_embedding(
                    text=chunk_text,
                )

                # Create metadata with extracted page numbers
                metadata = DocumentChunkMetadata(
                    media_path=document_path,
                    contextual_text=contextual_text,
                    page_number=(
                        page_numbers[0] if page_numbers else None
                    ),  # Use first page number
                    chunk_index=i,
                    doc_type=Path(document_path).suffix.lower().lstrip("."),
                )

                # Create chunk
                chunk = ChunkData(
                    text=chunk_text,
                    metadata=metadata,
                    text_embedding=embedding,
                )

                chunks.append(chunk)

            logger.info(
                "Document processing completed with HybridChunker",
                document_path=document_path,
                chunk_count=len(chunks),
            )

            return chunks

        except Exception as e:
            logger.error(
                "Document processing failed",
                document_path=document_path,
                user_id=user_id,
                error=str(e),
            )
            raise DocumentProcessingServiceError(
                f"Document processing failed: {e}"
            ) from e
        finally:
            # Clean up the document file that was passed to us
            try:
                from ..utils.gcs_utils import cleanup_temp_file

                cleanup_temp_file(document_path)
                logger.debug(
                    "Cleaned up main document file", document_path=document_path
                )
            except Exception as cleanup_error:
                logger.warning(
                    "Failed to cleanup document processing temp files",
                    document_path=document_path,
                    error=str(cleanup_error),
                )


# Global service instance
_document_processing_service: DocumentProcessingService | None = None


def get_document_processing_service(
    project_id: str | None = None,
) -> DocumentProcessingService:
    """
    Get a global document processing service instance.

    Args:
        project_id: Google Cloud project ID

    Returns:
        DocumentProcessingService instance
    """
    global _document_processing_service

    if _document_processing_service is None:
        _document_processing_service = DocumentProcessingService(
            project_id=project_id,
        )

    return _document_processing_service
