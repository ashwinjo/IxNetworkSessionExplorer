"""
Session commands: list, inspect, tag, untag, kill.

CLI commands for managing IxNetwork sessions via the REST API.
"""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from ixse.cli import _api

sessions_app = typer.Typer(help="Session operations", no_args_is_help=True)
console = Console()


@sessions_app.command("list")
def list_sessions(
    server: Optional[str] = typer.Option(None, "--server", "-s", help="Filter by IxNetwork server name"),
    tag: Optional[str] = typer.Option(None, "--tag", "-t", help="Filter by tag"),
) -> None:
    """List all sessions with optional filters."""
    params: dict = {}
    if server:
        params["server"] = server
    if tag:
        params["tag"] = tag

    data = _api.get("/sessions/", **params)
    servers = data.get("data", {}).get("servers", [])

    table = Table(title="IxNetwork Sessions", show_lines=False)
    table.add_column("Server", style="cyan", no_wrap=True)
    table.add_column("Session ID", style="dim", no_wrap=True)
    table.add_column("Name")
    table.add_column("User")
    table.add_column("Ports", justify="right")
    table.add_column("CP", justify="center")
    table.add_column("DP", justify="center")
    table.add_column("Utilized", justify="center")
    table.add_column("Tags")

    total = 0
    for srv in servers:
        srv_name = srv.get("name", "?")
        for sess in srv.get("sessions", []):
            utilized = sess.get("utilized", False)
            table.add_row(
                srv_name,
                sess.get("id", "?"),
                sess.get("name", ""),
                sess.get("username", ""),
                str(len(sess.get("ports", []))),
                "[green]✓[/green]" if sess.get("cp_active") else "[dim]·[/dim]",
                "[green]✓[/green]" if sess.get("dp_active") else "[dim]·[/dim]",
                "[green]yes[/green]" if utilized else "[dim]no[/dim]",
                ", ".join(sess.get("tags", [])) or "",
            )
            total += 1

    console.print(table)
    console.print(f"[dim]Total: {total} session(s) across {len(servers)} server(s)[/dim]")


@sessions_app.command("inspect")
def inspect(
    server: str = typer.Argument(..., help="IxNetwork server name"),
    session_id: str = typer.Argument(..., help="Session ID"),
) -> None:
    """Inspect a single session in detail."""
    data = _api.get(f"/sessions/{server}/{session_id}")
    sess = data.get("data", {})

    cp_str = "[green]active[/green]" if sess.get("cp_active") else "[dim]idle[/dim]"
    dp_str = "[green]active[/green]" if sess.get("dp_active") else "[dim]idle[/dim]"

    console.print()
    console.print(f"[bold cyan]Session:[/bold cyan]  {sess.get('name')} (ID: {sess.get('id')})")
    console.print(f"[bold]Server:[/bold]   {sess.get('ixnet_server')}")
    console.print(f"[bold]User:[/bold]     {sess.get('username') or '(none)'}")
    console.print(f"[bold]Tags:[/bold]     {', '.join(sess.get('tags', [])) or '(none)'}")
    console.print(f"[bold]Polled:[/bold]   {sess.get('last_polled', '')}")
    console.print(f"[bold]CP:[/bold] {cp_str}   [bold]DP:[/bold] {dp_str}")

    ports = sess.get("ports", [])
    if ports:
        console.print()
        ptable = Table(title=f"Ports ({len(ports)})", show_lines=False)
        ptable.add_column("Chassis", style="cyan")
        ptable.add_column("Card", justify="right")
        ptable.add_column("Port", justify="right")
        ptable.add_column("VPort Name")
        ptable.add_column("State")
        ptable.add_column("Speed (Mbps)", justify="right")
        ptable.add_column("CP", justify="center")
        ptable.add_column("LLDP Peer")

        for p in ports:
            lldp = p.get("lldp_peer") or {}
            lldp_str = (
                lldp.get("peer_system_name")
                or lldp.get("peer_chassis_id")
                or ""
            )
            speed = p.get("actual_speed", 0)
            ptable.add_row(
                p.get("chassis_name", ""),
                str(p.get("card", "")),
                str(p.get("port", "")),
                p.get("vport_name", ""),
                p.get("connection_state", ""),
                str(speed) if speed else "",
                "[green]✓[/green]" if p.get("cp_active") else "[dim]·[/dim]",
                lldp_str,
            )
        console.print(ptable)
    else:
        console.print("[dim]No ports assigned.[/dim]")


@sessions_app.command("tag")
def add_tag(
    server: str = typer.Argument(..., help="IxNetwork server name"),
    session_id: str = typer.Argument(..., help="Session ID"),
    tag_value: str = typer.Argument(..., metavar="TAG", help="Tag to add"),
) -> None:
    """Add a tag to a session."""
    data = _api.patch(
        f"/sessions/{server}/{session_id}/tags",
        {"add": [tag_value], "remove": []},
    )
    tags = data.get("data", {}).get("tags", [])
    typer.echo(f"Tags on {server}/{session_id}: {', '.join(tags) or '(none)'}")


@sessions_app.command("untag")
def remove_tag(
    server: str = typer.Argument(..., help="IxNetwork server name"),
    session_id: str = typer.Argument(..., help="Session ID"),
    tag_value: str = typer.Argument(..., metavar="TAG", help="Tag to remove"),
) -> None:
    """Remove a tag from a session."""
    data = _api.patch(
        f"/sessions/{server}/{session_id}/tags",
        {"add": [], "remove": [tag_value]},
    )
    tags = data.get("data", {}).get("tags", [])
    typer.echo(f"Tags on {server}/{session_id}: {', '.join(tags) or '(none)'}")


@sessions_app.command("kill")
def kill(
    server: str = typer.Argument(..., help="IxNetwork server name"),
    session_id: str = typer.Argument(..., help="Session ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
) -> None:
    """Destroy a session (irreversible)."""
    if not yes:
        confirmed = typer.confirm(
            f"Kill session {session_id!r} on server {server!r}? This cannot be undone."
        )
        if not confirmed:
            typer.echo("Aborted.")
            raise typer.Exit(0)

    data = _api.delete(f"/sessions/{server}/{session_id}", confirm="true")
    msg = data.get("data", {}).get("message", "Done.")
    typer.echo(typer.style(msg, fg=typer.colors.GREEN))
