# syntax=docker/dockerfile:1.7
# RAG Processor with baked-in standard Docling models
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim@sha256:333a8eff67ba7b71a649c20a7363ee1191d22cd003e9658e043b4c0a48060bda AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    curl \
    ffmpeg=7:5.1.* \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean \
    && rm -rf /tmp/* /var/tmp/*

WORKDIR /app

# Configure uv for Docker
ENV UV_COMPILE_BYTECODE=0 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_HTTP_TIMEOUT=600 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_NO_CACHE=1

# Copy dependency files
COPY uv.lock pyproject.toml ./

# Copy Python package first
COPY rag_processor/ ./rag_processor/

# Create venv and install everything in one step
RUN uv venv /app/.venv && \
    uv sync --locked --no-dev --group ml && \
    find /app/.venv -name "*.pyc" -delete && \
    find /app/.venv -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# Model download stage
FROM gcr.io/google.com/cloudsdktool/cloud-sdk:slim AS model-downloader

# Build arguments
ARG GCS_BUCKET
ARG GCS_MODEL_PATH="models/docling/"
# Cache buster - change this value to force model re-download when GCS content changes
ARG MODEL_CACHE_BUSTER="v2-flattened-layout"

WORKDIR /models

# Download model from GCS (MODEL_CACHE_BUSTER invalidates cache when GCS content changes)
RUN if [ -z "${GCS_BUCKET}" ]; then \
    echo "ERROR: GCS_BUCKET build argument is required" && exit 1; \
    fi && \
    echo "Cache version: ${MODEL_CACHE_BUSTER}" && \
    echo "Downloading model from gs://${GCS_BUCKET}/${GCS_MODEL_PATH}" && \
    gcloud storage cp -r "gs://${GCS_BUCKET}/${GCS_MODEL_PATH}" /models/ && \
    echo "Model download complete" && \
    ls -la /models/

# Runtime stage
FROM python:3.11-slim-bookworm@sha256:838ff46ae6c481e85e369706fa3dea5166953824124735639f3c9f52af85f319

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean \
    && rm -rf /tmp/* /var/tmp/*

# Create non-root user
RUN addgroup --system --gid 1001 appuser && \
    adduser --system --uid 1001 --ingroup appuser --home /app --no-create-home appuser

WORKDIR /app

# Copy Python environment and code from builder
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --from=builder --chown=appuser:appuser /app/rag_processor /app/rag_processor
COPY --from=builder --chown=appuser:appuser /app/pyproject.toml /app/pyproject.toml

# Copy pre-downloaded model
COPY --from=model-downloader --chown=appuser:appuser /models/docling /app/models/docling

USER appuser

ENV PORT=8080 \
    HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    DOCLING_ARTIFACTS_PATH="/app/models/docling"

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

EXPOSE 8080

CMD ["python", "-m", "rag_processor.main"]
