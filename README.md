# ESG Platform

AI-powered platform for ESG (Environmental, Social, Governance) document ingestion, analysis, and automated report generation. Built with React 19 + FastAPI, leveraging OpenAI for RAG-based retrieval and PDF report rendering.

---

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Architecture Overview](#architecture-overview)
- [Prerequisites](#prerequisites)
- [Getting Started](#getting-started)
  - [1. Clone the repository](#1-clone-the-repository)
  - [2. Environment variables](#2-environment-variables)
  - [3. Start infrastructure (Docker)](#3-start-infrastructure-docker)
  - [4. Backend](#4-backend)
  - [5. Frontend](#5-frontend)
- [Running Tests](#running-tests)
- [Project Structure](#project-structure)
- [API Reference](#api-reference)
- [Common Issues](#common-issues)
- [Contributing](#contributing)
- [License](#license)

---

## Features

- Upload and parse ESG documents (PDF, DOCX, XLSX, CSV)
- Vector-based semantic search with pgvector (RAG)
- AI-generated ESG reports aligned to GRI, SASB, TCFD standards
- PDF report export with Polish character support
- JWT-based authentication with configurable token expiry
- Asynchronous task queue (Celery + Redis) with real-time status polling
- Admin panel for knowledge base management
- Task monitoring via Flower dashboard

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 19, Vite, React Router DOM |
| Backend | FastAPI, Python 3.11+ |
| Task Queue | Celery 5, Redis 7 |
| Database | PostgreSQL + pgvector via Supabase |
| AI / Embeddings | OpenAI `text-embedding-3-small`, `gpt-4o-mini` |
| PDF generation | ReportLab |
| Auth | JWT (python-jose), passlib/bcrypt |
| Containerization | Docker + Docker Compose |

---

## Architecture Overview

```
React 19 / Vite (port 5173)
        |
        | HTTP REST  ·  JWT Bearer
        ▼
FastAPI backend (port 8000)
        |
        | Celery tasks
        ▼
Redis broker / result backend (port 6379)
        |
        ├──▶ OpenAI — text-embedding-3-small (embeddings)
        ├──▶ OpenAI — gpt-4o-mini (report & chat generation)
        └──▶ Supabase / PostgreSQL + pgvector
```

**Celery queues**

| Queue | Purpose |
|---|---|
| `default` | General background tasks |
| `parsing` | Document parsing and ingestion |
| `embeddings` | Single-document embedding |
| `embeddings_bulk` | Bulk re-indexing |
| `llm` | LLM calls (chat, report generation) |

---

## Prerequisites

Make sure the following tools are installed before proceeding:

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.11+ | Backend, Celery workers |
| Node.js | 18+ | Vite / React frontend |
| Docker + Docker Compose | latest | Redis, Celery worker/beat, Flower |
| Git | any | Version control |

---

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/Adask3s/esg-platform.git
cd esg-platform
```

### 2. Environment variables

Create a `.env` file in the project root. **Never commit this file.**

```dotenv
# ── OpenAI ──────────────────────────────────────────────────────────
OPENAI_API_KEY=sk-...

# ── Supabase ─────────────────────────────────────────────────────────
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>

# ── PostgreSQL (direct connection) ──────────────────────────────────
DATABASE_URL=postgresql://user:password@host:5432/dbname
DB_HOST=localhost
DB_NAME=esg
DB_USER=postgres
DB_PASSWORD=postgres
DB_PORT=5432

# ── Redis ────────────────────────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# ── JWT ──────────────────────────────────────────────────────────────
JWT_SECRET=<random-string-minimum-32-characters>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60

# ── App ──────────────────────────────────────────────────────────────
SIGNUP_ENABLED=false
TZ=Europe/Warsaw
```

Optional frontend variables (create `frontend/.env.local` or add to the root `.env`):

```dotenv
VITE_API_URL=http://localhost:8000
VITE_REPORT_MODEL_LABEL=AI POWERED
```

> **Note:** `REDIS_URL` uses `redis://` for local Docker. For managed Redis with TLS (Upstash, AWS ElastiCache) use `rediss://` — the Celery config detects the scheme automatically and enables SSL.

### 3. Start infrastructure (Docker)

Redis, Celery worker, and Celery beat run in containers. The FastAPI backend runs on the host.

```bash
# Start Redis + Celery worker + beat (required)
docker compose up -d redis celery-worker celery-beat

# Optional: Flower monitoring dashboard at http://localhost:5555
docker compose --profile monitoring up -d flower

# Follow worker logs
docker compose logs -f celery-worker
```

### 4. Backend

```bash
# Create and activate a virtual environment
python -m venv .venv

# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate

# Install dependencies
pip install -r backend/requirements.txt

# Run the API server
$env:PYTHONPATH="."            # PowerShell
# export PYTHONPATH=.          # bash/zsh

python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

The API is now available at:

- **API base:** `http://localhost:8000`
- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`

### 5. Frontend

```bash
cd frontend
npm install          # or: npm.cmd install on Windows if npm.ps1 is blocked
npm run dev
```

The Vite dev server runs at `http://localhost:5173`. API calls go to `VITE_API_URL` (default `http://localhost:8000`).

---

## Running Tests

All test commands should be run from the **project root** with the virtual environment active and `PYTHONPATH=.` set.

```bash
# Fast integration tests (no external services required)
python -m pytest backend/test_common_endpoints.py backend/test_negative_integration.py

# PDF generation tests
python -m pytest backend/test_pdf_generator.py backend/test_report_tasks.py

# RAG quality test — offline, uses monkeypatched embeddings
python -m pytest backend/test_rag_quality_sample_docs.py

# Unit tests
python -m pytest tests/unit/
```

**End-to-end report test** — requires a running API, Redis/Celery, OpenAI, Supabase, and an `admin/admin` account:

```bash
python backend/test_e2e.py Environmental
```

**RAG diagnostics** — prints matched chunks and source breakdown for a query:

```bash
python diagnose_rag.py "your question here" "<user_id>" "Environmental"
```

---

## Project Structure

```
esg-platform/
├── backend/
│   ├── main.py                  # FastAPI application entrypoint
│   ├── auth.py                  # JWT authentication
│   ├── rate_limiting.py         # Request rate limiting
│   ├── report_validation.py     # Report input/output validation
│   ├── celery/
│   │   ├── celery_app.py        # Celery configuration & queue routing
│   │   ├── tasks.py             # Parsing & chat tasks
│   │   ├── embedding_tasks.py   # Embedding generation tasks
│   │   └── report_tasks.py      # Report generation tasks
│   ├── RAG/
│   │   ├── rag_retriever.py     # Supabase pgvector retrieval
│   │   └── prompt_builder.py    # LLM prompt construction
│   ├── embeddings/
│   │   └── embedding_service.py # OpenAI embedding wrapper
│   ├── ingestion/               # Document chunking & filtering
│   ├── parsers/                 # PDF, DOCX, tabular file parsers
│   ├── utils/
│   │   ├── pdf_generator.py     # ReportLab PDF rendering
│   │   └── files.py             # File utilities
│   └── requirements.txt
├── database/
│   ├── db_config.py             # PostgreSQL connection
│   ├── db_init.py               # Table initialization script
│   ├── supabase_client.py       # Supabase client setup
│   ├── knowledge_service.py     # Knowledge base CRUD
│   ├── user_documents_service.py
│   ├── chat_repository.py
│   └── report_repo.py
├── frontend/
│   ├── src/
│   │   ├── pages/               # Login, Dashboard, AIReports, AdminPanel
│   │   ├── components/          # MultiFileUpload and shared UI
│   │   └── lib/                 # Auth token helpers, API error handling
│   ├── package.json
│   └── vite.config.js
├── docs/                        # Extended architecture & API reference
├── tests/
│   └── unit/
│       ├── backend/             # Backend unit tests
│       └── frontend/            # Frontend unit tests
├── docker-compose.yml
├── Dockerfile.celery
└── .gitignore
```

---

## API Reference

Interactive docs are served automatically at `http://localhost:8000/docs`.

Key endpoint groups:

| Group | Prefix | Description |
|---|---|---|
| Auth | `/auth` | Register, login, JWT token refresh |
| Documents | `/documents` | Upload, list, delete user documents |
| Embeddings | `/embeddings` | Trigger / status for embedding tasks |
| Reports | `/report` | Generate, poll status, download PDF |
| Chat | `/chat` | RAG-based Q&A sessions |
| Admin | `/admin` | Knowledge base management |

For the full specification see [`docs/api-reference.md`](docs/api-reference.md) and [`docs/API_REFERENCE_EXTENDED.md`](docs/API_REFERENCE_EXTENDED.md).

---

## Common Issues

**Celery task stays `PENDING`**
Verify Redis is running and `REDIS_URL` matches in both the backend and the worker container. Check with `docker compose ps` and `docker compose logs redis`.

**OpenAI embedding calls fail**
Check that `OPENAI_API_KEY` is set correctly and your account has access to `text-embedding-3-small`.

**PDF has broken Polish characters**
The PDF generator attempts Arial → DejaVu Sans → Liberation Sans → ReportLab Vera before falling back to Helvetica. Install one of the TTF fonts system-wide or configure the path explicitly.

**Frontend cannot reach backend**
Set `VITE_API_URL=http://localhost:8000` in your local env file. The Vite config has no built-in proxy — all API routing relies on this variable.

**`npm` blocked on Windows PowerShell**
Use `npm.cmd` instead of `npm` if the `npm.ps1` script is blocked by your ExecutionPolicy.

---

## Contributing

1. Fork the repository and create a feature branch from `main`.
2. Run the fast test suite before opening a PR.
3. Follow the existing code style — no new linter warnings.
4. Open a pull request with a clear description of the change and its motivation.

> Secrets and `.env` files must never be committed. The `.gitignore` already excludes them.

---

## License

This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.

## Team & Contributors

This project was developed as a collaborative effort by:

**Adask3s**

- GitHub: [@Adask3s](https://github.com/Adask3s)
- Email: adam.kopystecki@gmail.com

---
**xeadk**

- GitHub: [xeadk](https://github.com/xeadk)

---

**pogmaciek321**

- GitHub: [pogmaciek321](https://github.com/pogmaciek321)

---

**dambeeto**

- GitHub: [dambeeto](https://github.com/dambeeto)

---
