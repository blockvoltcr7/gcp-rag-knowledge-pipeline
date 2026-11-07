# RAG GCP Deployment Runbook

This runbook documents the process for deploying the RAG (Retrieval-Augmented Generation) document processing pipeline to Google Cloud Platform.

## Overview

The RAG pipeline enables creators to upload documents that are automatically processed, chunked, embedded, and stored in pgvector for semantic search during AI conversations.

### Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│  Creator uploads  │────▶│  GCS Bucket      │────▶│  GCS Handler        │
│  document       │     │  (Storage)       │     │  (Cloud Function)   │
└─────────────────┘     └──────────────────┘     └─────────┬───────────┘
                                                          │
                                                          ▼
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│  pgvector       │◀────│  RAG Processor   │◀────│  Task Processor     │
│  (Supabase)     │     │  (Cloud Run Job) │     │  (Cloud Function)   │
└─────────────────┘     └──────────────────┘     └─────────────────────┘
```

## Program-Based Isolation

The RAG pipeline implements **program-based isolation** using a 3-level GCS path structure:

```
documents/{creator_id}/{program_id}/{filename}
```

**Why 3 Levels?**
- **Creator Isolation**: Each creator's documents are separate
- **Program Isolation**: Within a creator, programs have distinct RAG contexts
- **Multi-Tenancy**: Students in Program A don't see Program B's documents

**Database Schema:**
Both `documents` and `document_chunks` tables include `program_id` for filtering:
```sql
CREATE TABLE documents (
    id UUID PRIMARY KEY,
    human_creator_id UUID NOT NULL,
    program_id UUID REFERENCES creator_programs(id),
    ...
);
```

**Migration Note:** The system was upgraded from 2-level paths (creator-only) to 3-level paths (program-based) in migration epic (Phases 1-4, completed January 2026).

### Components

| Component | Type | Purpose |
|-----------|------|---------|
| **GCS Bucket** | Cloud Storage | Stores uploaded documents |
| **GCS Handler** | Cloud Function | Triggered on file upload, enqueues processing task |
| **Task Processor** | Cloud Function | Receives task from Cloud Tasks, triggers Cloud Run Job |
| **RAG Processor** | Cloud Run Job | Processes documents with Docling, generates embeddings |
| **Cloud Tasks** | Queue | Manages async task processing |

## Quick Start

```bash
# From application-monorepo root directory (monorepo)
# Note: Deployment scripts are defined in the monorepo's package.json

# 1. Setup GCP infrastructure (one-time)
npm run setup:gcp:dev

# 2. Deploy services (in order)
npm run deploy:processor:dev      # ~10-15 min
npm run deploy:gcs-handler:dev    # ~2-3 min
npm run deploy:task-processor:dev # ~2-3 min
```

## Runbook Files

### Setup & Deployment
1. [Prerequisites](./01-prerequisites.md) - What you need before starting
2. [GCP Setup](./02-gcp-setup.md) - Infrastructure setup process
3. [Deployment](./03-deployment.md) - Deploying the services
4. [Testing](./04-testing.md) - Verifying the pipeline works
5. [Troubleshooting](./05-troubleshooting.md) - Common issues and solutions

### Deep Dive Documentation
6. [Architecture Deep Dive](./06-architecture-deep-dive.md) - Comprehensive architecture with Mermaid diagrams
7. [Setup Explained](./07-setup-explained.md) - What happens during each setup phase
8. [Deployment Explained](./08-deployment-explained.md) - What happens during each deployment
9. [Data Flow](./09-data-flow.md) - How data flows from upload to embeddings
10. [Docling Model Management](./10-docling-model-management.md) - ML models for PDF processing, cache busting, and troubleshooting

## Environments

| Environment | Command Suffix | Use Case |
|-------------|----------------|----------|
| Development | `:dev` | Local testing, iteration |
| Production | `:prod` | Live production system |

## Key Resources

- **Project ID**: Set in `GOOGLE_CLOUD_PROJECT_ID` env var
- **Region**: `us-central1` (default)
- **Bucket Pattern**: `{project-id}-rag-documents-{env}`
- **Service Pattern**: `rag-{service}-{env}`
