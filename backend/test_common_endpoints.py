from pathlib import Path
from types import SimpleNamespace
import importlib

from fastapi.testclient import TestClient
import pytest

import backend.auth as auth_mod
import backend.main as main

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
    main.app.dependency_overrides[auth_mod.get_current_user] = lambda: user
    main.app.dependency_overrides[main.get_current_user] = lambda: user


class FakeDispatcher:
    def __init__(self, text="parsed text"):
        self._text = text

    def parse(self, path):
        return SimpleNamespace(text=self._text, pages=[self._text] if self._text else [])


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


def _mock_openai_response(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _mock_openai_client(content="ok"):
    def _create(**kwargs):
        return _mock_openai_response(content)

    return SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=_create)
        )
    )


def test_ping_returns_pong(client):
    response = client.get("/ping")
    assert response.status_code == 200
    assert response.json() == {"message": "pong"}


def test_openai_status_missing_api_key(client, monkeypatch):
    monkeypatch.setattr(main.os, "getenv", lambda key, default=None: None if key == "OPENAI_API_KEY" else default)
    response = client.get("/openai-status")
    assert response.status_code == 200
    assert response.json()["configured"] is False


def test_openai_status_invalid_key_format(client, monkeypatch):
    monkeypatch.setattr(main.os, "getenv", lambda key, default=None: "abc" if key == "OPENAI_API_KEY" else default)
    response = client.get("/openai-status")
    assert response.status_code == 200
    assert response.json()["validated"] is False
    assert "format" in response.json()["message"].lower()


def test_openai_status_configured_but_client_invalid(client, monkeypatch):
    monkeypatch.setattr(main.os, "getenv", lambda key, default=None: "sk-test" if key == "OPENAI_API_KEY" else default)
    monkeypatch.setattr(main, "get_openai_client", lambda: None)
    response = client.get("/openai-status")
    assert response.status_code == 200
    assert response.json()["validated"] is False


def test_openai_status_ok(client, monkeypatch):
    monkeypatch.setattr(main.os, "getenv", lambda key, default=None: "sk-test" if key == "OPENAI_API_KEY" else default)
    monkeypatch.setattr(main, "get_openai_client", lambda: _mock_openai_client("hello"))
    response = client.get("/openai-status")
    assert response.status_code == 200
    assert response.json()["validated"] is True


def test_auth_contact_success(client):
    response = client.post("/auth/contact", json={"email": "a@b.com", "problem": "Issue"})
    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_auth_contact_validation_error(client):
    response = client.post("/auth/contact", json={"email": "a@b.com"})
    assert response.status_code == 422


def test_auth_signup_success(client, monkeypatch):
    monkeypatch.setattr(auth_mod, "get_user_by_username", lambda username: None)
    monkeypatch.setattr(auth_mod, "create_user", lambda username, email, hashed: 123)
    response = client.post("/auth/signup", json={"username": "u1", "email": "u1@example.com", "password": "secret"})
    assert response.status_code == 200
    assert "access_token" in response.json()


def test_auth_login_invalid_credentials(client, monkeypatch):
    monkeypatch.setattr(auth_mod, "get_user_by_username", lambda username: None)
    response = client.post("/auth/login", data={"username": "u1", "password": "bad"})
    assert response.status_code == 401


def test_auth_login_success(client, monkeypatch):
    password_hash = auth_mod.get_password_hash("good-pass")
    monkeypatch.setattr(auth_mod, "get_user_by_username", lambda username: {"id": 1, "username": username, "password_hash": password_hash, "role": "user"})
    response = client.post("/auth/login", data={"username": "u1", "password": "good-pass"})
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"


def test_parse_requires_auth(client):
    response = client.post("/parse")
    assert response.status_code == 401


def test_parse_without_files_returns_400(client):
    set_auth_user({"id": "u1", "role": "user"})
    response = client.post("/parse")
    assert response.status_code == 400


