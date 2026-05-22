# API Reference

FastAPI serves the backend API. User-scoped endpoints require a JWT bearer token
in the `Authorization: Bearer <token>` header unless stated otherwise.

## Authentication

### POST `/auth/login`

Authenticates a user with `OAuth2PasswordRequestForm`.

Request content type: `application/x-www-form-urlencoded`

Fields:
- `username`
- `password`

Response:

```json
{
  "access_token": "string",
  "token_type": "bearer"
}
```

### POST `/auth/signup`

Creates a user account and returns a bearer token. Signup is disabled by default
unless `SIGNUP_ENABLED=true`.

Request body:

```json
{
  "username": "string",
  "email": "optional@example.com",
  "password": "string"
}
```

### POST `/auth/contact`

Accepts a simple contact form payload:

```json
{
  "email": "string",
  "problem": "string"
}
```

## Task Status

### GET `/status/{task_id}`

Returns normalized Celery task status. If the task owner was registered in Redis,
the endpoint verifies that the authenticated user owns the task.

Response shape:

```json
{
  "task_id": "string",
  "state": "PENDING | STARTED | PROGRESS | RETRY | SUCCESS | FAILURE",
  "progress": 0,
  "stage": "string | null",
  "stage_pl": "string | null",
  "filename": "string | null",
  "attempts": 1,
  "result": {},
  "error": null,
  "updated_at": "ISO-8601"
}
```

## User Documents

### POST `/user/documents/upload`

Uploads one user document and starts the parse/chunk/embed Celery pipeline.

Request content type: `multipart/form-data`

Fields:
- `file`: PDF, DOCX, XLSX/CSV, TXT or supported text-like file
- `tag`: optional ESG tag, for example `Environmental`, `Social`, `Governance`

Response:

```json
{
  "task_id": "celery-task-id",
  "status": "queued",
  "message": "Dokument jest przetwarzany w tle. Sprawdz /status/{task_id} po wynik."
}
```

### POST `/user/documents/delete`

Deletes a user document and related chunks.

Request body:

```json
{
  "document_id": "uuid"
}
```

### GET `/documents/mine`

Lists documents for the authenticated user from Supabase.

### GET `/documents/knowledge`

Lists knowledge-base documents. Admin only.

### GET `/documents/`

Lists documents through the document getter router.

## Knowledge Base

### POST `/knowledge/upload`

Admin-only multi-file upload to the ESG knowledge base. Each accepted file starts
a background parsing task.

Request content type: `multipart/form-data`

Fields:
- `files`: one or more files
- `tag`: optional, defaults to `general`
- `document_type`: optional, defaults to `general`
- `version`: optional, defaults to `1.0`

### POST `/knowledge/parse-and-store`

Admin-only endpoint for parsing a file and storing it in
`knowledge_documents`/`knowledge_chunks`.

## Embeddings

### POST `/embeddings/generate-for-document`

Starts embedding generation for a selected document/chunk table target.

### POST `/embeddings/generate-for-tag`

Starts embedding generation for chunks matching a tag.

### POST `/embeddings/generate-all`

Starts bulk embedding generation.

### GET `/embeddings/status`

Returns basic embedding subsystem status.

## Reports

### POST `/report/generate`

Starts asynchronous ESG report generation.

Request body:

```json
{
  "report_scope": "Environmental | Social | Governance | ESG",
  "standard": "GRI | SASB | TCFD"
}
```

`standard` is optional for backward compatibility. If omitted, the backend uses
`GRI`. The selected standard is injected into the report-generation prompt with
the static checklist from `backend/report_validation.py`.

Response:

```json
{
  "task_id": "celery-task-id",
  "status": "queued",
  "message": "Raport jest generowany w tle. Sprawdz /status/{task_id} po wynik."
}
```

Partial scopes (`Environmental`, `Social`, `Governance`) try tag aliases only.
`ESG` runs without a tag filter. The task result contains:
- `status`: `success` or `partial_success`
- `kategoria`
- `standard`: selected reporting standard
- `applied_filter`
- `report_id`: stored report id when database persistence succeeds
- `used_chunks`
- `data`: structured report JSON or `null`

