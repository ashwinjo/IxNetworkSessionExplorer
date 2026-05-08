"""Unit tests for ixse.ixn_web (IxNetwork Web auth-path probe)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from ixse.ixn_web import ON_CHASSIS_AUTH_PATH, STANDALONE_AUTH_PATH, check_ixnetwork_web
from ixse.models import ServerEntry


def _entry() -> ServerEntry:
    return ServerEntry(name="srv1", host="10.0.0.1", username="admin", password="secret")


def test_green_standalone_when_only_ixnetworkweb_returns_api_key() -> None:
    def post_side_effect(url: str, **_kw: object) -> MagicMock:
        r = MagicMock()
        if "ixnetworkweb" in url:
            r.status_code = 200
            r.content = b'{"apiKey":"k1"}'
            r.json.return_value = {"apiKey": "k1"}
        else:
            r.status_code = 404
            r.content = b"{}"
            r.json.return_value = {}
        return r

    with patch("ixse.ixn_web.requests.post", side_effect=post_side_effect):
        snap = check_ixnetwork_web(_entry())

    assert snap.heartbeat == "green"
    assert snap.deployment == "standalone"
    assert snap.auth_path == STANDALONE_AUTH_PATH
    assert snap.detail is None


def test_green_on_chassis_when_only_platform_returns_api_key() -> None:
    def post_side_effect(url: str, **_kw: object) -> MagicMock:
        r = MagicMock()
        if ON_CHASSIS_AUTH_PATH in url or "/platform/api" in url:
            r.status_code = 200
            r.content = b'{"apiKey":"k2"}'
            r.json.return_value = {"apiKey": "k2"}
        else:
            r.status_code = 404
            r.content = b"{}"
            r.json.return_value = {}
        return r

    with patch("ixse.ixn_web.requests.post", side_effect=post_side_effect):
        snap = check_ixnetwork_web(_entry())

    assert snap.heartbeat == "green"
    assert snap.deployment == "onChassis"
    assert snap.auth_path == ON_CHASSIS_AUTH_PATH


def test_probe_urls_always_use_rest_port() -> None:
    """rest_port is always the web interface port — used verbatim for HTTPS probe."""
    seen: list[str] = []

    def post_side_effect(url: str, **_kw: object) -> MagicMock:
        seen.append(url)
        r = MagicMock()
        r.status_code = 404
        r.content = b"{}"
        r.json.return_value = {}
        return r

    for port in (31443, 11009, 8443):
        seen.clear()
        entry = ServerEntry(
            name="srv",
            host="10.36.77.250",
            username="admin",
            password="secret",
            rest_port=port,
        )
        with patch("ixse.ixn_web.requests.post", side_effect=post_side_effect):
            check_ixnetwork_web(entry)

        assert len(seen) == 2
        for u in seen:
            assert f":{port}" in u, f"Expected :{port} in URL, got: {u}"


def test_probe_green_standalone_custom_port() -> None:
    """Auth on custom port (31443) is classified as standalone + green."""
    def post_side_effect(url: str, **_kw: object) -> MagicMock:
        r = MagicMock()
        if "ixnetworkweb" in url and ":31443" in url:
            r.status_code = 200
            r.content = b'{"apiKey":"k1"}'
            r.json.return_value = {"apiKey": "k1"}
        else:
            r.status_code = 404
            r.content = b"{}"
            r.json.return_value = {}
        return r

    entry = ServerEntry(
        name="new27build",
        host="10.36.77.250",
        username="admin",
        password="secret",
        rest_port=31443,
    )
    with patch("ixse.ixn_web.requests.post", side_effect=post_side_effect):
        snap = check_ixnetwork_web(entry)

    assert snap.heartbeat == "green"
    assert snap.deployment == "standalone"


def test_red_when_both_network_errors() -> None:
    with patch(
        "ixse.ixn_web.requests.post",
        side_effect=requests.ConnectionError("refused"),
    ):
        snap = check_ixnetwork_web(_entry())

    assert snap.heartbeat == "red"
    assert snap.deployment is None
    assert snap.auth_path is None
    assert snap.detail is not None


def test_yellow_when_http_but_no_api_key() -> None:
    def post_side_effect(_url: str, **_kw: object) -> MagicMock:
        r = MagicMock()
        r.status_code = 401
        r.content = b"{}"
        r.json.return_value = {}
        return r

    with patch("ixse.ixn_web.requests.post", side_effect=post_side_effect):
        snap = check_ixnetwork_web(_entry())

    assert snap.heartbeat == "yellow"
    assert snap.deployment is None


@pytest.mark.parametrize(
    "prefer,expected",
    [
        ("standalone", "standalone"),
        ("onChassis", "onChassis"),
    ],
)
def test_tie_break_when_both_paths_return_key(
    prefer: str, expected: str
) -> None:
    def post_side_effect(_url: str, **_kw: object) -> MagicMock:
        r = MagicMock()
        r.status_code = 200
        r.content = b'{"apiKey":"same"}'
        r.json.return_value = {"apiKey": "same"}
        return r

    with patch("ixse.ixn_web.requests.post", side_effect=post_side_effect):
        snap = check_ixnetwork_web(_entry(), prefer=prefer)  # type: ignore[arg-type]

    assert snap.heartbeat == "green"
    assert snap.deployment == expected
