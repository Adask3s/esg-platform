# Development Setup

The local reference environment is Windows + PowerShell. The backend can also be
run from other shells if paths are adjusted.

## Prerequisites

| Tool | Purpose |
|------|---------|
| Python 3.11+ | FastAPI, Celery tasks and tests |
| Node.js 18+ | Vite/React frontend |
| Docker + Docker Compose | Redis, Celery worker/beat, Flower |
| Git | Version control |

The backend dependencies are listed in `backend/requirements.txt`. Important
packages include `fastapi`, `uvicorn`, `celery`, `redis`, `openai`, `supabase`,
`python-docx`, `pdfplumber`, `openpyxl`, `reportlab`, `pytest` and
`python-jose[cryptography]`.

## Environment Variables

Do not commit `.env`.

Required or commonly used variables:

```powershell
OPENAI_API_KEY=sk-...
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>
DATABASE_URL=postgresql://...
REDIS_URL=redis://localhost:6379/0
JWT_SECRET=<random-secret-min-32-chars>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
SIGNUP_ENABLED=false
TZ=Europe/Warsaw
```

Optional frontend variables:

```powershell
VITE_API_URL=http://localhost:8000
VITE_REPORT_MODEL_LABEL=AI POWERED
```

The current embedding model is `text-embedding-3-small`. Report and chat
generation use `gpt-4o-mini`.

## Backend

From the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH="."
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

The API runs at `http://localhost:8000`; OpenAPI docs are available at
`http://localhost:8000/docs`.

## Redis, Celery and Flower

```powershell
docker compose up -d redis celery-worker celery-beat
docker compose --profile monitoring up -d flower
```

Useful logs:

```powershell
docker compose logs -f celery-worker
```

## Frontend

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
npm.cmd run build
npm.cmd run lint
```

The Vite dev server runs at `http://localhost:5173`. There is no Vite proxy in
`frontend/vite.config.js`; frontend API calls use `VITE_API_URL` and fall back to
`http://localhost:8000`.

Use `npm.cmd`, not `npm`, on Windows PowerShell if `npm.ps1` is blocked by
ExecutionPolicy.

## Fast Backend Tests

From the repository root:

```powershell
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH="."
python -m pytest backend\test_common_endpoints.py backend\test_negative_integration.py
python -m pytest backend\test_pdf_generator.py backend\test_report_tasks.py
python -m pytest backend\test_rag_quality_sample_docs.py
```

The RAG quality sample test is offline and deterministic. It parses
`sample_uploads/*.docx`, uses the real chunker and monkeypatches embedding/RPC
calls so it does not require OpenAI, Supabase or Celery.

## E2E Report Test

Run only when API, Redis/Celery, OpenAI, Supabase and an `admin/admin` account
are available:

```powershell
python backend\test_e2e.py Environmental
```

## RAG Diagnostics

```powershell
python diagnose_rag.py "pytanie" "<user_id>" "Environmental"
```

The script calls the same retrieval path as the app and prints matched chunks,
source headers and a user-doc vs knowledge-base split.

## Common Issues

### Celery task stays `PENDING`

Check that Redis is running and `REDIS_URL` matches backend and worker config.

### OpenAI embedding calls fail

Check `OPENAI_API_KEY` and access to `text-embedding-3-small`.

### PDF has broken Polish characters

Install or configure TTF fonts. The PDF generator tries Arial, DejaVu Sans,
Liberation Sans and ReportLab Vera before falling back to Helvetica.

### Frontend cannot reach backend

Set `VITE_API_URL=http://localhost:8000` or rely on the same fallback. The Vite
config does not proxy API calls.
