# Development Setup

## Prerequisites

| Tool | Minimum version | Purpose |
|------|----------------|---------|
| Python | 3.11 | Backend runtime |
| Node.js | 18 | Frontend build |
| Docker + Docker Compose | 24 | Redis, Celery |
| Git | any | Version control |

The Python backend depends, among others, on `fastapi`, `uvicorn`, `celery`, `redis`, `openai`, `supabase`, `pdfplumber`, `python-docx`, `openpyxl`, `tiktoken`, `python-jose[cryptography]`, `passlib[bcrypt]`, `flower`, and **`reportlab`** (server-side PDF rendering for downloadable ESG reports). The full list is in `backend/requirements.txt`.

You also need:
- An OpenAI API key with access to `text-embedding-ada-002` and a GPT-4 model
- A Supabase project with the `pgvector` extension enabled

## Repository Setup

```bash
git clone <repository-url>
cd JKPSZ3-platforma-etg
```

## Environment Configuration

Copy the example env file and fill in your credentials:

```bash
cp .env.example .env
```

Required variables:

```
OPENAI_API_KEY=sk-...
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_KEY=<service-role-key>
DATABASE_URL=postgresql://...
REDIS_URL=redis://localhost:6379/0
JWT_SECRET=<random-secret-min-32-chars>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
TZ=Europe/Warsaw
```

## Database Initialization

Run the schema initialization script once against your Supabase PostgreSQL instance:

```bash
python check_schema.py
```

Ensure the `pgvector` extension is enabled in Supabase:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

## Backend

```bash
cd backend
python -m venv ../.venv        # skip if .venv already exists
source ../.venv/bin/activate   # Windows: ..\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`. Interactive docs are at `http://localhost:8000/docs`.

## Asynchronous Workers (Celery + Redis)

Start the infrastructure containers:

```bash
docker-compose up -d redis
```

Start the Celery worker from the project root (with the virtual environment activated):

```bash
celery -A backend.celery.celery_app worker \
  --loglevel=info \
  -Q default,parsing,embeddings,embeddings_bulk,llm \
  --concurrency=4
```

Optionally start the beat scheduler for periodic tasks:

```bash
celery -A backend.celery.celery_app beat --loglevel=info
```

Optionally start Flower for task monitoring:

```bash
celery -A backend.celery.celery_app flower --port=5555
```

Alternatively, bring up all services at once via Docker Compose:

```bash
docker-compose up --build
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

The development server runs at `http://localhost:5173` with HMR enabled. API requests are proxied to `http://localhost:8000` as configured in `vite.config.js`.

## Running Tests

From the `backend/` directory (with the virtual environment activated):

```bash
pytest                          # all tests
pytest test_common_endpoints.py # endpoint tests only
pytest test_e2e.py              # end-to-end tests
```

## Diagnostic Scripts

### diagnose_rag.py

A standalone script at the project root that exercises the RAG retrieval path directly, bypassing FastAPI and Celery. It is the fastest way to inspect what context the LLM would actually receive for a given query — useful when answers look wrong and you need to tell whether the issue is in retrieval or in the prompt/model.

**Usage:**

```bash
python diagnose_rag.py "Your question" "<user_id>" ["optional_tag"]
```

**Arguments:**

| Position | Name | Description |
|----------|------|-------------|
| 1 | `query` | Free-form question, e.g. `"What are our Scope 1 emissions?"` |
| 2 | `user_id` | UUID of the user whose documents should be searched |
| 3 | `tag` | Optional metadata tag filter (e.g. `Environmental`) |

**What it shows:**

- Total number of matching chunks returned
- Header line of each retrieved chunk
- First ~100 characters of each chunk's body
- A summary that splits the matches into two buckets:
  - **User documents** — chunks from `documents_embeddings`
  - **Knowledge base (EU regulations)** — chunks recognized by markers like `celex` or `rozporządzenie` in the header

If no chunks come back, the script prints likely causes (wrong `user_id`, non-existent tag, or a similarity threshold that is too strict).

**Defaults:** `match_count=20`, `match_threshold=0.20`. These can be tuned by editing the call to `run_diagnostics` in the script.

## Useful Commands

| Command | Purpose |
|---------|---------|
| `uvicorn main:app --reload` | Start backend with hot reload |
| `npm run build` | Build frontend for production |
| `npm run lint` | Run ESLint |
| `docker-compose logs -f celery-worker` | Stream Celery worker logs |
| `docker-compose down -v` | Stop all containers and remove volumes |

## Common Issues

**Celery tasks stay in PENDING state**
Verify Redis is running and `REDIS_URL` in `.env` matches the broker URL used in `celery_app.py`.

**Embedding calls fail**
Check that `OPENAI_API_KEY` is valid and the account has access to `text-embedding-ada-002`.

**pgvector errors on insert**
Confirm the `vector` extension is enabled in Supabase and that the `embedding` column type is `vector(1536)`.

**JWT token rejected**
Ensure `JWT_SECRET` is at least 32 characters and identical across the backend instances if running multiple workers.
