# GCP Setup Explained

This document explains what happens during each phase of `npm run setup:gcp:dev`.

## Setup Flow Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         SETUP PROCESS FLOW                                       │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│   Phase 1        Phase 2        Phase 3        Phase 4        Phase 5          │
│   ────────       ────────       ────────       ────────       ────────          │
│  ┌────────┐    ┌────────┐    ┌────────┐    ┌────────┐    ┌────────┐           │
│  │  API   │───▶│Storage │───▶│Service │───▶│Secrets │───▶│ Cloud  │           │
│  │Enable  │    │ Bucket │    │Accounts│    │Manager │    │ Tasks  │           │
│  └────────┘    └────────┘    └────────┘    └────────┘    └────────┘           │
│      │              │              │              │              │              │
│      ▼              ▼              ▼              ▼              ▼              │
│  11 APIs       1 Bucket       3 Service     2 Secrets     1 Queue             │
│  enabled       created        Accounts      stored        created             │
│                               + IAM roles                                       │
│                                                                                 │
│                         Phase 6                    Phase 7                      │
│                         ────────                   ────────                     │
│                       ┌────────┐                 ┌────────┐                    │
│                       │Artifact│────────────────▶│Docling │                    │
│                       │Registry│                 │ Models │                    │
│                       └────────┘                 └────────┘                    │
│                            │                          │                         │
│                            ▼                          ▼                         │
│                       1 Repository              ~1GB models                    │
│                       created                   uploaded to GCS                │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Phase 1: Enable Google Cloud APIs

```mermaid
flowchart TB
    subgraph Phase1["Phase 1: API Enablement"]
        Start[Start Setup] --> Check{APIs Enabled?}
        Check -->|No| Enable[Enable APIs]
        Check -->|Yes| Skip[Skip - Already Enabled]
        Enable --> Done[APIs Ready]
        Skip --> Done
    end

    subgraph APIs["11 Required APIs"]
        A1[run.googleapis.com<br/>Cloud Run]
        A2[cloudbuild.googleapis.com<br/>Cloud Build]
        A3[storage.googleapis.com<br/>Cloud Storage]
        A4[secretmanager.googleapis.com<br/>Secret Manager]
        A5[cloudtasks.googleapis.com<br/>Cloud Tasks]
        A6[eventarc.googleapis.com<br/>EventArc]
        A7[artifactregistry.googleapis.com<br/>Artifact Registry]
        A8[aiplatform.googleapis.com<br/>AI Platform]
        A9[pubsub.googleapis.com<br/>Pub/Sub]
        A10[speech.googleapis.com<br/>Speech API]
        A11[cloudfunctions.googleapis.com<br/>Cloud Functions]
    end

    Done --> APIs
```

### What Happens

```
📋 Phase 1: Enable Required APIs
   Enabling: run.googleapis.com
   ✅ run.googleapis.com enabled
   Enabling: cloudbuild.googleapis.com
   ✅ cloudbuild.googleapis.com enabled
   Enabling: storage.googleapis.com
   ✅ storage.googleapis.com enabled
   ... (continues for all 11 APIs)
```

**Purpose:** Each API enables specific GCP functionality:

| API | Purpose |
|-----|---------|
| `run.googleapis.com` | Deploy and run Cloud Run Jobs |
| `cloudbuild.googleapis.com` | Build Docker images in cloud |
| `storage.googleapis.com` | Store documents and models |
| `secretmanager.googleapis.com` | Store database URLs and API keys |
| `cloudtasks.googleapis.com` | Queue processing jobs |
| `eventarc.googleapis.com` | Trigger functions on events |
| `artifactregistry.googleapis.com` | Store Docker images |
| `aiplatform.googleapis.com` | Access Vertex AI embeddings |
| `pubsub.googleapis.com` | Event messaging backbone |
| `speech.googleapis.com` | Audio transcription (future) |
| `cloudfunctions.googleapis.com` | Deploy Cloud Functions |

**Timing:** ~30-60 seconds (APIs enable in parallel)

## Phase 2: Create Storage Bucket

