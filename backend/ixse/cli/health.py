"""
Health commands: check.

CLI commands for fleet health monitoring via the REST API.
"""

import typer


health_app = typer.Typer(help="Health checks")


@health_app.command()
def check() -> None:
    """
    Check health of all IxNetwork servers and chassis.
    """
    pass
