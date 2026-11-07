# Deployment Process Explained

This document explains what happens during each deployment command.

## Deployment Overview

```mermaid
flowchart TB
    subgraph Deploy["Deployment Order (Required)"]
        D1["1. RAG Processor<br/>npm run deploy:processor:dev"]
        D2["2. GCS Handler<br/>npm run deploy:gcs-handler:dev"]
        D3["3. Task Processor<br/>npm run deploy:task-processor:dev"]

        D1 --> D2
        D2 --> D3
    end

    subgraph Why["Why This Order?"]
        W1[Task Processor needs<br/>Processor Job URL]
        W2[GCS Handler needs<br/>Task Queue URL]
        W3[Processor must exist<br/>before being invoked]
    end
```

## 1. RAG Processor Deployment

```bash
npm run deploy:processor:dev
```

### Deployment Flow

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    RAG PROCESSOR DEPLOYMENT                                      │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│   Phase 1              Phase 2              Phase 3              Phase 4        │
│   ────────             ────────             ────────             ────────        │
│  ┌────────┐          ┌────────┐          ┌────────┐          ┌────────┐        │
│  │Download│─────────▶│ Build  │─────────▶│  Push  │─────────▶│ Deploy │        │
│  │ Models │          │ Docker │          │ Image  │          │  Job   │        │
│  └────────┘          └────────┘          └────────┘          └────────┘        │
│      │                   │                   │                   │              │
│   ~5 min              ~3 min               ~2 min              ~1 min           │
│   (first)             (first)                                                   │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Phase 1: Download Docling Models

```mermaid
flowchart TB
    subgraph Phase1["Model Download (~5 min first time)"]
        Check{Models in GCS?}
        Check -->|No| Download[Download from HuggingFace]
        Check -->|Yes| Skip[Skip - Use Cached]
        Download --> Upload[Upload to GCS]
        Upload --> Ready[Models Ready]
        Skip --> Ready
    end

    subgraph Models["Docling ML Models (~2GB)"]
        M1[layout_detection<br/>Document layout analysis]
        M2[tableformer<br/>Table extraction]
        M3[picture_classifier<br/>Image classification]
        M4[code_formula<br/>Code/formula detection]
        M5[easyocr<br/>OCR for images]
    end

    Ready --> Models
```

**What Happens:**

```
📦 Phase 1: Model Setup
   Checking for existing models in GCS...

   Downloading Docling models from HuggingFace:
   ⬇️ layout/model.safetensors (450MB)
   ⬇️ tableformer/model.safetensors (380MB)
   ⬇️ picture_classifier/model.safetensors (120MB)
   ⬇️ code_formula/model.safetensors (85MB)
   ⬇️ easyocr/craft_mlt_25k.pth (90MB)

   Uploading to GCS: gs://project-rag-documents-dev/models/docling/
   ✅ Models ready
```

**GCS Model Structure:**

```
gs://{project}-rag-documents-dev/models/docling/
├── layout/
│   ├── config.json
│   └── model.safetensors
├── tableformer/
│   ├── config.json
│   └── model.safetensors
├── picture_classifier/
│   ├── config.json
│   └── model.safetensors
├── code_formula/
│   ├── config.json
│   └── model.safetensors
└── easyocr/
    ├── craft_mlt_25k.pth
    └── latin_g2.pth
```

### Phase 2: Docker Build

```mermaid
flowchart TB
    subgraph Phase2["Docker Build (~3 min)"]
        Base[Python 3.11 Base Image]
        Base --> Deps[Install Dependencies<br/>docling, supabase, etc.]
        Deps --> Copy[Copy Application Code]
        Copy --> Image[Final Image<br/>~3.5GB]
    end

    subgraph Layers["Docker Layers"]
        L1[Base: python:3.11-slim]
        L2[System: libgl, tesseract]
        L3[Python: requirements.txt]
        L4[App: src/, main.py]
    end

    Image --> Layers
```

