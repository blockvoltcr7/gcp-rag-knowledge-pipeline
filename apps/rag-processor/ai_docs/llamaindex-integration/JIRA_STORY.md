# Jira Story: LlamaIndex Document Processing Integration

---

## Epic

**RAG Processor - Document Processing Improvements**

---

## Story

### Title
Integrate LlamaIndex to Replace Docling for Document Processing (DOCX, MD, PDF)

### Story ID
`RAG-XXX` _(assign appropriate ID)_

### Type
Story

### Priority
High

### Labels
`document-processing`, `llamaindex`, `performance`, `reliability`

---

## Description

### Summary
Replace Docling document processing with LlamaIndex for improved reliability and performance when processing Word documents (.docx), Markdown files (.md), and PDF files. The current Docling implementation has known issues with these file types causing processing failures and poor chunk quality.

### Background
Our RAG processor currently uses Docling for all document processing. We've experienced the following issues:

| File Type | Issue | Impact |
|-----------|-------|--------|
| DOCX | Parsing failures, incorrect text extraction | ~30% failure rate |
| Markdown | Poor chunk quality, header handling issues | ~40% failure rate |
| PDF | Hangs on large files, memory issues | Critical timeouts |

### Proposed Solution
Integrate LlamaIndex document readers as the primary document processor:
- `DocxReader` for Word documents
- `MarkdownReader` for Markdown files
- `LlamaParse` or `PDFReader` for PDF files

Use a factory pattern to enable gradual rollout and easy rollback.

---

## User Story

**As a** content creator using the RAG system,
**I want** my Word documents, Markdown files, and PDFs to be processed reliably,
**So that** I can search and retrieve information from all my uploaded content without failures.

---

## Acceptance Criteria

### Functional Requirements

- [ ] **AC1:** DOCX files process successfully with >95% success rate
- [ ] **AC2:** Markdown files process with proper header structure preservation
- [ ] **AC3:** PDF files process without timeout for files up to 500 pages
- [ ] **AC4:** Chunk metadata includes page numbers (where applicable)
- [ ] **AC5:** Existing embedding pipeline works with new processor
- [ ] **AC6:** Feature flag allows switching between LlamaIndex and Docling

### Non-Functional Requirements

- [ ] **AC7:** Processing time ≤10 seconds for typical documents (<50 pages)
- [ ] **AC8:** Memory usage ≤2GB during processing
- [ ] **AC9:** Error messages are clear and actionable
- [ ] **AC10:** Logging provides visibility into processing steps

### Testing Requirements

- [ ] **AC11:** Unit tests cover all file readers
- [ ] **AC12:** Integration tests validate end-to-end processing
- [ ] **AC13:** Performance benchmarks compare to Docling baseline

---

## Technical Details

### Architecture Changes

```
Before:
┌─────────┐    ┌─────────┐    ┌──────────┐
│  File   │───▶│ Docling │───▶│ Embedder │
└─────────┘    └─────────┘    └──────────┘

After:
┌─────────┐    ┌─────────────────────┐    ┌──────────┐
│  File   │───▶│ Document Service    │───▶│ Embedder │
└─────────┘    │ Factory             │    └──────────┘
               │ ├─ LlamaIndex       │
               │ └─ Docling (backup) │
               └─────────────────────┘
```

### New Files
| File | Purpose |
|------|---------|
| `llamaindex_document_service.py` | LlamaIndex document processing |
| `document_service_factory.py` | Processor selection factory |
| `test_llamaindex_document_service.py` | Unit tests |

### Modified Files
| File | Changes |
|------|---------|
| `processing_service.py` | Use factory for document processing |
| `config.py` | Add LlamaIndex configuration options |
| `pyproject.toml` | Add LlamaIndex dependencies |

### Dependencies
```toml
llama-index-core>=0.14.0
llama-index-readers-file>=0.4.0
llama-parse>=0.6.0  # Optional
```

