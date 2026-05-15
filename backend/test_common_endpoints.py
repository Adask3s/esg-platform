from pathlib import Path
from types import SimpleNamespace
import importlib

from fastapi.testclient import TestClient
import pytest

import backend.auth as auth_mod
import backend.main as main

# Import modułów routerów (nie obiektów APIRouter) do monkeypatchy funkcji.
docs_router = importlib.import_module("backend.documents_getter_endpoints.router")
emb_router = importlib.import_module("backend.embeddings.router")


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def clear_overrides_and_client(monkeypatch):
    main.app.dependency_overrides.clear()
    monkeypatch.setattr(main, "client", None, raising=False)
    yield
    main.app.dependency_overrides.clear()


def set_auth_user(user):
    # Główne endpointy z main.py
    main.app.dependency_overrides[main.get_current_user] = lambda: user
    # Routery, które importują get_current_user bezpośrednio z backend.auth
    main.app.dependency_overrides[auth_mod.get_current_user] = lambda: user
    if hasattr(emb_router, "get_current_user"):
        main.app.dependency_overrides[emb_router.get_current_user] = lambda: user
    if hasattr(docs_router, "get_current_user"):
        main.app.dependency_overrides[docs_router.get_current_user] = lambda: user


class FakeSupabaseQuery:
    def __init__(self, data=None, count=None):
        self._data = data if data is not None else []
        self._count = count

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def range(self, *args, **kwargs):
        return self

    @property
    def not_(self):
        return self

    def is_(self, *args, **kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=self._data, count=self._count)


class FakeSupabaseDocuments:
    def __init__(self, user_rows=None, knowledge_rows=None):
        self.user_rows = user_rows if user_rows is not None else []
        self.knowledge_rows = knowledge_rows if knowledge_rows is not None else []

    def table(self, name):
        if name == "user_documents":
            return FakeSupabaseQuery(data=self.user_rows)
        if name == "knowledge_documents":
            return FakeSupabaseQuery(data=self.knowledge_rows)
        return FakeSupabaseQuery(data=[])


class FakeSupabaseEmbeddings:
    def __init__(self, total_count, with_embedding_count):
        self.total_count = total_count
        self.with_embedding_count = with_embedding_count

    def table(self, name):
        assert name == "knowledge_chunks"
        return FakeSupabaseEmbeddingsQuery(self.total_count, self.with_embedding_count)


class FakeSupabaseEmbeddingsQuery:
    def __init__(self, total_count, with_embedding_count):
        self.total_count = total_count
        self.with_embedding_count = with_embedding_count
        self._not_null_filter = False

    def select(self, *args, **kwargs):
        return self

    @property
    def not_(self):
        self._not_null_filter = True
        return self

    def is_(self, *args, **kwargs):
        return self

    def execute(self):
        if self._not_null_filter:
            return SimpleNamespace(data=[], count=self.with_embedding_count)
        return SimpleNamespace(data=[], count=self.total_count)


# -------------------------
# Podstawowe API + auth
# -------------------------

def test_ping_returns_pong(client):
    response = client.get("/ping")
    assert response.status_code == 200
    assert response.json() == {"message": "pong"}


def test_openai_status_missing_api_key(client, monkeypatch):
    monkeypatch.setattr(main.os, "getenv", lambda key, default=None: None if key == "OPENAI_API_KEY" else default)
    response = client.get("/openai-status")
    assert response.status_code == 200
    assert response.json()["configured"] is False


def test_auth_contact_success(client):
    response = client.post("/auth/contact", json={"email": "a@b.com", "problem": "Issue"})
    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_auth_login_invalid_credentials(client, monkeypatch):
    monkeypatch.setattr(auth_mod, "get_user_by_username", lambda username: None)
    response = client.post("/auth/login", data={"username": "u1", "password": "bad"})
    assert response.status_code == 401


# -------------------------
# /parse
# -------------------------

def test_parse_requires_auth(client):
    response = client.post("/parse")
    assert response.status_code == 401


def test_parse_without_files_returns_400(client):
    set_auth_user({"id": "u1", "role": "user"})
    response = client.post("/parse")
    assert response.status_code == 400


