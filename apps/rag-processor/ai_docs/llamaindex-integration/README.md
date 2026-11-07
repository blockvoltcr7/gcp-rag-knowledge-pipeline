# LlamaIndex Integration for RAG Processor

This folder contains the implementation plan, code changes, and Jira story for integrating LlamaIndex document processing into the RAG Processor.

## Overview

Replace Docling with LlamaIndex for processing:
- **Word Documents** (.docx) → `DocxReader`
- **Markdown Files** (.md) → `MarkdownReader`
- **PDF Files** (.pdf) → `LlamaParse` / `PDFReader`

## Folder Structure

```
ai_docs/llamaindex-integration/
├── README.md                    # This file
├── IMPLEMENTATION_PLAN.md       # Detailed implementation phases
├── JIRA_STORY.md               # Jira story with subtasks
└── code/
    ├── llamaindex_document_service.py      # Main service implementation
    ├── document_service_factory.py         # Factory for processor selection
    ├── processing_service_changes.py       # Changes to processing_service.py
    ├── config_updates.py                   # Configuration additions
    ├── pyproject_additions.toml            # Dependency additions
    └── test_llamaindex_document_service.py # Unit tests
```

## Quick Start

### 1. Add Dependencies

```bash
# Add to pyproject.toml and install
uv add llama-index-core llama-index-readers-file

# Optional: For high-quality PDF parsing
uv add llama-parse
```

### 2. Copy Code Files

Copy files from `code/` to your `rag_processor/services/` directory:

```bash
cp code/llamaindex_document_service.py ../rag_processor/services/
cp code/document_service_factory.py ../rag_processor/services/
```

### 3. Update Configuration

Add to `.env.local`:

```bash
DOCUMENT_PROCESSOR=llamaindex
LLAMAINDEX_CHUNK_SIZE=1000
LLAMAINDEX_CHUNK_OVERLAP=200

# Optional: For LlamaParse
USE_LLAMAPARSE=false
LLAMAPARSE_API_KEY=llx-xxxxx
```

### 4. Modify processing_service.py

See `code/processing_service_changes.py` for required modifications.

### 5. Run Tests

```bash
pytest code/test_llamaindex_document_service.py -v
```

## Rollback

To revert to Docling, simply change the environment variable:

```bash
DOCUMENT_PROCESSOR=docling
```

## Documents

| Document | Description |
|----------|-------------|
| [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md) | Phased implementation approach |
| [JIRA_STORY.md](./JIRA_STORY.md) | Jira story with acceptance criteria |

## Architecture

### Before (Docling)
```
File → Docling → Chunker → Embedder → Database
```

### After (LlamaIndex)
```
File → Factory → LlamaIndex Readers → Node Parser → Embedder → Database
         │
         └── Docling (fallback)
```

## Contact

For questions, contact the RAG Processor team.
