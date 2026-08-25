"""Request correlation and structured application logs.

The middleware deliberately logs request metadata only. Bodies, query strings, headers and database
connection details are not part of the record because this service is unauthenticated and its
operator logs are not a safe place for request or credential material.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from os.path import basename
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

REQUEST_ID_HEADER = "X-Request-ID"
MAX_INBOUND_REQUEST_ID_LENGTH = 128
request_id_context: ContextVar[str | None] = ContextVar("touchline_request_id", default=None)


class JsonFormatter(logging.Formatter):
    """Serialize application records as one stable JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", record.getMessage()),
        }
        for field in (
            "request_id",
            "method",
            "route",
            "status",
            "duration_ms",
            "environment",
            "app_version",
            "model_version",
            "exception_type",
            "stack_frames",
        ):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def request_logger() -> logging.Logger:
    """Return the configured request logger without duplicating handlers on module reload."""
    logger = logging.getLogger("touchline.request")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not any(getattr(handler, "_touchline_json", False) for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        handler._touchline_json = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    return logger


def _safe_request_id(raw: str | None) -> str:
    """Reuse only a canonical UUID; malformed or oversized input is replaced safely."""
    if raw is not None and len(raw) <= MAX_INBOUND_REQUEST_ID_LENGTH:
        try:
            parsed = UUID(raw)
        except (ValueError, AttributeError):
            pass
        else:
            canonical = str(parsed)
            if raw == canonical:
                return canonical
    return str(uuid4())


def current_request_id() -> str | None:
    """Return the request ID for code that emits an application log within a request."""
    return request_id_context.get()


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "<unmatched>"


def _model_version(request: Request) -> str | None:
    """Read only the public model identity, without allowing logging to break a response."""
    try:
        runtime = getattr(request.app.state, "model_runtime", None)
        provenance = runtime.provenance() if runtime is not None else None
        value = provenance.get("model_version") if isinstance(provenance, dict) else None
        return value if isinstance(value, str) else None
    except Exception:
        return None


def _sanitized_stack_frames(exc: BaseException) -> list[dict[str, int | str]]:
    """Return a bounded trace identity without source text, locals, or exception messages."""
    frames: list[dict[str, int | str]] = []
    trace = exc.__traceback__
    while trace is not None:
        frame = trace.tb_frame
        frames.append(
            {
                "file": basename(frame.f_code.co_filename),
                "line": trace.tb_lineno,
                "function": frame.f_code.co_name,
            }
        )
        trace = trace.tb_next
    return frames[-8:]


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Attach a safe request ID and emit one structured completion record per request."""

    def __init__(self, app: Any, *, allowed_origins: list[str] | None = None) -> None:
        super().__init__(app)
        self.logger = request_logger()
        self.allowed_origins = frozenset(allowed_origins or ())

    def _apply_cors_headers(self, request: Request, response: Response) -> None:
        """Preserve the CORS contract when this outer middleware creates a 500 response."""
        origin = request.headers.get("origin")
        if origin is None or origin not in self.allowed_origins:
            return
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Expose-Headers"] = REQUEST_ID_HEADER
        response.headers["Vary"] = "Origin"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = _safe_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        token = request_id_context.set(request_id)
        started = perf_counter()
        response: Response | None = None
        exception_type: str | None = None
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        except Exception as exc:
            exception_type = type(exc).__name__
            self.logger.error(
                "unhandled_exception",
                extra={
                    "event": "unhandled_exception",
                    "request_id": request_id,
                    "exception_type": exception_type,
                    "stack_frames": _sanitized_stack_frames(exc),
                },
            )
            response = JSONResponse(
                status_code=500,
                content={"detail": "Internal server error."},
                headers={REQUEST_ID_HEADER: request_id},
            )
            self._apply_cors_headers(request, response)
            return response
        finally:
            fields: dict[str, Any] = {
                "event": "request_completed",
                "request_id": request_id,
                "method": request.method,
                "route": _route_template(request),
                "status": response.status_code if response is not None else 500,
                "duration_ms": round((perf_counter() - started) * 1000, 3),
                "environment": getattr(request.app.state, "environment", "unknown"),
                "app_version": request.app.version,
            }
            model_version = _model_version(request)
            if model_version is not None:
                fields["model_version"] = model_version
            if exception_type is not None:
                fields["exception_type"] = exception_type
            self.logger.info("request_completed", extra=fields)
            request_id_context.reset(token)