def test_parse_single_file_queued(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})

    async def fake_save_upload_streamed(file, tmp_path):
        tmp_path.write_bytes(b"x")
        return 1

    monkeypatch.setattr(main, "save_upload_streamed", fake_save_upload_streamed)
    monkeypatch.setattr(main.parse_and_store, "delay", lambda *args, **kwargs: SimpleNamespace(id="task-1"))

    response = client.post("/parse", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["task_id"] == "task-1"


def test_parse_single_file_too_large_returns_error_payload(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})

    async def fake_save_upload_streamed(file, tmp_path):
        return 10

    monkeypatch.setattr(main, "MAX_FILE_SIZE", 1)
    monkeypatch.setattr(main, "save_upload_streamed", fake_save_upload_streamed)

    response = client.post("/parse", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "error"
    assert "50MB" in payload["error"]


def test_parse_multi_file_mixed_result(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})

    async def fake_save_upload_streamed(file, tmp_path):
        if (file.filename or "").startswith("bad"):
            return 10
        tmp_path.write_bytes(b"x")
        return 1

    monkeypatch.setattr(main, "MAX_FILE_SIZE", 2)
    monkeypatch.setattr(main, "save_upload_streamed", fake_save_upload_streamed)
    monkeypatch.setattr(main.parse_and_store, "delay", lambda *args, **kwargs: SimpleNamespace(id="task-ok"))

    response = client.post(
        "/parse",
        files=[
            ("files", ("ok.txt", b"x", "text/plain")),
            ("files", ("bad.txt", b"x", "text/plain")),
        ],
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["count"] == 2
    assert any(item["status"] == "queued" for item in payload["results"])
    assert any(item["status"] == "error" for item in payload["results"])


# -------------------------
# Ingestion async
# -------------------------

def test_ingest_chunk_url_requires_auth(client):
    response = client.post("/ingest/chunk/url", json={"url": "https://example.com"})
    assert response.status_code == 401


def test_ingest_chunk_url_queued(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})
    monkeypatch.setattr(main.ingest_chunk_url_task, "delay", lambda *args, **kwargs: SimpleNamespace(id="ing-url-1"))

    response = client.post("/ingest/chunk/url", json={"url": "https://example.com", "keywords": ["esg"]})
    assert response.status_code == 200
    assert response.json()["task_id"] == "ing-url-1"


def test_ingest_chunk_file_requires_auth(client):
    response = client.post("/ingest/chunk/file", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 401


def test_ingest_chunk_file_too_large(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})

    async def fake_save_upload_streamed(file, tmp_path):
        return 10

    monkeypatch.setattr(main, "MAX_FILE_SIZE", 1)
    monkeypatch.setattr(main, "save_upload_streamed", fake_save_upload_streamed)

    response = client.post("/ingest/chunk/file", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 413


def test_ingest_chunk_file_queued(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})

    async def fake_save_upload_streamed(file, tmp_path):
        tmp_path.write_bytes(b"x")
        return 1

    monkeypatch.setattr(main, "save_upload_streamed", fake_save_upload_streamed)
    monkeypatch.setattr(main.ingest_chunk_file_task, "delay", lambda *args, **kwargs: SimpleNamespace(id="ing-file-1"))

    response = client.post("/ingest/chunk/file", files={"file": ("a.txt", b"x", "text/plain")}, data={"keywords": "esg"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == "ing-file-1"
    assert payload["status"] == "queued"


# -------------------------
# /process + /status + /report/generate
# -------------------------

def test_process_requires_auth(client):
    response = client.post("/process", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 401


def test_process_success_returns_task_id(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})

    async def fake_save_upload_streamed(file, tmp_path):
        tmp_path.write_bytes(b"x")
        return 1

    monkeypatch.setattr(main, "save_upload_streamed", fake_save_upload_streamed)
    monkeypatch.setattr(main, "validate_file_on_disk", lambda path, name: None)
    monkeypatch.setattr(main.parse_and_store, "delay", lambda *args, **kwargs: SimpleNamespace(id="task-2"))

    response = client.post("/process", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 200
    assert response.json()["task_id"] == "task-2"


def test_status_forbidden_when_not_owner(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})
    monkeypatch.setattr(main, "_check_task_owner", lambda task_id, user_id: False)

    response = client.get("/status/task-1")
    assert response.status_code == 403


def test_status_progress_payload(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})
    monkeypatch.setattr(main, "_check_task_owner", lambda task_id, user_id: True)

    class FakeAsyncResult:
        def __init__(self, task_id, app):
            self.state = "PROGRESS"
            self.info = {"step": "parsing", "stage_pl": "Parsowanie", "progress": 35, "filename": "a.txt", "attempts": 2}
            self.result = None

    monkeypatch.setattr(main, "AsyncResult", FakeAsyncResult)

    response = client.get("/status/task-1")
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "PROGRESS"
    assert payload["progress"] == 35
    assert payload["stage"] == "parsing"


def test_status_success_payload(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})
    monkeypatch.setattr(main, "_check_task_owner", lambda task_id, user_id: True)

    class FakeAsyncResult:
        def __init__(self, task_id, app):
            self.state = "SUCCESS"
            self.info = None
            self.result = {"ok": True}

    monkeypatch.setattr(main, "AsyncResult", FakeAsyncResult)

    response = client.get("/status/task-2")
    assert response.status_code == 200
    payload = response.json()
    assert payload["result"] == {"ok": True}
    assert payload["progress"] == 100


