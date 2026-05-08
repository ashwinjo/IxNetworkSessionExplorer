"""
Unit tests for ixse/config.py — TDD-first.

Tests cover:
1. Valid config loads correctly
2. Env var interpolation works
3. Missing env var raises ConfigError with useful message
4. Missing required field (no servers) raises ConfigError
5. Malformed YAML raises ConfigError
6. File not found raises ConfigError
"""

import os
import textwrap
from pathlib import Path

import pytest

# ConfigError and load_config are the two public contracts under test.
from ixse.config import ConfigError, load_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(tmp_path: Path, content: str) -> Path:
    """Write a YAML string to a temp file and return its path."""
    cfg = tmp_path / "ixse_config.yaml"
    cfg.write_text(textwrap.dedent(content))
    return cfg


# ---------------------------------------------------------------------------
# 1. Valid config loads correctly (no env vars, literal passwords)
# ---------------------------------------------------------------------------

class TestValidConfig:
    def test_basic_load(self, tmp_path: Path) -> None:
        cfg_file = _write_yaml(tmp_path, """
            poller:
              interval_seconds: 30
            ixnet_servers:
              - name: ixnet-server-01
                host: 10.1.1.100
                username: admin
                password: s3cr3t
        """)

        cfg = load_config(cfg_file)

        assert cfg.poller.interval_seconds == 30
        assert len(cfg.ixnet_servers) == 1
        server = cfg.ixnet_servers[0]
        assert server.name == "ixnet-server-01"
        assert server.host == "10.1.1.100"
        assert server.username == "admin"
        assert server.password == "s3cr3t"

    def test_multiple_servers(self, tmp_path: Path) -> None:
        cfg_file = _write_yaml(tmp_path, """
            poller:
              interval_seconds: 60
            ixnet_servers:
              - name: srv-01
                host: 10.1.1.1
                username: admin
                password: pass1
              - name: srv-02
                host: 10.1.1.2
                username: admin
                password: pass2
        """)

        cfg = load_config(cfg_file)
        assert len(cfg.ixnet_servers) == 2
        assert cfg.ixnet_servers[0].name == "srv-01"
        assert cfg.ixnet_servers[1].name == "srv-02"

    def test_default_poll_interval(self, tmp_path: Path) -> None:
        """PollerConfig.interval_seconds defaults to 60 when poller block absent."""
        cfg_file = _write_yaml(tmp_path, """
            ixnet_servers:
              - name: srv-01
                host: 10.1.1.1
                username: admin
                password: pass1
        """)

        cfg = load_config(cfg_file)
        assert cfg.poller.interval_seconds == 60

    def test_accepts_path_string(self, tmp_path: Path) -> None:
        """load_config accepts both str and Path."""
        cfg_file = _write_yaml(tmp_path, """
            ixnet_servers:
              - name: srv-01
                host: 10.1.1.1
                username: admin
                password: pass1
        """)

        cfg = load_config(str(cfg_file))
        assert cfg.ixnet_servers[0].name == "srv-01"


# ---------------------------------------------------------------------------
# 2. Env var interpolation works
# ---------------------------------------------------------------------------

