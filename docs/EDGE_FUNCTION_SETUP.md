# Edge Function Setup: validate-program-ownership

## Overview

The `validate-program-ownership` Edge Function provides a centralized validation service for the RAG processor. Instead of directly querying the `creator.programs` table, the RAG processor calls this Edge Function, maintaining domain isolation and security.

## Function Details

**Location**: `apps/web/supabase/functions/validate-program-ownership/index.ts` (in monorepo)

**Endpoint**: `POST /validate-program-ownership`

**Runtime**: Deno (TypeScript)

## Request Format

```json
{
  "program_id": "uuid-string",
  "creator_id": "uuid-string"
}
```

## Response Format

**Success (200 OK)**:
```json
{
  "is_owner": true
}
```

**Error (400+ status)**:
```json
{
  "is_owner": false,
  "error": "error message"
}
```

## Deployment

### Prerequisites
- Supabase CLI installed
- Authenticated to Supabase project
- SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY available

### Deploy to Development

```bash
cd /path/to/application-monorepo/apps/web

# Deploy function
supabase functions deploy validate-program-ownership

# Verify deployment
supabase functions list

# Get function URL
# Format: https://[project-id].supabase.co/functions/v1/validate-program-ownership
```

### Deploy to Production

```bash
# Link to production project (if not already linked)
supabase link --project-ref prod-project-id

# Deploy to production
supabase functions deploy validate-program-ownership --project-ref prod-project-id
```

## Testing

### Test with cURL

```bash
# Get required values
SUPABASE_URL="https://your-project.supabase.co"
SERVICE_ROLE_KEY="your-service-role-key"
PROGRAM_ID="test-program-uuid"
CREATOR_ID="test-creator-uuid"

# Test endpoint
curl -X POST "${SUPABASE_URL}/functions/v1/validate-program-ownership" \
  -H "Authorization: Bearer ${SERVICE_ROLE_KEY}" \
  -H "Content-Type: application/json" \
  -d "{
    \"program_id\": \"${PROGRAM_ID}\",
    \"creator_id\": \"${CREATOR_ID}\"
  }"
```

### Test with Python (from RAG Processor)

```python
import httpx
import os

async def test_validation():
    edge_function_url = "https://your-project.supabase.co/functions/v1"
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{edge_function_url}/validate-program-ownership",
            json={
                "program_id": "test-uuid",
                "creator_id": "test-creator-uuid"
            },
            headers={
                "Authorization": f"Bearer {service_role_key}",
                "Content-Type": "application/json",
            },
            timeout=10.0,
        )
        result = response.json()
        print(f"Is owner: {result['is_owner']}")
```

## Configuration in RAG Processor

### Required Environment Variables

```bash
# .env.local
EDGE_FUNCTION_BASE_URL=https://your-project.supabase.co/functions/v1
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
```

### Implementation in rag-processor/main.py

The RAG processor calls this function during startup to validate that the creator owns the program being processed:

```python
async def validate_program_ownership(
    program_id: str, creator_id: str
) -> bool:
    """Validate program ownership via Edge Function."""
    edge_function_url = os.getenv("EDGE_FUNCTION_BASE_URL")
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{edge_function_url}/validate-program-ownership",
            json={"program_id": program_id, "creator_id": creator_id},
            headers={
                "Authorization": f"Bearer {service_role_key}",
                "Content-Type": "application/json",
            },
            timeout=10.0,
        )
        response.raise_for_status()
        result = response.json()
        return result.get("is_owner", False)
```

## Error Handling

### HTTP Status Codes

| Status | Meaning | Response |
|--------|---------|----------|
| 200 | Success | `{"is_owner": true\|false}` |
| 400 | Bad Request | Missing/invalid parameters |
| 500 | Server Error | Database or auth error |

### Common Errors

**Missing parameters**:
- Ensure both `program_id` and `creator_id` are provided
- Both must be valid UUID strings

**Authentication failures**:
- Verify SUPABASE_SERVICE_ROLE_KEY is correct
- Check Bearer token format: `Authorization: Bearer <key>`

**Database errors**:
- Verify database connection is healthy
- Check that `programs` table exists in public schema
- Ensure service role has SELECT permission on programs table

## Security Considerations

### Access Control
- Function uses Supabase's built-in CORS handling
- Requires Bearer token authentication (service role key)
- Only accepts POST requests

### Data Privacy
- Function only returns boolean (is_owner)
- No sensitive data exposed in responses
- Errors logged but not exposed to client

### Rate Limiting
- Supabase Functions inherit platform rate limits
- Monitor for DDoS attacks on this endpoint
- Consider adding request throttling if needed

## Monitoring & Logs

### View Function Logs

```bash
# Local development
supabase functions serve validate-program-ownership

# Production logs via Supabase dashboard
# https://app.supabase.com/project/[project-id]/functions
```

### Monitor from RAG Processor

RAG processor logs all validation attempts:
```
Program ownership validated: program_id=xxx, user_id=yyy
Program ownership validation failed: program_id=xxx, user_id=yyy
```

## Troubleshooting

### Function not found (404)
- Verify function is deployed: `supabase functions list`
- Check function URL format
- Confirm project ID is correct

### Unauthorized (401/403)
- Verify SERVICE_ROLE_KEY is valid
- Check Bearer token format
- Confirm key has required permissions

### Timeout errors
- Check database connection latency
- Increase timeout in RAG processor (default: 10 seconds)
- Monitor function execution time in Supabase dashboard

### Wrong validation result
- Verify program exists in database
- Check creator_id matches database value
- Confirm no RLS policies blocking service role access

## Maintenance

### Updates
When updating the Edge Function:

```bash
# Make changes to index.ts
# ... edit code ...

# Redeploy
supabase functions deploy validate-program-ownership

# Test immediately after deployment
curl ... # test command above
```

### Versioning
- Function updates are deployed immediately
- No downtime during redeployment
- Test in dev before updating prod

### Backup
- Function code is version controlled in Git
- Database backups handled separately
- No state stored in function itself

## Related Documentation

- **RAG Processor**: See `DEPLOYMENT.md` for Edge Function configuration
- **Security**: Domain isolation prevents cross-boundary database access
- **Architecture**: See README.md for system overview
