# Deployment Guide: GCP RAG Knowledge Pipeline

This document provides step-by-step instructions for deploying the RAG pipeline to production.

## Phase 3 Completion Status

### ✅ Completed
- [x] **Task 008**: Repository created, applications moved, dependencies resolved
  - 3 RAG applications copied (processor, gcs-handler, task-processor)
  - 9 deployment scripts + 7 shared utilities migrated
  - Environment templates created (.env.example files)
  - Python imports verified

- [x] **Task 009**: Deployment scripts migrated and verified
  - Path references verified (work in new repository structure)
  - All modules import successfully
  - Configuration loading tested
  - Environment files load correctly for all apps

- [x] **Task 010**: CI/CD setup complete
  - 6 GitHub Actions workflows created (dev + prod for each app)
  - YAML syntax validated
  - Workflow triggers configured for automatic deployment

- [x] **Critical Fix**: Database violation resolved
  - Replaced direct creator.programs query with Edge Function call
  - Added async validate_program_ownership() function
  - Created Edge Function in monorepo (validate-program-ownership)

### ⏳ Remaining Work (Next Session)
1. Deploy Edge Function to monorepo
2. Create GitHub repository
3. Configure GitHub secrets
4. Push code to GitHub
5. Verify first deployment
6. End-to-end smoke test

## Pre-Deployment Checklist

### Infrastructure Requirements
- [ ] GCP project set up with billing enabled
- [ ] Service accounts created (dev + prod)
- [ ] Cloud APIs enabled:
  - [ ] Cloud Run API
  - [ ] Cloud Functions API
  - [ ] Cloud Storage API
  - [ ] Cloud Build API
  - [ ] Vertex AI API
  - [ ] Secret Manager API
- [ ] PostgreSQL database provisioned
- [ ] GCS buckets created

### Application Requirements
- [ ] All .env files populated with actual values
- [ ] Service account keys downloaded (JSON format)
- [ ] Supabase project configured
- [ ] Edge Function deployed

## Step-by-Step Deployment

### Step 1: Deploy Edge Function (Monorepo)

This MUST be done before RAG processor is deployed.

```bash
cd /path/to/application-monorepo/apps/web

# Deploy the validate-program-ownership function
supabase functions deploy validate-program-ownership

# Note the function URL: https://[project].supabase.co/functions/v1/validate-program-ownership
```

### Step 2: Create GitHub Repository

```bash
cd /path/to/gcp-rag-knowledge-pipeline

# Create the GitHub repository
# Option A: If you have gh CLI configured
gh repo create YOUR_GITHUB_ORG/gcp-rag-knowledge-pipeline \
  --private \
  --source=. \
  --remote=origin \
  --description="RAG Pipeline: Document processing with Docling, Vertex AI embeddings, and pgvector"

# Option B: Create manually on GitHub and add remote
# Then run:
# git remote add origin https://github.com/YOUR_GITHUB_ORG/gcp-rag-knowledge-pipeline.git
# git branch -M main
# git push -u origin main
```

### Step 3: Configure GitHub Secrets

Required secrets for development environment:

```bash
# Set development secrets
gh secret set GCP_SA_KEY_DEV --body "$(cat ~/path/to/dev-sa-key.json)"
gh secret set GCP_PROJECT_ID_DEV --body "your-project-dev"
gh secret set DATABASE_URL_DEV --body "postgresql://user:pass@host:5432/dbname"
gh secret set GEMINI_API_KEY --body "your-gemini-api-key"

# Set production secrets (after dev testing)
gh secret set GCP_SA_KEY_PROD --body "$(cat ~/path/to/prod-sa-key.json)"
gh secret set GCP_PROJECT_ID_PROD --body "your-project-prod"
gh secret set DATABASE_URL_PROD --body "postgresql://user:pass@host:5432/dbname"
gh secret set GEMINI_API_KEY_PROD --body "your-gemini-api-key-prod"
```

