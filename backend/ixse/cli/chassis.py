"""
Chassis commands: list.

CLI commands for querying chassis information via the REST API.
"""

import typer


chassis_app = typer.Typer(help="Chassis operations")


@chassis_app.command()
def list() -> None:
    """
    List all chassis with health status.
    """
    pass
