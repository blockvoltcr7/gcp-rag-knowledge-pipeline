# Troubleshooting

Common issues and solutions for the RAG GCP pipeline.

## Deployment Issues

### Docker Build Fails

**Symptom:**
```
ERROR: failed to solve: failed to compute cache key
```

**Solutions:**
1. Clear Docker cache:
   ```bash
   docker builder prune -f
   ```
2. Ensure Docker Desktop is running
3. Check available disk space (need ~10GB free)

### Cloud Build Permission Denied

**Symptom:**
```
ERROR: (gcloud.builds.submit) PERMISSION_DENIED
```

**Solutions:**
1. Re-run setup to grant permissions:
   ```bash
   npm run setup:gcp:dev
   ```
2. Manually grant Cloud Build Editor role:
   ```bash
   gcloud projects add-iam-policy-binding {PROJECT_ID} \
     --member="user:{YOUR_EMAIL}" \
     --role="roles/cloudbuild.builds.editor"
   ```

### Artifact Registry Push Fails

**Symptom:**
```
denied: Permission "artifactregistry.repositories.uploadArtifacts" denied
```

**Solution:**
```bash
gcloud auth configure-docker us-central1-docker.pkg.dev
```

## Runtime Issues

### Edge Function Not Responding

**Symptoms:**
- RAG processor can't validate program ownership
- Processing fails with authentication or network error
- Error message: `Edge function validation failed` or `Connection refused`

**Checks:**

1. Verify Edge Function is deployed:
   ```bash
   supabase functions list | grep validate-program-ownership
   ```

2. Check Edge Function logs:
   ```bash
   supabase functions logs validate-program-ownership --region {your-region}
   ```

3. Test Edge Function directly:
   ```bash
   curl -X POST https://{project}.supabase.co/functions/v1/validate-program-ownership \
     -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
     -H "Content-Type: application/json" \
     -d '{"program_id": "test-uuid", "creator_id": "test-creator-uuid"}'
   ```

4. Verify environment variables in RAG processor:
   ```bash
   gcloud secrets versions access latest --secret=edge-function-base-url-dev
   gcloud secrets versions access latest --secret=supabase-service-role-key-dev
   ```

**Solutions:**

- **If Edge Function not deployed:** Redeploy from monorepo:
  ```bash
  cd application-monorepo/apps/web
  supabase functions deploy validate-program-ownership
  ```

- **If secrets missing:** Add to Secret Manager:
  ```bash
  echo -n "https://your-project.supabase.co/functions/v1" | \
    gcloud secrets versions add edge-function-base-url-dev --data-file=-

  echo -n "your-service-role-key" | \
    gcloud secrets versions add supabase-service-role-key-dev --data-file=-

  # Grant RAG processor access
  gcloud secrets add-iam-policy-binding edge-function-base-url-dev \
    --member="serviceAccount:rag-processor-dev@{PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
  ```

- **If timeout occurs:** Increase Cloud Run timeout:
  ```bash
  # In scripts/deployment_config.py
  timeout_seconds: int = 3600  # Increase from 1800
  ```

### GCS Handler Not Triggering

**Symptoms:**
- File uploaded but no processing starts
- No logs in Cloud Functions

**Checks:**
1. Verify EventArc trigger exists:
   ```bash
   gcloud eventarc triggers list --location=us-central1
   ```

2. Check GCS service account permissions:
   ```bash
   gcloud projects get-iam-policy {PROJECT_ID} \
     --flatten="bindings[].members" \
     --filter="bindings.members:gs-project-accounts"
   ```

3. Re-deploy handler:
   ```bash
   npm run deploy:gcs-handler:dev
   ```

### Cloud Tasks Not Processing

**Symptoms:**
- Tasks stuck in queue
- Task Processor not invoked

**Checks:**
1. View queue status:
   ```bash
   gcloud tasks queues describe rag-processing-queue-dev \
     --location=us-central1
   ```