### Environment Variables
| Variable | Description | Default |
|----------|-------------|---------|
| `DOCUMENT_PROCESSOR` | Processor selection | `llamaindex` |
| `USE_LLAMAPARSE` | Enable LlamaParse for PDFs | `false` |
| `LLAMAPARSE_API_KEY` | LlamaParse API key | - |
| `LLAMAINDEX_CHUNK_SIZE` | Chunk size | `1000` |
| `LLAMAINDEX_CHUNK_OVERLAP` | Chunk overlap | `200` |

---

## Subtasks

### Development

- [ ] **RAG-XXX-1:** Add LlamaIndex dependencies to pyproject.toml
  - Estimate: 0.5 day
  - Assignee: Developer

- [ ] **RAG-XXX-2:** Implement LlamaIndexDocumentService class
  - Estimate: 2 days
  - Assignee: Developer

- [ ] **RAG-XXX-3:** Implement DocumentServiceFactory
  - Estimate: 0.5 day
  - Assignee: Developer

- [ ] **RAG-XXX-4:** Update processing_service.py integration
  - Estimate: 1 day
  - Assignee: Developer

- [ ] **RAG-XXX-5:** Add configuration options to config.py
  - Estimate: 0.5 day
  - Assignee: Developer

### Testing

- [ ] **RAG-XXX-6:** Write unit tests for LlamaIndex service
  - Estimate: 1 day
  - Assignee: Developer

- [ ] **RAG-XXX-7:** Write integration tests
  - Estimate: 1 day
  - Assignee: QA

- [ ] **RAG-XXX-8:** Performance benchmarking vs Docling
  - Estimate: 0.5 day
  - Assignee: QA

### Deployment

- [ ] **RAG-XXX-9:** Deploy to staging environment
  - Estimate: 0.5 day
  - Assignee: DevOps

- [ ] **RAG-XXX-10:** A/B testing with feature flag
  - Estimate: 2 days
  - Assignee: DevOps/QA

- [ ] **RAG-XXX-11:** Production rollout
  - Estimate: 0.5 day
  - Assignee: DevOps

### Documentation

- [ ] **RAG-XXX-12:** Update technical documentation
  - Estimate: 0.5 day
  - Assignee: Developer

---

## Estimation

| Phase | Effort |
|-------|--------|
| Development | 5 days |
| Testing | 2.5 days |
| Deployment | 3 days |
| Documentation | 0.5 day |
| **Total** | **11 days** |

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| LlamaParse API downtime | Low | High | Fallback to PDFReader |
| Different chunk quality | Medium | Medium | A/B testing, parameter tuning |
| Regression in existing features | Low | High | Comprehensive test suite |
| Cost increase (LlamaParse) | Medium | Low | Monitor usage, set quotas |

---

## Definition of Done

- [ ] All acceptance criteria met
- [ ] Code reviewed and approved
- [ ] Unit tests passing (>90% coverage)
- [ ] Integration tests passing
- [ ] Performance benchmarks meet targets
- [ ] Deployed to production
- [ ] Monitoring dashboards updated
- [ ] Documentation updated
- [ ] Rollback plan verified

---

## Related Documents

- [Implementation Plan](./IMPLEMENTATION_PLAN.md)
- [LlamaIndex Research Report](../llamaindex-research-report.md)
- [Code Changes](./code/)

---

## Sprint Assignment

**Sprint:** _TBD_
**Story Points:** 13

---

## Comments / Notes

### Technical Notes
1. LlamaIndex supports Python 3.9-3.13, compatible with our 3.10-3.12 requirement
2. LlamaParse free tier: 1,000 pages/day, paid: $0.003/page
3. Feature flag allows instant rollback if issues occur

### Open Questions
1. Should we migrate embeddings to LlamaIndex too, or keep Gemini?
   - **Decision:** Keep Gemini embeddings (already optimized)

2. Should we keep Docling for XLSX/PPTX processing?
   - **Decision:** Yes, start with DOCX/MD/PDF only

3. LlamaParse vs PDFReader for PDFs?
   - **Decision:** Use PDFReader by default, LlamaParse opt-in for complex docs

---

## Attachments

- [ ] Architecture diagrams
- [ ] Performance benchmark results (post-implementation)
- [ ] Test coverage report (post-implementation)
