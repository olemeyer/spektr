"""Health check ASGI endpoint.

Provides a lightweight JSON health response for K8s probes and monitoring.
Can be integrated into SpektrMiddleware via ``health_path`` parameter.
"""

from __future__ import annotations

import json
from typing import Any, Callable


async def health_check(scope: dict, receive: Callable, send: Callable) -> None:
    """Minimal ASGI app that returns a health check JSON response."""
    from .._config import get_config

    config = get_config()
    body = json.dumps({
        "status": "ok",
        "service": config.service,
    }).encode()

    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            [b"content-type", b"application/json"],
            [b"content-length", str(len(body)).encode()],
        ],
    })
    await send({
        "type": "http.response.body",
        "body": body,
    })
