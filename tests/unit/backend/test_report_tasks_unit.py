from __future__ import annotations

import backend.RAG.rag_retriever as rag_retriever
import backend.celery.report_tasks as report_tasks
from backend.celery.report_tasks import (
    _build_report_prompt,
    _format_standard_checklist,
    _report_filter_candidates,
    _split_report_chunks_by_source,
)


def test_report_filter_candidates_match_frontend_aliases():
    assert _report_filter_candidates("Environmental") == ["Environmental", "environmental", "E", "e"]
    assert _report_filter_candidates("Social") == ["Social", "social", "S", "s"]
    assert _report_filter_candidates("Governance") == ["Governance", "governance", "G", "g"]
    assert _report_filter_candidates("ESG") == [None]


def test_split_report_chunks_routes_legal_sources_away_from_company_data():
    chunks = [
        "--- DOKUMENT: company.docx ---\nEmisje Scope 1: 12 tCO2e",
        "--- DOKUMENT: CELEX_2024.pdf ---\nLegal reference 999999",
        "--- DOKUMENT: Rozporządzenie UE.pdf ---\nRegulatory context",
    ]

    user_chunks, kb_chunks = _split_report_chunks_by_source(chunks)

    assert user_chunks == [chunks[0]]
    assert kb_chunks == chunks[1:]


def test_format_standard_checklist_contains_codes_and_labels():
    checklist = _format_standard_checklist("TCFD")

    assert "TCFD Governance a" in checklist
    assert "Board oversight" in checklist


def test_build_report_prompt_contains_source_boundaries_and_selected_standard():
    prompt = _build_report_prompt(
        target_tag="ESG",
        user_context="company data",
        kb_context="legal data",
        hint="focus hint",
        reporting_standard="SASB",
    )

    assert "ZBIÓR 1: DOKUMENTY FIRMY" in prompt
    assert "ZBIÓR 2: BAZA WIEDZY / PRAWO UE" in prompt
    assert "CHECKLISTA STANDARDU SASB" in prompt
    assert "IF-EN-160a.1" in prompt


def test_generate_report_task_returns_partial_success_without_openai_when_no_chunks(monkeypatch):
    async def fake_retrieve_context_async(**_kwargs):
        return []

    monkeypatch.setattr(rag_retriever, "retrieve_context_async", fake_retrieve_context_async)
    monkeypatch.setattr(report_tasks.generate_report_task, "update_state", lambda *args, **kwargs: None)

    result = report_tasks.generate_report_task.run("user-1", "Social", "TCFD")

    assert result["status"] == "partial_success"
    assert result["kategoria"] == "Social"
    assert result["standard"] == "TCFD"
    assert result["data"] is None
    assert result["used_chunks"] == []
