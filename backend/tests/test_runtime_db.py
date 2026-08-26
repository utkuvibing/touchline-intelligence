"""Bounded pool and readiness cache contracts, including true concurrent single-flight."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event, Lock
from types import SimpleNamespace

import pytest
from fastapi import Request

from touchline import baseline
from touchline.config import Settings
from touchline.main import shot_conversion_rate
from touchline.runtime_db import DatabaseState, ReadinessProbe, create_pool

READY = DatabaseState(reachable=True, schema_current=True, detail=None)
DOWN = DatabaseState(reachable=False, schema_current=False, detail="database_unavailable")


def test_pool_uses_the_typed_connection_bound() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        db_url="postgresql://nobody:nothing@127.0.0.1:1/nonexistent",  # type: ignore[arg-type]
        db_pool_min_size=0,
        db_pool_max_size=2,
        db_pool_timeout_seconds=0.1,
    )
    pool = create_pool(settings)
    try:
        assert pool.min_size == 0
        assert pool.max_size == 2
    finally:
        pool.close()


def test_readiness_cache_reuses_a_success_within_its_monotonic_ttl() -> None:
    probe = ReadinessProbe(60)
    calls = 0

    def operation() -> DatabaseState:
        nonlocal calls
        calls += 1
        return READY

    assert probe.check(operation) == READY
    assert probe.check(operation) == READY
    assert calls == 1


def test_readiness_concurrent_cache_miss_is_true_single_flight_and_shares_failure() -> None:
    probe = ReadinessProbe(0)
    calls = 0
    lock = Lock()
    started = Event()
    release = Event()

    def operation() -> DatabaseState:
        nonlocal calls
        with lock:
            calls += 1
        started.set()
        assert release.wait(timeout=2)
        return DOWN

    with ThreadPoolExecutor(max_workers=8) as executor:
        leader = executor.submit(probe.check, operation)
        assert started.wait(timeout=2)
        followers = [executor.submit(probe.check, operation) for _ in range(7)]
        release.set()
        assert leader.result(timeout=2) == DOWN
        assert [future.result(timeout=2) for future in followers] == [DOWN] * 7

    assert calls == 1


class _BorrowSpy:
    def __init__(self) -> None:
        self.borrows = 0
        self.connection_object = object()

    @contextmanager
    def connection(self) -> Iterator[object]:
        self.borrows += 1
        yield self.connection_object


def test_runtime_request_reuses_its_single_application_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated requests borrow from one lifecycle pool instead of constructing connections."""
    pool = _BorrowSpy()
    request = Request({"type": "http", "app": SimpleNamespace(state=SimpleNamespace(db_pool=pool))})
    seen: list[object] = []

    def compute(connection: object) -> baseline.BaseRate:
        seen.append(connection)
        return baseline.BaseRate(shots=10, goals=2)

    monkeypatch.setattr(baseline, "compute_base_rate", compute)
    assert shot_conversion_rate(request).conversion_rate == 0.2
    assert shot_conversion_rate(request).conversion_rate == 0.2
    assert pool.borrows == 2
    assert seen == [pool.connection_object, pool.connection_object]
