"""Thin HTTP wrapper for CLI → REST API calls."""

from __future__ import annotations

from typing import Any

import requests
import typer

from ixse.cli import state


def _base() -> str:
    return state.api_url.rstrip("/")


def _abort(msg: str) -> None:
    typer.echo(typer.style(f"Error: {msg}", fg=typer.colors.RED), err=True)
    raise typer.Exit(code=1)


def get(path: str, **params: Any) -> dict:
    url = f"{_base()}{path}"
    try:
        r = requests.get(url, params=params or None, timeout=15)
        r.raise_for_status()
        return r.json()
    except requests.ConnectionError:
        _abort(f"Cannot connect to {_base()}. Is the ixse server running?")
    except requests.HTTPError as exc:
        try:
            detail = exc.response.json().get("detail", exc.response.text)
        except Exception:
            detail = exc.response.text
        _abort(f"HTTP {exc.response.status_code}: {detail}")
    return {}  # unreachable


def patch(path: str, body: dict) -> dict:
    url = f"{_base()}{path}"
    try:
        r = requests.patch(url, json=body, timeout=15)
        r.raise_for_status()
        return r.json()
    except requests.ConnectionError:
        _abort(f"Cannot connect to {_base()}. Is the ixse server running?")
    except requests.HTTPError as exc:
        try:
            detail = exc.response.json().get("detail", exc.response.text)
        except Exception:
            detail = exc.response.text
        _abort(f"HTTP {exc.response.status_code}: {detail}")
    return {}


def delete(path: str, **params: Any) -> dict:
    url = f"{_base()}{path}"
    try:
        r = requests.delete(url, params=params or None, timeout=15)
        r.raise_for_status()
        return r.json()
    except requests.ConnectionError:
        _abort(f"Cannot connect to {_base()}. Is the ixse server running?")
    except requests.HTTPError as exc:
        try:
            detail = exc.response.json().get("detail", exc.response.text)
        except Exception:
            detail = exc.response.text
        _abort(f"HTTP {exc.response.status_code}: {detail}")
    return {}