**What Happens:**

```
🐳 Phase 2: Docker Build
   Building image: us-central1-docker.pkg.dev/your-gcp-project-id/rag-services/rag-processor-job-dev

   Step 1/12: FROM python:3.11-slim
   Step 2/12: RUN apt-get update && apt-get install -y libgl1-mesa-glx...
   Step 3/12: COPY requirements.txt .
   Step 4/12: RUN pip install -r requirements.txt
   ...
   Step 12/12: CMD ["python", "main.py"]

   ✅ Image built successfully
   Size: 3.47GB
```

**Dockerfile Highlights:**

```dockerfile
FROM python:3.11-slim

# System dependencies for document processing
RUN apt-get install -y \
    libgl1-mesa-glx \    # OpenCV
    tesseract-ocr \      # OCR
    poppler-utils \      # PDF processing
    libmagic1            # File type detection

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY src/ src/
COPY main.py .

CMD ["python", "main.py"]
```

### Phase 3: Push to Artifact Registry

```mermaid
flowchart LR
    subgraph Phase3["Image Push (~2 min)"]
        Local[Local Image] -->|"docker push"| Registry[Artifact Registry]
        Registry --> Tag[Tagged as :latest]
    end

    subgraph Registry_Details["Registry Details"]
        R1["us-central1-docker.pkg.dev"]
        R2["{project}/rag-services"]
        R3["rag-processor-job-dev:latest"]
    end

    Tag --> Registry_Details
```

**What Happens:**

```
📤 Phase 3: Push Image
   Authenticating with Artifact Registry...
   ✅ Authenticated

   Pushing: us-central1-docker.pkg.dev/your-gcp-project-id/rag-services/rag-processor-job-dev:latest
   ⬆️ Layer 1/8: 125MB
   ⬆️ Layer 2/8: 450MB
   ⬆️ Layer 3/8: 1.2GB
   ...
   ✅ Image pushed successfully
```

### Phase 4: Deploy Cloud Run Job

```mermaid
flowchart TB
    subgraph Phase4["Cloud Run Job Deployment"]
        Create[Create/Update Job]
        Create --> Config[Apply Configuration]
        Config --> Secrets[Mount Secrets]
        Secrets --> Ready[Job Ready]
    end

    subgraph JobConfig["Job Configuration"]
        C1["CPU: 6"]
        C2["Memory: 8Gi"]
        C3["Timeout: 3600s (1 hour)"]
        C4["Max Retries: 1"]
        C5["Service Account: rag-processor-dev"]
    end

    Ready --> JobConfig
```

**What Happens:**

```
☁️ Phase 4: Deploy Cloud Run Job
   Creating Cloud Run Job: rag-processor-job-dev
   Region: us-central1

   Configuration:
   • CPU: 6
   • Memory: 8Gi
   • Timeout: 3600 seconds
   • Max retries: 1
   • Service account: rag-processor-dev@...

   Mounting secrets:
   • DATABASE_URL from database-url-dev:latest
   • GEMINI_API_KEY from gemini-api-key-dev:latest

   ✅ Cloud Run Job deployed successfully

   Job URL: https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/your-gcp-project-id/jobs/rag-processor-job-dev
```

**Cloud Run Job vs Service:**

| Aspect | Cloud Run Job | Cloud Run Service |
|--------|---------------|-------------------|
| Invocation | On-demand execution | Always-on HTTP endpoint |
| Billing | Pay per execution | Pay while running |
| Timeout | Up to 24 hours | 60 minutes max |
| Use Case | Batch processing | Web APIs |

---

## 2. GCS Handler Deployment

```bash
npm run deploy:gcs-handler:dev
```

