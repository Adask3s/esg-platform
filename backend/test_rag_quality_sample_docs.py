import asyncio
import os
from pathlib import Path

import pytest

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")

from backend.RAG import rag_retriever
from backend.celery.report_tasks import VECTOR_QUERIES, _split_report_chunks_by_source
from backend.ingestion.chunker import chunk_text
from backend.ingestion.models import ChunkConfig
from backend.parsers.dispatcher import ParserDispatcher


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = PROJECT_ROOT / "sample_uploads"
SAMPLE_DOCS = [
    SAMPLE_DIR / "test_esg_budowa_metro_2025.docx",
    SAMPLE_DIR / "test_esg_obwodnica_2025.docx",
]

SCOPE_TERMS = {
    "Environmental": ("Environmental", "Scope", "tCO2e", "recykling"),
    "Social": ("Social", "BHP", "pracownik", "szkoleni"),
    "Governance": ("Governance", "audyt", "compliance", "Whistleblowing"),
}

EXPECTED_COMPANY_FACTS = {
    "Environmental": ("18 420 tCO2e", "24 760 tCO2e", "75,0%", "79,5%"),
    "Social": ("486 pracownik", "352 osoby", "13 740 godzin", "9 860 godzin"),
    "Governance": ("6 audytow", "4 audyty", "4 zgloszenia", "6 zgloszen"),
}

LEGAL_BAIT_VALUE = "999999"


def _scope_for_filter(filter_tag: str | None) -> str | None:
    if not filter_tag:
        return None
    normalized = filter_tag.lower()
    if normalized in {"environmental", "e"}:
        return "Environmental"
    if normalized in {"social", "s"}:
        return "Social"
    if normalized in {"governance", "g"}:
        return "Governance"
    return None


def _parse_sample_docx_chunks() -> list[dict]:
    dispatcher = ParserDispatcher()
    config = ChunkConfig(target_tokens=220, min_tokens=50, max_tokens=360, overlap_tokens=0)
    rows = []

    for doc_path in SAMPLE_DOCS:
        parse_result = dispatcher.parse(doc_path)
        assert parse_result.text
        assert parse_result.tables

        chunks = chunk_text(parse_result.text, config)
        assert chunks

        for index, chunk in enumerate(chunks):
            rows.append(
                {
                    "source": doc_path.name,
                    "chunk_text": chunk.text,
                    "similarity": 0.4 - (index * 0.001),
                }
            )
    return rows


def _matches_scope(text: str, scope: str) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in SCOPE_TERMS[scope])


def _legal_bait_row(scope: str) -> dict:
    return {
        "source": f"CELEX_{scope}_legal_bait.pdf",
        "chunk_text": (
            f"Rozporzadzenie testowe dla {scope}: przykladowy wskaznik prawny "
            f"{LEGAL_BAIT_VALUE} tCO2e nie jest dana firmy i nie moze trafic do KPI."
        ),
        "similarity": 0.99,
    }


class _FakeRpc:
    def __init__(self, data: list[dict]):
        self._data = data

    def execute(self):
        return type("FakeResponse", (), {"data": self._data})()


class _FakeSupabase:
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def rpc(self, name: str, payload: dict):
        assert name == "match_chunks2"
        scope = _scope_for_filter(payload.get("filter_tag"))
        if scope is None:
            data = self.rows
        else:
            data = [row for row in self.rows if _matches_scope(row["chunk_text"], scope)]
            data.append(_legal_bait_row(scope))
        return _FakeRpc(data[: payload.get("match_count", 35)])


async def _fake_embedding(_query: str) -> list[float]:
    return [0.1, 0.2, 0.3]


@pytest.mark.parametrize("scope", ["Environmental", "Social", "Governance"])
def test_sample_docx_rag_retrieval_returns_scope_specific_company_data(monkeypatch, scope):
    rows = _parse_sample_docx_chunks()
    monkeypatch.setattr(rag_retriever, "get_embedding", _fake_embedding)
    monkeypatch.setattr(rag_retriever, "get_supabase", lambda: _FakeSupabase(rows))

    retrieved = asyncio.run(
        rag_retriever.retrieve_context_async(
            query=VECTOR_QUERIES[scope],
            user_id="00000000-0000-0000-0000-000000000000",
            match_count=35,
            match_threshold=0.20,
            filter_tag=scope,
        )
    )

    assert retrieved
    user_chunks, kb_chunks = _split_report_chunks_by_source(retrieved)
    user_text = "\n".join(user_chunks)
    kb_text = "\n".join(kb_chunks)

    for expected in EXPECTED_COMPANY_FACTS[scope]:
        assert expected in user_text

    assert LEGAL_BAIT_VALUE not in user_text
    assert LEGAL_BAIT_VALUE in kb_text
