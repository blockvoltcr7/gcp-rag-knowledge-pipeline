# Docling Model Management

This document explains how Docling ML models are managed in the RAG processor deployment pipeline.

## Overview

The RAG processor uses [Docling](https://github.com/docling-project/docling) for PDF document processing. Docling requires ML models for:

- **Layout detection** - Identifies document structure (headers, paragraphs, tables)
- **Tableformer** - Extracts table structure from documents
- **Picture classifier** - Classifies images (disabled in our config)
- **Code formula** - Detects code blocks and formulas (disabled in our config)
- **EasyOCR** - Optical character recognition (disabled in our config)

## Model Storage Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        MODEL DEPLOYMENT FLOW                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   1. Download          2. Flatten & Upload      3. Docker Build              │
│   ───────────          ─────────────────────    ─────────────                │
│  ┌────────────┐       ┌────────────────────┐   ┌────────────────┐           │
│  │ HuggingFace│──────▶│ GCS Bucket         │──▶│ Docker Image   │           │
│  │ docling-   │       │ (flattened layout) │   │ /app/models/   │           │
│  │ project    │       │                    │   │ docling/       │           │
│  └────────────┘       └────────────────────┘   └────────────────┘           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### GCS Structure (Required)

The deployment script uploads models to GCS with a **flattened layout structure**:

```
gs://{project-id}-rag-documents-dev/models/docling/
├── config.json                    # Layout model config (at ROOT)
├── model.safetensors              # Layout model weights (at ROOT)
├── preprocessor_config.json       # Layout preprocessor (at ROOT)
└── ds4sd--docling-models/         # Tableformer in subdirectory
    └── model_artifacts/
        └── tableformer/
            ├── accurate/
            │   └── tableformer_accurate.safetensors
            └── fast/
                └── tableformer_fast.safetensors
```

### Docker Image Structure

Models are baked into the Docker image at `/app/models/docling/`:

```
/app/models/docling/
├── config.json                    # Layout model (ROOT)
├── model.safetensors              # Layout model (ROOT)
├── preprocessor_config.json       # Layout model (ROOT)
└── ds4sd--docling-models/         # Tableformer
    └── model_artifacts/tableformer/
```

## Why Flattened Layout Structure?

Docling's `PdfPipelineOptions(artifacts_path=...)` expects layout model files **at the root** of the artifacts path:

```python
# Docling internal path resolution
layout_model_path = artifacts_path / "model.safetensors"  # Looks HERE
tableformer_path = artifacts_path / "ds4sd--docling-models" / "model_artifacts" / "tableformer"
```

The `docling-tools models download` command creates a nested structure:
```
docling-project--docling-layout-heron/
└── model.safetensors              # Docling can't find this!
```

Our deployment script **flattens** this by copying layout files to root.

## The `ds4sd` Prefix

**ds4sd** = "Data Science for Social Good" - IBM's original HuggingFace organization where Docling models were first hosted.

When Docling's code resolves model paths with `artifacts_path` set, it expects:
- `ds4sd--docling-models/` for tableformer models
- Layout files at root (no prefix)

The deployment script renames directories from `docling-project--*` to `ds4sd--*` for backwards compatibility.

## Kaniko Cache and the Cache Buster

### The Problem

Kaniko (our Docker build tool) caches layers based on:
- Dockerfile instructions
- ARG values

It does **NOT** check actual file content in GCS. This means:
1. You upload new models to GCS
2. Kaniko sees same ARGs (bucket name, path)
3. Kaniko serves cached layer with **old** models

### The Solution: Cache Buster ARG

The Dockerfile includes a cache buster ARG:

```dockerfile
# apps/rag-processor/Dockerfile (lines 47-63)

# Model download stage
FROM gcr.io/google.com/cloudsdktool/cloud-sdk:slim AS model-downloader

ARG GCS_BUCKET
ARG GCS_MODEL_PATH="models/docling/"
ARG MODEL_CACHE_BUSTER="v2-flattened-layout"  # <-- Cache buster

WORKDIR /models

# Cache buster is used in the RUN command to invalidate cache
RUN echo "Cache version: ${MODEL_CACHE_BUSTER}" && \
    gcloud storage cp -r "gs://${GCS_BUCKET}/${GCS_MODEL_PATH}" /models/
```

### When to Update Cache Buster

Update `MODEL_CACHE_BUSTER` whenever you:
1. Upload new models to GCS
2. Change model structure in GCS
3. Fix model-related bugs

Simply increment the version:
```dockerfile
ARG MODEL_CACHE_BUSTER="v3-new-version"
```

## Deployment Script Model Handling

The deployment script (`scripts/deploy_rag_processor_core.py`) handles models:

### 1. Download Models

```python
# Download specific models (skip easyocr - not needed with do_ocr=False)
models_to_download = ["layout", "tableformer"]
for model_name in models_to_download:
    subprocess.run([
        "docling-tools", "models", "download", model_name,
        "-o", str(model_dir)
    ])
```

### 2. Flatten Layout Structure

```python
# Copy layout files to root (critical for Docling to find them)
layout_dir = model_dir / "ds4sd--docling-layout-heron"
if layout_dir.exists():
    for file in layout_dir.iterdir():
        shutil.copy2(file, model_dir / file.name)
    shutil.rmtree(layout_dir)
```

### 3. Rename Directories

```python
# Fix directory prefix: docling-project-- → ds4sd--
prefix_fixes = [
    ("docling-project--docling-models", "ds4sd--docling-models"),
]
for old_name, new_name in prefix_fixes:
    old_path = model_dir / old_name
    new_path = model_dir / new_name
    if old_path.exists() and not new_path.exists():
        old_path.rename(new_path)
```

### 4. Upload to GCS

```python
subprocess.run([
    "gcloud", "storage", "cp", "-r",
    str(model_dir) + "/*",
    f"gs://{bucket_name}/models/docling/"
])
```

## Processor Configuration

The RAG processor configures Docling with:

```python
# apps/rag-processor/rag_processor/services/document_processing_service.py

pipeline_options = PdfPipelineOptions(
    artifacts_path="/app/models/docling",  # Points to baked-in models
    do_ocr=False,                          # Skip OCR (no easyocr models)
    do_table_structure=True,               # Use tableformer
    do_code_enrichment=False,              # Skip code formula model
    do_formula_enrichment=False,
    do_picture_classification=False,       # Skip picture classifier
    do_picture_description=False,
)
```

## Troubleshooting

### "Missing safe tensors file" Error

See [05-troubleshooting.md](./05-troubleshooting.md#missing-docling-model--safetensors-error)

### Force Model Re-download

```bash
# 1. Delete models from GCS
gcloud storage rm -r gs://{project-id}-rag-documents-dev/models/docling/

# 2. Clear local cache
rm -rf ~/.cache/docling/models

# 3. Re-run setup (downloads fresh models)
npm run setup:gcp:dev

# 4. Update cache buster in Dockerfile
# Edit apps/rag-processor/Dockerfile
# Change MODEL_CACHE_BUSTER to new value

# 5. Redeploy
npm run deploy:processor:dev
```

### Verify Model Structure in Docker

```bash
# Start a debug container
docker run -it --entrypoint /bin/bash \
  us-central1-docker.pkg.dev/{project}/rag-services/rag-processor-job-dev:latest

# List model files
ls -la /app/models/docling/
# Should show: config.json, model.safetensors, preprocessor_config.json, ds4sd--docling-models/
```

## References

- [Docling GitHub](https://github.com/docling-project/docling)
- [GitHub Discussion #2089 - Manual download of default models](https://github.com/docling-project/docling/discussions/2089)
- [GitHub Issue #2310 - FileNotFoundError for model.safetensors](https://github.com/docling-project/docling/issues/2310)
- [GitHub Discussion #2217 - Offline Support](https://github.com/docling-project/docling/discussions/2217)
- [HuggingFace - docling-project/docling-models](https://huggingface.co/docling-project/docling-models)

---

*Last Updated: 2025-12-10*
