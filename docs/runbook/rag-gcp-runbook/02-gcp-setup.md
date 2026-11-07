# GCP Infrastructure Setup

This step creates all the GCP infrastructure needed for the RAG pipeline.

## Overview

The setup script creates:
- Cloud Storage bucket for documents
- Service accounts with appropriate IAM roles
- Secret Manager secrets for credentials
- Cloud Tasks queue for async processing
- Artifact Registry for Docker images

## Running Setup

### Development Environment

```bash
# From application-monorepo root directory (monorepo)
npm run setup:gcp:dev
```

### Production Environment

```bash
npm run setup:gcp:prod
```

## Interactive Prompts

The setup script will prompt for:

### 1. Confirmation to Continue
```
Continue with development setup? [y/N]: y
```

### 2. Project Selection
```
Select project by number (1-2) or enter project ID manually: 2
```
Select your project or enter the project ID.

### 3. Bucket Name (optional)
```
Bucket name for development document storage
  Default: {project-id}-rag-documents-dev
  Enter value (or press Enter for default):
```
Press Enter to use the default.

### 4. Database URL
```
Pooled PostgreSQL URL (port 6543):
```
Paste your Supabase pooled connection string:
```
postgresql://postgres.xxxxx:password@region.pooler.supabase.com:6543/postgres
```

### 5. Gemini API Key (optional)
```
Gemini API Key (optional, press Enter to skip):
```
Enter your Gemini API key or press Enter to skip.

## What Gets Created

### APIs Enabled
- `run.googleapis.com` - Cloud Run
- `cloudbuild.googleapis.com` - Cloud Build
- `storage.googleapis.com` - Cloud Storage
- `secretmanager.googleapis.com` - Secret Manager
- `cloudtasks.googleapis.com` - Cloud Tasks
- `eventarc.googleapis.com` - EventArc
- `artifactregistry.googleapis.com` - Artifact Registry
- `aiplatform.googleapis.com` - AI Platform
- `pubsub.googleapis.com` - Pub/Sub
- `speech.googleapis.com` - Speech API
- `visionai.googleapis.com` - Vision AI

### Service Accounts

| Service Account | Purpose |
|-----------------|---------|
| `rag-processor-dev@...` | RAG processor Cloud Run Job |
| `rag-gcs-handler-dev@...` | GCS event handler Cloud Function |
| `rag-task-processor-dev@...` | Task processor Cloud Function |

### IAM Roles Assigned

**rag-processor-dev:**
- `roles/storage.admin`
- `roles/secretmanager.secretAccessor`
- `roles/aiplatform.user`
- `roles/speech.client`
- `roles/artifactregistry.writer`

**rag-gcs-handler-dev:**
- `roles/secretmanager.secretAccessor`
- `roles/cloudtasks.enqueuer`
- `roles/storage.objectViewer`

**rag-task-processor-dev:**
- `roles/run.invoker`
- `roles/run.developer`
- `roles/iam.serviceAccountUser`

### Secrets Created

| Secret Name | Contents |
|-------------|----------|
| `database-url-dev` | Supabase pooled connection string |
| `gemini-api-key-dev` | Gemini API key (if provided) |
| `llamaparse-api-key-dev` | LlamaParse API key for PDF processing (optional) |

