from __future__ import annotations

import pytest

from backend import rate_limiting


@pytest.fixture(autouse=True)
def reset_rate_limits(monkeypatch):
    monkeypatch.setenv("RATE_LIMITS_ENABLED", "true")
    rate_limiting.reset_rate_limit_state()
    yield
    rate_limiting.reset_rate_limit_state()


class FakeRedis:
    def __init__(self):
        self.counts = {}
        self.expired = []

    def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key, ttl):
        self.expired.append((key, ttl))


def test_redis_limiter_blocks_after_limit(monkeypatch):
    fake_redis = FakeRedis()
    monkeypatch.setattr(rate_limiting, "_get_redis_client", lambda: fake_redis)

    assert rate_limiting.check_rate_limit(scope="login", identity="ip:u1", limit=2, window_seconds=60) is None
    assert rate_limiting.check_rate_limit(scope="login", identity="ip:u1", limit=2, window_seconds=60) is None

    limited = rate_limiting.check_rate_limit(scope="login", identity="ip:u1", limit=2, window_seconds=60)

    assert limited is not None
    assert limited.count == 3
    assert limited.retry_after > 0
    assert fake_redis.expired


def test_limiter_falls_back_to_memory_when_redis_fails(monkeypatch):
    class BrokenRedis:
        def incr(self, _key):
            raise ConnectionError("redis down")

    monkeypatch.setattr(rate_limiting, "_get_redis_client", lambda: BrokenRedis())

    assert rate_limiting.check_rate_limit(scope="report", identity="u1", limit=1, window_seconds=60) is None
    limited = rate_limiting.check_rate_limit(scope="report", identity="u1", limit=1, window_seconds=60)

    assert limited is not None
    assert limited.count == 2


def test_memory_limiter_resets_after_fixed_window(monkeypatch):
    current_time = [1000.0]
    monkeypatch.setattr(rate_limiting, "_get_redis_client", lambda: None)
    monkeypatch.setattr(rate_limiting.time, "time", lambda: current_time[0])

    assert rate_limiting.check_rate_limit(scope="chat", identity="u1", limit=1, window_seconds=60) is None
    assert rate_limiting.check_rate_limit(scope="chat", identity="u1", limit=1, window_seconds=60) is not None

    current_time[0] = 1061.0

    assert rate_limiting.check_rate_limit(scope="chat", identity="u1", limit=1, window_seconds=60) is None


def test_limiter_can_be_disabled(monkeypatch):
    monkeypatch.setenv("RATE_LIMITS_ENABLED", "false")
    monkeypatch.setattr(rate_limiting, "_get_redis_client", lambda: None)

    assert rate_limiting.check_rate_limit(scope="global", identity="ip", limit=0, window_seconds=60) is None
    assert rate_limiting.check_rate_limit(scope="global", identity="ip", limit=1, window_seconds=60) is None
    assert rate_limiting.check_rate_limit(scope="global", identity="ip", limit=1, window_seconds=60) is None
