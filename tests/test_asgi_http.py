"""Tests for ASGI middleware with real HTTP requests via Starlette + httpx.

Unlike test_middleware.py (raw ASGI simulation), these tests exercise the
full HTTP stack: Starlette routing, httpx TestClient, real response parsing.
"""

from __future__ import annotations

import json

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route
from starlette.testclient import TestClient

from spektr import SpektrMiddleware, capture, log
from spektr._types import LogLevel


# ── App Factory ──────────────────────────────────────────────


def _make_app() -> Starlette:
    async def homepage(request: Request) -> Response:
        return PlainTextResponse("OK")

    async def users(request: Request) -> Response:
        log("fetching users", count=3)
        return JSONResponse({"users": ["alice", "bob", "charlie"]})

    async def create_item(request: Request) -> Response:
        body = await request.json()
        log("item created", name=body.get("name"))
        return JSONResponse({"id": 1, "name": body.get("name")}, status_code=201)

    async def error_endpoint(request: Request) -> Response:
        raise RuntimeError("something went wrong")

    async def slow_endpoint(request: Request) -> Response:
        import asyncio
        await asyncio.sleep(0.03)
        return PlainTextResponse("done")

    async def nested_logs(request: Request) -> Response:
        with log.context(user_id=42):
            log("step 1")
            log("step 2", action="validate")
        return PlainTextResponse("OK")

    app = Starlette(
        routes=[
            Route("/", homepage),
            Route("/users", users),
            Route("/items", create_item, methods=["POST"]),
            Route("/error", error_endpoint),
            Route("/slow", slow_endpoint),
            Route("/nested", nested_logs),
        ],
    )
    app.add_middleware(SpektrMiddleware)
    return app


@pytest.fixture
def app():
    return _make_app()


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


# ── Basic HTTP Tests ─────────────────────────────────────────


class TestHttpBasic:
    def test_get_returns_200(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert response.text == "OK"

    def test_get_json_endpoint(self, client):
        response = client.get("/users")
        assert response.status_code == 200
        data = response.json()
        assert len(data["users"]) == 3

    def test_post_with_body(self, client):
        response = client.post("/items", json={"name": "widget"})
        assert response.status_code == 201
        assert response.json()["name"] == "widget"


# ── Middleware Logging via HTTP ───────────────────────────────


class TestHttpMiddlewareLogging:
    def test_logs_request_completed(self, app):
        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/")

        assert response.status_code == 200
        completed = [r for r in logs if r.message == "request completed"]
        assert len(completed) == 1
        assert completed[0].data["method"] == "GET"
        assert completed[0].data["path"] == "/"
        assert completed[0].data["status_code"] == 200
        assert completed[0].data["duration_ms"] >= 0

    def test_logs_post_method_and_path(self, app):
        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            client.post("/items", json={"name": "test"})

        completed = [r for r in logs if r.message == "request completed"]
        assert completed[0].data["method"] == "POST"
        assert completed[0].data["path"] == "/items"
        assert completed[0].data["status_code"] == 201

    def test_logs_status_404_for_missing_route(self, app):
        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/nonexistent")

        assert response.status_code == 404
        completed = [r for r in logs if r.message == "request completed"]
        assert len(completed) == 1
        assert completed[0].data["status_code"] == 404

    def test_logs_error_on_exception(self, app):
        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/error")

        assert response.status_code == 500
        failed = [r for r in logs if r.message == "request failed"]
        assert len(failed) == 1
        assert failed[0].level == LogLevel.ERROR
        assert failed[0].data["method"] == "GET"
        assert failed[0].data["path"] == "/error"

    def test_measures_real_duration(self, app):
        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/slow")

        completed = [r for r in logs if r.message == "request completed"]
        assert completed[0].data["duration_ms"] >= 20


# ── Context Propagation via HTTP ─────────────────────────────


class TestHttpContextPropagation:
    def test_request_id_in_app_logs(self, app):
        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/users")

        app_logs = [r for r in logs if r.message == "fetching users"]
        assert len(app_logs) == 1
        assert "request_id" in app_logs[0].context

    def test_request_id_unique_per_request(self, app):
        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/users")
            client.get("/users")

        app_logs = [r for r in logs if r.message == "fetching users"]
        assert len(app_logs) == 2
        id_1 = app_logs[0].context["request_id"]
        id_2 = app_logs[1].context["request_id"]
        assert id_1 != id_2

    def test_nested_context_inside_middleware(self, app):
        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/nested")

        step1 = [r for r in logs if r.message == "step 1"]
        step2 = [r for r in logs if r.message == "step 2"]
        assert step1[0].context["user_id"] == 42
        assert step1[0].context["request_id"]  # from middleware
        assert step2[0].data["action"] == "validate"
        assert step2[0].context["request_id"] == step1[0].context["request_id"]

    def test_context_isolated_between_requests(self, app):
        """request_id from first request should not leak into second."""
        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/users")
            client.get("/users")

        fetches = [r for r in logs if r.message == "fetching users"]
        completed = [r for r in logs if r.message == "request completed"]
        # Each request has its own request_id
        all_ids = {r.context.get("request_id") for r in fetches + completed if r.context.get("request_id")}
        assert len(all_ids) >= 2


# ── Trace Spans via HTTP ─────────────────────────────────────


class TestHttpTraceSpans:
    def test_app_logs_have_trace_ids(self, app):
        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/users")

        app_logs = [r for r in logs if r.message == "fetching users"]
        assert app_logs[0].trace_id is not None
        assert app_logs[0].span_id is not None

    def test_trace_id_consistent_within_request(self, app):
        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/nested")

        app_logs = [r for r in logs if r.message in ("step 1", "step 2")]
        assert len(app_logs) == 2
        assert app_logs[0].trace_id == app_logs[1].trace_id

    def test_different_requests_different_traces(self, app):
        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/users")
            client.get("/users")

        fetches = [r for r in logs if r.message == "fetching users"]
        assert fetches[0].trace_id != fetches[1].trace_id


# ── Multiple Methods and Status Codes ────────────────────────


class TestHttpMethods:
    def test_head_request(self, app):
        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.head("/")

        assert response.status_code == 200
        completed = [r for r in logs if r.message == "request completed"]
        assert completed[0].data["method"] == "HEAD"

    def test_put_returns_405(self, app):
        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.put("/items", json={"name": "test"})

        assert response.status_code == 405
        completed = [r for r in logs if r.message == "request completed"]
        assert completed[0].data["status_code"] == 405

    def test_options_request(self, app):
        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.options("/")

        completed = [r for r in logs if r.message == "request completed"]
        assert completed[0].data["method"] == "OPTIONS"


# ── Install Integration ──────────────────────────────────────


class TestInstallWithStarlette:
    def test_install_adds_middleware_to_starlette(self):
        """spektr._install_framework detects Starlette and adds middleware."""
        from spektr._integrations._exceptions import _install_framework

        app = Starlette(routes=[Route("/", lambda r: PlainTextResponse("OK"))])
        _install_framework(app)

        # Verify middleware was added by making a request
        with capture() as logs:
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/")

        completed = [r for r in logs if r.message == "request completed"]
        assert len(completed) == 1