**Secret Details:**
- `GCP_SA_KEY_DEV/PROD`: Full service account JSON (base64 encoded if needed)
- `GCP_PROJECT_ID_DEV/PROD`: GCP project ID (e.g., "your-gcp-project-id")
- `DATABASE_URL_DEV/PROD`: PostgreSQL connection string with pooler
- `GEMINI_API_KEY`: Google Gemini API key from AI Studio

### Step 4: Update .env.local Files

For each RAG application, create `.env.local` from `.env.example`:

```bash
# RAG Processor
cd apps/rag-processor
cp .env.example .env.local
# Edit .env.local with actual values:
# - GOOGLE_CLOUD_PROJECT_ID
# - DATABASE_URL
# - GEMINI_API_KEY
# - EDGE_FUNCTION_BASE_URL (from deployed Edge Function)
# - SUPABASE_SERVICE_ROLE_KEY

# GCS Handler
cd ../rag-gcs-handler
cp .env.example .env.local
# Edit with actual values

# Task Processor
cd ../rag-task-processor
cp .env.example .env.local
# Edit with actual values
```

### Step 5: Push to GitHub

```bash
cd /path/to/gcp-rag-knowledge-pipeline

# Add all files
git add .

# Verify status before pushing
git status

# Push to GitHub
git push -u origin main
```

### Step 6: Monitor First Deployment

```bash
# Watch for workflow runs
gh workflow list

# Monitor the dev deployment
gh workflow run rag-processor-dev.yml
gh run watch

# Check deployment status
gcloud run jobs describe rag-processor-dev --region us-central1
```

### Step 7: End-to-End Smoke Test

```bash
# 1. Create a test document in the web app
# 2. Upload to GCS via signed URL
# 3. Verify GCS upload triggered gcs-handler:
gcloud functions logs read rag-gcs-handler-dev --limit 50

# 4. Check that processing job was created:
psql $DATABASE_URL_DEV -c "SELECT id, status FROM ai.document_processing_jobs ORDER BY created_at DESC LIMIT 1;"

# 5. Monitor rag-processor job:
gcloud run jobs logs rag-processor-dev --limit 100

# 6. Verify chunks were written:
psql $DATABASE_URL_DEV -c "SELECT COUNT(*) FROM ai.document_chunks WHERE document_id = '[test-id]';"

# 7. Test similarity search via API
curl -X POST https://[supabase-url]/functions/v1/rag-search \
  -H "Authorization: Bearer [ANON_KEY]" \
  -H "Content-Type: application/json" \
  -d '{"query": "test query", "program_id": "[program-id]"}'
```

## Troubleshooting

### GitHub Actions Failures

**Workflow not triggered:**
- Verify paths in `paths:` section match changed files
- Check `on:` triggers (push branches, tags, workflow_dispatch)
- Ensure secrets are configured correctly

**Deployment script errors:**
- Check CloudBuild logs: `gcloud builds log [BUILD_ID]`
- Verify environment variables are set
- Ensure service account has required permissions

### Processing Job Failures

**Job status: FAILED**
```bash
# Check job logs
gcloud run jobs logs rag-processor-dev --limit 200

# Check database error log
psql $DATABASE_URL_DEV -c "SELECT error_message FROM ai.document_processing_jobs WHERE status = 'failed' ORDER BY updated_at DESC LIMIT 1;"
```

**Program ownership validation fails:**
- Verify Edge Function is deployed and accessible
- Check EDGE_FUNCTION_BASE_URL is correct
- Verify SUPABASE_SERVICE_ROLE_KEY has sufficient permissions
- Test Edge Function directly:
  ```bash
  curl -X POST https://[project].supabase.co/functions/v1/validate-program-ownership \
    -H "Authorization: Bearer [SERVICE_ROLE_KEY]" \
    -H "Content-Type: application/json" \
    -d '{"program_id": "test-id", "creator_id": "user-id"}'
  ```

**Database connection timeouts:**
- Verify DATABASE_URL is correct
- Check PostgreSQL connection limits
- Ensure IP allowlist includes Cloud Run IPs
- Monitor pool usage: `PGPASSWORD=$pass psql -h $host -d $db -c "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database;"`

### Document Processing Issues

