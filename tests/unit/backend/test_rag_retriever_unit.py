from __future__ import annotations

import asyncio

from backend.RAG import rag_retriever


class FakeRpcResult:
    def __init__(self, rows):
        self.data = rows


class FakeRpc:
    def __init__(self, rows):
        self.rows = rows

    def execute(self):
        return FakeRpcResult(self.rows)


class FakeSupabase:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def rpc(self, name, payload):
        self.calls.append((name, payload))
        return FakeRpc(self.rows)


def test_retrieve_context_async_calls_match_chunks_rpc_and_sorts_results(monkeypatch):
    rows = [
        {"source": "low.docx", "chunk_text": "low", "similarity": 0.1},
        {"source": "high.docx", "chunk_text": "high", "similarity": 0.9},
    ]
    fake_supabase = FakeSupabase(rows)

    async def fake_embedding(query):
        assert query == "emisje"
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(rag_retriever, "get_embedding", fake_embedding)
    monkeypatch.setattr(rag_retriever, "get_supabase", lambda: fake_supabase)

    result = asyncio.run(
        rag_retriever.retrieve_context_async(
            "emisje",
            user_id="user-1",
            match_threshold=0.25,
            match_count=5,
            filter_tag="Environmental",
        )
    )

    assert result == [
        "--- DOKUMENT: high.docx ---\nhigh",
        "--- DOKUMENT: low.docx ---\nlow",
    ]
    assert fake_supabase.calls[0][0] == "match_chunks2"
    assert fake_supabase.calls[0][1]["query_user_id"] == "user-1"
    assert fake_supabase.calls[0][1]["filter_tag"] == "Environmental"


def test_retrieve_context_async_returns_empty_when_embedding_is_empty(monkeypatch):
    async def fake_embedding(_query):
        return []

    monkeypatch.setattr(rag_retriever, "get_embedding", fake_embedding)
    monkeypatch.setattr(
        rag_retriever,
        "get_supabase",
        lambda: (_ for _ in ()).throw(AssertionError("Supabase should not be called")),
    )

    assert asyncio.run(rag_retriever.retrieve_context_async("empty")) == []
