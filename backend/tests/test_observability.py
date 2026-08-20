"""WP3.3 request correlation and structured logging contracts."""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from touchline.main import app
from touchline.observability import REQUEST_ID_HEADER, JsonFormatter, request_logger


@app.get("/__wp33_test_unhandled_error")
def _raise_unhandled_error() -> None:
    raise RuntimeError("test-only failure")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("TOUCHLINE_DB_URL", "postgresql://u:p@localhost:5432/db")
    app.state.environment = "test"
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def log_output() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = request_logger()
    logger.addHandler(handler)
    try:
        yield stream
    finally:
        logger.removeHandler(handler)


def _completion_records(output: str) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for line in output.splitlines():
        if not line.startswith("{"):
            continue
        value = json.loads(line)
        if value.get("event") == "request_completed":
            records.append(value)
    return records


def test_valid_request_id_is_returned_and_logged(
    client: TestClient, log_output: io.StringIO
) -> None:
    request_id = "00000000-0000-4000-8000-000000000001"

    response = client.get("/health", headers={REQUEST_ID_HEADER: request_id})

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == request_id
    records = _completion_records(log_output.getvalue())
    assert records
    record = records[-1]
    assert record["request_id"] == request_id
    assert record["method"] == "GET"
    assert record["route"] == "/health"
    assert record["status"] == 200
    assert isinstance(record["duration_ms"], float)


@pytest.mark.parametrize("value", ["not-a-uuid", "x" * 129])
def test_malformed_or_oversized_request_id_is_replaced_without_rejecting_request(
    client: TestClient, value: str
) -> None:
    response = client.get("/health", headers={REQUEST_ID_HEADER: value})

    assert response.status_code == 200
    replacement = response.headers[REQUEST_ID_HEADER]
    assert replacement != value
    assert len(replacement) == 36
    assert replacement.count("-") == 4


def test_request_log_does_not_include_query_string(
    client: TestClient, log_output: io.StringIO
) -> None:
    secret_marker = "request-secret-marker-7f31"

    response = client.get(f"/health?token={secret_marker}")

    assert response.status_code == 200
    output = log_output.getvalue()
    assert secret_marker not in output
    records = _completion_records(output)
    assert records[-1]["route"] == "/health"


def test_cors_exposes_request_id_header(client: TestClient) -> None:
    response = client.get(
        "/health",
        headers={"Origin": "http://localhost:3000"},
    )

    assert response.headers["access-control-expose-headers"] == REQUEST_ID_HEADER


@pytest.mark.parametrize(
    "path, status",
    [
        ("/health", 200),
        ("/missing", 404),
        ("/model/shots", 403),
        ("/__wp33_test_unhandled_error", 500),
    ],
)
def test_request_id_is_returned_for_success_not_found_and_domain_error(
    client: TestClient, path: str, status: int
) -> None:
    response = client.get(path)

    assert response.status_code == status
    assert len(response.headers[REQUEST_ID_HEADER]) == 36


def test_unhandled_error_is_generic_but_correlated_and_redacted(
    client: TestClient, log_output: io.StringIO
) -> None:
    response = client.get("/__wp33_test_unhandled_error")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error."}
    record = _completion_records(log_output.getvalue())[-1]
    assert record["status"] == 500
    assert record["exception_type"] == "RuntimeError"
    assert "test-only failure" not in log_output.getvalue()


def test_allowed_origin_unhandled_error_retains_cors_and_request_id(client: TestClient) -> None:
    origin = "http://localhost:3000"

    response = client.get("/__wp33_test_unhandled_error", headers={"Origin": origin})

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == origin
    assert len(response.headers[REQUEST_ID_HEADER]) == 36


def test_unmatched_routes_use_one_bounded_log_label(
    client: TestClient, log_output: io.StringIO
) -> None:
    attacker_paths = ["/unknown/alpha", "/unknown/bravo"]

    for path in attacker_paths:
        assert client.get(path).status_code == 404

    records = _completion_records(log_output.getvalue())[-2:]
    assert [record["route"] for record in records] == ["<unmatched>", "<unmatched>"]
    assert all(path not in log_output.getvalue() for path in attacker_paths)