**Chunks not being written:**
1. Check Docling service logs for parsing errors
2. Verify Vertex AI API is enabled and quota available
3. Check pgvector extension is installed: `psql $DATABASE_URL -c "SELECT * FROM pg_extension WHERE extname = 'vector';"`
4. Verify HNSW indexes exist: `psql $DATABASE_URL -c "SELECT * FROM pg_stat_user_indexes WHERE indexname LIKE '%embedding%';"`

**Embedding generation fails:**
- Verify GEMINI_API_KEY is valid
- Check Google AI quota
- Verify Vertex AI API is enabled
- Check service account permissions for Vertex AI

### Cloud Function Errors

**GCS Handler fails to invoke:**
- Check EventArc trigger configuration
- Verify GCS bucket notifications are enabled
- Check Cloud Function permissions
- Monitor function logs: `gcloud functions logs read rag-gcs-handler-dev --limit 50`

**Task Processor doesn't execute:**
- Verify Cloud Tasks queue exists
- Check task processor function permissions
- Monitor Cloud Tasks logs for enqueue failures
- Verify task payload format

## Production Deployment

### Before Prod Deployment

1. **Test in Dev Environment**
   - Process multiple document types (PDF, DOCX, images)
   - Verify all chunks are created with correct embeddings
   - Test similarity search with real queries
   - Monitor performance and costs

2. **Database Scaling**
   - Review query performance
   - Optimize HNSW index parameters
   - Plan for pgvector maintenance (VACUUM, ANALYZE)
   - Set up monitoring alerts

3. **Cost Analysis**
   - Monitor Cloud Run job costs
   - Track Vertex AI API usage
   - Review storage costs for GCS
   - Estimate monthly costs

4. **Security Review**
   - Verify RLS policies on RAG tables
   - Audit service account permissions
   - Review secrets management
   - Test error handling for sensitive data

### Prod Deployment Steps

```bash
# 1. Deploy to production environment
gh workflow run rag-processor-prod.yml
gh run watch

# 2. Verify all 3 apps deployed successfully
gcloud run jobs describe rag-processor-prod --region us-central1
gcloud functions describe rag-gcs-handler-prod --region us-central1
gcloud functions describe rag-task-processor-prod --region us-central1

# 3. Test with real documents
# Use web app to upload production documents
# Monitor processing through database

# 4. Monitor for 24 hours
# Check error rates, performance, costs
```

## Maintenance & Monitoring

### Daily Checks
```bash
# Check for failed processing jobs
psql $DATABASE_URL -c "SELECT COUNT(*) FROM ai.document_processing_jobs WHERE status = 'failed' AND created_at > now() - interval '24 hours';"

# Monitor Cloud Run costs
gcloud billing accounts list
gcloud compute project-info describe $PROJECT_ID --format="value(quotas[].usage)"
```

### Weekly Tasks
- Review processing job error messages
- Check Vertex AI API usage and quotas
- Monitor database performance
- Review Cloud Logs for errors

### Monthly Tasks
- Optimize HNSW indexes
- Review and rotate service account keys
- Update dependencies (`uv update`)
- Performance optimization review

## Rollback Plan

If deployment fails:

```bash
# Revert to previous version
git revert HEAD
git push origin main

# Stop current deployment
gcloud run jobs cancel rag-processor-[env]

# Restore from backup
# Contact cloud team for GCS/database recovery
```

## Success Metrics

After deployment, verify:
- ✅ Documents process within 2 minutes
- ✅ Embeddings generated with <50ms latency
- ✅ Chunks searchable via similarity search
- ✅ Error rate <0.1%
- ✅ API response time <500ms for search
- ✅ Cost <$X per 1M tokens

## Next Steps

1. **Week 1**: Deploy to dev, test processing pipeline
2. **Week 2**: Load test with production volume, optimize
3. **Week 3**: Deploy to production, monitor
4. **Week 4+**: Performance optimization, cost management

## Support & Documentation

- **Architecture**: See README.md
- **API Reference**: See CLAUDE.md for development notes
- **GCP Setup**: See `scripts/setup_gcp_dev.py`
- **Issues**: Check CloudBuild logs and database error messages
