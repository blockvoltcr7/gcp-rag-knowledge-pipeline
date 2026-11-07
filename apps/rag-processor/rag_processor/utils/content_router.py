"""
Content type router for determining file types and processing pipelines.

Handles file type detection based on extensions and MIME types,
and routes files to appropriate processing pipelines.
"""

import mimetypes
from pathlib import Path

import structlog

from ..models.metadata_models import ContentTypes

logger = structlog.get_logger(__name__)


class ContentTypeRouter:
    """
    Router for determining content type and appropriate processing pipeline.
    """

    # File extension mappings to content types
    EXTENSION_MAPPING = {
        # Video files
        ".mp4": ContentTypes.VIDEO,
        ".avi": ContentTypes.VIDEO,
        ".mov": ContentTypes.VIDEO,
        ".mkv": ContentTypes.VIDEO,
        ".webm": ContentTypes.VIDEO,
        ".flv": ContentTypes.VIDEO,
        ".m4v": ContentTypes.VIDEO,
        ".wmv": ContentTypes.VIDEO,
        ".mpg": ContentTypes.VIDEO,
        ".mpeg": ContentTypes.VIDEO,
        ".3gp": ContentTypes.VIDEO,
        ".ogv": ContentTypes.VIDEO,
        # Audio files
        ".mp3": ContentTypes.AUDIO,
        ".wav": ContentTypes.AUDIO,
        ".flac": ContentTypes.AUDIO,
        ".aac": ContentTypes.AUDIO,
        ".ogg": ContentTypes.AUDIO,
        ".wma": ContentTypes.AUDIO,
        ".m4a": ContentTypes.AUDIO,
        ".opus": ContentTypes.AUDIO,
        ".aiff": ContentTypes.AUDIO,
        ".au": ContentTypes.AUDIO,
        # Image files (only formats supported by Google GenAI)
        ".jpg": ContentTypes.IMAGE,
        ".jpeg": ContentTypes.IMAGE,
        ".png": ContentTypes.IMAGE,
        ".webp": ContentTypes.IMAGE,
        ".svg": ContentTypes.IMAGE,
        ".heic": ContentTypes.IMAGE,
        ".heif": ContentTypes.IMAGE,
        # Document files (only formats supported by Docling)
        ".pdf": ContentTypes.DOCUMENT,
        ".docx": ContentTypes.DOCUMENT,
        ".xlsx": ContentTypes.DOCUMENT,
        ".pptx": ContentTypes.DOCUMENT,
        ".txt": ContentTypes.DOCUMENT,
        ".md": ContentTypes.DOCUMENT,
        ".html": ContentTypes.DOCUMENT,
        ".htm": ContentTypes.DOCUMENT,
        ".xml": ContentTypes.DOCUMENT,
        ".csv": ContentTypes.DOCUMENT,
        ".rtf": ContentTypes.DOCUMENT,
        ".odt": ContentTypes.DOCUMENT,
        ".ods": ContentTypes.DOCUMENT,
        ".odp": ContentTypes.DOCUMENT,
    }

    # MIME type mappings to content types
    MIME_TYPE_MAPPING = {
        # Video MIME types
        "video/mp4": ContentTypes.VIDEO,
        "video/avi": ContentTypes.VIDEO,
        "video/quicktime": ContentTypes.VIDEO,
        "video/x-msvideo": ContentTypes.VIDEO,
        "video/webm": ContentTypes.VIDEO,
        "video/x-flv": ContentTypes.VIDEO,
        "video/x-ms-wmv": ContentTypes.VIDEO,
        "video/mpeg": ContentTypes.VIDEO,
        "video/3gpp": ContentTypes.VIDEO,
        # Audio MIME types
        "audio/mpeg": ContentTypes.AUDIO,
        "audio/wav": ContentTypes.AUDIO,
        "audio/x-wav": ContentTypes.AUDIO,
        "audio/flac": ContentTypes.AUDIO,
        "audio/aac": ContentTypes.AUDIO,
        "audio/ogg": ContentTypes.AUDIO,
        "audio/x-ms-wma": ContentTypes.AUDIO,
        "audio/mp4": ContentTypes.AUDIO,
        "audio/x-m4a": ContentTypes.AUDIO,
        "audio/opus": ContentTypes.AUDIO,
        "audio/aiff": ContentTypes.AUDIO,
        # Image MIME types (only formats supported by Google GenAI)
        "image/jpeg": ContentTypes.IMAGE,
        "image/png": ContentTypes.IMAGE,
        "image/webp": ContentTypes.IMAGE,
        "image/svg+xml": ContentTypes.IMAGE,
        "image/heic": ContentTypes.IMAGE,
        "image/heif": ContentTypes.IMAGE,
        # Document MIME types (only formats supported by Docling)
        "application/pdf": ContentTypes.DOCUMENT,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ContentTypes.DOCUMENT,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ContentTypes.DOCUMENT,
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ContentTypes.DOCUMENT,
        "text/plain": ContentTypes.DOCUMENT,
        "text/markdown": ContentTypes.DOCUMENT,
        "text/html": ContentTypes.DOCUMENT,
        "application/xml": ContentTypes.DOCUMENT,
        "text/xml": ContentTypes.DOCUMENT,
        "text/csv": ContentTypes.DOCUMENT,
        "application/rtf": ContentTypes.DOCUMENT,
        "application/vnd.oasis.opendocument.text": ContentTypes.DOCUMENT,
        "application/vnd.oasis.opendocument.spreadsheet": ContentTypes.DOCUMENT,
        "application/vnd.oasis.opendocument.presentation": ContentTypes.DOCUMENT,
    }

    def __init__(self) -> None:
        """Initialize the content type router."""
        logger.info("Content type router initialized")

    def detect_content_type(self, file_path: str, mime_type: str | None = None) -> str:
        """
        Detect content type from file path and optional MIME type.

        Args:
            file_path: Path to the file
            mime_type: Optional MIME type hint

        Returns:
            Content type string (video, audio, image, document)

        Raises:
            ValueError: If content type cannot be determined
        """
        path = Path(file_path)
        extension = path.suffix.lower()

        logger.debug(
            "Detecting content type",
            file_path=file_path,
            extension=extension,
            mime_type=mime_type,
        )

        # Try extension-based detection first
        if extension in self.EXTENSION_MAPPING:
            content_type = self.EXTENSION_MAPPING[extension]
            logger.debug(
                "Content type detected from extension",
                file_path=file_path,
                extension=extension,
                content_type=content_type,
            )
            return content_type

        # Try MIME type-based detection
        if mime_type and mime_type in self.MIME_TYPE_MAPPING:
            content_type = self.MIME_TYPE_MAPPING[mime_type]
            logger.debug(
                "Content type detected from MIME type",
                file_path=file_path,
                mime_type=mime_type,
                content_type=content_type,
            )
            return content_type

        # Try to guess MIME type from file extension
        if not mime_type:
            guessed_mime_type, _ = mimetypes.guess_type(file_path)
            if guessed_mime_type and guessed_mime_type in self.MIME_TYPE_MAPPING:
                content_type = self.MIME_TYPE_MAPPING[guessed_mime_type]
                logger.debug(
                    "Content type detected from guessed MIME type",
                    file_path=file_path,
                    guessed_mime_type=guessed_mime_type,
                    content_type=content_type,
                )
                return content_type

        # Content type could not be determined
        logger.error(
            "Unable to determine content type",
            file_path=file_path,
            extension=extension,
            mime_type=mime_type,
        )
        raise ValueError(
            f"Unsupported file type: {file_path} (extension: {extension}, MIME: {mime_type})"
        )

    def is_supported(self, file_path: str, mime_type: str | None = None) -> bool:
        """
        Check if a file type is supported for processing.

        Args:
            file_path: Path to the file
            mime_type: Optional MIME type hint

        Returns:
            True if file type is supported, False otherwise
        """
        try:
            content_type = self.detect_content_type(file_path, mime_type)
            # If we can detect a content type, it's supported
            return content_type in ("video", "audio", "image", "document")
        except ValueError:
            return False

    def get_supported_extensions(self) -> dict[str, list[str]]:
        """
        Get a dictionary of supported file extensions by content type.

        Returns:
            Dictionary mapping content types to lists of supported extensions
        """
        supported: dict[str, list[str]] = {}

        for extension, content_type in self.EXTENSION_MAPPING.items():
            if content_type not in supported:
                supported[content_type] = []
            supported[content_type].append(extension)

        return supported

    def get_mime_type_for_extension(self, file_path: str) -> str | None:
        """
        Get the appropriate MIME type for a file based on its extension.

        Args:
            file_path: Path to the file

        Returns:
            MIME type string if found, None otherwise
        """
        path = Path(file_path)
        extension = path.suffix.lower()

        # Extension to MIME type mapping for common file types
        extension_to_mime = {
            # Audio files
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".m4a": "audio/x-m4a",  # M4A audio format
            ".aac": "audio/aac",
            ".ogg": "audio/ogg",
            ".flac": "audio/flac",
            ".wma": "audio/x-ms-wma",
            ".opus": "audio/opus",
            ".aiff": "audio/aiff",
            ".au": "audio/basic",
            # Video files
            ".mp4": "video/mp4",
            ".avi": "video/x-msvideo",
            ".mov": "video/quicktime",
            ".mkv": "video/x-matroska",
            ".webm": "video/webm",
            ".flv": "video/x-flv",
            ".wmv": "video/x-ms-wmv",
            ".mpg": "video/mpeg",
            ".mpeg": "video/mpeg",
            ".3gp": "video/3gpp",
            # Image files (only formats supported by Google GenAI)
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
            ".heic": "image/heic",
            ".heif": "image/heif",
        }

        return extension_to_mime.get(extension)


# Global router instance
_content_router: ContentTypeRouter | None = None


def get_content_router() -> ContentTypeRouter:
    """
    Get a global content type router instance.

    Returns:
        Content type router instance
    """
    global _content_router

    if _content_router is None:
        _content_router = ContentTypeRouter()

    return _content_router


def detect_file_type(file_path: str, mime_type: str | None = None) -> str:
    """
    Convenience function to detect content type of a file.

    Args:
        file_path: Path to the file
        mime_type: Optional MIME type hint

    Returns:
        Content type string
    """
    router = get_content_router()
    return router.detect_content_type(file_path, mime_type)


def is_file_supported(file_path: str, mime_type: str | None = None) -> bool:
    """
    Convenience function to check if a file type is supported.

    Args:
        file_path: Path to the file
        mime_type: Optional MIME type hint

    Returns:
        True if supported, False otherwise
    """
    router = get_content_router()
    return router.is_supported(file_path, mime_type)
