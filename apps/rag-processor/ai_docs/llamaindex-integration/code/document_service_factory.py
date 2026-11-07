"""
Document Service Factory.

Factory pattern for selecting between Docling and LlamaIndex document processors.
Enables gradual rollout and easy rollback via environment configuration.
"""

import os
from enum import Enum
from typing import Protocol, runtime_checkable

import structlog

from ..config import config

logger = structlog.get_logger(__name__)


class DocumentProcessor(str, Enum):
    """Available document processors."""

    DOCLING = "docling"
    LLAMAINDEX = "llamaindex"


@runtime_checkable
class DocumentServiceProtocol(Protocol):
    """
    Protocol defining the interface for document processing services.

    Both Docling and LlamaIndex services must implement this interface.
    """

    async def process_document_file(
        self,
        document_path: str,
        user_id: str,
        document_id: str | None = None,
        contextual_text: str | None = None,
    ) -> list:
        """Process a document file and return chunks."""
        ...


class DocumentServiceFactory:
    """
    Factory for creating document processing services.

    Supports switching between Docling and LlamaIndex based on configuration.
    """

    def __init__(self, project_id: str | None = None):
        """
        Initialize the factory.

        Args:
            project_id: Google Cloud project ID
        """
        self.project_id = project_id or config.PROJECT_ID
        self._processor_type = self._get_processor_type()

        logger.info(
            "Document service factory initialized",
            processor_type=self._processor_type.value,
        )

    def _get_processor_type(self) -> DocumentProcessor:
        """
        Determine which processor to use based on configuration.

        Returns:
            DocumentProcessor enum value
        """
        processor_env = os.getenv("DOCUMENT_PROCESSOR", "llamaindex").lower()

        if processor_env == "docling":
            return DocumentProcessor.DOCLING
        elif processor_env == "llamaindex":
            return DocumentProcessor.LLAMAINDEX
        else:
            logger.warning(
                f"Unknown DOCUMENT_PROCESSOR value: {processor_env}, defaulting to llamaindex"
            )
            return DocumentProcessor.LLAMAINDEX

    def get_service(self) -> DocumentServiceProtocol:
        """
        Get the configured document processing service.

        Returns:
            Document service instance (either Docling or LlamaIndex)
        """
        if self._processor_type == DocumentProcessor.LLAMAINDEX:
            return self._get_llamaindex_service()
        else:
            return self._get_docling_service()

    def _get_llamaindex_service(self) -> DocumentServiceProtocol:
        """Get LlamaIndex document service."""
        from .llamaindex_document_service import get_llamaindex_document_service

        return get_llamaindex_document_service(self.project_id)

    def _get_docling_service(self) -> DocumentServiceProtocol:
        """Get Docling document service (existing implementation)."""
        from ..services.document_processing_service import get_document_processing_service

        return get_document_processing_service(self.project_id)

    @property
    def processor_type(self) -> DocumentProcessor:
        """Get the current processor type."""
        return self._processor_type

    def is_llamaindex(self) -> bool:
        """Check if using LlamaIndex processor."""
        return self._processor_type == DocumentProcessor.LLAMAINDEX

    def is_docling(self) -> bool:
        """Check if using Docling processor."""
        return self._processor_type == DocumentProcessor.DOCLING


# Global factory instance
_document_service_factory: DocumentServiceFactory | None = None


def get_document_service_factory(
    project_id: str | None = None,
) -> DocumentServiceFactory:
    """
    Get a global document service factory instance.

    Args:
        project_id: Google Cloud project ID

    Returns:
        DocumentServiceFactory instance
    """
    global _document_service_factory

    if _document_service_factory is None:
        _document_service_factory = DocumentServiceFactory(project_id=project_id)

    return _document_service_factory


def get_document_service(project_id: str | None = None) -> DocumentServiceProtocol:
    """
    Convenience function to get the configured document service.

    Args:
        project_id: Google Cloud project ID

    Returns:
        Document service instance
    """
    factory = get_document_service_factory(project_id)
    return factory.get_service()


def reset_document_service_factory() -> None:
    """Reset the global factory instance (useful for testing)."""
    global _document_service_factory
    _document_service_factory = None
