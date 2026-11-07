"""
Configuration Updates for LlamaIndex Integration.

This file shows the additions needed to config.py to support
LlamaIndex document processing.

INSTRUCTIONS:
Add these new configuration options to the Config class in config.py
"""

import os


class Config:
    """
    Configuration settings for the RAG Processor service.

    ADD THESE NEW SETTINGS to the existing Config class:
    """

    # ==========================================================================
    # NEW: LlamaIndex Configuration Settings
    # ==========================================================================

    # Document processor selection: "llamaindex" or "docling"
    DOCUMENT_PROCESSOR: str = os.getenv("DOCUMENT_PROCESSOR", "llamaindex")

    # LlamaIndex chunking settings (defaults match existing Docling settings)
    LLAMAINDEX_CHUNK_SIZE: int = int(os.getenv("LLAMAINDEX_CHUNK_SIZE", "1000"))
    LLAMAINDEX_CHUNK_OVERLAP: int = int(os.getenv("LLAMAINDEX_CHUNK_OVERLAP", "200"))

    # LlamaParse configuration (for high-quality PDF parsing)
    USE_LLAMAPARSE: bool = os.getenv("USE_LLAMAPARSE", "false").lower() == "true"
    LLAMAPARSE_API_KEY: str | None = os.getenv("LLAMAPARSE_API_KEY")

    # LlamaParse tier selection: "fast", "cost_effective", "agentic", "agentic_plus"
    LLAMAPARSE_TIER: str = os.getenv("LLAMAPARSE_TIER", "cost_effective")

    # Feature flags for gradual rollout
    LLAMAINDEX_FALLBACK_ENABLED: bool = (
        os.getenv("LLAMAINDEX_FALLBACK_ENABLED", "true").lower() == "true"
    )

    # ==========================================================================
    # ADD TO validate() method
    # ==========================================================================

    @classmethod
    def validate(cls) -> dict[str, any]:
        """
        Validate the current Config class attributes.

        ADD THESE VALIDATIONS to the existing validate() method:
        """
        # ... existing validations ...

        # NEW: LlamaIndex validations
        if cls.DOCUMENT_PROCESSOR not in ("llamaindex", "docling"):
            warnings.append(
                f"Invalid DOCUMENT_PROCESSOR value: {cls.DOCUMENT_PROCESSOR}. "
                "Using 'llamaindex' as default."
            )

        if cls.USE_LLAMAPARSE and not cls.LLAMAPARSE_API_KEY:
            warnings.append(
                "USE_LLAMAPARSE is enabled but LLAMAPARSE_API_KEY is not set. "
                "Will fall back to basic PDFReader."
            )

        if cls.LLAMAINDEX_CHUNK_SIZE <= 0:
            raise NonRetryableError("LLAMAINDEX_CHUNK_SIZE must be greater than 0")

        if cls.LLAMAINDEX_CHUNK_OVERLAP < 0:
            raise NonRetryableError("LLAMAINDEX_CHUNK_OVERLAP must be non-negative")

        if cls.LLAMAINDEX_CHUNK_OVERLAP >= cls.LLAMAINDEX_CHUNK_SIZE:
            raise NonRetryableError(
                "LLAMAINDEX_CHUNK_OVERLAP must be less than LLAMAINDEX_CHUNK_SIZE"
            )

        valid_tiers = ("fast", "cost_effective", "agentic", "agentic_plus")
        if cls.LLAMAPARSE_TIER not in valid_tiers:
            warnings.append(
                f"Invalid LLAMAPARSE_TIER: {cls.LLAMAPARSE_TIER}. "
                f"Valid options: {valid_tiers}. Using 'cost_effective'."
            )

        # ... rest of existing validations ...

        return {
            # ... existing return values ...
            "llamaindex_config": {
                "processor": cls.DOCUMENT_PROCESSOR,
                "chunk_size": cls.LLAMAINDEX_CHUNK_SIZE,
                "chunk_overlap": cls.LLAMAINDEX_CHUNK_OVERLAP,
                "use_llamaparse": cls.USE_LLAMAPARSE,
                "llamaparse_tier": cls.LLAMAPARSE_TIER,
                "fallback_enabled": cls.LLAMAINDEX_FALLBACK_ENABLED,
            },
        }


# =============================================================================
# ENVIRONMENT VARIABLES REFERENCE
# =============================================================================
"""
Add these to your .env.local or Cloud Run environment:

# Document Processor Selection
DOCUMENT_PROCESSOR=llamaindex          # Options: "llamaindex" or "docling"

# LlamaIndex Chunking Settings
LLAMAINDEX_CHUNK_SIZE=1000             # Chunk size in characters
LLAMAINDEX_CHUNK_OVERLAP=200           # Overlap between chunks

# LlamaParse (Optional - for high-quality PDF parsing)
USE_LLAMAPARSE=false                   # Enable LlamaParse for PDFs
LLAMAPARSE_API_KEY=llx-xxxxx           # API key from cloud.llamaindex.ai
LLAMAPARSE_TIER=cost_effective         # Parsing tier

# Feature Flags
LLAMAINDEX_FALLBACK_ENABLED=true       # Enable fallback to Docling on failure
"""


# =============================================================================
# DOCKERFILE UPDATES
# =============================================================================
"""
Add to Dockerfile if using LlamaParse:

# LlamaIndex dependencies
RUN pip install llama-index-core llama-index-readers-file

# Optional: LlamaParse for high-quality PDF parsing
RUN pip install llama-parse
"""


# =============================================================================
# CLOUD RUN DEPLOYMENT UPDATES
# =============================================================================
"""
Add to your gcloud run deploy command:

gcloud run deploy rag-processor \
  --set-env-vars="DOCUMENT_PROCESSOR=llamaindex" \
  --set-env-vars="LLAMAINDEX_CHUNK_SIZE=1000" \
  --set-env-vars="LLAMAINDEX_CHUNK_OVERLAP=200" \
  --set-env-vars="USE_LLAMAPARSE=true" \
  --set-secrets="LLAMAPARSE_API_KEY=llamaparse-api-key:latest"
"""
