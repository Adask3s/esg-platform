from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

import backend.main as main


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    main.app.dependency_overrides.clear()
    yield
    main.app.dependency_overrides.clear()


def _mock_openai_client(create_impl):
    completions = SimpleNamespace(create=create_impl)
    chat = SimpleNamespace(completions=completions)
    return SimpleNamespace(chat=chat)


def _mock_openai_success(content: str):
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )

    def _create(**kwargs):
        return response

    return _mock_openai_client(_create)


def test_chat_ask_fallback_when_no_context_found(client, monkeypatch):
    async def fake_retrieve_context_async(query, match_count, filter_tag):
        return []

    monkeypatch.setattr(main, "retrieve_context_async", fake_retrieve_context_async)
    monkeypatch.setattr(main, "get_openai_client", lambda: _mock_openai_success("Fallback answer"))

    response = client.post(
        "/chat/ask",
        json={"query": "Co to jest ESG?", "tag": "Environmental"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["rag_used"] is False
    assert "Brak danych w załączonych dokumentach" in payload["debug_prompt"]
    assert payload["ai_answer"] == "Fallback answer"


def test_chat_ask_returns_429_on_openai_rate_limit(client, monkeypatch):
    class FakeRateLimitError(Exception):
        pass

    async def fake_retrieve_context_async(query, match_count, filter_tag):
        return ["chunk"]

    def fake_construct_prompt(query, context_chunks, focused_tag):
        return "prompt"

    def fail_with_rate_limit(**kwargs):
        raise FakeRateLimitError("rate limit")

    monkeypatch.setattr(main, "retrieve_context_async", fake_retrieve_context_async)
    monkeypatch.setattr(main, "construct_prompt", fake_construct_prompt)
    monkeypatch.setattr(main.openai, "RateLimitError", FakeRateLimitError)
    monkeypatch.setattr(main, "get_openai_client", lambda: _mock_openai_client(fail_with_rate_limit))

    response = client.post("/chat/ask", json={"query": "Pytanie testowe"})

    assert response.status_code == 429
    assert "Rate Limit (429)" in response.json()["detail"]


def test_chat_ask_returns_500_on_unexpected_openai_error(client, monkeypatch):
    async def fake_retrieve_context_async(query, match_count, filter_tag):
        return ["chunk"]

    def fake_construct_prompt(query, context_chunks, focused_tag):
        return "prompt"

    def fail_unexpected(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(main, "retrieve_context_async", fake_retrieve_context_async)
    monkeypatch.setattr(main, "construct_prompt", fake_construct_prompt)
    monkeypatch.setattr(main, "get_openai_client", lambda: _mock_openai_client(fail_unexpected))

    response = client.post("/chat/ask", json={"query": "Pytanie testowe"})

    assert response.status_code == 500
    assert "Wewnętrzny błąd serwera AI" in response.json()["detail"]
    assert "boom" in response.json()["detail"]


def test_chat_ask_rejects_empty_query(client):
    response = client.post("/chat/ask", json={"query": "   "})

    assert response.status_code == 400
    assert "Pytanie nie może być puste" in response.json()["detail"]


def test_documents_mine_requires_auth(client):
    response = client.get("/documents/mine")

    assert response.status_code == 401
    assert "Not authenticated" in response.json()["detail"]


def test_documents_knowledge_forbidden_for_non_admin(client):
    main.app.dependency_overrides[main.get_current_user] = lambda: {
        "id": "u-1",
        "username": "user",
        "role": "user",
    }

    response = client.get("/documents/knowledge")

    assert response.status_code == 403
    assert "Only admins can access knowledge documents" in response.json()["detail"]


def test_user_documents_delete_returns_401_when_user_has_no_id(client):
    main.app.dependency_overrides[main.get_current_user] = lambda: {"role": "user"}

    response = client.post("/user/documents/delete", json={"document_id": "doc-1"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Unauthorized"
