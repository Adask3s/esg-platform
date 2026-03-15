from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from database.supabase_client import get_supabase
from backend.embeddings.embedding_service import get_embedding

DEFAULT_MATCH_THRESHOLD: float = 0.5 # próg podobienstwa
DEFAULT_MATCH_COUNT: int = 12 # top_k embeddingu - ile wartosci bedzie wzietych pod uwage

async def retrieve_context_async(
    query: str,
    user_id: Optional[str] = None,  # reserved for future filtering
    *,
    match_threshold: float = DEFAULT_MATCH_THRESHOLD,
    match_count: int = DEFAULT_MATCH_COUNT,
    filter_tag: Optional[str] = None,
) -> List[str]:
    """
    Asynchronously retrieve context chunks for a given query.

    Args:
        query: Natural language query text.
        user_id: ID of the requesting user. Not used in current RPC but kept for future filtering.
        match_threshold: Minimum similarity threshold.
        match_count: Max number of matches to return.
        filter_tag: Optional tag filter passed to the RPC (reserved for future use).

    Returns:
        List of chunk_texts sorted by similarity (descending).
    """
    # 1) Generate embedding for the query
    query_embedding: List[float] = await get_embedding(query)
    if not query_embedding:
        return []

    # 2) Prepare RPC payload
    # Placeholder for future per-user filtering. Example options when SQL supports it:
    # - Use `filter_tag` like f"user:{user_id}" (convention-based) OR
    # - Extend RPC signature to accept `filter_user_id` explicitly.
    payload: Dict[str, Any] = {
        "query_embedding": query_embedding,
        "match_threshold": match_threshold,
        "match_count": match_count,
        # Current SQL signature supports `filter_tag`; keep it None unless provided.
        "filter_tag": filter_tag,
    }

    # 3) Call Supabase RPC
    supabase = get_supabase()
    try:
        response = supabase.rpc("match_chunks2", payload).execute()
    except Exception as exc:
        raise RuntimeError(f"RPC match_chunks2 failed: {exc}") from exc

    data: List[Dict[str, Any]] = getattr(response, "data", None) or []

    # 4) Sort by similarity desc and return only chunk_text
    # Expected item keys: chunk_id, chunk_text, tag, source, similarity
    sorted_items = sorted(
        data,
        key=lambda item: float(item.get("similarity", 0.0)),
        reverse=True,
    )
    return [str(item.get("chunk_text", "")) for item in sorted_items if item.get("chunk_text")]

def retrieve_context(
    query: str,
    user_id: Optional[str] = None,
    *,
    match_threshold: float = DEFAULT_MATCH_THRESHOLD,
    match_count: int = DEFAULT_MATCH_COUNT,
    filter_tag: Optional[str] = None,
) -> List[str]:
    """
    Synchronous wrapper for `retrieve_context_async`.

    Safe in non-async contexts. If called from within a running event loop,
    raises a RuntimeError to avoid deadlocks; use `await retrieve_context_async(...)` instead.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running event loop — safe to create one.
        return asyncio.run(
            retrieve_context_async(
                query,
                user_id,
                match_threshold=match_threshold,
                match_count=match_count,
                filter_tag=filter_tag,
            )
        )
    else:
        # We are already in an event loop; ask caller to use async API instead.
        raise RuntimeError(
            "retrieve_context() called from within an event loop. "
            "Use `await retrieve_context_async(...)` in async contexts."
        )
"""
for testing:
python -m backend.RAG.rag_retriever -q "emisje CO2 budownictwo GRI" --threshold 0.75 --count 10
"""

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Run RAG retrieval and print results to terminal")
    parser.add_argument("-q", "--query", required=True, help="Query text to search for context")
    parser.add_argument("-u", "--user-id", required=False, default=None, help="Optional user ID (reserved for future filtering)")
    parser.add_argument("--threshold", type=float, default=DEFAULT_MATCH_THRESHOLD, help="Match similarity threshold (default: %(default)s)")
    parser.add_argument("--count", type=int, default=DEFAULT_MATCH_COUNT, help="Max number of matches to return (default: %(default)s)")
    parser.add_argument("--tag", dest="filter_tag", default=None, help="Optional tag filter passed to RPC")

    args = parser.parse_args()

    try:
        results = retrieve_context(
            args.query,
            args.user_id,
            match_threshold=args.threshold,
            match_count=args.count,
            filter_tag=args.filter_tag,
        )
        if results:
            print("Retrieved chunks (most similar first):")
            for i, text in enumerate(results, start=1):
                print(f"{i}. {text}")
        else:
            print("No results found.")
    except Exception as e:
        print(f"ERROR running retrieval: {e}", file=sys.stderr)
        sys.exit(1)