def test_parse_single_file_success(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})
    monkeypatch.setattr(main, "ParserDispatcher", lambda: FakeDispatcher("ok"))
    monkeypatch.setattr(main, "write_result", lambda result, out_root: {"folder": "out"})
    monkeypatch.setattr(main, "save_report", lambda **kwargs: 1)

    response = client.post(
        "/parse",
        files={"file": ("a.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_parse_single_file_too_large(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})
    monkeypatch.setattr(main, "MAX_FILE_SIZE", 1)
    response = client.post(
        "/parse",
        files={"file": ("a.txt", b"12", "text/plain")},
    )
    assert response.status_code == 413


def test_parse_multi_file_mixed_result(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})
    monkeypatch.setattr(main, "MAX_FILE_SIZE", 3)
    monkeypatch.setattr(main, "ParserDispatcher", lambda: FakeDispatcher("ok"))
    monkeypatch.setattr(main, "write_result", lambda result, out_root: {"folder": "out"})
    monkeypatch.setattr(main, "save_report", lambda **kwargs: 1)

    response = client.post(
        "/parse",
        files=[
            ("files", ("ok.txt", b"ab", "text/plain")),
            ("files", ("bad.txt", b"1234", "text/plain")),
        ],
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] >= 2
    assert any(item["status"] == "error" for item in payload["results"])


def test_ingest_chunk_url_fetch_error(client, monkeypatch):
    monkeypatch.setattr(main, "fetch_url_text_blocks", lambda url: (_ for _ in ()).throw(RuntimeError("nope")))
    response = client.post("/ingest/chunk/url", json={"url": "https://example.com"})
    assert response.status_code == 400
    assert "Fetch error" in response.json()["detail"]


def test_ingest_chunk_url_success_without_keywords(client, monkeypatch):
    monkeypatch.setattr(main, "fetch_url_text_blocks", lambda url: ["a", "b"])
    monkeypatch.setattr(main, "chunk_text", lambda text, cfg: [
        {"text": "chunk", "token_count": 10, "start_block": 0, "end_block": 1}
    ])
    response = client.post("/ingest/chunk/url", json={"url": "https://example.com"})
    assert response.status_code == 200
    assert response.json()["total_blocks"] == 2


def test_ingest_chunk_url_keywords_no_match_sets_note(client, monkeypatch):
    monkeypatch.setattr(main, "fetch_url_text_blocks", lambda url: ["a", "b"])
    monkeypatch.setattr(main, "keyword_filter_blocks", lambda blocks, cfg: ([], []))
    monkeypatch.setattr(main, "chunk_text", lambda text, cfg: [])
    response = client.post("/ingest/chunk/url", json={"url": "https://example.com", "keywords": ["esg"]})
    assert response.status_code == 200
    assert "Brak dopas" in response.json()["notes"]


def test_ingest_chunk_file_success(client, monkeypatch):
    monkeypatch.setattr(main, "ParserDispatcher", lambda: FakeDispatcher("file text"))
    monkeypatch.setattr(main, "make_blocks", lambda text: ["b1", "b2"])
    monkeypatch.setattr(main, "chunk_text", lambda text, cfg: [
        {"text": "chunk", "token_count": 20, "start_block": 0, "end_block": 1}
    ])
    response = client.post("/ingest/chunk/file", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 200
    assert response.json()["source_type"] == "file"


def test_ingest_chunk_file_too_large(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_FILE_SIZE", 1)
    response = client.post("/ingest/chunk/file", files={"file": ("a.txt", b"12", "text/plain")})
    assert response.status_code == 413


def test_ingest_chunk_file_no_text_returns_400(client, monkeypatch):
    monkeypatch.setattr(main, "ParserDispatcher", lambda: FakeDispatcher(""))
    response = client.post("/ingest/chunk/file", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 400


def test_process_requires_auth(client):
    response = client.post("/process", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 401


def test_process_too_large_returns_413(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})

    async def fake_save_upload_streamed(file, tmp_path):
        return 10

    monkeypatch.setattr(main, "MAX_FILE_SIZE", 1)
    monkeypatch.setattr(main, "save_upload_streamed", fake_save_upload_streamed)
    response = client.post("/process", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 413


def test_process_success_returns_task_id(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})

    async def fake_save_upload_streamed(file, tmp_path):
        return 1

    monkeypatch.setattr(main, "save_upload_streamed", fake_save_upload_streamed)
    monkeypatch.setattr(main, "validate_file_on_disk", lambda path, name: None)
    monkeypatch.setattr(main.parse_and_store, "delay", lambda path, name, user_id: SimpleNamespace(id="task-1"))
    response = client.post("/process", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 200
    assert response.json()["task_id"] == "task-1"


@pytest.mark.parametrize(
    "state,info,result,expected_key",
    [
        ("PROGRESS", {"step": "parsing"}, None, "meta"),
        ("SUCCESS", None, {"ok": True}, "result"),
        ("FAILURE", "boom", None, "error"),
    ],
)
def test_status_endpoint_states(client, monkeypatch, state, info, result, expected_key):
    set_auth_user({"id": "u1", "role": "user"})

    class FakeAsyncResult:
        def __init__(self, task_id, app):
            self.state = state
            self.info = info
            self.result = result

    monkeypatch.setattr(main, "AsyncResult", FakeAsyncResult)
    response = client.get("/status/task-1")
    assert response.status_code == 200
    assert expected_key in response.json()


@pytest.mark.parametrize(
    "endpoint",
    ["/analyze-social", "/analyze-environmental", "/analyze-governance"],
)
def test_analyze_endpoints_require_openai_client(client, monkeypatch, endpoint):
    set_auth_user({"id": "u1", "role": "user"})
    monkeypatch.setattr(main, "get_openai_client", lambda: None)
    response = client.post(endpoint, params={"report_path": "C:/tmp/missing"})
    assert response.status_code == 500


@pytest.mark.parametrize(
    "endpoint",
    ["/analyze-social", "/analyze-environmental", "/analyze-governance"],
)
def test_analyze_endpoints_missing_directory(client, monkeypatch, endpoint):
    set_auth_user({"id": "u1", "role": "user"})
    monkeypatch.setattr(main, "get_openai_client", lambda: _mock_openai_client("json"))
    response = client.post(endpoint, params={"report_path": "C:/tmp/not-existing"})
    assert response.status_code == 404
    assert "Directory not found" in response.json()["detail"]


@pytest.mark.parametrize(
    "endpoint",
    ["/analyze-social", "/analyze-environmental", "/analyze-governance"],
)
def test_analyze_endpoints_missing_text_file(client, monkeypatch, tmp_path, endpoint):
    set_auth_user({"id": "u1", "role": "user"})
    monkeypatch.setattr(main, "get_openai_client", lambda: _mock_openai_client("json"))
    response = client.post(endpoint, params={"report_path": str(tmp_path)})
    assert response.status_code == 404
    assert "File not found" in response.json()["detail"]


@pytest.mark.parametrize(
    "endpoint",
    ["/analyze-social", "/analyze-environmental", "/analyze-governance"],
)
def test_analyze_endpoints_success(client, monkeypatch, tmp_path, endpoint):
    set_auth_user({"id": "u1", "role": "user"})
    text_file = Path(tmp_path) / "text.txt"
    text_file.write_text("example report", encoding="utf-8")

    monkeypatch.setattr(main, "get_openai_client", lambda: _mock_openai_client('{"ok": true}'))
    monkeypatch.setattr(main, "save_report", lambda **kwargs: 1)

    response = client.post(endpoint, params={"report_path": str(tmp_path)})
    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_knowledge_upload_forbidden_for_non_admin(client):
    set_auth_user({"id": "u1", "role": "user"})
    response = client.post("/knowledge/upload", files=[("files", ("a.txt", b"x", "text/plain"))])
    assert response.status_code == 403


def test_knowledge_upload_success(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "admin"})

    async def fake_save_upload_streamed(file, tmp_path):
        return 1

    async def fake_add_document_to_knowledge_base(**kwargs):
        return {"document_id": "doc-1"}

    monkeypatch.setattr(main, "save_upload_streamed", fake_save_upload_streamed)
    monkeypatch.setattr(main, "ParserDispatcher", lambda: FakeDispatcher("knowledge text"))
    monkeypatch.setattr(main, "sanitize_filename", lambda name: name)
    monkeypatch.setattr(main, "add_document_to_knowledge_base", fake_add_document_to_knowledge_base)

    response = client.post("/knowledge/upload", files=[("files", ("a.txt", b"x", "text/plain"))])
    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "success"


def test_knowledge_upload_skips_empty_text(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "admin"})

    async def fake_save_upload_streamed(file, tmp_path):
        return 1

    monkeypatch.setattr(main, "save_upload_streamed", fake_save_upload_streamed)
    monkeypatch.setattr(main, "ParserDispatcher", lambda: FakeDispatcher(""))
    monkeypatch.setattr(main, "sanitize_filename", lambda name: name)

    response = client.post("/knowledge/upload", files=[("files", ("a.txt", b"x", "text/plain"))])
    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "skipped"


def test_knowledge_parse_and_store_forbidden_for_non_admin(client):
    set_auth_user({"id": "u1", "role": "user"})
    response = client.post("/knowledge/parse-and-store", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 403


def test_knowledge_parse_and_store_too_large(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "admin"})

    async def fake_save_upload_streamed(file, tmp_path):
        return 10

    monkeypatch.setattr(main, "MAX_FILE_SIZE", 1)
    monkeypatch.setattr(main, "save_upload_streamed", fake_save_upload_streamed)
    response = client.post("/knowledge/parse-and-store", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 413


def test_knowledge_parse_and_store_success(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "admin"})

    async def fake_save_upload_streamed(file, tmp_path):
        return 1

    monkeypatch.setattr(main, "save_upload_streamed", fake_save_upload_streamed)
    monkeypatch.setattr(main, "validate_file_on_disk", lambda path, name: None)
    monkeypatch.setattr(main, "sanitize_filename", lambda name: name)
    monkeypatch.setattr(main.parse_and_store_to_knowledge, "delay", lambda *args, **kwargs: SimpleNamespace(id="kb-task-1"))

    response = client.post("/knowledge/parse-and-store", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 200
    assert response.json()["task_id"] == "kb-task-1"


def test_user_documents_upload_requires_auth(client):
    response = client.post("/user/documents/upload", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 401


def test_user_documents_upload_user_without_id(client):
    set_auth_user({"role": "user"})
    response = client.post("/user/documents/upload", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 401


def test_user_documents_upload_empty_text_returns_500(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})

    async def fake_save_upload_streamed(file, tmp_path):
        return 1

    monkeypatch.setattr(main, "save_upload_streamed", fake_save_upload_streamed)
    monkeypatch.setattr(main, "ParserDispatcher", lambda: FakeDispatcher(""))
    monkeypatch.setattr(main, "sanitize_filename", lambda name: name)

    response = client.post("/user/documents/upload", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 500


def test_user_documents_upload_success(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})

    async def fake_save_upload_streamed(file, tmp_path):
        return 1

    async def fake_process_and_save_user_document(**kwargs):
        return {"chunks_processed": 2}

    monkeypatch.setattr(main, "save_upload_streamed", fake_save_upload_streamed)
    monkeypatch.setattr(main, "ParserDispatcher", lambda: FakeDispatcher("user text"))
    monkeypatch.setattr(main, "sanitize_filename", lambda name: name)
    monkeypatch.setattr(main, "process_and_save_user_document", fake_process_and_save_user_document)

    response = client.post("/user/documents/upload", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_user_documents_delete_success(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "user"})
    monkeypatch.setattr(main, "delete_user_document_cascade", lambda user_id, document_id: {"status": "success", "document_id": document_id})

    response = client.post("/user/documents/delete", json={"document_id": "doc-1"})
    assert response.status_code == 200
    assert response.json()["status"] == "success"


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
    assert response.json()[0]["origin"] == "user"


def test_documents_knowledge_forbidden_for_non_admin(client):
    set_auth_user({"id": "u1", "role": "user"})
    response = client.get("/documents/knowledge")
    assert response.status_code == 403


def test_documents_knowledge_admin_success(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "admin"})
    supabase = FakeSupabaseDocuments(
        knowledge_rows=[{"id": "k1", "title": "doc", "source": "s", "tag": "t", "created_at": "2026-01-02T00:00:00", "document_type": "general", "version": "1.0"}]
    )
    monkeypatch.setattr(docs_router, "get_supabase", lambda: supabase)

    response = client.get("/documents/knowledge")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["origin"] == "knowledge"


def test_documents_all_for_admin_combines_lists(client, monkeypatch):
    set_auth_user({"id": "u1", "role": "admin"})
    supabase = FakeSupabaseDocuments(
        user_rows=[{"id": "u-doc", "filename": "a.pdf", "file_type": "pdf", "tag": "x", "created_at": "2026-01-01T00:00:00"}],
        knowledge_rows=[{"id": "k-doc", "title": "kb", "source": "s", "tag": "x", "created_at": "2026-01-03T00:00:00", "document_type": "general", "version": "1.0"}],
    )
    monkeypatch.setattr(docs_router, "get_supabase", lambda: supabase)

    response = client.get("/documents/")
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_embeddings_generate_for_document_success(client, monkeypatch):
    async def fake_generate_embeddings_for_document(document_id, model, table_name):
        return {"document_id": document_id, "updated": 1}

    monkeypatch.setattr(emb_router, "generate_embeddings_for_document", fake_generate_embeddings_for_document)
    response = client.post("/embeddings/generate-for-document", json={"document_id": "doc-1"})
    assert response.status_code == 200
    assert response.json()["updated"] == 1


def test_embeddings_generate_for_document_error(client, monkeypatch):
    async def fail_generate_embeddings_for_document(document_id, model, table_name):
        raise RuntimeError("embedding failure")

    monkeypatch.setattr(emb_router, "generate_embeddings_for_document", fail_generate_embeddings_for_document)
    response = client.post("/embeddings/generate-for-document", json={"document_id": "doc-1"})
    assert response.status_code == 500


def test_embeddings_generate_for_tag_success(client, monkeypatch):
    async def fake_generate_embeddings_by_tag(tag, model):
        return {"tag": tag, "updated": 3}

    monkeypatch.setattr(emb_router, "generate_embeddings_by_tag", fake_generate_embeddings_by_tag)
    response = client.post("/embeddings/generate-for-tag", json={"tag": "social"})
    assert response.status_code == 200
    assert response.json()["updated"] == 3


def test_embeddings_generate_all_success(client, monkeypatch):
    async def fake_generate_embeddings_for_all_documents(model):
        return {"status": "completed", "updated": 4}

    monkeypatch.setattr(emb_router, "generate_embeddings_for_all_documents", fake_generate_embeddings_for_all_documents)
    response = client.post("/embeddings/generate-all")
    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_embeddings_status_success(client, monkeypatch):
    monkeypatch.setattr(emb_router, "get_supabase", lambda: FakeSupabaseEmbeddings(total_count=10, with_embedding_count=4))
    response = client.get("/embeddings/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_chunks"] == 10
    assert payload["with_embeddings"] == 4
    assert payload["without_embeddings"] == 6


def test_embeddings_status_error(client, monkeypatch):
    monkeypatch.setattr(emb_router, "get_supabase", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    with pytest.raises(RuntimeError, match="db down"):
        client.get("/embeddings/status")
