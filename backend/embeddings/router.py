"""
Router dla endpointów embeddingów.
Generowanie embeddingów odbywa się ASYNCHRONICZNIE przez Celery.
Endpointy zwracają task_id — wynik pobierasz przez GET /status/{task_id}.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from database.supabase_client import get_supabase

# Celery taski embeddingów
from backend.celery.embedding_tasks import (
    generate_embeddings_for_document_task,
    generate_embeddings_for_tag_task,
    generate_embeddings_for_all_task,
)

# Potrzebujemy get_current_user do ownership registration
try:
    from backend.auth import get_current_user
except ImportError:
    from auth import get_current_user  # type: ignore


router = APIRouter(
    prefix="/embeddings",
    tags=["Embeddings"],
    responses={404: {"description": "Not found"}},
)


# ============================================================
# MODELE PYDANTIC
# ============================================================

class DocumentEmbeddingRequest(BaseModel):
    """Model do generowania embeddingów dla całego dokumentu."""
    document_id: str
    model: str = "text-embedding-3-small"
    table_name: str = "knowledge_chunks"


class TagEmbeddingRequest(BaseModel):
    """Model do generowania embeddingów dla chunków z danym tagiem."""
    tag: str
    model: str = "text-embedding-3-small"


# ============================================================
# ENDPOINTY — asynchroniczne (Celery)
# ============================================================


@router.post("/generate-for-document")
async def generate_document_embeddings(
    request: DocumentEmbeddingRequest,
    user=Depends(get_current_user),
):
    """
    Asynchroniczne generowanie embeddingów dla WSZYSTKICH chunków danego dokumentu.
    Zwraca task_id — wynik pobierasz przez GET /status/{task_id}.

    Body: {"document_id": "uuid", "model": "text-embedding-3-small", "table_name": "knowledge_chunks"}
    """
    async_result = generate_embeddings_for_document_task.delay(
        request.document_id,
        request.model,
        request.table_name,
    )
    return {
        "task_id": async_result.id,
        "status": "queued",
        "document_id": request.document_id,
        "table_name": request.table_name,
    }


@router.post("/generate-for-tag")
async def generate_tag_embeddings(
    request: TagEmbeddingRequest,
    user=Depends(get_current_user),
):
    """
    Asynchroniczne generowanie embeddingów dla chunków z danym tagiem ESG.
    Zwraca task_id — wynik pobierasz przez GET /status/{task_id}.

    Body: {"tag": "social", "model": "text-embedding-3-small"}
    """
    async_result = generate_embeddings_for_tag_task.delay(request.tag, request.model)
    return {
        "task_id": async_result.id,
        "status": "queued",
        "tag": request.tag,
    }


@router.post("/generate-all")
async def generate_all_embeddings(
    model: str = "text-embedding-3-small",
    user=Depends(get_current_user),
):
    """
    Asynchroniczne generowanie embeddingów dla WSZYSTKICH chunków bez embeddingu.
    ⚠️ Długotrwałe — używaj tylko podczas inicjalizacji bazy.
    Zwraca task_id — wynik pobierasz przez GET /status/{task_id}.
    """
    async_result = generate_embeddings_for_all_task.delay(model)
    return {
        "task_id": async_result.id,
        "status": "queued",
        "model": model,
    }


@router.get("/status")
async def embeddings_status():
    """
    Sprawdza status embeddingów w bazie wiedzy.

    Returns:
    {
        "total_chunks": 500,
        "with_embeddings": 350,
        "without_embeddings": 150,
        "coverage_percent": 70.0
    }
    """
    supabase = get_supabase()

    try:
        # Zlicz wszystkie chunki
        total_response = supabase.table("knowledge_chunks").select("id", count="exact").execute()
        total = total_response.count if hasattr(total_response, 'count') else len(total_response.data)

        # Zlicz chunki z embeddingami
        with_emb_response = supabase.table("knowledge_chunks").select("id", count="exact").not_.is_("embedding", "null").execute()
        with_emb = with_emb_response.count if hasattr(with_emb_response, 'count') else len(with_emb_response.data)

        without_emb = total - with_emb
        coverage = (with_emb / total * 100) if total > 0 else 0

        return {
            "total_chunks": total,
            "with_embeddings": with_emb,
            "without_embeddings": without_emb,
            "coverage_percent": round(coverage, 2)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd sprawdzania statusu: {str(e)}")

