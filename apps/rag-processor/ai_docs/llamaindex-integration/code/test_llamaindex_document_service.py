"""
Tests for LlamaIndex Document Service.

Run with: pytest test_llamaindex_document_service.py -v
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mark all tests as async
pytestmark = pytest.mark.asyncio


class TestLlamaIndexDocumentService:
    """Tests for LlamaIndexDocumentService class."""

    @pytest.fixture
    def sample_docx_content(self):
        """Create a sample DOCX file for testing."""
        # This would require python-docx to create actual DOCX
        # For unit tests, we'll mock the reader
        return "This is sample document content for testing purposes."

    @pytest.fixture
    def sample_markdown_content(self):
        """Sample markdown content."""
        return """# Test Document

## Section 1

This is the first section with some content.

## Section 2

This is the second section with more content.

### Subsection 2.1

Details about the subsection.
"""

    @pytest.fixture
    def sample_text_content(self):
        """Sample text content."""
        return "This is a simple text file with some content for testing."

    @pytest.fixture
    def temp_text_file(self, sample_text_content):
        """Create a temporary text file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
            f.write(sample_text_content)
            temp_path = f.name

        yield temp_path

        # Cleanup
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    @pytest.fixture
    def temp_markdown_file(self, sample_markdown_content):
        """Create a temporary markdown file."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False
        ) as f:
            f.write(sample_markdown_content)
            temp_path = f.name

        yield temp_path

        # Cleanup
        if os.path.exists(temp_path):
            os.unlink(temp_path)

    def test_service_initialization(self):
        """Test service initializes with correct defaults."""
        from llamaindex_document_service import LlamaIndexDocumentService

        service = LlamaIndexDocumentService(
            project_id="test-project",
            chunk_size=500,
            chunk_overlap=100,
        )

        assert service.project_id == "test-project"
        assert service.chunk_size == 500
        assert service.chunk_overlap == 100
        assert service.use_llamaparse is False
        assert service._initialized is False

    def test_is_supported_extensions(self):
        """Test file extension support detection."""
        from llamaindex_document_service import LlamaIndexDocumentService

        service = LlamaIndexDocumentService()

        # Supported extensions
        assert service.is_supported("document.pdf") is True
        assert service.is_supported("document.docx") is True
        assert service.is_supported("document.md") is True
        assert service.is_supported("document.txt") is True
        assert service.is_supported("document.html") is True

        # Unsupported extensions
        assert service.is_supported("video.mp4") is False
        assert service.is_supported("audio.mp3") is False
        assert service.is_supported("image.jpg") is False
        assert service.is_supported("data.json") is False

    def test_is_supported_case_insensitive(self):
        """Test that extension checking is case-insensitive."""
        from llamaindex_document_service import LlamaIndexDocumentService

        service = LlamaIndexDocumentService()

        assert service.is_supported("document.PDF") is True
        assert service.is_supported("document.DOCX") is True
        assert service.is_supported("document.Md") is True

    @pytest.mark.asyncio
    async def test_process_text_file(self, temp_text_file):
        """Test processing a simple text file."""
        from llamaindex_document_service import LlamaIndexDocumentService

        service = LlamaIndexDocumentService(
            project_id="test-project",
            chunk_size=100,
            chunk_overlap=20,
        )

        chunks = await service.process_document_file(
            document_path=temp_text_file,
            user_id="test-user",
            document_id="test-doc-id",
        )

        assert len(chunks) > 0
        assert all(chunk.text for chunk in chunks)
        assert all(chunk.metadata is not None for chunk in chunks)
        assert all(chunk.metadata.content_type == "document" for chunk in chunks)

    @pytest.mark.asyncio
    async def test_process_markdown_file(self, temp_markdown_file):
        """Test processing a markdown file."""
        from llamaindex_document_service import LlamaIndexDocumentService

        service = LlamaIndexDocumentService(
            project_id="test-project",
            chunk_size=200,
            chunk_overlap=50,
        )

        chunks = await service.process_document_file(
            document_path=temp_markdown_file,
            user_id="test-user",
        )

        assert len(chunks) > 0
        # Verify chunk indices are sequential
        for idx, chunk in enumerate(chunks):
            assert chunk.metadata.chunk_index == idx

    @pytest.mark.asyncio
    async def test_process_unsupported_file_raises_error(self):
        """Test that unsupported files raise appropriate error."""
        from llamaindex_document_service import (
            LlamaIndexDocumentService,
            LlamaIndexDocumentServiceError,
        )

        service = LlamaIndexDocumentService()

        with pytest.raises(LlamaIndexDocumentServiceError) as exc_info:
            await service.process_document_file(
                document_path="/fake/path/video.mp4",
                user_id="test-user",
            )

        assert "Unsupported file type" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_process_nonexistent_file_raises_error(self):
        """Test that nonexistent files raise appropriate error."""
        from llamaindex_document_service import (
            LlamaIndexDocumentService,
            LlamaIndexDocumentServiceError,
        )

        service = LlamaIndexDocumentService()

        with pytest.raises(LlamaIndexDocumentServiceError):
            await service.process_document_file(
                document_path="/nonexistent/path/document.pdf",
                user_id="test-user",
            )

    def test_llamaparse_initialization_with_api_key(self):
        """Test LlamaParse is used when API key is provided."""
        from llamaindex_document_service import LlamaIndexDocumentService

        with patch.dict(os.environ, {"LLAMAPARSE_API_KEY": "test-api-key"}):
            service = LlamaIndexDocumentService(
                use_llamaparse=True,
                llamaparse_api_key="test-api-key",
            )

            assert service.use_llamaparse is True
            assert service.llamaparse_api_key == "test-api-key"

    def test_llamaparse_fallback_without_api_key(self):
        """Test fallback to PDFReader when LlamaParse API key is missing."""
        from llamaindex_document_service import LlamaIndexDocumentService

        service = LlamaIndexDocumentService(
            use_llamaparse=True,
            llamaparse_api_key=None,  # No API key
        )

        # Should not raise, will use PDFReader fallback
        assert service.use_llamaparse is True
        assert service.llamaparse_api_key is None


class TestDocumentServiceFactory:
    """Tests for DocumentServiceFactory class."""

    def test_factory_defaults_to_llamaindex(self):
        """Test factory defaults to LlamaIndex processor."""
        from document_service_factory import (
            DocumentServiceFactory,
            DocumentProcessor,
        )

        with patch.dict(os.environ, {}, clear=True):
            # Clear DOCUMENT_PROCESSOR env var
            os.environ.pop("DOCUMENT_PROCESSOR", None)

            factory = DocumentServiceFactory()
            assert factory.processor_type == DocumentProcessor.LLAMAINDEX

    def test_factory_respects_docling_env_var(self):
        """Test factory uses Docling when configured."""
        from document_service_factory import (
            DocumentServiceFactory,
            DocumentProcessor,
            reset_document_service_factory,
        )

        reset_document_service_factory()

        with patch.dict(os.environ, {"DOCUMENT_PROCESSOR": "docling"}):
            factory = DocumentServiceFactory()
            assert factory.processor_type == DocumentProcessor.DOCLING
            assert factory.is_docling() is True
            assert factory.is_llamaindex() is False

    def test_factory_respects_llamaindex_env_var(self):
        """Test factory uses LlamaIndex when configured."""
        from document_service_factory import (
            DocumentServiceFactory,
            DocumentProcessor,
            reset_document_service_factory,
        )

        reset_document_service_factory()

        with patch.dict(os.environ, {"DOCUMENT_PROCESSOR": "llamaindex"}):
            factory = DocumentServiceFactory()
            assert factory.processor_type == DocumentProcessor.LLAMAINDEX
            assert factory.is_llamaindex() is True
            assert factory.is_docling() is False


class TestChunkMetadata:
    """Tests for chunk metadata generation."""

    @pytest.mark.asyncio
    async def test_chunk_metadata_includes_page_number(self, temp_text_file):
        """Test that metadata includes page numbers when available."""
        from llamaindex_document_service import LlamaIndexDocumentService

        service = LlamaIndexDocumentService()

        chunks = await service.process_document_file(
            document_path=temp_text_file,
            user_id="test-user",
        )

        # Text files don't have page numbers
        assert all(chunk.metadata.page_number is None for chunk in chunks)

    @pytest.mark.asyncio
    async def test_chunk_metadata_includes_doc_type(self, temp_markdown_file):
        """Test that metadata includes correct document type."""
        from llamaindex_document_service import LlamaIndexDocumentService

        service = LlamaIndexDocumentService()

        chunks = await service.process_document_file(
            document_path=temp_markdown_file,
            user_id="test-user",
        )

        assert all(chunk.metadata.doc_type == "md" for chunk in chunks)

    @pytest.mark.asyncio
    async def test_chunk_metadata_includes_contextual_text(self, temp_text_file):
        """Test that contextual text is included in metadata."""
        from llamaindex_document_service import LlamaIndexDocumentService

        service = LlamaIndexDocumentService()

        chunks = await service.process_document_file(
            document_path=temp_text_file,
            user_id="test-user",
            contextual_text="This is context",
        )

        assert all(
            chunk.metadata.contextual_text == "This is context"
            for chunk in chunks
        )


# =============================================================================
# Integration Tests (require actual LlamaIndex installation)
# =============================================================================


@pytest.mark.integration
class TestLlamaIndexIntegration:
    """
    Integration tests that require LlamaIndex to be installed.

    Run with: pytest test_llamaindex_document_service.py -v -m integration
    """

    @pytest.fixture
    def real_pdf_path(self):
        """Path to a real PDF file for testing."""
        # Update this path to point to a real test PDF
        test_pdf = Path(__file__).parent / "test_files" / "sample.pdf"
        if test_pdf.exists():
            return str(test_pdf)
        pytest.skip("Test PDF file not found")

    @pytest.fixture
    def real_docx_path(self):
        """Path to a real DOCX file for testing."""
        test_docx = Path(__file__).parent / "test_files" / "sample.docx"
        if test_docx.exists():
            return str(test_docx)
        pytest.skip("Test DOCX file not found")

    @pytest.mark.asyncio
    async def test_real_pdf_processing(self, real_pdf_path):
        """Test processing a real PDF file."""
        from llamaindex_document_service import LlamaIndexDocumentService

        service = LlamaIndexDocumentService()

        chunks = await service.process_document_file(
            document_path=real_pdf_path,
            user_id="test-user",
        )

        assert len(chunks) > 0
        print(f"Processed PDF into {len(chunks)} chunks")

    @pytest.mark.asyncio
    async def test_real_docx_processing(self, real_docx_path):
        """Test processing a real DOCX file."""
        from llamaindex_document_service import LlamaIndexDocumentService

        service = LlamaIndexDocumentService()

        chunks = await service.process_document_file(
            document_path=real_docx_path,
            user_id="test-user",
        )

        assert len(chunks) > 0
        print(f"Processed DOCX into {len(chunks)} chunks")