### Deployment Flow

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    GCS HANDLER DEPLOYMENT                                        │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│   Phase 1              Phase 2              Phase 3                             │
│   ────────             ────────             ────────                             │
│  ┌────────┐          ┌────────┐          ┌────────┐                            │
│  │Package │─────────▶│ Deploy │─────────▶│Configure│                           │
│  │  Code  │          │Function│          │EventArc │                           │
│  └────────┘          └────────┘          └────────┘                            │
│      │                   │                   │                                  │
│   ~30 sec             ~2 min              ~30 sec                               │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Phase 1: Package Code

```mermaid
flowchart TB
    subgraph Phase1["Code Packaging"]
        Source[Source Code<br/>apps/rag-gcs-handler/]
        Source --> Bundle[Create Deployment Bundle]
        Bundle --> Upload[Upload to Cloud Build]
    end

    subgraph Files["Packaged Files"]
        F1[main.py - Entry point]
        F2[requirements.txt - Dependencies]
        F3[.gcloudignore - Exclusions]
    end

    Upload --> Files
```

### Phase 2: Deploy Cloud Function

```mermaid
flowchart TB
    subgraph Phase2["Function Deployment"]
        Build[Cloud Build Compiles]
        Build --> Deploy[Deploy Gen 2 Function]
        Deploy --> Ready[Function Ready]
    end

    subgraph Config["Function Configuration"]
        C1["Runtime: python311"]
        C2["Memory: 256Mi"]
        C3["Timeout: 60s"]
        C4["Entry Point: handle_gcs_event"]
        C5["Service Account: rag-gcs-handler-dev"]
    end

    Ready --> Config
```

**What Happens:**

```
🚀 GCS Handler Deployment
=======================================

📋 Deploying Cloud Function: rag-gcs-handler-dev
   Runtime: python311
   Entry point: handle_gcs_event
   Memory: 256Mi
   Timeout: 60s

   Building function...
   ⏳ Build in progress...
   ✅ Build complete

   Deploying function...
   ✅ Function deployed
```

### Phase 3: Configure EventArc Trigger

```mermaid
flowchart LR
    subgraph Phase3["EventArc Configuration"]
        GCS[GCS Bucket] -->|"file.finalized"| EventArc[EventArc]
        EventArc -->|"Trigger"| Function[GCS Handler]
    end

    subgraph TriggerDetails["Trigger Details"]
        T1["Event: google.cloud.storage.object.v1.finalized"]
        T2["Filter: bucket={project}-rag-documents-dev"]
        T3["Filter: prefix=documents/"]
    end

    Function --> TriggerDetails
```

**What Happens:**

```
📡 Configuring EventArc Trigger
   Event type: google.cloud.storage.object.v1.finalized
   Bucket: your-gcp-project-id-rag-documents-dev
   Path filter: documents/*

   ✅ EventArc trigger configured
```

**Trigger Logic:**

```python
# Only triggers for files matching:
# gs://{bucket}/documents/{creator-id}/{program-id}/{filename}

def handle_gcs_event(cloud_event):
    data = cloud_event.data
    bucket = data["bucket"]
    name = data["name"]  # e.g., "documents/creator-123/program-456/file.pdf"

    # Validate path structure
    if not name.startswith("documents/"):
        return  # Ignore non-document uploads

    # Extract creator_id and program_id from path
    parts = name.split("/")
    if len(parts) < 4:  # Validate 3-level structure
        return
    creator_id = parts[1]
    program_id = parts[2]
    filename = parts[3]

    # Create task for processing
    create_cloud_task(bucket, name, creator_id, program_id)
```

---

## 3. Task Processor Deployment

```bash
npm run deploy:task-processor:dev
```

### Deployment Flow

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    TASK PROCESSOR DEPLOYMENT                                     │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│   Phase 1              Phase 2              Phase 3                             │
│   ────────             ────────             ────────                             │
│  ┌────────┐          ┌────────┐          ┌────────┐                            │
│  │Package │─────────▶│ Deploy │─────────▶│Configure│                           │
│  │  Code  │          │Function│          │ as Task │                           │
│  └────────┘          └────────┘          │ Target  │                           │
│      │                   │               └────────┘                            │
│   ~30 sec             ~2 min              ~30 sec                               │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Phase 2: Deploy Cloud Function

