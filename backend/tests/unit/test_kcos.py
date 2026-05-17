"""Unit tests for the KCOS SSH banner probe."""

from unittest.mock import MagicMock, patch

from ixse.kcos import probe_kcos

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

KCOS_BANNER = (
    b"\r\n"
    b" IP:            10.36.71.98/22 fe80::21a:c5ff:fe05:f/64\r\n"
    b" BMC channel 1:        10.36.71.42/22\r\n"
    b" IxNetwork Web:        26.1.1137\r\n"
    b" kcos-aresone:        1.2.156\r\n"
    b" nucleon-kcos:        2.14.2-49\r\n"
    b"\r\n"
    b" Welcome to KCOS shell. Type 'kcos help' in order to list the available commands.\r\n"
)

NON_KCOS_BANNER = (
    b"Welcome to Ubuntu 22.04.4 LTS (GNU/Linux 5.15.0-107-generic x86_64)\r\n"
    b"Last login: Sat May 17 10:00:00 2026 from 10.0.0.1\r\n"
)


def _mock_ssh_client(banner: bytes) -> MagicMock:
    """Return a mock paramiko.SSHClient that feeds *banner* from invoke_shell.

    Uses a closure-based side_effect so recv_ready() never raises StopIteration
    (a list-based side_effect would raise StopIteration when exhausted, which
    the probe's broad except-clause would catch and return None).
    """
    chan = MagicMock()
    _sent = [False]

    def recv_ready() -> bool:
        if not _sent[0]:
            _sent[0] = True
            return True
        return False

    chan.recv_ready.side_effect = recv_ready
    chan.recv.return_value = banner

    client = MagicMock()
    client.invoke_shell.return_value = chan
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_detects_kcos_and_parses_versions():
    with patch("paramiko.SSHClient", return_value=_mock_ssh_client(KCOS_BANNER)):
        result = probe_kcos("10.36.71.98", "admin", "secret", motd_wait=0.3)

    assert result == {"kcos_aresone": "1.2.156", "nucleon_kcos": "2.14.2-49"}


def test_returns_none_for_non_kcos_banner():
    with patch("paramiko.SSHClient", return_value=_mock_ssh_client(NON_KCOS_BANNER)):
        result = probe_kcos("10.0.0.1", "admin", "secret", motd_wait=0.3)

    assert result is None


def test_connection_error_returns_none_does_not_raise():
    client = MagicMock()
    client.connect.side_effect = OSError("Connection refused")
    with patch("paramiko.SSHClient", return_value=client):
        result = probe_kcos("10.0.0.1", "admin", "secret", motd_wait=0.3)

    assert result is None


def test_auth_error_returns_none_does_not_raise():
    import paramiko

    client = MagicMock()
    client.connect.side_effect = paramiko.AuthenticationException("Auth failed")
    with patch("paramiko.SSHClient", return_value=client):
        result = probe_kcos("10.0.0.1", "admin", "wrongpassword", motd_wait=0.3)

    assert result is None


def test_kcos_marker_without_version_strings_returns_unknown():
    """KCOS marker present but version fields missing → fallback to 'unknown'."""
    minimal_banner = b"Welcome to KCOS shell.\r\n"
    with patch("paramiko.SSHClient", return_value=_mock_ssh_client(minimal_banner)):
        result = probe_kcos("10.0.0.1", "admin", "secret", motd_wait=0.3)

    assert result == {"kcos_aresone": "unknown", "nucleon_kcos": "unknown"}


def test_paramiko_import_error_returns_none(monkeypatch):
    """If paramiko is not installed, probe returns None without raising."""
    import builtins
    real_import = builtins.__import__

    def _block_paramiko(name, *args, **kwargs):
        if name == "paramiko":
            raise ImportError("No module named 'paramiko'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_paramiko)
    result = probe_kcos("10.0.0.1", "admin", "secret", motd_wait=0.3)
    assert result is None
