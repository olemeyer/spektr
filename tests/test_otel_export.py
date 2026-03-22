"""Tests for OTel export with a real OTLP HTTP collector.

Spins up an in-process HTTP server that accepts OTLP protobuf payloads,
then verifies that spektr spans actually arrive over the wire with correct
service name, span names, attributes, status, and parent-child relationships.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)

from spektr import SpektrMiddleware, capture, log, trace
import spektr._otel as otel_bridge


# ── In-process OTLP Collector ────────────────────────────────


class _OTLPCollector:
    """Minimal HTTP server that accepts OTLP trace export requests."""

    def __init__(self) -> None:
        self.received: list[ExportTraceServiceRequest] = []
        self._lock = threading.Lock()
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port: int = 0

    def start(self) -> None:
        collector = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length)

                request = ExportTraceServiceRequest()
                request.ParseFromString(body)

                with collector._lock:
                    collector.received.append(request)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{}')

            def log_message(self, format: str, *args: Any) -> None:
                pass  # Silence HTTP server logs

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
        if self._thread:
            self._thread.join(timeout=5)

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def get_spans(self) -> list[dict]:
        """Extract all spans from received requests as flat list of dicts."""
        spans = []
        with self._lock:
            for request in self.received:
                for resource_spans in request.resource_spans:
                    resource_attrs = {
                        attr.key: attr.value.string_value
                        for attr in resource_spans.resource.attributes
                    }
                    for scope_spans in resource_spans.scope_spans:
                        for span in scope_spans.spans:
                            span_attrs = {}
                            for attr in span.attributes:
                                value = attr.value
                                if value.HasField("string_value"):
                                    span_attrs[attr.key] = value.string_value
                                elif value.HasField("int_value"):
                                    span_attrs[attr.key] = value.int_value
                                elif value.HasField("double_value"):
                                    span_attrs[attr.key] = value.double_value
                                elif value.HasField("bool_value"):
                                    span_attrs[attr.key] = value.bool_value

                            spans.append({
                                "name": span.name,
                                "trace_id": span.trace_id.hex(),
                                "span_id": span.span_id.hex(),
                                "parent_span_id": span.parent_span_id.hex() if span.parent_span_id else None,
                                "status_code": span.status.code,
                                "status_message": span.status.message,
                                "attributes": span_attrs,
                                "resource": resource_attrs,
                                "events": [
                                    {
                                        "name": e.name,
                                        "attributes": {
                                            a.key: a.value.string_value
                                            for a in e.attributes
                                        },
                                    }
                                    for e in span.events
                                ],
                            })
        return spans

    def wait_for_spans(self, count: int, timeout: float = 5.0) -> list[dict]:
        """Poll until at least *count* spans arrive, or timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            spans = self.get_spans()
            if len(spans) >= count:
                return spans
            time.sleep(0.05)
        return self.get_spans()


@pytest.fixture
def collector():
    c = _OTLPCollector()
    c.start()
    yield c
    c.stop()
    otel_bridge.shutdown()


# ── Basic OTLP Export ────────────────────────────────────────


class TestOTLPBasicExport:
    def test_single_span_arrives_at_collector(self, collector):
        otel_bridge.setup(
            service_name="test-svc",
            endpoint=collector.endpoint,
        )

        with trace("hello-span"):
            pass

        otel_bridge.shutdown()
        spans = collector.wait_for_spans(1)
        assert len(spans) >= 1
        assert spans[0]["name"] == "hello-span"

    def test_service_name_in_resource(self, collector):
        otel_bridge.setup(
            service_name="my-service",
            endpoint=collector.endpoint,
        )

        with trace("test"):
            pass

        otel_bridge.shutdown()
        spans = collector.wait_for_spans(1)
        assert spans[0]["resource"]["service.name"] == "my-service"

    def test_span_attributes_exported(self, collector):
        otel_bridge.setup(
            service_name="test-svc",
            endpoint=collector.endpoint,
        )

        with trace("db-query", table="users", limit=10):
            pass

        otel_bridge.shutdown()
        spans = collector.wait_for_spans(1)
        assert spans[0]["attributes"]["table"] == "users"
        assert spans[0]["attributes"]["limit"] == 10

    def test_multiple_spans_exported(self, collector):
        otel_bridge.setup(
            service_name="test-svc",
            endpoint=collector.endpoint,
        )

        with trace("span-1"):
            pass
        with trace("span-2"):
            pass
        with trace("span-3"):
            pass

        otel_bridge.shutdown()
        spans = collector.wait_for_spans(3)
        names = {s["name"] for s in spans}
        assert names == {"span-1", "span-2", "span-3"}