The report JSON keeps legacy fields and may include richer fields:
`standard_raportowania`, `streszczenie_wykonawcze`, `zakres_i_metodyka`,
`szczegolowa_analiza`, `luki_w_danych`, `rekomendacje`,
`zgodnosc_ze_standardami`.

### GET `/report/download/{task_id}`

Downloads a generated report as PDF from the cached Celery task result. This does
not call the LLM again.

Behavior:
- Requires the task to be in `SUCCESS`.
- Verifies task ownership when owner metadata exists in Redis.
- Maps task `data` to `ReportData`.
- For `partial_success`, renders an empty-state PDF with the message.
- Returns `application/pdf` with `Content-Disposition`.

### POST `/report/{report_id}/validate`

Validates a stored report against a selected disclosure standard. The validation
uses the stored report JSON and parsed `used_chunks`, calls the LLM once, and
does not persist the validation result.

Request body:

```json
{
  "standard": "GRI | SASB | TCFD"
}
```

Response:

```json
{
  "status": "success",
  "report_id": "123",
  "standard": "GRI",
  "overall_status": "complete | partial | missing",
  "score": 75,
  "items": [
    {
      "code": "GRI 305-1",
      "label": "Direct Scope 1 GHG emissions",
      "present": true,
      "evidence": "Krotka parafraza z raportu.",
      "recommendation": "Co uzupelnic, jesli brakuje."
    }
  ],
  "summary": "Krotka ocena zgodnosci."
}
```

Supported v1 checklists:
- `GRI`: GRI 305-1 through 305-5 and GRI 401-1 through 401-3.
- `SASB`: Engineering & Construction Services metrics, including
  `IF-EN-160a.1`, `IF-EN-160a.2`, `IF-EN-250a.1`, `IF-EN-250a.2`,
  `IF-EN-320a.1`, `IF-EN-410a.1`, `IF-EN-410a.2`, `IF-EN-410b.1`,
  `IF-EN-510a.1`.
- `TCFD`: the 11 recommended disclosures across governance, strategy, risk
  management, and metrics and targets.

The v1 checklists are static backend definitions, not knowledge-base lookups at
request time. The LLM marks individual items as present or missing; the backend
then recomputes `score` and `overall_status` from normalized `items` so the
summary percentage always matches the green/red checklist.

### GET `/report/{report_id}/validate?standard=GRI`

GET alias for the same validation logic. If `standard` is omitted, `GRI` is used.

### GET `/reports/user`

Lists report history for the authenticated user.

### GET `/reports/{report_id}`

Returns one stored report owned by the authenticated user, including parsed JSON
content and parsed `used_chunks`.

### DELETE `/reports/{report_id}`

Deletes a stored report owned by the authenticated user.

## Chat

### POST `/chat/ask`

Starts a background RAG chat task and stores the user message.

Request body:

```json
{
  "query": "string",
  "tag": "optional tag",
  "session_id": "optional session id"
}
```

Response:

```json
{
  "status": "queued",
  "task_id": "celery-task-id",
  "session_id": "uuid",
  "message": "Pytanie przetwarzane w tle. Sprawdz status zadania."
}
```

### GET `/chat/sessions`

Lists chat sessions for the authenticated user. Supports `limit` and `offset`.

### GET `/chat/sessions/{session_id}/history`

Lists messages for a session. Supports `limit` and `offset`.

### DELETE `/chat/sessions/{session_id}`

Deletes an owned chat session and its message history.

## Utility and Ingestion Endpoints

### GET `/ping`

Health check.

### GET `/openai-status`

Checks whether the backend can initialize OpenAI configuration.

### POST `/parse`

Parses an uploaded file synchronously for parser diagnostics.

### POST `/process`

Legacy async parse-and-store entrypoint.

### POST `/upload`

Legacy upload endpoint.

### POST `/ingest/chunk/url`

Fetches a URL, filters/chunks text and returns chunking output.

### POST `/ingest/chunk/file`

Chunks an uploaded file and returns chunking output.

## Error Responses

FastAPI validation and error responses use the standard shape:

```json
{
  "detail": "Human-readable error message"
}
```

Common statuses: `400`, `401`, `403`, `404`, `409`, `413`, `422`, `500`.