```mermaid
flowchart LR
    subgraph Phase2["Phase 2: Storage Setup"]
        Check{Bucket Exists?}
        Check -->|No| Create[Create Bucket]
        Check -->|Yes| Skip[Skip Creation]
        Create --> Configure[Configure Settings]
        Skip --> Configure
        Configure --> Ready[Bucket Ready]
    end

    subgraph Config["Bucket Configuration"]
        C1[Location: us-central1]
        C2[Storage Class: STANDARD]
        C3[Uniform Bucket Access: ON]
        C4[Public Access: BLOCKED]
    end

    Ready --> Config
```

### What Happens

```
📦 Phase 2: Create Storage Bucket
   Creating bucket: gs://your-gcp-project-id-rag-documents-dev
   Setting uniform bucket-level access...
   Blocking public access...
   ✅ Bucket created successfully
```

**Bucket Structure Created:**

```
gs://{project-id}-rag-documents-dev/
├── documents/           # Creator uploaded documents
│   └── {creator-id}/     # Organized by creator
│       └── {program-id}/  # Then by program
├── models/             # Docling ML models (added during deployment)
│   └── docling/
└── temp/               # Temporary processing files
    └── processing/
```

**Security Settings:**
- Uniform bucket-level access (no per-object ACLs)
- Public access prevention enabled
- Only service accounts can access

## Phase 3: Create Service Accounts & IAM Roles

```mermaid
flowchart TB
    subgraph Phase3["Phase 3: Service Accounts"]
        SA1[Create rag-processor-dev]
        SA2[Create rag-gcs-handler-dev]
        SA3[Create rag-task-processor-dev]

        SA1 --> R1[Assign Roles]
        SA2 --> R2[Assign Roles]
        SA3 --> R3[Assign Roles]
    end

    subgraph Roles1["Processor Roles"]
        PR1[storage.admin]
        PR2[secretmanager.secretAccessor]
        PR3[aiplatform.user]
        PR4[artifactregistry.writer]
        PR5[run.developer]
        PR6[run.invoker]
    end

    subgraph Roles2["GCS Handler Roles"]
        HR1[secretmanager.secretAccessor]
        HR2[cloudtasks.enqueuer]
        HR3[storage.objectViewer]
        HR4[iam.serviceAccountTokenCreator]
    end

    subgraph Roles3["Task Processor Roles"]
        TR1[run.invoker]
        TR2[run.developer]
        TR3[iam.serviceAccountUser]
    end

    R1 --> Roles1
    R2 --> Roles2
    R3 --> Roles3
```

### What Happens

```
🔐 Phase 3: Create Service Accounts
   Creating service account: rag-processor-dev
   ✅ Created rag-processor-dev@{project}.iam.gserviceaccount.com

   Assigning roles to rag-processor-dev:
   ✅ roles/storage.admin
   ✅ roles/secretmanager.secretAccessor
   ✅ roles/aiplatform.user
   ✅ roles/artifactregistry.writer
   ✅ roles/run.developer
   ✅ roles/run.invoker

   Creating service account: rag-gcs-handler-dev
   ... (continues for all accounts)
```

**Service Account Purposes:**

| Service Account | Purpose | Key Permissions |
|-----------------|---------|-----------------|
| `rag-processor-dev` | Runs the RAG processor job | Read/write storage, access secrets, use AI |
| `rag-gcs-handler-dev` | Handles GCS upload events | Read storage, create tasks, access secrets |
| `rag-task-processor-dev` | Processes queued tasks | Invoke Cloud Run jobs |

**Cross-Service Permissions:**

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    INTER-SERVICE PERMISSION CHAIN                               │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│   GCS Handler                Task Processor              RAG Processor          │
│   ───────────               ──────────────              ─────────────           │
│                                                                                 │
│   ┌─────────┐     creates    ┌─────────┐    invokes    ┌─────────┐            │
│   │  GCS    │───────────────▶│  Task   │──────────────▶│   Job   │            │
│   │ Handler │    task        │Processor│               │Execution│            │
│   └─────────┘                └─────────┘               └─────────┘            │
│       │                           │                         │                  │
│       │ needs:                    │ needs:                  │ needs:           │
│       │ • cloudtasks.enqueuer    │ • run.invoker           │ • storage.admin  │
│       │ • tokenCreator           │ • run.developer         │ • aiplatform     │
│       │                          │ • serviceAccountUser    │ • secrets        │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Phase 4: Configure Secrets