def test_report_generate_requires_user_id(client):
    set_auth_user({"role": "user"})
    response = client.post("/report/generate", json={"report_scope": "Environmental"})
    assert response.status_code == 401


def test_report_generate_queued(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})
    monkeypatch.setattr(main.generate_report_task, "delay", lambda user_id, report_scope: SimpleNamespace(id="report-1"))

    response = client.post("/report/generate", json={"report_scope": "Environmental"})
    assert response.status_code == 200
    assert response.json()["task_id"] == "report-1"


def test_report_download_pdf_success(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})
    monkeypatch.setattr(main, "_check_task_owner", lambda task_id, user_id: True)
    used_chunks = ["--- DOKUMENT: raport.pdf ---\nFragment zrodlowy."]
    captured = {}

    class FakeAsyncResult:
        def __init__(self, task_id, app):
            self.state = "SUCCESS"
            self.result = {
                "data": {
                    "kategoria": "Environmental",
                    "wskazniki_liczbowe": [{"nazwa": "Emisje CO2", "wartosc": 12.5, "jednostka": "tCO2e"}],
                    "wdrozone_polityki_i_dzialania": ["Polityka recyklingu"],
                    "zidentyfikowane_ryzyka": ["Ryzyko braku danych"],
                    "wnioski_i_zgodnosc_prawna": "Wniosek testowy.",
                },
                "used_chunks": used_chunks,
            }

    def fake_generate_report_pdf(report_data, used_chunks=None):
        captured["category"] = report_data.kategoria
        captured["used_chunks"] = used_chunks
        return b"%PDF-fake"

    monkeypatch.setattr(main, "AsyncResult", FakeAsyncResult)
    monkeypatch.setattr(main, "generate_report_pdf", fake_generate_report_pdf)

    response = client.get("/report/download/report-1")

    assert response.status_code == 200
    assert response.content == b"%PDF-fake"
    assert response.headers["content-type"] == "application/pdf"
    assert 'filename="raport_Environmental.pdf"' in response.headers["content-disposition"]
    assert captured == {"category": "Environmental", "used_chunks": used_chunks}


def test_report_download_pdf_handles_partial_success_without_data(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})
    monkeypatch.setattr(main, "_check_task_owner", lambda task_id, user_id: True)
    captured = {}

    class FakeAsyncResult:
        def __init__(self, task_id, app):
            self.state = "SUCCESS"
            self.result = {
                "status": "partial_success",
                "kategoria": "Social",
                "message": "Brak danych w dokumentach zrodlowych dla tego obszaru.",
                "used_chunks": [],
                "data": None,
            }

    def fake_generate_report_pdf(report_data, used_chunks=None):
        captured["category"] = report_data.kategoria
        captured["summary"] = report_data.wnioski_i_zgodnosc_prawna
        captured["used_chunks"] = used_chunks
        return b"%PDF-empty"

    monkeypatch.setattr(main, "AsyncResult", FakeAsyncResult)
    monkeypatch.setattr(main, "generate_report_pdf", fake_generate_report_pdf)

    response = client.get("/report/download/report-empty")

    assert response.status_code == 200
    assert response.content == b"%PDF-empty"
    assert captured["category"] == "Social"
    assert captured["summary"] == "Brak danych w dokumentach zrodlowych dla tego obszaru."
    assert captured["used_chunks"] == []


# -------------------------
# Knowledge endpoints
# -------------------------

def test_knowledge_upload_forbidden_for_non_admin(client):
    set_auth_user({"id": "u1", "role": "user"})
    response = client.post("/knowledge/upload", files=[("files", ("a.txt", b"x", "text/plain"))])
    assert response.status_code == 403


