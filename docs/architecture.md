# System Architecture

## High-Level Overview

The platform is a full-stack web application composed of four main layers: a React frontend, a FastAPI backend, an asynchronous task processing layer (Celery + Redis), and a PostgreSQL database managed through Supabase. AI capabilities are provided by the OpenAI API.

```
+------------------+
|    React SPA     |  User interface (Vite, React 19)
+--------+---------+
         |  HTTP / REST
+--------+---------+
|  FastAPI Backend |  Business logic, auth, routing
+----+--------+----+
     |        |
     |   +----+-------+
     |   |  Celery     |  Async task queue (parsing, embedding, LLM)
     |   |  Workers    |
     |   +----+--------+
     |        |
+----+--------+----+
|   Supabase /     |  PostgreSQL + pgvector for embeddings
|   PostgreSQL     |
+------------------+
         |
+------------------+
|   OpenAI API     |  Embeddings (text-embedding-ada-002) + Chat (GPT-4)
+------------------+
```

## Components

### Frontend

- **Technology:** React 19, Vite, React Router DOM 6
- **Pages:** Login, Sign Up, Dashboard, Reset Password, Contact
- **Responsibility:** File upload, tag selection, report viewing, interactive chat/editing

### Backend (FastAPI)

- **Technology:** Python, FastAPI, Uvicorn (ASGI)
- **Authentication:** JWT-based (`python-jose`, `passlib[bcrypt]`)
- **Key routers:**
  - Document ingestion and management
  - Embedding and knowledge base operations
  - RAG-based chat and report generation
  - Document retrieval

### Asynchronous Processing (Celery + Redis)

- **Broker:** Redis 7
- **Task queues:**

| Queue | Purpose |
|-------|---------|
| `default` | General tasks |
| `parsing` | Document text extraction |
| `embeddings` | Single-document embedding |
| `embeddings_bulk` | Bulk embedding operations |
| `llm` | LLM calls (report generation, chat) |

- **Scheduler:** Celery Beat for periodic tasks
- **Monitoring:** Flower UI (port 5555)

### Database (Supabase / PostgreSQL)

- **User data:** accounts, authentication
- **Documents:** uploaded file metadata, processing status
- **Embeddings:** `documents_embeddings` table — chunks with pgvector embeddings for user documents
- **Knowledge base:** `knowledge_embeddings` table — pre-chunked ESG regulation fragments
- **Chat history:** conversation records per user session
- **Reports:** generated report storage

### AI Services (OpenAI)

- **Embedding model:** `text-embedding-ada-002` — converts text chunks to 1536-dimensional vectors
- **Chat/generation model:** GPT-4 family — report generation, question answering, summarization

## Infrastructure

The platform is containerized using Docker Compose for local and staging environments.

| Service | Image | Port |
|---------|-------|------|
| redis | redis:7-alpine | 6379 |
| celery-worker | custom (Dockerfile.celery) | — |
| celery-beat | custom (Dockerfile.celery) | — |
| flower | optional | 5555 |

The FastAPI application and frontend are run separately (e.g., `uvicorn` and `vite dev` for development).

## Security Considerations

- All API endpoints requiring user data are protected by JWT bearer token authentication.
- Uploaded files are stored in a temporary directory (`tmp_uploads/`) and processed asynchronously.
- Environment secrets (API keys, DB credentials, JWT secret) are managed via `.env` and must not be committed to version control.
- Supabase row-level security should be enabled to isolate user data at the database layer.