class TestEnvVarInterpolation:
    def test_single_env_var(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("IXNET_PASSWORD", "resolved_secret")
        cfg_file = _write_yaml(tmp_path, """
            ixnet_servers:
              - name: srv-01
                host: 10.1.1.1
                username: admin
                password: ${IXNET_PASSWORD}
        """)

        cfg = load_config(cfg_file)
        assert cfg.ixnet_servers[0].password == "resolved_secret"

    def test_multiple_env_vars_same_field(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Two ${VAR} references in the same value are both resolved."""
        monkeypatch.setenv("HOST_PREFIX", "10.1")
        monkeypatch.setenv("HOST_SUFFIX", "1.100")
        cfg_file = _write_yaml(tmp_path, """
            ixnet_servers:
              - name: srv-01
                host: ${HOST_PREFIX}.${HOST_SUFFIX}
                username: admin
                password: pass
        """)

        cfg = load_config(cfg_file)
        assert cfg.ixnet_servers[0].host == "10.1.1.100"

    def test_env_var_in_different_fields(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("IXNET_USER", "netadmin")
        monkeypatch.setenv("IXNET_PASS", "topsecret")
        cfg_file = _write_yaml(tmp_path, """
            ixnet_servers:
              - name: srv-01
                host: 10.1.1.1
                username: ${IXNET_USER}
                password: ${IXNET_PASS}
        """)

        cfg = load_config(cfg_file)
        assert cfg.ixnet_servers[0].username == "netadmin"
        assert cfg.ixnet_servers[0].password == "topsecret"

    def test_env_var_across_multiple_servers(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHARED_PASS", "shared_secret")
        cfg_file = _write_yaml(tmp_path, """
            ixnet_servers:
              - name: srv-01
                host: 10.1.1.1
                username: admin
                password: ${SHARED_PASS}
              - name: srv-02
                host: 10.1.1.2
                username: admin
                password: ${SHARED_PASS}
        """)

        cfg = load_config(cfg_file)
        assert cfg.ixnet_servers[0].password == "shared_secret"
        assert cfg.ixnet_servers[1].password == "shared_secret"

    def test_non_interpolated_values_are_untouched(self, tmp_path: Path) -> None:
        """Literal strings without ${} markers pass through unchanged."""
        cfg_file = _write_yaml(tmp_path, """
            ixnet_servers:
              - name: srv-01
                host: 192.168.1.1
                username: plain_user
                password: plain_pass
        """)

        cfg = load_config(cfg_file)
        assert cfg.ixnet_servers[0].username == "plain_user"
        assert cfg.ixnet_servers[0].password == "plain_pass"


# ---------------------------------------------------------------------------
# 3. Missing env var raises ConfigError with useful message
# ---------------------------------------------------------------------------

class TestMissingEnvVar:
    def test_missing_env_var_raises_config_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("IXNET_PASSWORD", raising=False)
        cfg_file = _write_yaml(tmp_path, """
            ixnet_servers:
              - name: srv-01
                host: 10.1.1.1
                username: admin
                password: ${IXNET_PASSWORD}
        """)

        with pytest.raises(ConfigError) as exc_info:
            load_config(cfg_file)

        error_msg = str(exc_info.value)
        # Must identify the missing variable
        assert "IXNET_PASSWORD" in error_msg

    def test_missing_env_var_message_is_actionable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Error message should tell the operator what to do."""
        monkeypatch.delenv("MY_SECRET_VAR", raising=False)
        cfg_file = _write_yaml(tmp_path, """
            ixnet_servers:
              - name: srv-01
                host: 10.1.1.1
                username: admin
                password: ${MY_SECRET_VAR}
        """)

        with pytest.raises(ConfigError) as exc_info:
            load_config(cfg_file)

        error_msg = str(exc_info.value)
        assert "MY_SECRET_VAR" in error_msg
        # Should include the config file path for context
        assert str(cfg_file) in error_msg

    def test_multiple_missing_env_vars_raises_on_first(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fail fast: first missing var triggers ConfigError immediately."""
        monkeypatch.delenv("VAR_A", raising=False)
        monkeypatch.delenv("VAR_B", raising=False)
        cfg_file = _write_yaml(tmp_path, """
            ixnet_servers:
              - name: srv-01
                host: 10.1.1.1
                username: ${VAR_A}
                password: ${VAR_B}
        """)

        with pytest.raises(ConfigError):
            load_config(cfg_file)

    def test_invalid_var_name_syntax_raises_config_error(self, tmp_path: Path) -> None:
        """${...} with invalid variable name (lowercase, spaces, special chars) raises ConfigError."""
        cfg_file = _write_yaml(tmp_path, """
            ixnet_servers:
              - name: srv-01
                host: 10.1.1.1
                username: admin
                password: ${ MY_VAR }
        """)

        with pytest.raises(ConfigError) as exc_info:
            load_config(cfg_file)

        error_msg = str(exc_info.value)
        assert "Invalid environment variable syntax" in error_msg
        assert "[A-Z_][A-Z0-9_]*" in error_msg

    def test_lowercase_var_name_raises_config_error(self, tmp_path: Path) -> None:
        """${lowercase_var} does not match the strict pattern and raises ConfigError."""
        cfg_file = _write_yaml(tmp_path, """
            ixnet_servers:
              - name: srv-01
                host: 10.1.1.1
                username: admin
                password: ${ixnet_password}
        """)

        with pytest.raises(ConfigError) as exc_info:
            load_config(cfg_file)

        assert "Invalid environment variable syntax" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 4. Missing required field raises ConfigError
# ---------------------------------------------------------------------------

class TestMissingRequiredFields:
    def test_empty_servers_list_raises(self, tmp_path: Path) -> None:
        cfg_file = _write_yaml(tmp_path, """
            ixnet_servers: []
        """)

        with pytest.raises(ConfigError) as exc_info:
            load_config(cfg_file)

        assert "ixnet_servers" in str(exc_info.value).lower() or "server" in str(exc_info.value).lower()

    def test_missing_servers_key_raises(self, tmp_path: Path) -> None:
        cfg_file = _write_yaml(tmp_path, """
            poller:
              interval_seconds: 30
        """)

        with pytest.raises(ConfigError):
            load_config(cfg_file)

    def test_server_missing_name_raises(self, tmp_path: Path) -> None:
        cfg_file = _write_yaml(tmp_path, """
            ixnet_servers:
              - host: 10.1.1.1
                username: admin
                password: secret
        """)

        with pytest.raises(ConfigError):
            load_config(cfg_file)

    def test_server_missing_host_raises(self, tmp_path: Path) -> None:
        cfg_file = _write_yaml(tmp_path, """
            ixnet_servers:
              - name: srv-01
                username: admin
                password: secret
        """)

        with pytest.raises(ConfigError):
            load_config(cfg_file)

    def test_server_missing_username_raises(self, tmp_path: Path) -> None:
        cfg_file = _write_yaml(tmp_path, """
            ixnet_servers:
              - name: srv-01
                host: 10.1.1.1
                password: secret
        """)

        with pytest.raises(ConfigError):
            load_config(cfg_file)

    def test_server_missing_password_raises(self, tmp_path: Path) -> None:
        cfg_file = _write_yaml(tmp_path, """
            ixnet_servers:
              - name: srv-01
                host: 10.1.1.1
                username: admin
        """)

        with pytest.raises(ConfigError):
            load_config(cfg_file)

    def test_config_error_includes_file_path(self, tmp_path: Path) -> None:
        """ValidationError message must include the config file path."""
        cfg_file = _write_yaml(tmp_path, """
            ixnet_servers: []
        """)

        with pytest.raises(ConfigError) as exc_info:
            load_config(cfg_file)

        assert str(cfg_file) in str(exc_info.value)


# ---------------------------------------------------------------------------
# 5. Malformed YAML raises ConfigError
# ---------------------------------------------------------------------------

class TestMalformedYaml:
    def test_invalid_yaml_syntax_raises(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "bad.yaml"
        cfg_file.write_text("ixnet_servers:\n  - name: [unclosed bracket\n    host: 10.1.1.1\n")

        with pytest.raises(ConfigError) as exc_info:
            load_config(cfg_file)

        assert str(cfg_file) in str(exc_info.value)

    def test_yaml_with_tabs_raises(self, tmp_path: Path) -> None:
        """YAML does not allow tab indentation."""
        cfg_file = tmp_path / "tabs.yaml"
        # Write raw bytes to embed actual tab characters
        cfg_file.write_bytes(b"ixnet_servers:\n\t- name: srv\n\t  host: 10.1.1.1\n")

        with pytest.raises(ConfigError):
            load_config(cfg_file)

    def test_empty_file_raises(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "empty.yaml"
        cfg_file.write_text("")

        with pytest.raises(ConfigError):
            load_config(cfg_file)

    def test_yaml_is_not_dict_raises(self, tmp_path: Path) -> None:
        """YAML that parses to a list (not a dict) is invalid."""
        cfg_file = _write_yaml(tmp_path, """
            - item1
            - item2
        """)

        with pytest.raises(ConfigError):
            load_config(cfg_file)


# ---------------------------------------------------------------------------
# 6. File not found raises ConfigError
# ---------------------------------------------------------------------------

class TestFileNotFound:
    def test_nonexistent_file_raises_config_error(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist.yaml"

        with pytest.raises(ConfigError) as exc_info:
            load_config(missing)

        error_msg = str(exc_info.value)
        assert str(missing) in error_msg

    def test_nonexistent_file_raises_config_error_not_os_error(self, tmp_path: Path) -> None:
        """ConfigError, not raw OSError/FileNotFoundError, must be raised."""
        missing = tmp_path / "ghost.yaml"

        with pytest.raises(ConfigError):
            load_config(missing)

    def test_config_error_is_exception_subclass(self) -> None:
        """ConfigError must inherit from Exception."""
        assert issubclass(ConfigError, Exception)

    def test_path_as_string(self, tmp_path: Path) -> None:
        missing = str(tmp_path / "also_missing.yaml")

        with pytest.raises(ConfigError):
            load_config(missing)