2. Check for paused queue:
   ```bash
   gcloud tasks queues resume rag-processing-queue-dev \
     --location=us-central1
   ```

3. View failed tasks:
   ```bash
   gcloud tasks list --queue=rag-processing-queue-dev \
     --location=us-central1
   ```

### Missing Docling Model / Safetensors Error

**Symptom:**
```
Document processing failed: Document chunking failed for /tmp/.../file.pdf: Missing safe tensors file: /app/models/docling/model.safetensors
```

**Root Cause:**
Docling's `PdfPipelineOptions(artifacts_path=...)` expects layout model files **at the root** of the artifacts path, not in subdirectories. This error occurs when:

1. **Model structure mismatch:** Models stored in `ds4sd--docling-layout-heron/` subdirectory instead of root
2. **Kaniko cache serving stale models:** Even after fixing GCS, Docker build cache serves old structure

**Solution:**

**Step 1:** Verify GCS has correct flattened structure:
```bash
gcloud storage ls gs://{project-id}-rag-documents-dev/models/docling/
```

Expected output (layout files at ROOT):
```
gs://{project-id}-rag-documents-dev/models/docling/config.json
gs://{project-id}-rag-documents-dev/models/docling/model.safetensors
gs://{project-id}-rag-documents-dev/models/docling/preprocessor_config.json
gs://{project-id}-rag-documents-dev/models/docling/ds4sd--docling-models/
```

**Step 2:** If structure is wrong, delete and re-upload:
```bash
# Delete old models
gcloud storage rm -r gs://{project-id}-rag-documents-dev/models/docling/

# Re-run setup to upload with correct structure
npm run setup:gcp:dev
```

**Step 3:** Bust Kaniko cache to force fresh model download:

Edit `apps/rag-processor/Dockerfile` and increment the cache buster:
```dockerfile
ARG MODEL_CACHE_BUSTER="v3-your-new-version"  # Change this value
```

**Step 4:** Redeploy:
```bash
npm run deploy:processor:dev
```

**Why this happens:**
- Kaniko caches Docker layers based on Dockerfile ARGs, not actual GCS content
- The `MODEL_CACHE_BUSTER` ARG forces cache invalidation when GCS content changes
- See `ai_docs/runbooks/rag-gcp-runbook/10-docling-model-management.md` for full details

### Cloud Run Job Fails

**Symptoms:**
- Job execution shows FAILED status
- Document stuck in `processing` state

**Checks:**
1. View job executions:
   ```bash
   gcloud run jobs executions list \
     --job=rag-processor-dev \
     --region=us-central1
   ```

2. View execution logs:
   ```bash
   gcloud run jobs executions logs {EXECUTION_NAME} \
     --region=us-central1
   ```

3. Common causes:
   - Memory limit exceeded (increase in deployment config)
   - Timeout exceeded (increase timeout)
   - Database connection failed (check DATABASE_URL secret)

### Database Connection Issues

**Symptom:**
```
FATAL: password authentication failed
```

**Solutions:**
1. Verify secret value:
   ```bash
   gcloud secrets versions access latest \
     --secret=database-url-dev
   ```

2. Update secret if incorrect:
   ```bash
   echo -n "postgresql://..." | gcloud secrets versions add database-url-dev --data-file=-
   ```

3. Ensure using pooled connection (port 6543)

### Out of Memory

**Symptom:**
```
Container called exit(137)  # OOMKilled
```

**Solution:**
Increase memory in deployment config (`scripts/deployment_config.py`):
```python
memory: str = "4Gi"  # Increase from 2Gi
```

Then redeploy:
```bash
npm run deploy:processor:dev
```

## LlamaParse Issues

### LlamaParse API Key Not Found

**Symptom:**
```
LlamaIndex document service created, use_llamaparse=False
```
(When you expected LlamaParse to be enabled)

**Checks:**
1. Verify secret exists:
   ```bash
   gcloud secrets describe llamaparse-api-key-dev
   ```

2. Verify secret has a value:
   ```bash
   gcloud secrets versions access latest --secret=llamaparse-api-key-dev
   ```

