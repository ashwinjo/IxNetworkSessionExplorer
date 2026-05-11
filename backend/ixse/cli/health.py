"""
Health commands: check.

CLI commands for fleet health monitoring via the REST API.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from ixse.cli import _api

health_app = typer.Typer(help="Health checks", no_args_is_help=True)
console = Console()


@health_app.command("check")
def check() -> None:
    """Check health of all IxNetwork servers and chassis."""
    data = _api.get("/health/")
    status = data.get("status", "unknown")
    timestamp = data.get("timestamp", "")

    color = "green" if status == "ok" else "red"
    console.print(f"\nFleet status: [{color}]{status}[/{color}]  [dim]{timestamp}[/dim]")

    servers = data.get("data", {}).get("servers", [])
    chassis = data.get("data", {}).get("chassis", [])

    if servers:
        table = Table(title="Servers")
        table.add_column("Name", style="cyan")
        table.add_column("Status")
        for s in servers:
            s_status = s.get("status", "unknown")
            s_color = "green" if s_status == "ok" else "red"
            table.add_row(s.get("name", ""), f"[{s_color}]{s_status}[/{s_color}]")
        console.print(table)

    if chassis:
        table = Table(title="Chassis")
        table.add_column("Name", style="cyan")
        table.add_column("Status")
        for c in chassis:
            c_status = c.get("status", "unknown")
            c_color = "green" if c_status == "ok" else "red"
            table.add_row(c.get("name", ""), f"[{c_color}]{c_status}[/{c_color}]")
        console.print(table)

    if not servers and not chassis:
        console.print("[dim]No server/chassis detail in health response.[/dim]")
