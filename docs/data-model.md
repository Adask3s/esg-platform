# Data Model

This document describes the main database tables and their relationships. The database is PostgreSQL hosted on Supabase with the `pgvector` extension for vector similarity search.

## Tables

### users

Stores registered user accounts.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| email | TEXT | Unique, used for login |
| hashed_password | TEXT | bcrypt hash |
| created_at | TIMESTAMPTZ | |

### documents

Metadata for files uploaded by users.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| user_id | UUID | Foreign key -> users.id |
| filename | TEXT | Original file name |
| file_type | TEXT | pdf, docx, xlsx, etc. |
| status | TEXT | pending, processing, ready, failed |
| tags | TEXT[] | User-supplied tags |
| created_at | TIMESTAMPTZ | |

### documents_embeddings

Stores text chunks and their vector embeddings for user-uploaded documents.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| document_id | UUID | Foreign key -> documents.id |
| user_id | UUID | Denormalized for efficient RLS filtering |
| chunk_text | TEXT | Raw segment content |
| embedding | vector(1536) | OpenAI text-embedding-ada-002 output |
| chunk_index | INTEGER | Position of chunk within the document |
| metadata | JSONB | page number, category, tags, etc. |
| created_at | TIMESTAMPTZ | |

**Index:** `ivfflat` or `hnsw` on the `embedding` column for fast approximate nearest-neighbor search.

### knowledge_embeddings

Stores pre-processed chunks from ESG standards (GRI, SASB, TCFD). Shared across all users; managed by platform administrators.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| source | TEXT | Standard name (e.g., GRI, SASB, TCFD) |
| section | TEXT | Section or topic identifier |
| chunk_text | TEXT | Raw segment content |
| embedding | vector(1536) | Vector representation |
| chunk_index | INTEGER | Position within the source document |
| metadata | JSONB | version, publication date, category |
| created_at | TIMESTAMPTZ | |

**Index:** `ivfflat` or `hnsw` on the `embedding` column.

### reports

Generated ESG reports per user.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| user_id | UUID | Foreign key -> users.id |
| title | TEXT | |
| content | TEXT | Full report text |
| standard | TEXT | GRI, SASB, TCFD |
| document_ids | UUID[] | Source documents used |
| tags | TEXT[] | Tags applied during generation |
| created_at | TIMESTAMPTZ | |

### conversations

Chat session containers.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| user_id | UUID | Foreign key -> users.id |
| created_at | TIMESTAMPTZ | |

### chat_messages

Individual messages within a conversation.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| conversation_id | UUID | Foreign key -> conversations.id |
| role | TEXT | user or assistant |
| content | TEXT | Message text |
| sources | JSONB | Retrieved chunks used for this response |
| created_at | TIMESTAMPTZ | |

## Entity Relationships

```
users
  |--< documents
  |       |--< documents_embeddings
  |
  |--< reports
  |
  |--< conversations
          |--< chat_messages

knowledge_embeddings  (no user foreign key — shared global table)
```

## Vector Search Pattern

Both `documents_embeddings` and `knowledge_embeddings` support cosine similarity queries using pgvector:

```sql
SELECT chunk_text, metadata, 1 - (embedding <=> $query_vector) AS similarity
FROM documents_embeddings
WHERE user_id = $user_id
ORDER BY embedding <=> $query_vector
LIMIT 10;
```

The `<=>` operator computes cosine distance; subtracting from 1 gives cosine similarity. The same pattern applies to `knowledge_embeddings` without the user filter.

## Notes on Row-Level Security

To prevent cross-user data leakage, Supabase RLS policies should restrict access on `documents`, `documents_embeddings`, `reports`, `conversations`, and `chat_messages` to rows where `user_id` matches the authenticated user's ID. The `knowledge_embeddings` table is read-only for all authenticated users.
