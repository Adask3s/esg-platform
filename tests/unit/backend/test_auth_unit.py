from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from fastapi import HTTPException
from jose import jwt

from backend import auth


def test_password_hash_verification_roundtrip():
    hashed = auth.get_password_hash("correct-password")

    assert hashed != "correct-password"
    assert auth.verify_password("correct-password", hashed) is True
    assert auth.verify_password("wrong-password", hashed) is False


def test_create_access_token_contains_subject_role_and_expiry():
    token = auth.create_access_token(
        {"sub": "alice", "user_id": "u1", "role": "admin"},
        expires_delta=timedelta(minutes=5),
    )

    payload = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])

    assert payload["sub"] == "alice"
    assert payload["user_id"] == "u1"
    assert payload["role"] == "admin"
    assert "exp" in payload


def test_get_current_user_returns_repository_user(monkeypatch):
    token = auth.create_access_token({"sub": "alice"}, expires_delta=timedelta(minutes=5))
    expected_user = {"id": "u1", "username": "alice", "role": "user"}

    monkeypatch.setattr(auth, "get_user_by_username", lambda username: expected_user)

    assert asyncio.run(auth.get_current_user(token)) == expected_user


def test_get_current_user_rejects_invalid_token():
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(auth.get_current_user("not-a-jwt"))

    assert exc_info.value.status_code == 401