```mermaid
flowchart TB
    subgraph Phase4["Phase 4: Secret Manager"]
        Input1[DATABASE_URL Input]
        Input2[GEMINI_API_KEY Input]

        Input1 --> Create1[Create database-url-dev]
        Input2 --> Create2[Create gemini-api-key-dev]

        Create1 --> Grant1[Grant Access to Processor]
        Create1 --> Grant2[Grant Access to Handler]
        Create2 --> Grant3[Grant Access to Processor]
    end

    subgraph Mounting["Runtime Secret Mounting"]
        S1[database-url-dev] -->|"Mounted as"| E1[DATABASE_URL env var]
        S2[gemini-api-key-dev] -->|"Mounted as"| E2[GEMINI_API_KEY env var]
    end
```

### What Happens

```
🔑 Phase 4: Configure Secrets
   Creating secret: database-url-dev
   ✅ Secret created
   Adding secret version...
   ✅ Secret value stored

   Granting access to rag-processor-dev...
   ✅ Access granted
   Granting access to rag-gcs-handler-dev...
   ✅ Access granted

   Creating secret: gemini-api-key-dev (optional)
   ... (if API key provided)
```

**Secret Security:**
- Secrets stored encrypted at rest
- Accessed only by authorized service accounts
- Mounted at runtime (not baked into images)
- Version-controlled for safe updates

**Database URL Format:**
```
postgresql://postgres.{ref}:{password}@{region}.pooler.supabase.com:6543/postgres
                                                                    ^^^^
                                                              MUST be pooled port
```

## Phase 5: Create Cloud Tasks Queue

```mermaid
flowchart LR
    subgraph Phase5["Phase 5: Cloud Tasks"]
        Create[Create Queue] --> Configure[Configure Settings]
        Configure --> Ready[Queue Ready]
    end

    subgraph Settings["Queue Configuration"]
        S1["Max Dispatches/Second: 10"]
        S2["Max Concurrent: 5"]
        S3["Max Retries: 3"]
        S4["Min Backoff: 10s"]
        S5["Max Backoff: 300s"]
    end

    Ready --> Settings
```

### What Happens

```
📋 Phase 5: Create Cloud Tasks Queue
   Creating queue: rag-processing-queue-dev
   Location: us-central1

   Configuring queue settings:
   • Max dispatches per second: 10
   • Max concurrent dispatches: 5
   • Max retry attempts: 3
   • Min backoff: 10 seconds
   • Max backoff: 300 seconds

   ✅ Queue created successfully
```

**Queue Behavior:**

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         TASK LIFECYCLE                                          │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│   Task Created ──▶ Queued ──▶ Dispatched ──▶ Processing ──▶ Complete           │
│                       │            │              │                             │
│                       │            │              ▼                             │
│                       │            │          Failure?                          │
│                       │            │              │                             │
│                       │            │         ┌────┴────┐                        │
│                       │            │         │  Yes    │                        │
│                       │            │         ▼         │                        │
│                       │            │    Retry < 3?     │                        │
│                       │            │         │         │                        │
│                       │            │    ┌────┴────┐    │                        │
│                       │            │    │  Yes    │    │ No                     │
│                       │            │    ▼         │    ▼                        │
│                       │◀───────────┴──Backoff    Dead Letter                   │
│                       │              (10-300s)                                  │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Phase 6: Create Artifact Registry

```mermaid
flowchart TB
    subgraph Phase6["Phase 6: Artifact Registry"]
        Create[Create Repository] --> Config[Configure Settings]
        Config --> Ready[Repository Ready]
    end

    subgraph Settings["Repository Configuration"]
        S1["Format: Docker"]
        S2["Location: us-central1"]
        S3["Name: rag-services"]
    end

    subgraph Images["Container Images"]
        I1[rag-processor-job-dev:latest]
        I2[rag-processor-job-prod:latest]
    end

    Ready --> Settings
    Ready --> Images
```

### What Happens

