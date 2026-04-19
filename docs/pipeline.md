# Data Processing Pipeline

This document describes the end-to-end pipeline from document upload to ESG report generation.

## Pipeline Overview

```
[1] Upload          -> User submits documents via the frontend
[2] Text Extraction -> Celery parses raw text from files
[3] Chunking        -> Text is split into semantic segments (<= 2000 chars)
[4] Embedding       -> Each chunk is vectorized and stored in Supabase
[5] Knowledge Base  -> Pre-embedded ESG regulation fragments (static)
[6] RAG Retrieval   -> Relevant chunks are selected for the user query
[7] Prompt Building -> Layered prompt is assembled for the LLM
[8] Generation      -> LLM produces the ESG report or answer
[9] Editing         -> User iterates; each edit re-enters the pipeline from step 6
```

---

## Stage 1 — Document Upload

The user uploads one or more documents through the frontend (supported formats: PDF, XLSX, DOCX, and plain text). The user may also attach tags that will later be used to filter relevant chunks during retrieval. Celery enqueues a processing task for each uploaded file.

## Stage 2 — Text Extraction

A Celery worker picks up the parsing task from the `parsing` queue. The appropriate parser is dispatched based on file type:

| Format | Parser module |
|--------|--------------|
| PDF | `pdf_parser.py` |
| DOCX | `docx_parser.py` |
| XLSX / CSV | `tabular_parser.py` (outputs JSON for structured data) |
| HTML | `html_fetcher.py` |

The result is raw text (or structured JSON for tabular data) stored temporarily before the next stage.

## Stage 3 — Chunking

Because document texts are too large to fit in a single LLM context window, the text is split into semantically meaningful segments. Each chunk must not exceed 2000 characters. The chunker (`ingestion/chunker.py`) respects sentence and paragraph boundaries to avoid splitting mid-sentence.

A chunk carries:
- `text` — the raw segment content
- `metadata` — document ID, page number, source file, tags, ESG category if detected

## Stage 4 — Embedding (User Documents)

Each chunk is sent to the `embeddings` Celery queue. The embedding service (`embeddings/embedding_service.py`) calls the OpenAI embeddings API and stores the result in the `documents_embeddings` table in Supabase.

Each row in `documents_embeddings` contains:
- `chunk_text` — the segment text
- `embedding` — a 1536-dimensional vector (pgvector)
- `metadata` — document ID, user ID, tags, category

## Stage 5 — ESG Knowledge Base

The knowledge base is a second vector table (`knowledge_embeddings`) containing pre-chunked and pre-embedded fragments from ESG standards: GRI, SASB, TCFD, and relevant construction-sector regulations.

This table is shared across all users and updated only when regulations change. The ingestion process is identical to stages 2-4 but is run by platform administrators, not end users.

## Stage 6 — RAG Retrieval

When a user requests a report or asks a question:

1. The query text is embedded using the same OpenAI model.
2. A cosine similarity search is performed against both `documents_embeddings` (user's documents) and `knowledge_embeddings` (ESG standards).
3. The top-N most semantically similar chunks from each table are selected.
4. If the user specified tags, the search is pre-filtered by those tag metadata fields.

Supabase's pgvector extension handles the vector similarity search efficiently.

## Stage 7 — Prompt Building

The final prompt sent to the LLM is assembled in layers (`RAG/prompt_builder.py`):

```
[System message]
You are an expert ESG analyst for the construction sector.

[Knowledge context]
<selected fragments from ESG standards>

[Data context]
<selected fragments from user documents>

[Task instruction]
Generate an ESG report section covering: <user's request or selected tags>
```

This layered structure ensures the model has regulatory grounding (knowledge context) before it interprets company-specific data (data context).

## Stage 8 — Report Generation

The assembled prompt is submitted to the LLM via the `llm` Celery queue. The model:
- Interprets the company data in the context of ESG regulations
- Generates structured report content in natural language
- Returns the output to the backend, which stores it and forwards it to the frontend

If the user selected tags, the retrieved chunks are further filtered by metadata category before prompt assembly, producing a tag-specific report section.

## Stage 9 — Interactive Editing

After initial generation the user can:
- Edit sections manually
- Upload additional documents
- Ask follow-up questions about specific regulations
- Request expansion or summarization of any section

Each interaction re-enters the pipeline at stage 6: the new query is embedded, fresh chunks are retrieved, and a new prompt is built incorporating the conversation history where relevant.
