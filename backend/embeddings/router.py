"""
Router dla endpointów embeddingów.
Obsługuje generowanie i zarządzanie embeddingami OpenAI.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from backend.embeddings.embedding_service import (
    generate_embedding,
    generate_embeddings_for_document,
    generate_embeddings_for_all_documents,
    generate_embeddings_by_tag
)
from database.supabase_client import get_supabase


router = APIRouter(
    prefix="/embeddings",
    tags=["Embeddings"],
    responses={404: {"description": "Not found"}},
)


# ============================================================
# MODELE PYDANTIC
# ============================================================

class EmbeddingRequest(BaseModel):
    """Model do generowania pojedynczego embeddingu (test)."""
    text: str
    model: str = "text-embedding-3-small"


class DocumentEmbeddingRequest(BaseModel):
    """Model do generowania embeddingów dla całego dokumentu."""
    document_id: str
    model: str = "text-embedding-3-small"
    table_name: str = "knowledge_chunks"  # Nowe pole do obslugi zarowno bazy wiedzy jak i dokumentow uzytkownika


class TagEmbeddingRequest(BaseModel):
    """Model do generowania embeddingów dla chunków z danym tagiem."""
    tag: str
    model: str = "text-embedding-3-small"


# ============================================================
# ENDPOINTY
# ============================================================

@router.post("/generate")
async def generate_single_embedding(request: EmbeddingRequest):
    """
    ENDPOINT TESTOWY: Generuje embedding dla pojedynczego tekstu.

    Użyj tego endpointu do testowania czy klucz OpenAI działa poprawnie.

    Body:
    {
        "text": "Przykładowy tekst do embedowania",
        "model": "text-embedding-3-small"  // opcjonalne
    }

    Returns:
    {
        "embedding": [0.123, -0.456, ...],  // 1536 wymiarów
        "model": "text-embedding-3-small",
        "dimensions": 1536
    }
    """
    try:
        embedding = await generate_embedding(request.text, model=request.model)
        return {
            "embedding": embedding,
            "model": request.model,
            "dimensions": len(embedding)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd generowania embeddingu: {str(e)}")


@router.post("/generate-for-document")
async def generate_document_embeddings(request: DocumentEmbeddingRequest):
    """
    GŁÓWNY ENDPOINT EMBEDDINGÓW (ZADANIE 2).

    Generuje embeddingi dla WSZYSTKICH chunków należących do danego dokumentu.

    Body:
    {
        "document_id": "uuid-dokumentu",
        "model": "text-embedding-3-small"  // opcjonalne
    }

    Flow:
    1. Pobiera wszystkie chunki z knowledge_chunks WHERE document_id = ...
    2. Generuje embeddingi (batch processing)
    3. Zapisuje embeddingi do kolumny 'embedding' w knowledge_chunks

    Returns:
    {
        "document_id": "...",
        "total_chunks": 42,
        "updated": 42,
        "failed": 0,
        "model": "text-embedding-3-small",
        "embedding_dim": 1536
    }
    """
    try:
        result = await generate_embeddings_for_document(
            request.document_id,
            model=request.model,
            table_name=request.table_name  # Przekazujemy parametr
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd generowania embeddingów: {str(e)}")


@router.post("/generate-for-tag")
async def generate_tag_embeddings(request: TagEmbeddingRequest):
    """
    ENDPOINT EMBEDDINGÓW DLA TAGU (ZADANIE 2 - rozszerzenie).

    Generuje embeddingi dla wszystkich chunków z danym tagiem (np. 'social', 'environmental').

    Body:
    {
        "tag": "social",
        "model": "text-embedding-3-small"  // opcjonalne
    }

    Przydatne gdy chcesz embedować tylko chunki z konkretnej kategorii ESG.

    Returns:
    {
        "tag": "social",
        "total_chunks_processed": 120,
        "updated": 120,
        "failed": 0,
        "model": "text-embedding-3-small",
        "embedding_dim": 1536
    }
    """
    try:
        result = await generate_embeddings_by_tag(request.tag, model=request.model)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd generowania embeddingów: {str(e)}")


@router.post("/generate-all")
async def generate_all_embeddings(model: str = "text-embedding-3-small"):
    """
    ENDPOINT EMBEDDINGÓW - BATCH PROCESSING (ZADANIE 2 - zaawansowane).

    Generuje embeddingi dla WSZYSTKICH chunków w bazie, które nie mają jeszcze embeddingu.

    ⚠️ UWAGA: Może być kosztowne dla dużych baz danych!
    ⚠️ Zalecane użycie tylko podczas pierwszej inicjalizacji bazy.

    Query params:
    - model: "text-embedding-3-small" (domyślnie)

    Returns:
    {
        "status": "completed",
        "total_chunks_processed": 500,
        "updated": 500,
        "failed": 0,
        "model": "text-embedding-3-small",
        "embedding_dim": 1536
    }
    """
    try:
        result = await generate_embeddings_for_all_documents(model=model)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Błąd generowania embeddingów: {str(e)}")


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