3. Verify service account has access:
   ```bash
   gcloud secrets get-iam-policy llamaparse-api-key-dev
   ```

**Solution:**
If secret is missing, create it:
```bash
gcloud secrets create llamaparse-api-key-dev --replication-policy=automatic
printf '%s' "llx-YOUR_API_KEY" | gcloud secrets versions add llamaparse-api-key-dev --data-file=-
gcloud secrets add-iam-policy-binding llamaparse-api-key-dev \
  --member="serviceAccount:rag-processor-dev@{PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### LlamaParse Rate Limiting

**Symptom:**
```
LlamaParse API error: Rate limit exceeded
```

**Solutions:**
1. Wait and retry - LlamaParse has per-minute rate limits
2. Enable fallback to use PDFReader when LlamaParse fails:
   ```bash
   # In .env.local
   LLAMAINDEX_FALLBACK_ENABLED=true
   ```
3. Contact LlamaIndex for higher rate limits if processing large volumes

### LlamaParse Timeout

**Symptom:**
```
LlamaParse processing timeout for large PDF
```

**Solution:**
Large PDFs (100+ pages) may take longer. The processor has a 2-hour timeout by default. For very large documents, consider:
1. Splitting the PDF into smaller parts before upload
2. Using the local PDFReader instead (`USE_LLAMAPARSE=false`)

## Embedding Issues

### Embeddings Not Generated

**Symptom:**
- Chunks created but `text_embedding` is NULL

**Checks:**
1. Verify Gemini API key:
   ```bash
   gcloud secrets versions access latest --secret=gemini-api-key-dev
   ```

2. Check AI Platform API enabled:
   ```bash
   gcloud services list --enabled | grep aiplatform
   ```

3. View processor logs for embedding errors

### Vector Search Returns No Results

**Symptom:**
- RAG search returns empty results

**Checks:**
1. Verify embeddings exist:
   ```sql
   SELECT COUNT(*) FROM document_chunks
   WHERE text_embedding IS NOT NULL;
   ```

2. Check embedding dimensions:
   ```sql
   SELECT array_length(text_embedding::real[], 1)
   FROM document_chunks LIMIT 1;
   -- Should return 768
   ```

3. Verify pgvector extension:
   ```sql
   SELECT * FROM pg_extension WHERE extname = 'vector';
   ```

## Viewing Logs

### Cloud Functions Logs

```bash
# GCS Handler
gcloud functions logs read rag-gcs-handler-dev \
  --region=us-central1 \
  --limit=100

# Task Processor
gcloud functions logs read rag-task-processor-dev \
  --region=us-central1 \
  --limit=100
```

### Cloud Run Job Logs

```bash
# List recent executions
gcloud run jobs executions list \
  --job=rag-processor-dev \
  --region=us-central1

# View specific execution logs
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=rag-processor-dev" \
  --limit=100 \
  --format="table(timestamp,textPayload)"
```

### All RAG-Related Logs

```bash
gcloud logging read "rag-processor OR rag-gcs-handler OR rag-task-processor" \
  --limit=200 \
  --format="table(timestamp,resource.type,textPayload)"
```

## Cleanup / Reset

### Delete Failed Job Executions

```bash
# List executions
gcloud run jobs executions list --job=rag-processor-dev --region=us-central1

# Delete specific execution
gcloud run jobs executions delete {EXECUTION_NAME} \
  --job=rag-processor-dev \
  --region=us-central1
```

### Purge Cloud Tasks Queue

```bash
gcloud tasks queues purge rag-processing-queue-dev --location=us-central1
```

### Reset Document Status

```sql
UPDATE documents
SET processing_status = 'pending',
    error_message = NULL
WHERE processing_status = 'error';
```

## Getting Help

1. Check GCP Console for detailed error messages
2. Review Cloud Logging for stack traces
3. Verify all secrets are correctly set
4. Re-run setup script to fix IAM permissions
5. Check Supabase logs for database issues
