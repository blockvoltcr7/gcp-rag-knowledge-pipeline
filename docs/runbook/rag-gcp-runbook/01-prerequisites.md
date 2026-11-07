# Prerequisites

Before deploying the RAG pipeline to GCP, ensure you have the following:

## Required Tools

### 1. Google Cloud SDK (gcloud)

```bash
# Check if installed
gcloud --version

# Expected output:
# Google Cloud SDK 548.0.0 (or later)
```

**Installation:** https://cloud.google.com/sdk/docs/install

### 2. UV Package Manager

```bash
# Check if installed
uv --version

# Expected output:
# uv 0.7.x (or later)
```

**Installation:** https://github.com/astral-sh/uv

### 3. Node.js and npm

```bash
# Check versions
node --version  # v18+ recommended
npm --version   # v9+ recommended
```

## GCP Account Setup

### 1. Authenticate with GCP

```bash
# Login to GCP
gcloud auth login

# Set application default credentials
gcloud auth application-default login

# Verify authentication
gcloud auth list
```

### 2. Select or Create Project

```bash
# List available projects
gcloud projects list

# Set active project
gcloud config set project YOUR_PROJECT_ID

# Verify
gcloud config get-value project
```

### 3. Enable Billing

Ensure billing is enabled for your project in the GCP Console:
https://console.cloud.google.com/billing

## Environment Variables

Create or update `apps/web/.env.local` with:

```bash
# GCP Configuration
GOOGLE_CLOUD_PROJECT_ID="your-project-id"
GOOGLE_CLOUD_REGION="us-central1"

# Database (Supabase pooled connection - port 6543)
DATABASE_URL="postgresql://postgres.xxxxx:password@region.pooler.supabase.com:6543/postgres"

# Optional: Gemini API key (for embeddings)
GEMINI_API_KEY="your-gemini-api-key"
```

### Getting the Database URL

1. Go to Supabase Dashboard → Settings → Database → Connection String
2. Select **Transaction pooler** (NOT direct connection)
3. Copy the connection string with port `6543`
4. Replace `[YOUR-PASSWORD]` with your actual database password

## Supabase Configuration

### 1. Enable pgvector Extension

In Supabase Dashboard → Database → Extensions, ensure `vector` is enabled.

### 2. Create Storage Bucket

The `creator-documents` bucket should exist in Supabase Storage with:
- 50MB file size limit
- Allowed MIME types: PDF, DOCX, TXT, images, audio, video

**Path Structure:** Documents are organized by program within creator directories:
`documents/{creator_id}/{program_id}/{filename}`

### 3. Run Database Migrations

```bash
cd apps/web
npm run db:migrate
```

## Edge Function Setup

The RAG processor validates program ownership through a Supabase Edge Function rather than direct database queries to maintain domain isolation. This must be set up before deployment.

### 1. Deploy Edge Function (in monorepo)

The `validate-program-ownership` Edge Function is defined in the monorepo and must be deployed to Supabase before RAG processor deployment.

```bash
# From application-monorepo root directory (monorepo)
cd apps/web
supabase functions deploy validate-program-ownership
```

**Expected output:**
```
✓ Function deployed successfully
  Endpoint: https://<project>.supabase.co/functions/v1/validate-program-ownership
```

### 2. Configure RAG Processor Environment

Add Edge Function URL and credentials to RAG processor `.env.local`:

```bash
# Edge Function endpoint (from deployment output above)
EDGE_FUNCTION_BASE_URL=https://<project>.supabase.co/functions/v1

# Service role key for authentication (found in Supabase → Settings → API Keys)
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

### 3. Test Edge Function

```bash
curl -X POST https://<project>.supabase.co/functions/v1/validate-program-ownership \
  -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
  -H "Content-Type: application/json" \
  -d '{"program_id": "test-uuid", "creator_id": "test-creator-uuid"}'
```

**Expected response:**
```json
{"is_owner": false}
```

(Returns `false` for invalid UUIDs, which is expected)

## Checklist

- [ ] gcloud CLI installed and authenticated
- [ ] uv package manager installed
- [ ] GCP project selected with billing enabled
- [ ] `GOOGLE_CLOUD_PROJECT_ID` set in `.env.local`
- [ ] `DATABASE_URL` set (pooled connection, port 6543)
- [ ] pgvector extension enabled in Supabase
- [ ] creator-documents storage bucket exists
- [ ] Database migrations applied
- [ ] Edge Function `validate-program-ownership` deployed to Supabase
- [ ] `EDGE_FUNCTION_BASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` configured in RAG processor

## Next Step

Once all prerequisites are met, proceed to [GCP Setup](./02-gcp-setup.md).
