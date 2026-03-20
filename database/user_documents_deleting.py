from __future__ import annotations

from typing import Any, Dict

from fastapi import HTTPException

from database.supabase_client import get_supabase


def delete_user_document_cascade(*, user_id: str, document_id: str) -> Dict[str, Any]:
    """Usuwa dokument użytkownika oraz powiązane chunki (wektory) z Supabase.

    Kontrakt:
    - Weryfikuje, że dokument należy do user_id.
    - Kasuje user_document_chunks gdzie document_id.
    - Kasuje user_documents gdzie id.

    Zwraca liczby usuniętych rekordów.

    Uwaga: używamy Supabase service role key po stronie backendu, więc RLS nie chroni.
    Właśnie dlatego tu jest jawna walidacja właściciela dokumentu.
    """

    supabase = get_supabase()

    # 1) Sprawdź istnienie i właściciela dokumentu
    doc_res = (
        supabase.table("user_documents")
        .select("id, user_id")
        .eq("id", document_id)
        .limit(1)
        .execute()
    )

    if not doc_res.data:
        raise HTTPException(status_code=404, detail="Document not found")

    doc = doc_res.data[0]
    if str(doc.get("user_id")) != str(user_id):
        # celowo 403 zamiast 404, żeby było jasne, że to kwestia uprawnień
        raise HTTPException(status_code=403, detail="You do not have access to this document")

    # 2) Usuń powiązane chunki
    chunks_del_res = (
        supabase.table("user_document_chunks")
        .delete()
        .eq("document_id", document_id)
        .execute()
    )

    deleted_chunks = len(chunks_del_res.data or [])

    # 3) Usuń dokument
    doc_del_res = (
        supabase.table("user_documents")
        .delete()
        .eq("id", document_id)
        .execute()
    )

    deleted_docs = len(doc_del_res.data or [])

    return {
        "document_id": document_id,
        "deleted_documents": deleted_docs,
        "deleted_chunks": deleted_chunks,
    }

