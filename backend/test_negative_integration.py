from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

import backend.auth as auth_mod
import backend.main as main


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    main.app.dependency_overrides.clear()
    yield
    main.app.dependency_overrides.clear()


def set_auth_user(user):
    main.app.dependency_overrides[main.get_current_user] = lambda: user
    main.app.dependency_overrides[auth_mod.get_current_user] = lambda: user


def test_chat_ask_requires_auth(client):
    response = client.post("/chat/ask", json={"query": "Co to jest ESG?"})
    assert response.status_code == 401


def test_chat_ask_rejects_empty_query(client):
    set_auth_user({"id": "u1", "role": "user"})
    response = client.post("/chat/ask", json={"query": "   "})
    assert response.status_code == 400
    assert "Pytanie nie może być puste" in response.json()["detail"]


def test_chat_ask_rejects_user_without_id(client):
    set_auth_user({"role": "user"})
    response = client.post("/chat/ask", json={"query": "test"})
    assert response.status_code == 401


def test_status_requires_auth(client):
    response = client.get("/status/task-1")
    assert response.status_code == 401


def test_status_forbidden_for_foreign_task(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})
    monkeypatch.setattr(main, "_check_task_owner", lambda task_id, user_id: False)

    response = client.get("/status/task-1")
    assert response.status_code == 403


def test_status_failure_marks_non_retryable_for_value_error(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})
    monkeypatch.setattr(main, "_check_task_owner", lambda task_id, user_id: True)

    class FakeAsyncResult:
        def __init__(self, task_id, app):
            self.state = "FAILURE"
            self.info = None
            self.result = ValueError("bad input")

    monkeypatch.setattr(main, "AsyncResult", FakeAsyncResult)

    response = client.get("/status/task-1")
    assert response.status_code == 200
    payload = response.json()
    assert payload["error"]["type"] == "ValueError"
    assert payload["error"]["retryable"] is False


def test_status_failure_marks_retryable_for_runtime_error(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})
    monkeypatch.setattr(main, "_check_task_owner", lambda task_id, user_id: True)

    class FakeAsyncResult:
        def __init__(self, task_id, app):
            self.state = "FAILURE"
            self.info = None
            self.result = RuntimeError("temporary")

    monkeypatch.setattr(main, "AsyncResult", FakeAsyncResult)

    response = client.get("/status/task-1")
    assert response.status_code == 200
    payload = response.json()
    assert payload["error"]["type"] == "RuntimeError"
    assert payload["error"]["retryable"] is True


def test_knowledge_upload_forbidden_for_non_admin(client):
    set_auth_user({"id": "u1", "role": "user"})
    response = client.post("/knowledge/upload", files=[("files", ("a.txt", b"x", "text/plain"))])
    assert response.status_code == 403


def test_knowledge_parse_and_store_forbidden_for_non_admin(client):
    set_auth_user({"id": "u1", "role": "user"})
    response = client.post("/knowledge/parse-and-store", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 403


def test_user_documents_upload_rejects_duplicate_file(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})

    async def fake_save_upload_streamed(file, tmp_path):
        tmp_path.write_bytes(b"x")
        return 1

    monkeypatch.setattr(main, "save_upload_streamed", fake_save_upload_streamed)
    monkeypatch.setattr(main, "check_user_document_hash", lambda user_id, file_hash: True)

    response = client.post("/user/documents/upload", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 409
    assert "duplikat" in response.json()["detail"].lower()


def test_report_generate_requires_user_id(client):
    set_auth_user({"role": "user"})
    response = client.post("/report/generate", json={"report_scope": "Environmental"})
    assert response.status_code == 401


def test_report_generate_queued_for_valid_user(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})
    monkeypatch.setattr(main.generate_report_task, "delay", lambda user_id, report_scope: SimpleNamespace(id="rep-1"))

    response = client.post("/report/generate", json={"report_scope": "Environmental"})
    assert response.status_code == 200
    assert response.json()["task_id"] == "rep-1"