# ── Parent-Child Relationships ───────────────────────────────


class TestOTLPParentChild:
    def test_nested_spans_have_parent(self, collector):
        otel_bridge.setup(
            service_name="test-svc",
            endpoint=collector.endpoint,
        )

        with trace("parent"):
            with trace("child"):
                pass

        otel_bridge.shutdown()
        spans = collector.wait_for_spans(2)

        parent = next(s for s in spans if s["name"] == "parent")
        child = next(s for s in spans if s["name"] == "child")

        assert child["parent_span_id"] == parent["span_id"]
        assert child["trace_id"] == parent["trace_id"]

    def test_sibling_spans_share_parent(self, collector):
        otel_bridge.setup(
            service_name="test-svc",
            endpoint=collector.endpoint,
        )

        with trace("root"):
            with trace("child-a"):
                pass
            with trace("child-b"):
                pass

        otel_bridge.shutdown()
        spans = collector.wait_for_spans(3)

        root = next(s for s in spans if s["name"] == "root")
        child_a = next(s for s in spans if s["name"] == "child-a")
        child_b = next(s for s in spans if s["name"] == "child-b")

        assert child_a["parent_span_id"] == root["span_id"]
        assert child_b["parent_span_id"] == root["span_id"]
        assert child_a["span_id"] != child_b["span_id"]

    def test_deep_nesting(self, collector):
        otel_bridge.setup(
            service_name="test-svc",
            endpoint=collector.endpoint,
        )

        with trace("level-1"):
            with trace("level-2"):
                with trace("level-3"):
                    pass

        otel_bridge.shutdown()
        spans = collector.wait_for_spans(3)

        level1 = next(s for s in spans if s["name"] == "level-1")
        level2 = next(s for s in spans if s["name"] == "level-2")
        level3 = next(s for s in spans if s["name"] == "level-3")

        assert level2["parent_span_id"] == level1["span_id"]
        assert level3["parent_span_id"] == level2["span_id"]
        assert level1["trace_id"] == level2["trace_id"] == level3["trace_id"]


# ── Error Recording ──────────────────────────────────────────


class TestOTLPErrorRecording:
    def test_error_span_status(self, collector):
        otel_bridge.setup(
            service_name="test-svc",
            endpoint=collector.endpoint,
        )

        with pytest.raises(ValueError):
            with trace("failing"):
                raise ValueError("test error")

        otel_bridge.shutdown()
        spans = collector.wait_for_spans(1)

        # OTel StatusCode.ERROR = 2
        assert spans[0]["status_code"] == 2
        assert "test error" in spans[0]["status_message"]

    def test_error_recorded_as_exception_event(self, collector):
        otel_bridge.setup(
            service_name="test-svc",
            endpoint=collector.endpoint,
        )

        with pytest.raises(RuntimeError):
            with trace("error-span"):
                raise RuntimeError("boom")

        otel_bridge.shutdown()
        spans = collector.wait_for_spans(1)

        events = spans[0]["events"]
        exception_events = [e for e in events if e["name"] == "exception"]
        assert len(exception_events) == 1
        assert exception_events[0]["attributes"]["exception.type"] == "RuntimeError"
        assert "boom" in exception_events[0]["attributes"]["exception.message"]

    def test_ok_span_status(self, collector):
        otel_bridge.setup(
            service_name="test-svc",
            endpoint=collector.endpoint,
        )

        with trace("success"):
            pass

        otel_bridge.shutdown()
        spans = collector.wait_for_spans(1)

        # OTel StatusCode.OK = 1
        assert spans[0]["status_code"] == 1


# ── Decorator with OTLP Export ───────────────────────────────


class TestOTLPDecorator:
    def test_decorated_function_exports_span(self, collector):
        otel_bridge.setup(
            service_name="test-svc",
            endpoint=collector.endpoint,
        )

        @trace
        def process_order(order_id: int):
            return f"processed {order_id}"

        result = process_order(order_id=42)

        otel_bridge.shutdown()
        spans = collector.wait_for_spans(1)

        assert result == "processed 42"
        assert len(spans) >= 1
        span = next(s for s in spans if "process_order" in s["name"])
        assert span["attributes"]["order_id"] == 42

    def test_async_decorated_exports_span(self, collector):
        otel_bridge.setup(
            service_name="test-svc",
            endpoint=collector.endpoint,
        )

        @trace
        async def fetch_data(source: str):
            await asyncio.sleep(0.01)
            return f"data from {source}"

        async def run():
            return await fetch_data(source="api")

        result = asyncio.run(run())

        otel_bridge.shutdown()
        spans = collector.wait_for_spans(1)

        assert result == "data from api"
        span = next(s for s in spans if "fetch_data" in s["name"])
        assert span["attributes"]["source"] == "api"