def test_knowledge_upload_duplicate_hash_returns_error_item(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "admin"})

    async def fake_save_upload_streamed(file, tmp_path):
        tmp_path.write_bytes(b"x")
        return 1

    monkeypatch.setattr(main, "save_upload_streamed", fake_save_upload_streamed)
    monkeypatch.setattr(main, "check_knowledge_document_hash", lambda file_hash: True)

    response = client.post("/knowledge/upload", files=[("files", ("a.txt", b"x", "text/plain"))])
    assert response.status_code == 200
    item = response.json()["results"][0]
    assert item["status"] == "error"
    assert "duplikat" in item["error"].lower()


def test_knowledge_upload_queued(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "admin"})

    async def fake_save_upload_streamed(file, tmp_path):
        tmp_path.write_bytes(b"x")
        return 1

    monkeypatch.setattr(main, "save_upload_streamed", fake_save_upload_streamed)
    monkeypatch.setattr(main, "check_knowledge_document_hash", lambda file_hash: False)
    monkeypatch.setattr(main.process_knowledge_document_full, "delay", lambda *args, **kwargs: SimpleNamespace(id="kb-1"))

    response = client.post("/knowledge/upload", files=[("files", ("a.txt", b"x", "text/plain"))])
    assert response.status_code == 200
    item = response.json()["results"][0]
    assert item["status"] == "queued"
    assert item["task_id"] == "kb-1"


def test_knowledge_parse_and_store_forbidden_for_non_admin(client):
    set_auth_user({"id": "u1", "role": "user"})
    response = client.post("/knowledge/parse-and-store", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 403


def test_knowledge_parse_and_store_duplicate_returns_409(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "admin"})

    async def fake_save_upload_streamed(file, tmp_path):
        tmp_path.write_bytes(b"x")
        return 1

    monkeypatch.setattr(main, "save_upload_streamed", fake_save_upload_streamed)
    monkeypatch.setattr(main, "validate_file_on_disk", lambda path, name: None)
    monkeypatch.setattr(main, "check_knowledge_document_hash", lambda file_hash: True)

    response = client.post("/knowledge/parse-and-store", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 409


def test_knowledge_parse_and_store_success(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "admin"})

    async def fake_save_upload_streamed(file, tmp_path):
        tmp_path.write_bytes(b"x")
        return 1

    monkeypatch.setattr(main, "save_upload_streamed", fake_save_upload_streamed)
    monkeypatch.setattr(main, "validate_file_on_disk", lambda path, name: None)
    monkeypatch.setattr(main, "check_knowledge_document_hash", lambda file_hash: False)
    monkeypatch.setattr(main.parse_and_store_to_knowledge, "delay", lambda *args, **kwargs: SimpleNamespace(id="kb-task-1"))

    response = client.post("/knowledge/parse-and-store", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 200
    assert response.json()["task_id"] == "kb-task-1"


# -------------------------
# User documents
# -------------------------

def test_user_documents_upload_requires_auth(client):
    response = client.post("/user/documents/upload", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 401


def test_user_documents_upload_duplicate_returns_409(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})

    async def fake_save_upload_streamed(file, tmp_path):
        tmp_path.write_bytes(b"x")
        return 1

    monkeypatch.setattr(main, "save_upload_streamed", fake_save_upload_streamed)
    monkeypatch.setattr(main, "check_user_document_hash", lambda user_id, file_hash: True)

    response = client.post("/user/documents/upload", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 409


def test_user_documents_upload_queued(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})

    async def fake_save_upload_streamed(file, tmp_path):
        tmp_path.write_bytes(b"x")
        return 1

    monkeypatch.setattr(main, "save_upload_streamed", fake_save_upload_streamed)
    monkeypatch.setattr(main, "check_user_document_hash", lambda user_id, file_hash: False)
    monkeypatch.setattr(main.process_user_document, "delay", lambda *args, **kwargs: SimpleNamespace(id="user-doc-1"))

    response = client.post("/user/documents/upload", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["task_id"] == "user-doc-1"


def test_user_documents_delete_success(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})
    monkeypatch.setattr(main, "delete_user_document_cascade", lambda user_id, document_id: {"status": "success", "document_id": document_id})

    response = client.post("/user/documents/delete", json={"document_id": "doc-1"})
    assert response.status_code == 200
    assert response.json()["status"] == "success"


# -------------------------
# Chat
# -------------------------

def test_chat_sessions_requires_user_id(client):
    set_auth_user({"role": "user"})
    response = client.get("/chat/sessions")
    assert response.status_code == 401


def test_chat_sessions_success(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})
    monkeypatch.setattr(main, "get_chat_sessions", lambda user_id, limit, offset: [{"id": "s1", "title": "Chat 1"}])

    response = client.get("/chat/sessions")
    assert response.status_code == 200
    assert response.json()[0]["id"] == "s1"


