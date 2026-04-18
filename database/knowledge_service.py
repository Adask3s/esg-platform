from database.supabase_client import get_supabase
# Importujemy chunker kolegi
from backend.ingestion.chunker import chunk_text
from backend.ingestion.models import ChunkConfig
from backend.embeddings.embedding_service import get_embedding

def check_knowledge_document_hash(file_hash: str) -> bool:
    supabase = get_supabase()
    result = supabase.table("knowledge_documents").select("id").eq("file_hash", file_hash).execute()
    return len(result.data) > 0

# Funkcja orkiestrująca proces RAG Ingestion:
# 1. Insert do knowledge_documents (z raw_text i tagiem).
# 2. Chunkowanie (użycie ingestion modułu).
# 3. Insert do knowledge_chunks (z tagiem i document_id).
async def add_document_to_knowledge_base(title: str, source: str, raw_text: str, file_hash: str = None, tag: str = "general", document_type: str = "general", version: str = "1.0", uploaded_by: str | None = None):
    supabase = get_supabase()

    # Zapis dokumentu ---
    print(f"Adding document: {title}")

    # Mapowanie na kolumny tabeli knowledge_documents
    document_payload = {
        "title": title,
        "source": source,
        "tag": tag,  # Zapisujemy tag
        "raw_text": raw_text,  # Zapisujemy pełny tekst oryginału
        "document_type": document_type,
        "version": version
    }
    if file_hash:
        document_payload["file_hash"] = file_hash
    if uploaded_by:
        document_payload["uploaded_by"] = uploaded_by

    doc_response = supabase.table("knowledge_documents").insert(document_payload).execute()

    # Obsługa błędów (Supabase-py może zwracać błąd w różny sposób zależnie od wersji)
    if not doc_response.data:
        raise Exception("Błąd zapisu dokumentu: Nie otrzymano danych zwrotnych z Supabase.")

    # Wyciągamy UUID nowo powstałego dokumentu
    document_id = doc_response.data[0]['id']

    # Cięcie na kawałki (Chunking)
    # Konfiguracja dla modułu Patryka (możesz dostosować wartości)
    # Ustawiamy NAJMNIEJSZE MOŻLIWE wartości, na jakie pozwala models.py
    # ustawimy tak z racji na testy, potem wrócimy do oryginalnych wartosci, czyli:
    #     config = ChunkConfig(
    #         target_tokens=800,  # Celujemy w solidne kawałki tekstu
    #         min_tokens=400,
    #         max_tokens=1200,
    #         overlap_tokens=100  # Zakładka, żeby nie gubić wątku
    #     )
    config = ChunkConfig(
        target_tokens=60,  # Musi być >= 50
        min_tokens=50,  # Musi być >= 50 (tu był Twój błąd)
        max_tokens=100,  # Musi być >= 100
        overlap_tokens=10
    )

    # Używamy funkcji Patryka z pliku chunker.py
    # Zwraca listę obiektów Chunk (z polami text, token_count itd.)
    generated_chunks = chunk_text(raw_text, config)
    print(f"Generated {len(generated_chunks)} chunks. Generating embeddings...")

    # Zapis Chunków (ADAPTACJA DO ISTNIEJĄCEJ STRUKTURY)
    chunks_payload = []
    skipped_chunks = 0

    for chunk_obj in generated_chunks:
        try:
            # Wywołujemy OpenAI dla każdego kawałka - embeddingi generowane OD RAZU
            embedding_vector = await get_embedding(chunk_obj.text)

            # Mapowanie na kolumny tabeli knowledge_chunks
            chunks_payload.append({
                "document_id": document_id,  # uuid NOT NULL
                "chunk_text": chunk_obj.text,  # text NULL
                "tag": tag,  # varchar NULL
                "embedding": embedding_vector  # Embedding generowany od razu
                # created_at - NULL (baza wstawi automatycznie)
            })
        except Exception as e:
            # Jeśli embedding failuje, pomijamy chunk i kontynuujemy
            print(f"WARNING: Nie udało się wygenerować embeddingu dla chunka: {e}")
            skipped_chunks += 1
            continue

    # Wykonujemy jeden duży insert (bulk insert) zamiast setki małych
    if chunks_payload:
        supabase.table("knowledge_chunks").insert(chunks_payload).execute()

    print(f"Successfully inserted {len(chunks_payload)} chunks with embeddings. Skipped: {skipped_chunks}")

    return {
        "document_id": document_id,
        "chunks_created": len(chunks_payload),
        "chunks_skipped": skipped_chunks,
        "tag_assigned": tag,
        "embedding_model": "text-embedding-3-small"
    }