# ── Log-Trace Correlation with OTLP ─────────────────────────


class TestOTLPLogCorrelation:
    def test_log_trace_id_matches_exported_span(self, collector):
        otel_bridge.setup(
            service_name="test-svc",
            endpoint=collector.endpoint,
        )

        with capture() as logs:
            with trace("request"):
                log("inside span")

        otel_bridge.shutdown()
        spans = collector.wait_for_spans(1)

        log_record = logs[0]
        exported_span = spans[0]

        assert log_record.trace_id == exported_span["trace_id"]

    def test_nested_log_correlation(self, collector):
        otel_bridge.setup(
            service_name="test-svc",
            endpoint=collector.endpoint,
        )

        with capture() as logs:
            with trace("parent"):
                log("in parent")
                with trace("child"):
                    log("in child")

        otel_bridge.shutdown()
        spans = collector.wait_for_spans(2)

        parent_span = next(s for s in spans if s["name"] == "parent")
        child_span = next(s for s in spans if s["name"] == "child")

        parent_log = next(r for r in logs if r.message == "in parent")
        child_log = next(r for r in logs if r.message == "in child")

        assert parent_log.trace_id == parent_span["trace_id"]
        assert child_log.span_id == child_span["span_id"]


# ── ASGI Middleware with OTLP Export ─────────────────────────


class TestOTLPMiddleware:
    def test_middleware_spans_exported(self, collector):
        """Middleware spans should arrive at the OTLP collector."""
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.responses import PlainTextResponse
        from starlette.routing import Route
        from starlette.testclient import TestClient

        otel_bridge.setup(
            service_name="web-app",
            endpoint=collector.endpoint,
        )

        async def homepage(request: Request):
            return PlainTextResponse("OK")

        app = Starlette(routes=[Route("/", homepage)])
        app.add_middleware(SpektrMiddleware)

        with capture():
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/")

        otel_bridge.shutdown()
        spans = collector.wait_for_spans(1)

        assert len(spans) >= 1
        request_span = next(s for s in spans if "GET" in s["name"])
        assert request_span["attributes"]["method"] == "GET"
        assert request_span["attributes"]["path"] == "/"
        assert request_span["resource"]["service.name"] == "web-app"

    def test_middleware_error_span_exported(self, collector):
        from starlette.applications import Starlette
        from starlette.requests import Request
        from starlette.routing import Route
        from starlette.testclient import TestClient

        otel_bridge.setup(
            service_name="web-app",
            endpoint=collector.endpoint,
        )

        async def fail(request: Request):
            raise RuntimeError("handler error")

        app = Starlette(routes=[Route("/fail", fail)])
        app.add_middleware(SpektrMiddleware)

        with capture():
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/fail")

        otel_bridge.shutdown()
        spans = collector.wait_for_spans(1)

        error_span = next(s for s in spans if "GET" in s["name"])
        assert error_span["status_code"] == 2  # ERROR


# ── Full Scenario: Multiple Services ─────────────────────────


class TestOTLPFullScenario:
    def test_web_request_with_nested_spans(self, collector):
        """Simulates a web handler that calls DB and cache — all spans exported."""
        otel_bridge.setup(
            service_name="order-service",
            endpoint=collector.endpoint,
        )

        @trace
        def query_db(table: str):
            return [{"id": 1}]

        @trace
        def check_cache(key: str):
            return None

        with capture() as logs:
            with trace("handle-request", method="GET", path="/orders"):
                log("handling request")
                check_cache(key="orders:recent")
                query_db(table="orders")
                log("request complete")

        otel_bridge.shutdown()
        spans = collector.wait_for_spans(3)

        names = {s["name"] for s in spans}
        assert "handle-request" in names
        assert any("query_db" in n for n in names)
        assert any("check_cache" in n for n in names)

        root = next(s for s in spans if s["name"] == "handle-request")
        assert root["attributes"]["method"] == "GET"
        assert root["resource"]["service.name"] == "order-service"

        # All spans share same trace_id
        trace_ids = {s["trace_id"] for s in spans}
        assert len(trace_ids) == 1

        # Verify log correlation
        assert logs[0].trace_id == root["trace_id"]
