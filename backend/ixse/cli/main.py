"""
Typer CLI entrypoint: command routing and app initialization.

Provides the main command-line interface with subcommands for
server management, session operations, chassis info, and health checks.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import typer

from ixse.cli import state
from ixse.cli.chassis import chassis_app
from ixse.cli.health import health_app
from ixse.cli.sessions import sessions_app

app = typer.Typer(
    help="IxNetworkSessionExplorer CLI",
    no_args_is_help=True,
    add_completion=True,
)
app.add_typer(sessions_app, name="sessions")
app.add_typer(chassis_app, name="chassis")
app.add_typer(health_app, name="health")

_PID_FILE = Path("/tmp/ixse.pid")


@app.callback()
def main_callback(
    api_url: str = typer.Option(
        "http://localhost:8080",
        envvar="IXSE_API_URL",
        help="Base URL of the running ixse REST API",
    ),
) -> None:
    """IxNetworkSessionExplorer — session manager for IxNetwork lab environments."""
    state.api_url = api_url.rstrip("/")


@app.command()
def server(
    action: str = typer.Argument(..., help="start | stop"),
    port: int = typer.Option(8080, "--port", "-p", help="API server port"),
) -> None:
    """Start or stop the REST API server."""
    if action == "start":
        _start_server(port)
    elif action == "stop":
        _stop_server()
    else:
        typer.echo(
            typer.style(f"Unknown action: {action!r}. Use 'start' or 'stop'.", fg=typer.colors.RED),
            err=True,
        )
        raise typer.Exit(1)


def _start_server(port: int) -> None:
    cmd = [
        sys.executable, "-m", "uvicorn",
        "ixse.api.main:app",
        "--host", "0.0.0.0",
        "--port", str(port),
    ]

    typer.echo(f"Starting ixse API server on port {port}...")
    proc = subprocess.Popen(cmd)
    _PID_FILE.write_text(str(proc.pid))
    typer.echo(
        f"Server running (PID {proc.pid}). "
        f"Run 'ixse server stop' to terminate."
    )

    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()
    finally:
        _PID_FILE.unlink(missing_ok=True)


def _stop_server() -> None:
    if not _PID_FILE.exists():
        typer.echo(
            typer.style(
                "No ixse PID file found at /tmp/ixse.pid. Is the server running?",
                fg=typer.colors.YELLOW,
            ),
            err=True,
        )
        raise typer.Exit(1)

    pid = int(_PID_FILE.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        _PID_FILE.unlink(missing_ok=True)
        typer.echo(f"Sent SIGTERM to PID {pid}.")
    except ProcessLookupError:
        typer.echo(
            typer.style(f"PID {pid} not found. Server may have already stopped.", fg=typer.colors.YELLOW),
            err=True,
        )
        _PID_FILE.unlink(missing_ok=True)
        raise typer.Exit(1)


def main() -> None:
    """Main entry point for CLI."""
    app()


if __name__ == "__main__":
    main()
