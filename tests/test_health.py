"""Tests for the health check endpoint."""

from __future__ import annotations

import json

import pytest

import spektr._config as config_module
from spektr._config import Config, get_config
from spektr._integrations._health import health_check


@pytest.fixture(autouse=True)
def reset_config():
    old = config_module._config
    yield
    config_module._config = old


class TestHealthCheck:
    @pytest.mark.anyio
    async def test_health_returns_200(self):
        sent = []

        async def send(message):
            sent.append(message)

        await health_check({}, None, send)
        assert sent[0]["status"] == 200

    @pytest.mark.anyio
    async def test_health_returns_json(self):
        sent = []

        async def send(message):
            sent.append(message)

        await health_check({}, None, send)
        assert [b"content-type", b"application/json"] in sent[0]["headers"]

    @pytest.mark.anyio
    async def test_health_body_contains_status_ok(self):
        sent = []

        async def send(message):
            sent.append(message)

        await health_check({}, None, send)
        body = json.loads(sent[1]["body"])
        assert body["status"] == "ok"

    @pytest.mark.anyio
    async def test_health_body_contains_service_name(self):
        from spektr import configure

        configure(service="my-api")
        sent = []

        async def send(message):
            sent.append(message)

        await health_check({}, None, send)
        body = json.loads(sent[1]["body"])
        assert body["service"] == "my-api"

    @pytest.mark.anyio
    async def test_health_sends_two_messages(self):
        sent = []

        async def send(message):
            sent.append(message)

        await health_check({}, None, send)
        assert len(sent) == 2
        assert sent[0]["type"] == "http.response.start"
        assert sent[1]["type"] == "http.response.body"

    @pytest.mark.anyio
    async def test_health_content_length_matches(self):
        sent = []

        async def send(message):
            sent.append(message)

        await health_check({}, None, send)
        content_length = None
        for name, value in sent[0]["headers"]:
            if name == b"content-length":
                content_length = int(value)
        assert content_length == len(sent[1]["body"])


class TestHealthCheckInMiddleware:
    @pytest.mark.anyio
    async def test_middleware_serves_health_when_configured(self):
        from spektr import configure
        from spektr._integrations._middleware import SpektrMiddleware

        configure(health_path="/healthz")

        async def app(scope, receive, send):
            pytest.fail("Should not reach app for health path")

        middleware = SpektrMiddleware(app)
        sent = []

        async def send(message):
            sent.append(message)

        await middleware({"type": "http", "path": "/healthz", "method": "GET", "headers": []}, None, send)
        assert sent[0]["status"] == 200
        body = json.loads(sent[1]["body"])
        assert body["status"] == "ok"

    @pytest.mark.anyio
    async def test_middleware_passes_through_non_health_paths(self):
        from spektr import configure
        from spektr._integrations._middleware import SpektrMiddleware

        configure(health_path="/healthz")

        reached = []

        async def app(scope, receive, send):
            reached.append(True)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = SpektrMiddleware(app)
        sent = []

        async def send(message):
            sent.append(message)

        await middleware({"type": "http", "path": "/api/users", "method": "GET", "headers": []}, None, send)
        assert len(reached) == 1

    @pytest.mark.anyio
    async def test_middleware_no_health_path_by_default(self):
        """When health_path is None, all paths go to the app."""
        from spektr._integrations._middleware import SpektrMiddleware

        # Reset to defaults.
        config_module._config = Config()

        reached = []

        async def app(scope, receive, send):
            reached.append(True)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = SpektrMiddleware(app)
        sent = []

        async def send(message):
            sent.append(message)

        await middleware({"type": "http", "path": "/healthz", "method": "GET", "headers": []}, None, send)
        assert len(reached) == 1
