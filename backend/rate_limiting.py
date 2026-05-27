from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

import redis
from fastapi import HTTPException, Request


DEFAULT_GLOBAL_LIMIT = int(os.getenv("RATE_LIMIT_GLOBAL_PER_MINUTE", "300"))
DEFAULT_GLOBAL_WINDOW_SECONDS = 60

_memory_lock = threading.Lock()
_memory_windows: dict[str, tuple[int, float]] = {}
_redis_client: Any | None = None
_redis_url_seen: str | None = None


@dataclass(frozen=True)
class RateLimitResult:
    scope: str
    identity: str
    limit: int
    window_seconds: int
    count: int
    retry_after: int


def rate_limits_enabled() -> bool:
    return os.getenv("RATE_LIMITS_ENABLED", "true").lower() not in {"0", "false", "no", "off"}


def trust_proxy_headers() -> bool:
    return os.getenv("RATE_LIMIT_TRUST_PROXY_HEADERS", "false").lower() in {"1", "true", "yes", "on"}


def client_identifier(request: Request) -> str:
    if trust_proxy_headers():
        forwarded_for = request.headers.get("x-forwarded-for", "")
        if forwarded_for:
            return forwarded_for.split(",", 1)[0].strip() or "unknown"
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _identity_hash(identity: str) -> str:
    normalized = str(identity or "unknown").strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def _redis_url() -> str:
    return os.getenv("RATE_LIMIT_REDIS_URL") or os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _get_redis_client() -> Any | None:
    global _redis_client, _redis_url_seen

    url = _redis_url()
    if _redis_client is not None and _redis_url_seen == url:
        return _redis_client

    try:
        _redis_client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=0.2,
            socket_timeout=0.2,
        )
        _redis_url_seen = url
        return _redis_client
    except Exception:
        _redis_client = None
        _redis_url_seen = url
        return None


def _check_memory_limit(key: str, limit: int, window_seconds: int, now: float) -> RateLimitResult | None:
    reset_at = (int(now // window_seconds) + 1) * window_seconds
    with _memory_lock:
        stale_keys = [
            memory_key
            for memory_key, (_count, memory_reset_at) in _memory_windows.items()
            if memory_reset_at <= now
        ]
        for memory_key in stale_keys:
            _memory_windows.pop(memory_key, None)

        count, existing_reset_at = _memory_windows.get(key, (0, reset_at))
        if existing_reset_at <= now:
            count = 0
            existing_reset_at = reset_at
        count += 1
        _memory_windows[key] = (count, existing_reset_at)

    retry_after = max(1, int(existing_reset_at - now))
    if count > limit:
        parts = key.split(":")
        return RateLimitResult(parts[1], parts[2], limit, window_seconds, count, retry_after)
    return None


def check_rate_limit(
    *,
    scope: str,
    identity: str,
    limit: int,
    window_seconds: int,
) -> RateLimitResult | None:
    if not rate_limits_enabled() or limit <= 0 or window_seconds <= 0:
        return None

    now = time.time()
    window_id = int(now // window_seconds)
    identity_key = _identity_hash(identity)
    redis_key = f"rate_limit:{scope}:{identity_key}:{window_id}"

    client = _get_redis_client()
    if client is not None:
        try:
            count = int(client.incr(redis_key))
            if count == 1:
                client.expire(redis_key, window_seconds + 2)
            retry_after = max(1, int(((window_id + 1) * window_seconds) - now))
            if count > limit:
                return RateLimitResult(scope, identity_key, limit, window_seconds, count, retry_after)
            return None
        except Exception:
            pass

    return _check_memory_limit(redis_key, limit, window_seconds, now)


def enforce_rate_limit(
    *,
    request: Request,
    scope: str,
    limit: int,
    window_seconds: int,
    identity: str | None = None,
) -> None:
    limited = check_rate_limit(
        scope=scope,
        identity=identity or client_identifier(request),
        limit=limit,
        window_seconds=window_seconds,
    )
    if limited is None:
        return

    raise HTTPException(
        status_code=429,
        detail="Too many requests. Please try again later.",
        headers={"Retry-After": str(limited.retry_after)},
    )


def reset_rate_limit_state() -> None:
    global _redis_client, _redis_url_seen

    with _memory_lock:
        _memory_windows.clear()
    _redis_client = None
    _redis_url_seen = None
