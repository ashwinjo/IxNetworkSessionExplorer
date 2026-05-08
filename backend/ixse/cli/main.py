"""
Typer CLI entrypoint: command routing and app initialization.

Provides the main command-line interface with subcommands for
server management, session operations, chassis info, and health checks.
"""

import typer
from typing import Optional


app = typer.Typer(help="IxNetworkSessionExplorer CLI")


@app.command()
def server(
    action: str = typer.Argument(..., help="start or stop"),
    config: Optional[str] = typer.Option(None, help="Path to ixse_config.yaml"),
    port: int = typer.Option(8080, help="API server port"),
) -> None:
    """
    Start or stop the REST API server.

    Args:
        action: "start" or "stop"
        config: Path to configuration file
        port: REST API port (default 8080)
    """
    pass


def main():
    """Main entry point for CLI."""
    app()


if __name__ == "__main__":
    main()
