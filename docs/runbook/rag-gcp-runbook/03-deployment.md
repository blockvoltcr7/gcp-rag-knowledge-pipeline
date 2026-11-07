# Deploying RAG Services

After GCP infrastructure is set up, deploy the three services in order.

## Prerequisites

> ⚠️ **CRITICAL:** You MUST run `npm run setup:gcp:dev` before deploying.
>
> The setup script uploads Docling ML models (~1GB) to GCS. The deployment will fail with "Missing safe tensors file" error if models are not in GCS.
>
> **Verify models exist before deploying:**
> ```bash
> gcloud storage ls gs://{project-id}-rag-documents-dev/models/docling/
> ```

## Deployment Order

**IMPORTANT:** Deploy in this exact order due to dependencies:

1. **RAG Processor** (Cloud Run Job) - Processes documents
2. **GCS Handler** (Cloud Function) - Triggers on file upload
3. **Task Processor** (Cloud Function) - Queues processing jobs

## 1. Deploy RAG Processor

The RAG processor is a Cloud Run Job that processes documents using LlamaIndex (primary) with Docling as fallback.

### Secrets Injected

The deployment automatically injects these secrets from Secret Manager:

| Secret | Environment Variable | Purpose |
|--------|---------------------|---------|
| `database-url-dev` | `DATABASE_URL` | PostgreSQL connection |
| `gemini-api-key-dev` | `GEMINI_API_KEY` | Embeddings generation |
| `llamaparse-api-key-dev` | `LLAMAPARSE_API_KEY` | PDF processing (optional) |

> **Note:** If `llamaparse-api-key-dev` secret doesn't exist, PDF processing will use the local PDFReader instead of LlamaParse cloud service.

```bash
npm run deploy:processor:dev
```

### What Happens

1. Docker build pulls Docling ML models from GCS bucket (requires setup to have run first)
2. Builds Docker image with all dependencies and models baked in
3. Pushes image to Artifact Registry
4. Creates/updates Cloud Run Job

### Duration

**First deployment:** 10-15 minutes (model download + build)
**Subsequent deployments:** 3-5 minutes (cached layers)

### Expected Output

```
🚀 RAG Processor Deployment - Development
==========================================

📋 Phase 1: Configuration
✅ Configuration loaded successfully

📦 Phase 2: Model Setup
   Downloading Docling models...
   ✅ Models downloaded successfully

🐳 Phase 3: Docker Build
   Building image: us-central1-docker.pkg.dev/{project}/rag-services/rag-processor-dev
   ✅ Image built successfully

☁️ Phase 4: Cloud Run Deployment
   Deploying Cloud Run Job: rag-processor-dev
   ✅ Cloud Run Job deployed successfully

🎉 RAG Processor deployment completed!
```

## 2. Deploy GCS Handler

The GCS handler is a Cloud Function triggered when files are uploaded to the storage bucket.

```bash
npm run deploy:gcs-handler:dev
```

### What Happens

1. Packages Cloud Function code
2. Deploys to Cloud Functions Gen 2
3. Configures EventArc trigger for GCS events

### Duration

2-3 minutes

### Expected Output

```
🚀 GCS Handler Deployment - Development
=======================================

📋 Deploying Cloud Function: rag-gcs-handler-dev
   Trigger: google.cloud.storage.object.v1.finalized
   Bucket: {project-id}-rag-documents-dev

✅ Cloud Function deployed successfully
✅ EventArc trigger configured
```

## 3. Deploy Task Processor

The task processor receives tasks from Cloud Tasks and triggers the RAG processor.

```bash
npm run deploy:task-processor:dev
```

### What Happens

1. Packages Cloud Function code
2. Deploys to Cloud Functions Gen 2
3. Configures as Cloud Tasks target

### Duration

2-3 minutes

### Expected Output

```
🚀 Task Processor Deployment - Development
==========================================

📋 Deploying Cloud Function: rag-task-processor-dev
   Queue: rag-processing-queue-dev

✅ Cloud Function deployed successfully
✅ Cloud Tasks integration configured
```

## Verifying Deployment

### Check Cloud Run Job

```bash
gcloud run jobs list --region=us-central1
```

Expected output:
```
JOB                   REGION        LAST RUN
rag-processor-dev     us-central1   -
```

### Check Cloud Functions

```bash
gcloud functions list --v2 --regions=us-central1
```

Expected output:
```
NAME                      STATE   TRIGGER
rag-gcs-handler-dev       ACTIVE  Event Trigger
rag-task-processor-dev    ACTIVE  HTTPS
```

### Check Cloud Tasks Queue

```bash
gcloud tasks queues describe rag-processing-queue-dev --location=us-central1
```

## Production Deployment

For production, use the `:prod` suffix:

```bash
npm run deploy:processor:prod
npm run deploy:gcs-handler:prod
npm run deploy:task-processor:prod
```

## Updating Deployments

To update code after changes:

```bash
# Redeploy specific service
npm run deploy:processor:dev      # If processor code changed
npm run deploy:gcs-handler:dev    # If handler code changed
npm run deploy:task-processor:dev # If task processor code changed
```

## Rollback

### Cloud Run Job

```bash
# List revisions
gcloud run jobs revisions list --job=rag-processor-dev --region=us-central1

# Jobs don't support rollback - redeploy previous code version
```

### Cloud Functions

```bash
# Cloud Functions Gen 2 - redeploy previous code version
npm run deploy:gcs-handler:dev
```

## Next Step

Proceed to [Testing](./04-testing.md) to verify the pipeline works end-to-end.
