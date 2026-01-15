"""
Serwis do generowania embeddingów dla chunków tekstu.
Używa OpenAI text-embedding-3-small (1536 wymiarów).
"""

import os
from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI
from dotenv import load_dotenv
from database.supabase_client import get_supabase

load_dotenv()

# Globalny async client dla wydajności
_aclient: Optional[AsyncOpenAI] = None


def _get_async_client() -> AsyncOpenAI:
    """Inicjalizacja globalnego async klienta OpenAI."""
    global _aclient
    if _aclient is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key or not api_key.startswith("sk-"):
            raise Exception("Brak poprawnego klucza OPENAI_API_KEY dla embeddingów")
        _aclient = AsyncOpenAI(api_key=api_key)
    return _aclient


async def get_embedding(text: str, model: str = "text-embedding-3-small") -> List[float]:
    """
    Generuje embedding dla pojedynczego tekstu (async).
    Używamy AsyncOpenAI dla FastAPI.

    Args:
        text: Tekst do embedowania
        model: Model OpenAI (domyślnie text-embedding-3-small - 1536 wymiarów)

    Returns:
        Lista floatów (wektor embedding)
    """
    if not text:
        return []

    client = _get_async_client()

    try:
        # Ograniczenie długości tekstu (max ~8000 tokenów dla text-embedding-3-small)
        # Przybliżone: 1 token ≈ 4 znaki, więc 8000 tokenów ≈ 32000 znaków
        max_chars = 30000
        if len(text) > max_chars:
            text = text[:max_chars]
            print(f"WARNING: Tekst został skrócony do {max_chars} znaków")

        # Zamiana znaków nowej linii na spacje to dobra praktyka przy embeddingach
        text = text.replace("\n", " ")

        response = await client.embeddings.create(
            model=model,
            input=text
        )

        embedding = response.data[0].embedding
        return embedding

    except Exception as e:
        print(f"ERROR generating embedding: {e}")
        raise


async def generate_embedding(text: str, model: str = "text-embedding-3-small") -> Optional[List[float]]:
    """
    Alias dla get_embedding() - backward compatibility.

    Args:
        text: Tekst do embedowania
        model: Model OpenAI (domyślnie text-embedding-3-small - 1536 wymiarów)

    Returns:
        Lista floatów (wektor embedding) lub None w przypadku błędu
    """
    try:
        return await get_embedding(text, model)
    except Exception:
        return None


async def generate_embeddings_batch(texts: List[str], model: str = "text-embedding-3-small") -> List[List[float]]:
    """
    Generuje embeddingi dla wielu tekstów naraz (batch) - async.
    OpenAI API pozwala na max ~2048 requestów w jednym batchu.

    Args:
        texts: Lista tekstów do embedowania
        model: Model OpenAI

    Returns:
        Lista wektorów embeddingów
    """
    client = _get_async_client()

    if not texts:
        return []

    try:
        # Batch processing - OpenAI obsługuje do 2048 inputów naraz
        batch_size = 100  # Bezpieczna wartość dla stabilności
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]

            # Ograniczenie długości tekstów w batchu
            max_chars = 30000
            truncated_batch = [t[:max_chars] if len(t) > max_chars else t for t in batch]

            response = await client.embeddings.create(
                model=model,
                input=truncated_batch
            )

            batch_embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(batch_embeddings)

        return all_embeddings

    except Exception as e:
        print(f"ERROR generating batch embeddings: {e}")
        raise


def update_chunk_embedding(chunk_id: str, embedding: List[float]) -> Dict[str, Any]:
    """
    Aktualizuje embedding dla istniejącego chunka w Supabase.
    Synchroniczna funkcja (Supabase client jest sync).

    Args:
        chunk_id: UUID chunka w tabeli knowledge_chunks
        embedding: Wektor embedding (lista floatów)

    Returns:
        Słownik z informacją o sukcesie
    """
    supabase = get_supabase()

    try:
        response = supabase.table("knowledge_chunks").update({
            "embedding": embedding
        }).eq("id", chunk_id).execute()

        if not response.data:
            raise Exception(f"Nie znaleziono chunka o id: {chunk_id}")

        return {
            "chunk_id": chunk_id,
            "status": "updated",
            "embedding_dim": len(embedding)
        }

    except Exception as e:
        print(f"ERROR updating chunk embedding: {e}")
        raise


