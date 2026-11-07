# GCP RAG Knowledge Pipeline: architecture and flows

Open `rag-architecture.html` for the interactive component map. It describes the checked-out source, not a verified deployment. The upstream application is outside the reviewed repository.

## Upload and dispatch

1. An object-finalized event reaches the GCS handler. It looks up an existing `ai.documents` record by GCS path and transitions an `uploading` document to `processing`; it creates or updates the processing job. A missing document does not proceed. [Handler](../../apps/rag-gcs-handler/main.py#L254)
2. Only a successful document transition causes a named Cloud Task to be enqueued. The task sends an OIDC-authenticated HTTP request. If enqueueing fails, the handler reverts the document status. [Enqueue](../../apps/rag-gcs-handler/main.py#L391) · [Transition and failure handling](../../apps/rag-gcs-handler/main.py#L513)
3. The task processor starts a Cloud Run Job with per-execution environment overrides and returns after initiation. That response does not establish processing success. [Task processor](../../apps/rag-task-processor/main.py#L113)

## Processing and persistence

1. The job validates program ownership through a Supabase Edge Function before invoking processing. [Entry point](../../apps/rag-processor/rag_processor/main.py#L25)
2. It downloads the file and routes it to document, video, audio, or image processing. Document processing uses the selected document service and generates missing text embeddings; image processing produces text and multimodal embeddings. [Processing service](../../apps/rag-processor/rag_processor/services/processing_service.py#L60)
3. The processor writes chunks and vectors to `ai.document_chunks`, replacing prior chunks for the document transactionally, and updates job/document status. An empty chunk list skips storage. [Database service](../../apps/rag-processor/rag_processor/services/database_service.py#L578) · [Status handling](../../apps/rag-processor/rag_processor/services/processing_service.py#L501)

The reviewed runtime is an ingestion pipeline; no retrieval or chat endpoint was identified in the reviewed code. Deployment scripts and workflows describe intended configuration, not evidence of a live deployment.
