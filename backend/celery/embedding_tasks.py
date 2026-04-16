"""
Celery taski do generowania embeddingów (OpenAI) w tle.

Funkcje serwisowe (`generate_embeddings_for_document`, `generate_embeddings_by_tag`,
`generate_embeddings_for_all_documents`) są async/def i bity do OpenAI.
Worker opakowuje je w `asyncio.run(...)` i dopisuje granulowane progress-meta.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict

import openai
import requests

from backend.celery.celery_app import celery_app

# Transient errors — retryowalne
TRANSIENT_EXC = (
    openai.RateLimitError,
    openai.APIConnectionError,
    openai.APITimeoutError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    ConnectionError,
    TimeoutError,
)


@celery_app.task(
    bind=True,
    name="backend.generate_embeddings_for_document",
    autoretry_for=TRANSIENT_EXC,
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
    soft_time_limit=1200,
    time_limit=1500,
)
def generate_embeddings_for_document_task(
    self,
    document_id: str,
    model: str = "text-embedding-3-small",
    table_name: str = "knowledge_chunks",
) -> Dict[str, Any]:
    """Generuj embeddingi dla wszystkich chunków danego dokumentu."""
    from backend.embeddings.embedding_service import generate_embeddings_for_document

    self.update_state(
        state="PROGRESS",
        meta={
            "step": "generating_embeddings",
            "stage_pl": "Generowanie embeddingów",
            "progress": 10,
            "document_id": document_id,
            "table": table_name,
        },
    )

    result = asyncio.run(generate_embeddings_for_document(
        document_id=document_id,
        model=model,
        table_name=table_name,
    ))

    self.update_state(
        state="PROGRESS",
        meta={
            "step": "done",
            "stage_pl": "Gotowe",
            "progress": 100,
            "document_id": document_id,
            "table": table_name,
        },
    )
    return result


@celery_app.task(
    bind=True,
    name="backend.generate_embeddings_for_tag",
    autoretry_for=TRANSIENT_EXC,
    retry_backoff=True,
    retry_backoff_max=120,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
    soft_time_limit=1800,
    time_limit=2100,
)
def generate_embeddings_for_tag_task(
    self,
    tag: str,
    model: str = "text-embedding-3-small",
) -> Dict[str, Any]:
    """Generuj embeddingi dla wszystkich chunków z podanym tagiem."""
    from backend.embeddings.embedding_service import generate_embeddings_by_tag

    self.update_state(
        state="PROGRESS",
        meta={
            "step": "generating_embeddings",
            "stage_pl": "Generowanie embeddingów dla tagu",
            "progress": 10,
            "tag": tag,
        },
    )

    result = asyncio.run(generate_embeddings_by_tag(tag=tag, model=model))

    self.update_state(
        state="PROGRESS",
        meta={
            "step": "done",
            "stage_pl": "Gotowe",
            "progress": 100,
            "tag": tag,
        },
    )
    return result


@celery_app.task(
    bind=True,
    name="backend.generate_embeddings_for_all",
    autoretry_for=TRANSIENT_EXC,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
    soft_time_limit=3600,
    time_limit=4200,
)
def generate_embeddings_for_all_task(
    self,
    model: str = "text-embedding-3-small",
) -> Dict[str, Any]:
    """Generuj embeddingi dla wszystkich chunków bez embeddingu. Długotrwałe!"""
    from backend.embeddings.embedding_service import generate_embeddings_for_all_documents

    self.update_state(
        state="PROGRESS",
        meta={
            "step": "generating_embeddings_bulk",
            "stage_pl": "Generowanie embeddingów (batch)",
            "progress": 10,
        },
    )

    result = asyncio.run(generate_embeddings_for_all_documents(model=model))

    self.update_state(
        state="PROGRESS",
        meta={
            "step": "done",
            "stage_pl": "Gotowe",
            "progress": 100,
        },
    )
    return result
