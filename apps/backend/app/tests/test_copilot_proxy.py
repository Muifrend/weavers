from __future__ import annotations

import json
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

import httpx
from starlette.requests import Request

from app.main import copilotkit_proxy


class UnreachableAsyncClient:
    def __init__(self, *args, **kwargs) -> None:
        self.closed = False

    def build_request(self, method: str, url: str, *, headers, content) -> httpx.Request:
        return httpx.Request(method, url, headers=headers, content=content)

    async def send(self, request: httpx.Request, *, stream: bool) -> httpx.Response:
        raise httpx.ConnectError("All connection attempts failed", request=request)

    async def aclose(self) -> None:
        self.closed = True


class CopilotProxyTests(IsolatedAsyncioTestCase):
    async def test_returns_503_when_runtime_is_unreachable(self) -> None:
        request = make_request()
        unavailable_settings = SimpleNamespace(copilot_runtime_url="http://127.0.0.1:3001")

        with (
            patch("app.main.settings", unavailable_settings),
            patch("app.main.httpx.AsyncClient", UnreachableAsyncClient),
        ):
            response = await copilotkit_proxy(request)

        assert response.status_code == 503
        detail = json.loads(response.body)["detail"]
        assert detail["error_code"] == "copilot_runtime_unavailable"
        assert detail["runtime_url"] == "http://127.0.0.1:3001"


def make_request() -> Request:
    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"{}", "more_body": False}

    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/copilotkit",
            "raw_path": b"/api/copilotkit",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        },
        receive=receive,
    )
