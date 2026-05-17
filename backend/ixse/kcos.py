"""KCOS platform detection via SSH banner (post-auth MOTD).

KCOS (Keysight Cloud OS) presents a distinctive welcome banner after SSH login:

    Welcome to KCOS shell. Type 'kcos help' in order to list the available commands.

The banner also includes kcos-aresone and nucleon-kcos version strings that are
not exposed via the IxNetwork HTTP API, making SSH the only detection path.
"""

from __future__ import annotations

import logging
import re
import time

log = logging.getLogger(__name__)

_KCOS_MARKER = "KCOS shell"
_RE_ARESONE = re.compile(r"kcos-aresone\s*:\s*(\S+)")
_RE_NUCLEON = re.compile(r"nucleon-kcos\s*:\s*(\S+)")


def probe_kcos(
    host: str,
    username: str,
    password: str,
    timeout: float = 10.0,
    motd_wait: float = 5.0,
) -> dict | None:
    """SSH into *host* and detect whether it is a KCOS platform.

    Captures the post-auth MOTD (interactive shell welcome banner) and checks
    for the KCOS marker string.  If detected, parses ``kcos-aresone`` and
    ``nucleon-kcos`` version strings from the banner.

    Parameters
    ----------
    host:
        Hostname or IP address.
    username / password:
        SSH credentials — same as the IxNetwork REST credentials in ServerEntry.
    timeout:
        TCP connect + auth timeout in seconds.
    motd_wait:
        How long to collect MOTD bytes after the shell opens, in seconds.

    Returns
    -------
    dict with keys ``kcos_aresone`` and ``nucleon_kcos`` if KCOS detected,
    or ``None`` if not KCOS or any connection / auth error occurs.

    Never raises — all exceptions are swallowed and logged at DEBUG level so
    a probe failure never disrupts the caller.
    """
    try:
        import paramiko
    except ImportError:
        log.warning("paramiko not installed; KCOS probe skipped for %s", host)
        return None

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            host,
            username=username,
            password=password,
            timeout=timeout,
            look_for_keys=False,
            allow_agent=False,
        )

        # Open an interactive shell so the server sends its MOTD.
        # paramiko.Transport.get_banner() returns the SSH protocol banner only
        # (e.g. "SSH-2.0-OpenSSH_8.9"), NOT the post-auth welcome message.
        chan = client.invoke_shell(width=220, height=50)
        chan.settimeout(2.0)

        chunks: list[str] = []
        deadline = time.monotonic() + motd_wait
        while time.monotonic() < deadline:
            if chan.recv_ready():
                data = chan.recv(4096)
                if not data:
                    break
                chunks.append(data.decode("utf-8", errors="replace"))
            else:
                time.sleep(0.1)
        chan.close()

        text = "".join(chunks)
        if _KCOS_MARKER not in text:
            return None

        aresone_m = _RE_ARESONE.search(text)
        nucleon_m = _RE_NUCLEON.search(text)
        return {
            "kcos_aresone": aresone_m.group(1) if aresone_m else "unknown",
            "nucleon_kcos": nucleon_m.group(1) if nucleon_m else "unknown",
        }

    except Exception as exc:  # noqa: BLE001
        log.debug("KCOS probe failed for %s: %s", host, exc)
        return None
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass
