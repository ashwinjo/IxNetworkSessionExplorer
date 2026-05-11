"""
Chassis commands: list.

CLI commands for querying chassis information via the REST API.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from ixse.cli import _api

chassis_app = typer.Typer(help="Chassis operations", no_args_is_help=True)
console = Console()


@chassis_app.command("list")
def list_chassis() -> None:
    """List all chassis with health status."""
    data = _api.get("/chassis/")
    chassis_list = data.get("data", {}).get("chassis", [])

    if not chassis_list:
        typer.echo("No chassis configured.")
        return

    table = Table(title="Chassis")
    table.add_column("Name", style="cyan")
    table.add_column("Host")
    table.add_column("Reachable", justify="center")
    table.add_column("Latency (ms)", justify="right")
    table.add_column("Ports In Use", justify="right")
    table.add_column("Last Checked")

    for c in chassis_list:
        reachable = c.get("reachable", False)
        latency = c.get("latency_ms")
        table.add_row(
            c.get("name", ""),
            c.get("host", ""),
            "[green]yes[/green]" if reachable else "[red]no[/red]",
            f"{latency:.1f}" if latency is not None else "",
            str(c.get("ports_in_use", 0)),
            c.get("last_checked", "") or "",
        )

    console.print(table)
