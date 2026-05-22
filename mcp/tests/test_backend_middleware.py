"""Tests for BackendURLMiddleware and ContextVar backend resolution."""
import ixnse_mcp as sut
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import PlainTextResponse
from starlette.testclient import TestClient


def _make_test_app() -> Starlette:
    """Minimal Starlette app that echoes which backend ContextVar resolves to."""

    async def echo_backend(request):
        return PlainTextResponse(sut._backend_url.get(sut._backend_config[0]))

    app = Starlette(routes=[Route("/", echo_backend)])
    app.add_middleware(sut.BackendURLMiddleware)
    return app


def test_no_backend_param_uses_default():
    client = TestClient(_make_test_app())
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.text == sut._backend_config[0]


def test_backend_param_overrides():
    client = TestClient(_make_test_app())
    resp = client.get("/?backend=http://other:9090")
    assert resp.status_code == 200
    assert resp.text == "http://other:9090"


def test_backend_param_strips_trailing_slash():
    client = TestClient(_make_test_app())
    resp = client.get("/?backend=http://other:9090/")
    assert resp.status_code == 200
    assert resp.text == "http://other:9090"


def test_contextvar_resets_after_request():
    """ContextVar must not leak between requests."""
    client = TestClient(_make_test_app())
    client.get("/?backend=http://leaked:1234")
    resp = client.get("/")
    assert resp.text == sut._backend_config[0]
