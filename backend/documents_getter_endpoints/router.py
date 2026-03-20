from typing import List, Optional, Literal
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

try:
    # prefer relative import when used as a package
    from ..auth import get_current_user
except Exception:
    from backend.auth import get_current_user  # type: ignore

from database.supabase_client import get_supabase

router = APIRouter(prefix="/documents", tags=["documents"])  # grouped under /documents


class DocumentItem(BaseModel):
    id: str
    name: str
    origin: Literal["user", "knowledge"]
    tag: Optional[str] = None
    created_at: Optional[datetime] = None
    # Optional metadata
    source: Optional[str] = None  # for knowledge docs or static "user_upload"
    file_type: Optional[str] = None  # for user docs
    document_type: Optional[str] = None  # for knowledge docs
    version: Optional[str] = None  # for knowledge docs


def _apply_pagination(query, limit: int | None, offset: int | None):
    if limit is None and offset is None:
        return query
    # Supabase python client uses range(from, to) inclusive
    start = offset or 0
    end = start + (limit if limit is not None else 50) - 1
    return query.range(start, end)


@router.get("/mine", response_model=List[DocumentItem])
def list_my_documents(
    tag: Optional[str] = Query(None, description="Filter by tag"),
    limit: Optional[int] = Query(50, ge=1, le=500),
    offset: Optional[int] = Query(0, ge=0),
    user=Depends(get_current_user),
):
    """List documents uploaded by the authenticated user (from user_documents)."""
    if not user or "id" not in user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    supabase = get_supabase()

    q = supabase.table("user_documents").select("id, filename, file_type, tag, created_at")
    # Filter by current user
    q = q.eq("user_id", str(user["id"]))
    if tag:
        q = q.eq("tag", tag)

    q = _apply_pagination(q, limit, offset)

    res = q.execute()
    items = []
    for row in res.data or []:
        items.append(
            DocumentItem(
                id=row.get("id"),
                name=row.get("filename"),
                origin="user",
                tag=row.get("tag"),
                created_at=row.get("created_at"),
                source="user_upload",
                file_type=row.get("file_type"),
            )
        )
    return items


@router.get("/knowledge", response_model=List[DocumentItem])
def list_knowledge_documents(
    tag: Optional[str] = Query(None, description="Filter by tag"),
    source: Optional[str] = Query(None, description="Filter by source"),
    limit: Optional[int] = Query(50, ge=1, le=500),
    offset: Optional[int] = Query(0, ge=0),
    user=Depends(get_current_user),
):
    # tylko admin
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Only admins can access knowledge documents")

    supabase = get_supabase()

    q = supabase.table("knowledge_documents").select(
        "id, title, source, tag, created_at, document_type, version"
    )
    if tag:
        q = q.eq("tag", tag)
    if source:
        q = q.eq("source", source)

    q = _apply_pagination(q, limit, offset)

    res = q.execute()
    items = []
    for row in res.data or []:
        items.append(
            DocumentItem(
                id=row.get("id"),
                name=row.get("title"),
                origin="knowledge",
                tag=row.get("tag"),
                created_at=row.get("created_at"),
                source=row.get("source"),
                document_type=row.get("document_type"),
                version=row.get("version"),
            )
        )
    return items


@router.get("/", response_model=List[DocumentItem])
def list_all_documents(
    tag: Optional[str] = Query(None),
    source: Optional[str] = Query(None, description="Only applies to knowledge documents"),
    limit: Optional[int] = Query(100, ge=1, le=500),
    offset: Optional[int] = Query(0, ge=0),
    user=Depends(get_current_user),
):
    """Combined list of user's documents and knowledge base documents.
    Optional filters and simple pagination are supported.
    """
    mine = list_my_documents(tag=tag, limit=limit, offset=offset, user=user)

    # baza wiedzy tylko kiedy admin
    knowledge: List[DocumentItem] = []
    if user and user.get("role") == "admin":
        knowledge = list_knowledge_documents(tag=tag, source=source, limit=limit, offset=offset, user=user)

    # Simple merge; in the future consider separate pagination per-origin
    combined = [*mine, *knowledge]

    # Optionally, sort by created_at desc (if available)
    combined.sort(key=lambda x: x.created_at or datetime.min, reverse=True)
    return combined