> **Note:** The `llamaparse-api-key-dev` secret must be created manually if you want to use LlamaParse for enhanced PDF processing. See [Adding LlamaParse API Key](#adding-llamaparse-api-key) below.

### Infrastructure

| Resource | Name |
|----------|------|
| Storage Bucket | `{project-id}-rag-documents-dev` |
| Artifact Registry | `rag-services` |
| Cloud Tasks Queue | `rag-processing-queue-dev` |

## Expected Output

Successful setup ends with:

```
======================================================================
🎉 DEVELOPMENT INFRASTRUCTURE SETUP SUCCESSFUL! 🎉
======================================================================

📋 Infrastructure Summary:
  • Environment: Development
  • Project: your-project-id
  • Region: us-central1
  • Service Name: rag-processor (ready for deployment)
  • Storage Bucket: gs://your-project-id-rag-documents-dev
  • Service Accounts (Queue Architecture):
    - Processor: rag-processor-dev@your-project-id.iam.gserviceaccount.com
    - GCS Handler: rag-gcs-handler-dev@your-project-id.iam.gserviceaccount.com
    - Task Processor: rag-task-processor-dev@your-project-id.iam.gserviceaccount.com
```

## Re-running Setup

The setup script is **idempotent** - safe to run multiple times:
- Existing resources are detected and preserved
- Only missing components are created
- Configuration is updated to latest values

## Troubleshooting

### Billing Not Enabled
```
❌ Billing is not enabled for this project
```
**Solution:** Enable billing at https://console.cloud.google.com/billing

### Permission Denied
```
❌ Permission denied: You don't have permission to enable APIs
```
**Solution:**
1. Ask project owner to add you as Editor
2. Or create a new project where you're the owner

### Invalid Database URL
```
❌ Invalid database URL
```
**Solution:** Ensure you're using the pooled connection (port 6543), not direct connection (port 5432).

## Docling ML Models

**IMPORTANT:** The setup script also downloads and uploads Docling ML models (~1GB) to GCS. These models are required for PDF processing and must be in GCS before deployment.

### What Gets Uploaded

```
gs://{project-id}-rag-documents-dev/
└── models/
    └── docling/
        ├── layout/
        │   ├── config.json
        │   └── model.safetensors (~450MB)
        ├── tableformer/
        │   ├── config.json
        │   └── model.safetensors (~380MB)
        ├── picture_classifier/
        │   ├── config.json
        │   └── model.safetensors (~120MB)
        └── code_formula/
            ├── config.json
            └── model.safetensors (~85MB)
```

### Model Download Process

1. Downloads models using `docling-tools models download`
2. Models are cached locally at `~/.cache/docling/models/`
3. Uploads models to GCS bucket at `models/docling/`

### Duration

**First run:** 10-15 minutes (model download ~1GB)
**Subsequent runs:** 1-2 minutes (uses cached models)

### Verifying Models

```bash
gcloud storage ls gs://{project-id}-rag-documents-dev/models/docling/
```

Expected output:
```
gs://{project-id}-rag-documents-dev/models/docling/layout/
gs://{project-id}-rag-documents-dev/models/docling/tableformer/
gs://{project-id}-rag-documents-dev/models/docling/picture_classifier/
gs://{project-id}-rag-documents-dev/models/docling/code_formula/
```

## Adding LlamaParse API Key

LlamaParse provides enhanced PDF processing with better structure preservation and pricing extraction. This is **optional** but recommended for production use.

### Getting a LlamaParse API Key

1. Sign up at [LlamaCloud](https://cloud.llamaindex.ai/)
2. Create an API key in the dashboard
3. Cost: ~$0.003 per page processed

### Creating the Secret

```bash
# Create the secret
gcloud secrets create llamaparse-api-key-dev \
  --replication-policy=automatic \
  --project={PROJECT_ID}

# Add the API key value
printf '%s' "llx-YOUR_API_KEY_HERE" | \
  gcloud secrets versions add llamaparse-api-key-dev --data-file=-

# Grant access to the RAG processor service account
gcloud secrets add-iam-policy-binding llamaparse-api-key-dev \
  --member="serviceAccount:rag-processor-dev@{PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor" \
  --project={PROJECT_ID}
```

### For Production

Replace `dev` with `prod` in the commands above:
- Secret name: `llamaparse-api-key-prod`
- Service account: `rag-processor-prod@{PROJECT_ID}.iam.gserviceaccount.com`

### Verifying the Secret

```bash
gcloud secrets describe llamaparse-api-key-dev --project={PROJECT_ID}
```

## Next Step

Proceed to [Deployment](./03-deployment.md) to deploy the services.
