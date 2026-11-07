"""
Token counting and text chunking utilities for embedding services.

Provides shared tokenizer functionality and text chunking for token-aware processing.
Ensures all text embeddings stay within model token limits (2047 tokens for gemini-embedding-001).
"""

from collections.abc import Callable

import structlog
from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer
from google.genai import Client

logger = structlog.get_logger(__name__)


class GoogleTokenizer(BaseTokenizer):
    """Tokenizer wrapper for Google's embedding service that implements BaseTokenizer interface."""

    def __init__(
        self,
        genai_client: Client,
        text_model: str = "gemini-2.5-flash",
        max_tokens: int = 2047,
    ) -> None:
        # Call parent class constructor if it has one
        super().__init__()

        # Store client and configuration as private attributes to avoid field conflicts
        self._genai_client = genai_client
        self._text_model = text_model
        self._max_tokens = max_tokens

    def count_tokens(self, text: str) -> int:
        """Count tokens using Google GenAI client directly."""
        if not text.strip():
            return 0

        try:
            # Use Google GenAI client directly for token counting
            response = self._genai_client.models.count_tokens(
                model=self._text_model,
                contents=text,
            )

            if response.total_tokens is not None:
                token_count: int = response.total_tokens
                return token_count
            else:
                # Fallback to character-based estimation
                return len(text) // 4  # Conservative estimate: 4 chars per token

        except Exception as e:
            error_msg = str(e).lower()
            if "400" in error_msg or "bad request" in error_msg:
                # Content error - text contains invalid characters
                logger.warning(
                    "Token counting failed due to content validation error",
                    error=str(e)[:200],  # Limit error message length
                    text_length=len(text),
                    text_preview=text[:100] if text else "",
                )
                # Conservative estimate that prevents loops and ensures under token limits
                conservative_estimate = min(len(text) // 6, self._max_tokens - 1)
                return max(conservative_estimate, 1)  # Ensure at least 1 token
            else:
                # Network or other error - use normal fallback
                logger.debug(
                    "Token counting failed due to network/API error",
                    error=str(e)[:100],
                    text_length=len(text),
                )
                return len(text) // 4  # Conservative estimate: 4 chars per token

    def get_max_tokens(self) -> int:
        """Get maximum token limit."""
        return self._max_tokens

    def get_tokenizer(self) -> Callable[[str], int]:
        """Return callable tokenizer function for use with semchunk."""
        return self.count_tokens


def chunk_text_by_tokens(
    text: str, tokenizer: GoogleTokenizer, max_tokens: int = 2047
) -> list[str]:
    """
    Split text into chunks that fit within token limits.

    Args:
        text: Text to chunk
        tokenizer: GoogleTokenizer instance for token counting
        max_tokens: Maximum tokens per chunk (default: 2047 for gemini-embedding-001)

    Returns:
        List of text chunks, each within token limit

    Raises:
        ValueError: If max_tokens is invalid
    """
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")

    if not text.strip():
        return []

    # Check if text is already within limit
    total_tokens = tokenizer.count_tokens(text)
    if total_tokens <= max_tokens:
        return [text]

    logger.info(
        "Chunking text for token limits",
        total_tokens=total_tokens,
        max_tokens=max_tokens,
        text_length=len(text),
    )

    # Split text into chunks based on token counting
    chunks: list[str] = []
    words = text.split()
    current_chunk_words: list[str] = []

    for word in words:
        # Try adding this word to current chunk
        test_chunk = " ".join(current_chunk_words + [word])
        test_tokens = tokenizer.count_tokens(test_chunk)

        if test_tokens <= max_tokens:
            # Word fits, add it to current chunk
            current_chunk_words.append(word)
        else:
            # Word doesn't fit, save current chunk and start new one
            if current_chunk_words:
                chunks.append(" ".join(current_chunk_words))
                current_chunk_words = []

            # Handle case where single word exceeds token limit
            word_tokens = tokenizer.count_tokens(word)
            if word_tokens > max_tokens:
                # Split word by characters if it's too long
                char_chunks = _chunk_long_word(word, tokenizer, max_tokens)
                chunks.extend(char_chunks)
            else:
                current_chunk_words = [word]

    # Add final chunk if there are remaining words
    if current_chunk_words:
        chunks.append(" ".join(current_chunk_words))

    logger.info(
        "Text chunking completed",
        original_tokens=total_tokens,
        num_chunks=len(chunks),
        chunk_tokens=[tokenizer.count_tokens(chunk) for chunk in chunks],
    )

    return chunks


def _chunk_long_word(
    word: str, tokenizer: GoogleTokenizer, max_tokens: int
) -> list[str]:
    """
    Split a single word that exceeds token limits by characters.

    Args:
        word: Word to split
        tokenizer: GoogleTokenizer instance
        max_tokens: Maximum tokens per chunk

    Returns:
        List of character-based chunks of the word
    """
    if tokenizer.count_tokens(word) <= max_tokens:
        return [word]

    chunks: list[str] = []
    chars = list(word)
    current_chunk_chars: list[str] = []

    for char in chars:
        test_chunk = "".join(current_chunk_chars + [char])
        if tokenizer.count_tokens(test_chunk) <= max_tokens:
            current_chunk_chars.append(char)
        else:
            if current_chunk_chars:
                chunks.append("".join(current_chunk_chars))
                current_chunk_chars = []
            current_chunk_chars = [char]

    if current_chunk_chars:
        chunks.append("".join(current_chunk_chars))

    return chunks


def truncate_text_to_tokens(
    text: str, tokenizer: GoogleTokenizer, max_tokens: int = 2047
) -> str:
    """
    Truncate text to fit within token limits (simple approach).

    Args:
        text: Text to truncate
        tokenizer: GoogleTokenizer instance for token counting
        max_tokens: Maximum tokens allowed (default: 2047 for gemini-embedding-001)

    Returns:
        Truncated text that fits within token limit

    Raises:
        ValueError: If max_tokens is invalid
    """
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")

    if not text.strip():
        return text

    # Check if text is already within limit
    if tokenizer.count_tokens(text) <= max_tokens:
        return text

    logger.info(
        "Truncating text for token limits",
        original_tokens=tokenizer.count_tokens(text),
        max_tokens=max_tokens,
        original_length=len(text),
    )

    # Simple truncation by words to stay under token limit
    words = text.split()
    truncated_words: list[str] = []

    for word in words:
        # Try adding this word
        test_text = " ".join(truncated_words + [word])
        if tokenizer.count_tokens(test_text) <= max_tokens:
            truncated_words.append(word)
        else:
            # Adding this word would exceed limit, stop here
            break

    truncated_text = " ".join(truncated_words)

    logger.info(
        "Text truncation completed",
        original_tokens=tokenizer.count_tokens(text),
        truncated_tokens=tokenizer.count_tokens(truncated_text),
        original_length=len(text),
        truncated_length=len(truncated_text),
    )

    return truncated_text


def create_google_tokenizer(genai_client: Client) -> GoogleTokenizer:
    """
    Create a GoogleTokenizer instance with standard configuration.

    Args:
        genai_client: Google GenAI client

    Returns:
        Configured GoogleTokenizer instance
    """
    return GoogleTokenizer(
        genai_client=genai_client,
        text_model="gemini-2.5-flash",
        max_tokens=2047,
    )