def test_chat_history_success(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})
    monkeypatch.setattr(main, "get_chat_messages", lambda session_id, limit, offset: [{"role": "user", "content": "hej"}])

    response = client.get("/chat/sessions/s1/history")
    assert response.status_code == 200
    assert response.json()[0]["role"] == "user"


def test_chat_ask_rejects_empty_query(client):
    set_auth_user({"id": "u1", "role": "user"})
    response = client.post("/chat/ask", json={"query": "   "})
    assert response.status_code == 400


def test_chat_ask_creates_session_and_queues_task(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})

    calls = {"created": 0, "saved": 0}

    def fake_create_chat_session(user_id, title):
        calls["created"] += 1
        return "session-new"

    def fake_add_chat_message(session_id, role, content):
        calls["saved"] += 1

    monkeypatch.setattr(main, "create_chat_session", fake_create_chat_session)
    monkeypatch.setattr(main, "add_chat_message", fake_add_chat_message)
    monkeypatch.setattr(main.process_chat_query, "delay", lambda *args, **kwargs: SimpleNamespace(id="chat-task-1"))

    response = client.post("/chat/ask", json={"query": "Co z ESG?", "tag": "E"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["task_id"] == "chat-task-1"
    assert payload["session_id"] == "session-new"
    assert calls["created"] == 1
    assert calls["saved"] == 1


def test_chat_ask_uses_existing_session(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})

    monkeypatch.setattr(main, "create_chat_session", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not create new session")))
    monkeypatch.setattr(main, "add_chat_message", lambda *args, **kwargs: None)
    monkeypatch.setattr(main.process_chat_query, "delay", lambda *args, **kwargs: SimpleNamespace(id="chat-task-2"))

    response = client.post("/chat/ask", json={"query": "Pytanie", "session_id": "session-existing"})
    assert response.status_code == 200
    assert response.json()["session_id"] == "session-existing"


# -------------------------
# Documents router
# -------------------------

def test_documents_mine_requires_auth(client):
    response = client.get("/documents/mine")
    assert response.status_code == 401


def test_documents_mine_success(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})
    supabase = FakeSupabaseDocuments(
        user_rows=[{"id": "1", "filename": "a.pdf", "file_type": "pdf", "tag": "x", "created_at": "2026-01-01T00:00:00"}]
    )
    monkeypatch.setattr(docs_router, "get_supabase", lambda: supabase)

    response = client.get("/documents/mine")
    assert response.status_code == 200
    assert len(response.json()) == 1


# -------------------------
# Embeddings router
# -------------------------

def test_embeddings_generate_for_document_requires_auth(client):
    response = client.post("/embeddings/generate-for-document", json={"document_id": "doc-1"})
    assert response.status_code == 401


def test_embeddings_generate_for_document_queued(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "admin"})
    monkeypatch.setattr(emb_router.generate_embeddings_for_document_task, "delay", lambda *args, **kwargs: SimpleNamespace(id="emb-doc-1"))

    response = client.post("/embeddings/generate-for-document", json={"document_id": "doc-1"})
    assert response.status_code == 200
    assert response.json()["task_id"] == "emb-doc-1"


def test_embeddings_generate_for_tag_queued(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "admin"})
    monkeypatch.setattr(emb_router.generate_embeddings_for_tag_task, "delay", lambda *args, **kwargs: SimpleNamespace(id="emb-tag-1"))

    response = client.post("/embeddings/generate-for-tag", json={"tag": "social"})
    assert response.status_code == 200
    assert response.json()["task_id"] == "emb-tag-1"


def test_embeddings_generate_all_queued(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "admin"})
    monkeypatch.setattr(emb_router.generate_embeddings_for_all_task, "delay", lambda *args, **kwargs: SimpleNamespace(id="emb-all-1"))

    response = client.post("/embeddings/generate-all")
    assert response.status_code == 200
    assert response.json()["task_id"] == "emb-all-1"


def test_embeddings_status_success(client, monkeypatch):
    monkeypatch.setattr(emb_router, "get_supabase", lambda: FakeSupabaseEmbeddings(total_count=10, with_embedding_count=4))
    response = client.get("/embeddings/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_chunks"] == 10
    assert payload["with_embeddings"] == 4
    assert payload["without_embeddings"] == 6
