"""
Serwis do generowania embeddingów dla chunków tekstu.
Używa OpenAI text-embedding-3-small (1536 wymiarów).
"""

import os
from typing import List, Dict, Any, Optional
import asyncio
import openai
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
    Zawiera mechanizm Exponential Backoff na wypadek awarii API OpenAI.
    """
    if not text:
        return []

    client = _get_async_client()

    # Ograniczenie długości tekstu
    max_chars = 30000
    if len(text) > max_chars:
        text = text[:max_chars]
        print(f"WARNING: Tekst został skrócony do {max_chars} znaków")

    text = text.replace("\n", " ")

    # --- MECHANIZM RETRY (Exponential Backoff) ---
    max_retries = 3
    base_delay = 1.0  # sekunda

    for attempt in range(max_retries):
        try:
            response = await client.embeddings.create(
                model=model,
                input=text,
                timeout=10.0  # Twardy limit czasu (zabezpieczenie przed zawieszeniem)
            )
            return response.data[0].embedding

        except (openai.RateLimitError, openai.APIConnectionError, openai.APITimeoutError) as e:
            # Błędy sieciowe / limity - czekamy i ponawiamy
            if attempt == max_retries - 1:
                print(f"CRITICAL: Błąd OpenAI po {max_retries} próbach: {str(e)}")
                raise Exception(f"Nie udało się wygenerować wektora z powodu awarii OpenAI: {str(e)}")

            delay = base_delay * (2 ** attempt)
            print(
                f"Ostrzeżenie: Błąd API OpenAI ({type(e).__name__}). Próba {attempt + 1}/{max_retries}. Czekam {delay}s...")
            await asyncio.sleep(delay)

        except Exception as e:
            # Inne błędy (np. zła autoryzacja klucza) - przerywamy natychmiast
            print(f"ERROR: Krytyczny błąd strukturalny embeddingu: {e}")
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
    Zawiera mechanizm Exponential Backoff na wypadek awarii API OpenAI.
    """
    client = _get_async_client()

    if not texts:
        return []

    batch_size = 100
    all_embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        max_chars = 30000
        truncated_batch = [t[:max_chars] if len(t) > max_chars else t for t in batch]

        # --- MECHANIZM RETRY (Exponential Backoff) ---
        max_retries = 3
        base_delay = 1.0

        for attempt in range(max_retries):
            try:
                response = await client.embeddings.create(
                    model=model,
                    input=truncated_batch,
                    timeout=20.0  # Większy timeout dla paczki
                )
                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)
                break  # Sukces dla tego batcha, wychodzimy z pętli prób

            except (openai.RateLimitError, openai.APIConnectionError, openai.APITimeoutError) as e:
                if attempt == max_retries - 1:
                    print(f"CRITICAL: Błąd OpenAI Batch po {max_retries} próbach: {str(e)}")
                    raise Exception(f"Awaria OpenAI podczas przetwarzania paczki wektorów: {str(e)}")

                delay = base_delay * (2 ** attempt)
                print(
                    f"Ostrzeżenie: Błąd API OpenAI Batch ({type(e).__name__}). Próba {attempt + 1}/{max_retries}. Czekam {delay}s...")
                await asyncio.sleep(delay)

            except Exception as e:
                print(f"ERROR generating batch embeddings: {e}")
                raise

    return all_embeddings


def update_chunk_embedding(chunk_id: str, embedding: List[float], table_name: str = "knowledge_chunks") -> Dict[str, Any]:
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
        # ZMIANA: używamy zmiennej table_name zamiast wpisanego na sztywno "knowledge_chunks"
        # żeby to działało dla bazy danych, ale tez dokumentow uzytkownika
        response = supabase.table(table_name).update({
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


async def generate_embeddings_for_document(document_id: str, model: str = "text-embedding-3-small", table_name: str = "knowledge_chunks") -> Dict[str, Any]:
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
        response = supabase.table(table_name).select("id, chunk_text").eq("document_id", document_id).execute()

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
            update_chunk_embedding(chunk_id, embedding, table_name=table_name)
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

