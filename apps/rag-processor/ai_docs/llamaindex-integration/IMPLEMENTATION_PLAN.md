# LlamaIndex Integration - Implementation Plan

## Overview

This document outlines the implementation plan for integrating LlamaIndex into the RAG Processor to replace Docling for document processing (DOCX, MD, PDF files).

---

## 1. Current State Analysis

### Existing Architecture
```
┌─────────┐    ┌─────────────────────────┐    ┌──────────────┐    ┌──────────┐
│  GCS    │───▶│  document_processing    │───▶│  Embedding   │───▶│ Database │
│         │    │  _service.py (Docling)  │    │  Service     │    │ Service  │
└─────────┘    └─────────────────────────┘    └──────────────┘    └──────────┘
```

### Current Issues with Docling
| Issue | Impact | Severity |
|-------|--------|----------|
| DOCX parsing failures | Word documents not processed correctly | High |
| Markdown handling issues | MD files produce poor chunks | High |
| PDF hangs on large files | Processing timeouts, job failures | Critical |
| High memory usage | Requires GPU, expensive Cloud Run instances | Medium |
| Complex dependency tree | Deployment challenges | Medium |

---

## 2. Target Architecture

### Proposed Architecture
```
┌─────────┐    ┌─────────────────────────────────────────┐    ┌──────────────┐
│  GCS    │───▶│  llamaindex_document_service.py        │───▶│  Embedding   │
│         │    │  ├─ DocxReader (DOCX)                  │    │  Service     │
└─────────┘    │  ├─ MarkdownReader (MD)                │    │  (unchanged) │
               │  ├─ LlamaParse/PDFReader (PDF)         │    └──────────────┘
               │  └─ Node Parser (chunking)             │
               └─────────────────────────────────────────┘
```

### File Type Routing
| Extension | Current Handler | New Handler | Fallback |
|-----------|-----------------|-------------|----------|
| `.docx` | Docling | `DocxReader` | None |
| `.md` | Docling | `MarkdownReader` | None |
| `.pdf` | Docling | `LlamaParse` | `PDFReader` |
| `.txt` | Docling | `SimpleDirectoryReader` | None |
| `.html` | Docling | `HTMLReader` | None |
| `.xlsx` | Docling | Keep Docling (optional) | `PandasExcelReader` |
| `.pptx` | Docling | Keep Docling (optional) | `PptxReader` |

---

## 3. Implementation Phases

### Phase 1: Setup & Infrastructure (Day 1-2)
- [ ] Add LlamaIndex dependencies to `pyproject.toml`
- [ ] Create `llamaindex_document_service.py`
- [ ] Add configuration for LlamaParse API key
- [ ] Update environment variables

### Phase 2: Core Implementation (Day 3-5)
- [ ] Implement `LlamaIndexDocumentService` class
- [ ] Create file reader factory pattern
- [ ] Implement async document loading
- [ ] Add chunking with `SentenceSplitter`
- [ ] Create chunk-to-embedding pipeline

### Phase 3: Integration (Day 6-7)
- [ ] Update `processing_service.py` to use new service
- [ ] Modify content router for document delegation
- [ ] Add feature flag for gradual rollout
- [ ] Update database service for new metadata format

### Phase 4: Testing & Validation (Day 8-10)
- [ ] Unit tests for each reader
- [ ] Integration tests with sample documents
- [ ] Performance benchmarking vs Docling
- [ ] Error handling validation

### Phase 5: Deployment & Monitoring (Day 11-12)
- [ ] Deploy to staging environment
- [ ] A/B testing with feature flag
- [ ] Monitor error rates and processing times
- [ ] Full rollout

---

## 4. Dependencies

### New Dependencies
```toml
# Add to pyproject.toml [project.dependencies]
"llama-index-core>=0.14.0",
"llama-index-readers-file>=0.4.0",
"llama-parse>=0.6.0",  # Optional: for complex PDFs
"llama-index-embeddings-vertex>=0.3.0",  # Optional: if using LlamaIndex embeddings
```

### Environment Variables
```bash
# New environment variables
LLAMAPARSE_API_KEY=llx-...          # Required for LlamaParse
USE_LLAMAPARSE=true                  # Feature flag
LLAMAINDEX_CHUNK_SIZE=1000          # Chunk size (default: 1000)
LLAMAINDEX_CHUNK_OVERLAP=200        # Chunk overlap (default: 200)
DOCUMENT_PROCESSOR=llamaindex       # Switch: "llamaindex" or "docling"
```

---

## 5. File Structure

```
rag_processor/
├── services/
│   ├── document_processing_service.py    # Existing (keep as fallback)
│   ├── llamaindex_document_service.py    # NEW: LlamaIndex implementation
│   ├── document_service_factory.py       # NEW: Factory for choosing processor
│   └── ...
├── utils/
│   ├── content_router.py                 # Update: route to correct processor
│   └── ...
└── config.py                             # Update: add new config options
```

---

## 6. Rollback Plan

### If Issues Occur
1. Set `DOCUMENT_PROCESSOR=docling` environment variable
2. Redeploy Cloud Run service
3. All document processing reverts to Docling

### Feature Flag Strategy
```python
# In config.py
DOCUMENT_PROCESSOR: str = os.getenv("DOCUMENT_PROCESSOR", "llamaindex")

# In processing_service.py
if config.DOCUMENT_PROCESSOR == "llamaindex":
    service = get_llamaindex_document_service()
else:
    service = get_document_processing_service()  # Docling fallback
```

---

## 7. Success Metrics

| Metric | Current (Docling) | Target (LlamaIndex) |
|--------|-------------------|---------------------|
| DOCX success rate | ~70% | >95% |
| MD success rate | ~60% | >98% |
| PDF success rate | ~80% | >95% |
| Avg processing time | 15-30s | <10s |
| Memory usage | 4-8GB | 1-2GB |
| Error rate | ~15% | <3% |

---

## 8. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| LlamaParse API downtime | Low | High | Fallback to PDFReader |
| Different chunk quality | Medium | Medium | A/B testing, tune parameters |
| Missing features | Low | Low | Keep Docling as fallback |
| Cost increase (LlamaParse) | Medium | Low | Monitor usage, set limits |

---

## 9. Timeline

```
Week 1:
├── Day 1-2: Setup & dependencies
├── Day 3-4: Core service implementation
└── Day 5: Integration with processing_service

Week 2:
├── Day 6-7: Testing & validation
├── Day 8-9: Staging deployment & A/B testing
└── Day 10: Production rollout
```

---

## 10. Contacts

| Role | Responsibility |
|------|----------------|
| Developer | Implementation, testing |
| DevOps | Deployment, monitoring |
| QA | Validation, benchmarking |
| Product | Sign-off, success criteria |
