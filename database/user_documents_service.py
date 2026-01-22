import asyncio
from database.supabase_client import get_supabase
from backend.ingestion.chunker import chunk_text
from backend.ingestion.models import ChunkConfig
# Importujemy Twój działający serwis embeddingów
from backend.embeddings.embedding_service import get_embedding


async def process_and_save_user_document(
        user_id: str,
        filename: str,
        raw_text: str,
        file_type: str = "pdf",
        tag: str = "user_upload"
):
    """
    1. Zapisuje dokument w tabeli user_documents.
    2. Tnie tekst na chunki.
    3. Generuje embeddingi.
    4. Zapisuje chunki w tabeli user_document_chunks.
    """
    supabase = get_supabase()

    # 1. Zapis dokumentu (Rodzic)
    print(f"Saving user document: {filename} for user {user_id}")

    document_payload = {
        "user_id": user_id,
        "filename": filename,
        "file_type": file_type,
        "raw_text": raw_text,
        "tag": tag
    }

    # Insert i pobranie ID
    doc_response = supabase.table("user_documents").insert(document_payload).execute()

    # Obsługa błędu lub braku danych
    if not doc_response.data:
        raise Exception("Failed to insert user document")

    document_id = doc_response.data[0]['id']

    # 2. Chunkowanie (Używamy tej samej konfiguracji co w knowledge base)
    config = ChunkConfig(target_tokens=800, min_tokens=400, max_tokens=1200, overlap_tokens=100)
    generated_chunks = chunk_text(raw_text, config)

    print(f"Generated {len(generated_chunks)} chunks. Generating embeddings...")

    # 3. Generowanie Embeddingów i przygotowanie payloadu
    chunks_payload = []

    for chunk_obj in generated_chunks:
        # To jest ten moment - wywołanie OpenAI
        embedding_vector = await get_embedding(chunk_obj.text)

        chunks_payload.append({
            "document_id": document_id,
            "chunk_text": chunk_obj.text,
            "embedding": embedding_vector,  # <-- Zapisujemy wektor!
            "tag": tag
        })

    # 4. Zapis chunków do bazy (Batch insert)
    if chunks_payload:
        supabase.table("user_document_chunks").insert(chunks_payload).execute()

    return {
        "document_id": document_id,
        "chunks_processed": len(chunks_payload),
        "status": "success"
    }