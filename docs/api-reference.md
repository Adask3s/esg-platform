# API Reference

All endpoints are served by the FastAPI backend. Authentication is required for all user-scoped routes via a JWT bearer token in the `Authorization` header.

## Authentication

### POST /auth/register
Register a new user account.

**Request body:**
```json
{
  "email": "string",
  "password": "string"
}
```

**Response:** `201 Created` with user ID.

### POST /auth/login
Authenticate and receive a JWT token.

**Request body:**
```json
{
  "email": "string",
  "password": "string"
}
```

**Response:**
```json
{
  "access_token": "string",
  "token_type": "bearer"
}
```

---

## Documents

### POST /documents/upload
Upload one or more documents for processing.

**Auth:** Required

**Request:** `multipart/form-data`
- `files` — one or more files (PDF, DOCX, XLSX)
- `tags` — optional comma-separated tag list

**Response:**
```json
{
  "document_ids": ["uuid", "..."],
  "task_ids": ["celery-task-id", "..."]
}
```

Processing (parsing, chunking, embedding) is performed asynchronously. Use the task status endpoint to poll progress.

### GET /documents
List all documents belonging to the authenticated user.

**Auth:** Required

**Response:** Array of document metadata objects including `id`, `filename`, `status`, `created_at`.

### DELETE /documents/{document_id}
Delete a document and all its associated chunks and embeddings.

**Auth:** Required

---

## Tasks

### GET /tasks/{task_id}
Check the status of an asynchronous Celery task.

**Auth:** Required

**Response:**
```json
{
  "task_id": "string",
  "status": "PENDING | STARTED | SUCCESS | FAILURE",
  "result": null
}
```

---

## Chat / Q&A

### POST /ask/chat
Submit a question against the user's documents and the ESG knowledge base.

**Auth:** Required

**Request body:**
```json
{
  "question": "string",
  "tags": ["optional", "tag", "filters"],
  "conversation_id": "uuid (optional, for history)"
}
```

**Response:**
```json
{
  "answer": "string",
  "sources": [
    {
      "chunk_text": "string",
      "source": "user_document | knowledge_base",
      "document_id": "uuid",
      "similarity": 0.91
    }
  ],
  "conversation_id": "uuid"
}
```

### GET /ask/chat/{conversation_id}/history
Retrieve paginated chat history for a conversation.

**Auth:** Required

**Query params:** `page` (default 1), `page_size` (default 20)

---

## Report Generation

### POST /report/generate
Trigger asynchronous ESG report generation.

**Auth:** Required

**Request body:**
```json
{
  "title": "string",
  "tags": ["optional", "tag", "filters"],
  "standard": "GRI | SASB | TCFD",
  "document_ids": ["uuid", "..."]
}
```

**Response:**
```json
{
  "report_id": "uuid",
  "task_id": "string"
}
```

### GET /report/download/{task_id}
Download a generated report as a PDF, streamed directly from the cached Celery task result.

**Auth:** Required

**Path params:**
- `task_id` — the ID returned from `/report/generate`

**Behavior:**
- Verifies that the authenticated user owns the task.
- Verifies that the task state is `SUCCESS`. Returns `400` if it is still pending or has failed.
- Reads the structured `ReportData` payload from the task result, renders it to PDF via ReportLab, and streams the binary response.
- The LLM is **not** re-run; this endpoint is purely a render-and-download operation.

**Response:** `application/pdf` with header `Content-Disposition: attachment; filename="raport_<kategoria>.pdf"`.

**Error responses:**
| Status | Cause |
|--------|-------|
| 400 | Task is not in `SUCCESS` state |
| 401 | Missing or invalid token |
| 403 | The task does not belong to the authenticated user |
| 404 | Task succeeded but contains no report payload |
| 500 | PDF rendering error |

### GET /report/{report_id}
Retrieve a generated report by ID.

**Auth:** Required

**Response:** Report object with `id`, `title`, `content`, `standard`, `created_at`.

### GET /report
List all reports for the authenticated user.

**Auth:** Required

---

## Knowledge Base

### POST /knowledge/upload
Upload a document to the shared ESG knowledge base (admin only).

**Auth:** Required (admin role)

**Request:** `multipart/form-data` — single file

### GET /knowledge
List knowledge base entries.

**Auth:** Required

---

## Embeddings

### POST /embeddings/reindex/{document_id}
Re-trigger the embedding pipeline for an existing document (e.g., after a knowledge base update).

**Auth:** Required

---

## Error Responses

All error responses follow the standard FastAPI format:

```json
{
  "detail": "Human-readable error message"
}
```

| HTTP Status | Meaning |
|-------------|---------|
| 400 | Bad request — malformed input |
| 401 | Unauthorized — missing or invalid token |
| 403 | Forbidden — insufficient permissions |
| 404 | Resource not found |
| 422 | Validation error — request body schema mismatch |
| 500 | Internal server error |
