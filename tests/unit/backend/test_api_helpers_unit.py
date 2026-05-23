from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

import backend.main as main


def test_rel_task_path_returns_posix_relative_path(tmp_path: Path):
    tmp_root = tmp_path / "tmp_uploads"
    nested = tmp_root / "upload_1" / "file.pdf"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"x")

    assert main._rel_task_path(nested, tmp_root) == "upload_1/file.pdf"


def test_parse_report_json_for_validation_accepts_dict_and_json_string():
    payload = {"kategoria": "ESG"}

    assert main._parse_report_json_for_validation(payload) == payload
    assert main._parse_report_json_for_validation(json.dumps(payload)) == payload


def test_parse_report_json_for_validation_rejects_invalid_json():
    with pytest.raises(HTTPException) as exc_info:
        main._parse_report_json_for_validation("{not-json")

    assert exc_info.value.status_code == 400


def test_parse_used_chunks_for_validation_accepts_list_json_and_bad_values():
    chunks = ["chunk-1"]

    assert main._parse_used_chunks_for_validation(chunks) == chunks
    assert main._parse_used_chunks_for_validation(json.dumps(chunks)) == chunks
    assert main._parse_used_chunks_for_validation("{bad-json") == []
    assert main._parse_used_chunks_for_validation(None) == []


def test_task_owner_check_allows_legacy_task_without_owner(monkeypatch):
    class FakeRedis:
        def get(self, key):
            assert key == "task:task-1:owner"
            return None

    monkeypatch.setattr(main, "_redis_client", FakeRedis())

    assert main._check_task_owner("task-1", "user-1") is True


def test_task_owner_check_rejects_mismatch(monkeypatch):
    class FakeRedis:
        def get(self, _key):
            return "owner-1"

    monkeypatch.setattr(main, "_redis_client", FakeRedis())

    assert main._check_task_owner("task-1", "owner-1") is True
    assert main._check_task_owner("task-1", "other-user") is False
