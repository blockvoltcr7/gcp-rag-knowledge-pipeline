# Testing the RAG Pipeline

After deployment, verify the pipeline works end-to-end.

## Test Flow

```
Upload document → GCS → Handler → Task Queue → Processor → pgvector
```

## Method 1: Via Web App (Recommended)

### 1. Login as Creator

1. Start the web app: `npm run dev` (from `apps/web`)
2. Login with a creator account
3. Navigate to `/creator/documents`

### 2. Upload a Test Document

1. Click "Upload Document"
2. Select a PDF, DOCX, or TXT file
3. Observe the status changes:
   - `uploading` → `pending` → `processing` → `completed`

### 3. Verify Processing

Check the document list shows:
- Status: `completed`
- Chunk count: > 0
- No errors

### 4. Test RAG Chat

1. Navigate to creator chat/test interface
2. Ask a question about content in the uploaded document
3. Verify the AI response references the document content

## Method 2: Via GCS Direct Upload

### 1. Upload to GCS Bucket

```bash
# Upload a test file
gsutil cp test-document.pdf gs://{project-id}-rag-documents-dev/documents/{creator-id}/{program-id}/

# Or via GCP Console:
# 1. Go to Cloud Storage
# 2. Navigate to your bucket
# 3. Upload file to documents/{creator-id}/{program-id}/ folder
```

**Note:** When testing via direct GCS upload, you must use a valid program_id that exists in your database. The RAG processor will validate that the program exists before processing.

### 2. Monitor Processing

```bash
# Check Cloud Tasks queue
gcloud tasks queues describe rag-processing-queue-dev \
  --location=us-central1

# Check Cloud Run Job executions
gcloud run jobs executions list \
  --job=rag-processor-dev \
  --region=us-central1
```

### 3. Check Logs

```bash
# GCS Handler logs
gcloud functions logs read rag-gcs-handler-dev \
  --region=us-central1 \
  --limit=50

# Task Processor logs
gcloud functions logs read rag-task-processor-dev \
  --region=us-central1 \
  --limit=50

# RAG Processor logs
gcloud run jobs executions logs rag-processor-dev \
  --region=us-central1
```

## Method 3: Database Verification

### Check Documents Table

```sql
SELECT id, file_name, processing_status, chunk_count, created_at
FROM documents
WHERE human_creator_id = '{creator-id}'
ORDER BY created_at DESC;
```

### Check Document Chunks

```sql
SELECT
  dc.id,
  dc.content,
  dc.chunk_index,
  d.file_name
FROM document_chunks dc
JOIN documents d ON d.id = dc.document_id
WHERE d.human_creator_id = '{creator-id}'
LIMIT 10;
```

### Verify Embeddings Exist

```sql
SELECT
  id,
  LENGTH(text_embedding::text) as embedding_length
FROM document_chunks
WHERE document_id = '{document-id}'
LIMIT 5;
```

## Expected Results

### Successful Processing

| Stage | Expected |
|-------|----------|
| GCS Upload | File appears in bucket |
| Handler Triggered | Task created in queue |
| Task Processed | Cloud Run Job executed |
| Document Updated | Status = `completed` |
| Chunks Created | chunk_count > 0 |
| Embeddings Generated | 768-dimension vectors |

### Timing Expectations

| Document Size | Processing Time |
|---------------|-----------------|
| Small (< 10 pages) | 30-60 seconds |
| Medium (10-50 pages) | 1-3 minutes |
| Large (50+ pages) | 3-10 minutes |

## Test RAG Search

After processing, test the vector search:

```sql
-- Test similarity search (replace with actual query embedding)
SELECT
  dc.content,
  dc.chunk_index,
  d.file_name,
  1 - (dc.text_embedding <=> '{query_embedding}') as similarity
FROM document_chunks dc
JOIN documents d ON d.id = dc.document_id
WHERE d.human_creator_id = '{creator-id}'
ORDER BY dc.text_embedding <=> '{query_embedding}'
LIMIT 5;
```

## Verification Checklist

- [ ] Document uploaded to GCS bucket
- [ ] GCS Handler function triggered (check logs)
- [ ] Task created in Cloud Tasks queue
- [ ] Task Processor invoked RAG Processor (check logs)
- [ ] Cloud Run Job completed successfully
- [ ] Document status updated to `completed`
- [ ] Document chunks created in database
- [ ] Embeddings (768 dimensions) stored
- [ ] RAG search returns relevant results

## Next Step

If issues occur, see [Troubleshooting](./05-troubleshooting.md).