async def generate_embeddings_for_document(document_id: str, model: str = "text-embedding-3-small") -> Dict[str, Any]:
    """
    Generuje embeddingi dla wszystkich chunków należących do danego dokumentu (async).

    Args:
        document_id: UUID dokumentu w tabeli knowledge_documents
        model: Model OpenAI do embeddingów

    Returns:
        Raport z procesowania (liczba chunków, sukcesy, błędy)
    """
    supabase = get_supabase()

    # 1. Pobierz wszystkie chunki dla tego dokumentu
    try:
        response = supabase.table("knowledge_chunks").select("id, chunk_text").eq("document_id", document_id).execute()

        if not response.data:
            return {
                "document_id": document_id,
                "status": "no_chunks",
                "message": "Brak chunków dla tego dokumentu"
            }

        chunks = response.data
        chunk_ids = [c["id"] for c in chunks]
        chunk_texts = [c["chunk_text"] for c in chunks]

    except Exception as e:
        raise Exception(f"Błąd pobierania chunków: {e}")

    # 2. Generuj embeddingi (batch) - async
    try:
        embeddings = await generate_embeddings_batch(chunk_texts, model=model)
    except Exception as e:
        raise Exception(f"Błąd generowania embeddingów: {e}")

    # 3. Zapisz embeddingi do bazy
    updated_count = 0
    errors = []

    for chunk_id, embedding in zip(chunk_ids, embeddings):
        try:
            update_chunk_embedding(chunk_id, embedding)
            updated_count += 1
        except Exception as e:
            errors.append({"chunk_id": chunk_id, "error": str(e)})

    return {
        "document_id": document_id,
        "total_chunks": len(chunks),
        "updated": updated_count,
        "failed": len(errors),
        "errors": errors if errors else None,
        "model": model,
        "embedding_dim": len(embeddings[0]) if embeddings else 0
    }


async def generate_embeddings_for_all_documents(model: str = "text-embedding-3-small") -> Dict[str, Any]:
    """
    Generuje embeddingi dla WSZYSTKICH chunków w bazie, które nie mają jeszcze embeddingu (async).
    UWAGA: Może być kosztowne dla dużych baz!

    Returns:
        Raport z procesowania
    """
    supabase = get_supabase()

    # 1. Pobierz wszystkie chunki bez embeddingu
    try:
        response = supabase.table("knowledge_chunks").select("id, chunk_text").is_("embedding", "null").execute()

        if not response.data:
            return {
                "status": "completed",
                "message": "Wszystkie chunki mają już embeddingi"
            }

        chunks = response.data
        chunk_ids = [c["id"] for c in chunks]
        chunk_texts = [c["chunk_text"] for c in chunks]

    except Exception as e:
        raise Exception(f"Błąd pobierania chunków: {e}")

    # 2. Generuj embeddingi (batch) - async
    try:
        embeddings = await generate_embeddings_batch(chunk_texts, model=model)
    except Exception as e:
        raise Exception(f"Błąd generowania embeddingów: {e}")

    # 3. Zapisz embeddingi do bazy
    updated_count = 0
    errors = []

    for chunk_id, embedding in zip(chunk_ids, embeddings):
        try:
            update_chunk_embedding(chunk_id, embedding)
            updated_count += 1
        except Exception as e:
            errors.append({"chunk_id": chunk_id, "error": str(e)})

    return {
        "status": "completed",
        "total_chunks_processed": len(chunks),
        "updated": updated_count,
        "failed": len(errors),
        "errors": errors if errors else None,
        "model": model,
        "embedding_dim": len(embeddings[0]) if embeddings else 0
    }


async def generate_embeddings_by_tag(tag: str, model: str = "text-embedding-3-small") -> Dict[str, Any]:
    """
    Generuje embeddingi dla wszystkich chunków z danym tagiem (np. 'social', 'environmental') - async.

    Args:
        tag: Tag do filtrowania chunków (np. 'social', 'environmental', 'governance')
        model: Model OpenAI

    Returns:
        Raport z procesowania
    """
    supabase = get_supabase()

    # 1. Pobierz chunki z danym tagiem, które nie mają embeddingu
    try:
        response = supabase.table("knowledge_chunks").select("id, chunk_text").eq("tag", tag).is_("embedding", "null").execute()

        if not response.data:
            return {
                "tag": tag,
                "status": "no_chunks_to_process",
                "message": f"Brak chunków z tagiem '{tag}' bez embeddingu"
            }

        chunks = response.data
        chunk_ids = [c["id"] for c in chunks]
        chunk_texts = [c["chunk_text"] for c in chunks]

    except Exception as e:
        raise Exception(f"Błąd pobierania chunków dla tagu '{tag}': {e}")

    # 2. Generuj embeddingi (batch) - async
    try:
        embeddings = await generate_embeddings_batch(chunk_texts, model=model)
    except Exception as e:
        raise Exception(f"Błąd generowania embeddingów: {e}")

    # 3. Zapisz embeddingi do bazy
    updated_count = 0
    errors = []

    for chunk_id, embedding in zip(chunk_ids, embeddings):
        try:
            update_chunk_embedding(chunk_id, embedding)
            updated_count += 1
        except Exception as e:
            errors.append({"chunk_id": chunk_id, "error": str(e)})

    return {
        "tag": tag,
        "status": "completed",
        "total_chunks_processed": len(chunks),
        "updated": updated_count,
        "failed": len(errors),
        "errors": errors if errors else None,
        "model": model,
        "embedding_dim": len(embeddings[0]) if embeddings else 0
    }