```mermaid
flowchart TB
    subgraph Phase2["Function Deployment"]
        Build[Cloud Build]
        Build --> Deploy[Deploy Gen 2 Function]
        Deploy --> Ready[Function Ready]
    end

    subgraph Config["Function Configuration"]
        C1["Runtime: python311"]
        C2["Memory: 512Mi"]
        C3["Timeout: 540s (9 min)"]
        C4["Entry Point: process_task"]
        C5["Service Account: rag-task-processor-dev"]
        C6["Trigger: HTTPS"]
    end

    Ready --> Config
```

**What Happens:**

```
🚀 Task Processor Deployment
==========================================

📋 Deploying Cloud Function: rag-task-processor-dev
   Runtime: python311
   Entry point: process_task
   Memory: 512Mi
   Timeout: 540s

   Building function...
   ⏳ Build in progress...
   ✅ Build complete

   Deploying function...
   ✅ Function deployed

   Function URL: https://us-central1-your-gcp-project-id.cloudfunctions.net/rag-task-processor-dev
```

### Phase 3: Configure as Task Target

```mermaid
flowchart LR
    subgraph Phase3["Cloud Tasks Integration"]
        Queue[Cloud Tasks Queue] -->|"HTTP POST"| Function[Task Processor]
        Function -->|"Execute"| Job[Cloud Run Job]
    end

    subgraph Auth["Authentication"]
        A1["OIDC Token"]
        A2["Service Account: rag-gcs-handler-dev"]
        A3["Audience: Function URL"]
    end

    Queue --> Auth
```

**Task Processor Logic:**

```python
def process_task(request):
    """Receives task from Cloud Tasks, invokes RAG Processor Job."""

    # Parse task payload
    task_data = request.get_json()
    bucket = task_data["bucket"]
    object_name = task_data["object_name"]
    creator_id = task_data["creator_id"]
    program_id = task_data["program_id"]

    # Execute Cloud Run Job
    job_name = "rag-processor-job-dev"
    execution = run_job(
        job_name=job_name,
        env_vars={
            "GCS_BUCKET": bucket,
            "GCS_OBJECT": object_name,
            "CREATOR_ID": creator_id,
            "PROGRAM_ID": program_id,
        }
    )

    return {"execution_id": execution.name}
```

---

## Complete Deployment Architecture

```mermaid
flowchart TB
    subgraph Deployed["Deployed Components"]
        subgraph CloudRun["Cloud Run"]
            Job[RAG Processor Job<br/>rag-processor-job-dev]
        end

        subgraph Functions["Cloud Functions Gen 2"]
            Handler[GCS Handler<br/>rag-gcs-handler-dev]
            TaskProc[Task Processor<br/>rag-task-processor-dev]
        end

        subgraph Storage["Cloud Storage"]
            Bucket[Documents Bucket<br/>models/, documents/]
        end

        subgraph Tasks["Cloud Tasks"]
            Queue[Processing Queue<br/>rag-processing-queue-dev]
        end
    end

    Bucket -->|"EventArc"| Handler
    Handler -->|"Enqueue"| Queue
    Queue -->|"Dispatch"| TaskProc
    TaskProc -->|"Execute"| Job
    Job -->|"Read Models"| Bucket
```

## Deployment Verification Commands

After all deployments complete:

```bash
# Verify Cloud Run Job
gcloud run jobs list --region=us-central1

# Verify Cloud Functions
gcloud functions list --v2 --regions=us-central1

# Verify EventArc Trigger
gcloud eventarc triggers list --location=us-central1

# Verify Cloud Tasks Queue
gcloud tasks queues describe rag-processing-queue-dev --location=us-central1
```

## Next Step

Proceed to [Testing](./04-testing.md) to verify the pipeline works end-to-end.
