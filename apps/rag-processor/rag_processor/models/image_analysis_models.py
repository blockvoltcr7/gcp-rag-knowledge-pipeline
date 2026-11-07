"""
Image analysis models for RAG processor.

Simple models for image analysis with basic error handling.
"""

from enum import Enum

from ..utils.retry_utils import NonRetryableError


class ImageAnalysisError(NonRetryableError):
    """Base exception for image analysis errors."""

    pass


class ImageFormat(str, Enum):
    """Supported image formats for analysis (Google GenAI compatible)."""

    JPEG = "jpeg"
    JPG = "jpg"
    PNG = "png"
    WEBP = "webp"
