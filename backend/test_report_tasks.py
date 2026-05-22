import json
from types import SimpleNamespace

import backend.RAG.rag_retriever as rag_retriever
import backend.celery.report_tasks as report_tasks
import database.report_repo as report_repo
from backend.celery.report_tasks import _report_filter_candidates
from backend.report_validation import CHECKLISTS, _normalize_validation_payload


def test_report_filter_candidates_include_frontend_tag_aliases():
    assert _report_filter_candidates("Environmental") == [
        "Environmental",
        "environmental",
        "E",
        "e",
    ]
    assert _report_filter_candidates("Social") == ["Social", "social", "S", "s"]
    assert _report_filter_candidates("Governance") == [
        "Governance",
        "governance",
        "G",
        "g",
    ]


def test_report_filter_candidates_for_esg_do_not_filter():
    assert _report_filter_candidates("ESG") == [None]


def test_generate_report_task_returns_saved_report_id(monkeypatch):
    async def fake_retrieve_context_async(**kwargs):
        return ["--- DOKUMENT: raport.docx ---\nScope 1 emissions: 12 tCO2e"]

    report_payload = {
        "kategoria": "Environmental",
        "wskazniki_liczbowe": [{"nazwa": "Scope 1", "wartosc": 12, "jednostka": "tCO2e"}],
    }

    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured["messages"] = kwargs["messages"]
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=json.dumps(report_payload))
                    )
                ]
            )

    class FakeOpenAI:
        def __init__(self, api_key):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(rag_retriever, "retrieve_context_async", fake_retrieve_context_async)
    monkeypatch.setattr(report_repo, "save_report", lambda **kwargs: 42)
    monkeypatch.setattr(report_tasks, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(report_tasks.generate_report_task, "update_state", lambda *args, **kwargs: None)

    result = report_tasks.generate_report_task.run("u1", "Environmental", "SASB")

    assert result["status"] == "success"
    assert result["report_id"] == 42
    assert result["standard"] == "SASB"
    assert result["data"] == {**report_payload, "standard_raportowania": "SASB"}
    assert "CHECKLISTA STANDARDU SASB" in captured["messages"][1]["content"]
    assert "IF-EN-160a.1" in captured["messages"][1]["content"]


def test_validation_score_and_status_are_computed_from_items_not_llm_score():
    payload = {
        "overall_status": "missing",
        "score": 0,
        "items": [
            {"code": "GRI 305-1", "label": "Direct Scope 1 GHG emissions", "present": True},
            {"code": "GRI 305-2", "label": "Energy indirect Scope 2 GHG emissions", "present": "true"},
        ],
        "summary": "Model summary can be inconsistent.",
    }

    result = _normalize_validation_payload(
        payload=payload,
        report_id="7",
        standard="GRI",
        checklist=CHECKLISTS["GRI"],
    )

    assert result.score == 25
    assert result.overall_status == "partial"
    assert sum(1 for item in result.items if item.present) == 2