```
🐳 Phase 6: Create Artifact Registry
   Creating repository: rag-services
   Format: Docker
   Location: us-central1

   ✅ Repository created successfully

   Repository URL:
   us-central1-docker.pkg.dev/{project}/rag-services/
```

**Registry Purpose:**
- Stores Docker images for Cloud Run Jobs
- Provides versioning and tagging
- Enables fast deployment from pre-built images
- Scans images for vulnerabilities

## Phase 7: Download and Upload Docling Models

```mermaid
flowchart TB
    subgraph Phase7["Phase 7: Docling Models"]
        Check{Models in Cache?}
        Check -->|No| Download[Download from HuggingFace]
        Check -->|Yes| Skip[Skip Download]
        Download --> Upload[Upload to GCS]
        Skip --> Upload
        Upload --> Ready[Models Ready in GCS]
    end

    subgraph Models["Model Files (~1GB total)"]
        M1[layout/model.safetensors ~450MB]
        M2[tableformer/model.safetensors ~380MB]
        M3[picture_classifier/model.safetensors ~120MB]
        M4[code_formula/model.safetensors ~85MB]
    end

    Ready --> Models
```

### What Happens

```
🤖 Phase 7: Download Docling Models
   Checking local cache: ~/.cache/docling/models/
   Downloading models from HuggingFace...
   ✅ layout model downloaded
   ✅ tableformer model downloaded
   ✅ picture_classifier model downloaded
   ✅ code_formula model downloaded

   Uploading to GCS: gs://{project}-rag-documents-dev/models/docling/
   ✅ Models uploaded successfully
```

**Purpose:**
- Docling ML models are required for PDF document processing
- Models are downloaded once and cached locally at `~/.cache/docling/models/`
- Models are uploaded to GCS so Docker builds can pull them during deployment
- This avoids baking ~1GB of models directly into Docker images

**Timing:**
- **First run:** 10-15 minutes (downloading ~1GB from HuggingFace)
- **Subsequent runs:** 1-2 minutes (uses local cache, only uploads to GCS)

**GCS Structure After Upload:**

```
gs://{project-id}-rag-documents-dev/
└── models/
    └── docling/
        ├── layout/
        │   ├── config.json
        │   └── model.safetensors
        ├── tableformer/
        │   ├── config.json
        │   └── model.safetensors
        ├── picture_classifier/
        │   ├── config.json
        │   └── model.safetensors
        └── code_formula/
            ├── config.json
            └── model.safetensors
```

**Why This Matters:**
- Deployment will **FAIL** without models in GCS
- Docker build's model-downloader stage pulls from GCS, not HuggingFace
- Error if missing: `Missing safe tensors file: /app/models/docling/model.safetensors`

## Complete Setup Summary

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         SETUP COMPLETION                                         │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│   ✅ 11 APIs enabled                                                            │
│   ✅ 1 Storage bucket created                                                   │
│   ✅ 3 Service accounts with IAM roles                                          │
│   ✅ 2 Secrets stored (DATABASE_URL, optional GEMINI_API_KEY)                   │
│   ✅ 1 Cloud Tasks queue configured                                             │
│   ✅ 1 Artifact Registry repository                                             │
│   ✅ Docling ML models uploaded to GCS (~1GB)                                   │
│                                                                                 │
│   📋 Infrastructure Summary:                                                     │
│     • Environment: Development                                                   │
│     • Project: your-gcp-project-id                                       │
│     • Region: us-central1                                                        │
│     • Storage: gs://your-gcp-project-id-rag-documents-dev                │
│     • Models: gs://your-gcp-project-id-rag-documents-dev/models/docling/ │
│                                                                                 │
│   🚀 Ready for deployment!                                                       │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Idempotency

The setup script is **idempotent** - safe to run multiple times:

| Resource | On Re-run |
|----------|-----------|
| APIs | Skipped if already enabled |
| Bucket | Skipped if exists |
| Service Accounts | Updated with latest roles |
| Secrets | New version added (preserves history) |
| Queue | Configuration updated |
| Registry | Skipped if exists |

## Next Step

After setup completes, proceed to [Deployment](./03-deployment.md).
