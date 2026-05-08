#!/usr/bin/env python3
"""
Standalone LLDP probe: connects to all configured IxNetwork servers,
fetches LLDP neighbor info for every assigned port, and prints a table.

Usage:
    python lldp_probe.py [--config ixse_config.yaml] [--server <name>]

Run from the backend/ directory with the virtual environment active.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running without installing the package
sys.path.insert(0, str(Path(__file__).parent))

from ixse.client import RestPyClient, fetch_lldp_map, _parse_location_str  # noqa: E402
from ixse.config import load_config  # noqa: E402
from ixse.models import LldpPeerInfo  # noqa: E402


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

_COL_W = {
    "server": 20,
    "session": 30,
    "port": 20,
    "system": 30,
    "chassis_id": 20,
    "port_id": 20,
    "ip": 16,
    "description": 35,
}


def _hdr() -> str:
    return (
        f"{'Server':<{_COL_W['server']}} "
        f"{'Session':<{_COL_W['session']}} "
        f"{'Port (chassis;c;p)':<{_COL_W['port']}} "
        f"{'Peer System':<{_COL_W['system']}} "
        f"{'Peer ChassisID':<{_COL_W['chassis_id']}} "
        f"{'Peer PortID':<{_COL_W['port_id']}} "
        f"{'Peer IP':<{_COL_W['ip']}} "
        f"{'Peer Description':<{_COL_W['description']}}"
    )


def _row(
    server: str,
    session: str,
    port_label: str,
    lldp: LldpPeerInfo | None,
) -> str:
    if lldp is None or not lldp.has_peer:
        peer_system = "(no LLDP)"
        chassis_id = port_id = ip = desc = ""
    else:
        peer_system = lldp.peer_system_name
        chassis_id  = lldp.peer_chassis_id
        port_id     = lldp.peer_port_id
        ip          = lldp.peer_ip_address
        desc        = lldp.peer_description

    return (
        f"{server:<{_COL_W['server']}} "
        f"{session:<{_COL_W['session']}} "
        f"{port_label:<{_COL_W['port']}} "
        f"{peer_system:<{_COL_W['system']}} "
        f"{chassis_id:<{_COL_W['chassis_id']}} "
        f"{port_id:<{_COL_W['port_id']}} "
        f"{ip:<{_COL_W['ip']}} "
        f"{desc:<{_COL_W['description']}}"
    )


def _sep() -> str:
    return "-" * (sum(_COL_W.values()) + len(_COL_W) - 1)


# ---------------------------------------------------------------------------
# Main probe logic
# ---------------------------------------------------------------------------


def probe_server(server_name: str, host: str, username: str, password: str, rest_port: int | None) -> None:
    """Connect to one IxNetwork server and print LLDP info for all session ports."""
    print(f"\n{'='*70}")
    print(f"  Server: {server_name}  ({host})")
    print(f"{'='*70}")

    client = RestPyClient(host, username, password, rest_port)
    try:
        client.connect()
    except Exception as exc:
        print(f"  ERROR: Could not connect — {exc}")
        return

    try:
        raw_sessions = client.get_raw_sessions()
        if not raw_sessions:
            print("  (no sessions found)")
            return

        print(_hdr())
        print(_sep())

        for raw_sess in raw_sessions:
            sess_id   = str(raw_sess.Id)
            sess_name = str(raw_sess.Name)
            label     = f"{sess_name} [{sess_id}]"

            # Fetch LLDP map for this session
            try:
                lldp_map = fetch_lldp_map(raw_sess.Ixnetwork)
            except Exception as exc:
                print(f"  WARNING: LLDP fetch failed for session {sess_id}: {exc}")
                lldp_map = {}

            # Fetch vports to list assigned ports
            try:
                vports = raw_sess.Ixnetwork.Vport.find()
            except Exception as exc:
                print(f"  WARNING: Vport fetch failed for session {sess_id}: {exc}")
                continue

            if not vports:
                print(_row(server_name, label, "(no ports)", None))
                continue

            for vp in vports:
                location_str = str(getattr(vp, "Location",   "") or "")
                assigned_str = str(getattr(vp, "AssignedTo", "") or "")
                parsed = _parse_location_str(location_str) or _parse_location_str(assigned_str)

                if parsed is None:
                    port_label = location_str or assigned_str or "(unassigned)"
                    print(_row(server_name, label, port_label, None))
                    continue

                chassis_ip, card, port_num = parsed
                port_label = f"{chassis_ip};{card};{port_num}"
                lldp = lldp_map.get((chassis_ip, card, port_num))
                print(_row(server_name, label, port_label, lldp))

    finally:
        client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="LLDP probe for IxNetwork sessions")
    parser.add_argument(
        "--config",
        default="ixse_config.yaml",
        help="Path to ixse_config.yaml (default: ixse_config.yaml)",
    )
    parser.add_argument(
        "--server",
        default=None,
        help="Only probe this server name (default: all configured servers)",
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
    except Exception as exc:
        print(f"ERROR: Could not load config '{args.config}': {exc}", file=sys.stderr)
        sys.exit(1)

    servers = config.ixnet_servers
    if args.server:
        servers = [s for s in servers if s.name == args.server]
        if not servers:
            print(f"ERROR: No server named '{args.server}' in config.", file=sys.stderr)
            sys.exit(1)

    for srv in servers:
        probe_server(
            server_name=srv.name,
            host=srv.host,
            username=srv.username,
            password=srv.password,
            rest_port=srv.rest_port,
        )

    print()


if __name__ == "__main__":
    main()
