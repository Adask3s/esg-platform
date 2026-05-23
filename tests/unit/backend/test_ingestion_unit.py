from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.ingestion.chunker import chunk_text, estimate_tokens, make_blocks, normalize_newlines
from backend.ingestion.filter import keyword_filter_blocks
from backend.ingestion.models import ChunkConfig, IngestUrlRequest, KeywordFilterConfig


def test_normalize_newlines_and_estimate_tokens_are_stable():
    assert normalize_newlines("a\r\nb\rc") == "a\nb\nc"
    assert estimate_tokens("") == 0
    assert estimate_tokens("Scope 1 emissions: 12 tCO2e.") > 0


def test_make_blocks_repairs_pdf_hyphenation_and_merges_short_heading():
    text = "ENVIRONMENTAL\nfoto-\nwoltaicznych instalacji.\n\nDrugi akapit."

    blocks = make_blocks(text)

    assert "fotowoltaicznych" in blocks[0]
    assert blocks[0].startswith("ENVIRONMENTAL")
    assert blocks[-1] == "Drugi akapit."


def test_keyword_filter_blocks_supports_context_and_match_all():
    blocks = [
        "intro",
        "emisje CO2 i energia",
        "recykling",
        "governance",
    ]

    filtered, indices = keyword_filter_blocks(
        blocks,
        KeywordFilterConfig(
            keywords=["emisje", "energia"],
            match_all=True,
            context_before=1,
            context_after=1,
        ),
    )

    assert indices == [0, 1, 2]
    assert filtered == blocks[:3]


def test_keyword_filter_blocks_returns_empty_when_keywords_do_not_match():
    filtered, indices = keyword_filter_blocks(
        ["environmental", "social"],
        KeywordFilterConfig(keywords=["governance"]),
    )

    assert filtered == []
    assert indices == []


def test_chunk_config_rejects_invalid_bounds():
    with pytest.raises(ValidationError):
        ChunkConfig(target_tokens=100, min_tokens=150, max_tokens=200)

    with pytest.raises(ValidationError):
        ChunkConfig(target_tokens=200, min_tokens=100, max_tokens=150)


def test_chunk_text_splits_large_text_without_losing_content():
    text = " ".join(f"Sentence {idx} has ESG data." for idx in range(120))
    chunks = chunk_text(text, ChunkConfig(target_tokens=50, min_tokens=50, max_tokens=100, overlap_tokens=0))

    assert len(chunks) > 1
    assert chunks[0].start_block == 0
    assert all(chunk.text for chunk in chunks)


def test_ingest_url_request_builds_filter_and_chunk_configs():
    request = IngestUrlRequest(
        url="https://example.com",
        keywords=["ESG"],
        context_before=1,
        target_tokens=100,
        min_tokens=50,
        max_tokens=150,
        overlap_tokens=10,
    )

    keyword_cfg, chunk_cfg = request.to_configs()

    assert keyword_cfg.keywords == ["ESG"]
    assert keyword_cfg.context_before == 1
    assert chunk_cfg.target_tokens == 100
    assert chunk_cfg.max_tokens == 150
