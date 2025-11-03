import os
import sys
import json
from typing import Any

import typer
import requests


app = typer.Typer(add_completion=False)


def _base_url() -> str:
    return os.environ.get("BACKEND_BASE_URL", "http://localhost:8000").rstrip("/")


def _print_json(obj: Any) -> None:
    sys.stdout.write(json.dumps(obj, indent=2) + "\n")
    sys.stdout.flush()


def _exit(code: int, message: str) -> None:
    sys.stderr.write(message.rstrip("\n") + "\n")
    sys.stderr.flush()
    raise typer.Exit(code)


@app.command("list")
def list_cmd() -> None:
    url = f"{_base_url()}/curricula"
    try:
        r = requests.get(url, headers={"Accept": "application/json"}, timeout=30)
    except requests.RequestException as e:
        _exit(1, f"Request failed: {e}")
    if r.status_code != 200:
        body = r.text
        try:
            body = json.dumps(r.json(), indent=2)
        except Exception:
            pass
        _exit(1, f"HTTP {r.status_code}: {body}")
    data = r.json()
    items = data.get("curricula") if isinstance(data, dict) else None
    if items is None:
        _exit(1, "Invalid response: missing 'curricula'")
    _print_json(items)


@app.command("create")
def create_cmd(name: str = typer.Option(..., "--name", help="Curriculum name")) -> None:
    url = f"{_base_url()}/curricula"
    try:
        r = requests.post(
            url,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json={"name": name},
            timeout=30,
        )
    except requests.RequestException as e:
        _exit(1, f"Request failed: {e}")
    if r.status_code in (200, 201):
        try:
            obj = r.json()
        except Exception:
            _exit(1, f"Invalid JSON response: {r.text}")
        _print_json(obj)
        return
    if r.status_code == 409:
        try:
            err = r.json()
            msg = err.get("error", {}).get("message") or "Duplicate"
        except Exception:
            msg = r.text or "Duplicate"
        _exit(2, f"409 DUPLICATE: {msg}")
    body = r.text
    try:
        body = json.dumps(r.json(), indent=2)
    except Exception:
        pass
    _exit(1, f"HTTP {r.status_code}: {body}")


@app.command("delete")
def delete_cmd(id: str = typer.Option(..., "--id", help="Curriculum UUID")) -> None:
    url = f"{_base_url()}/curricula/{id}"
    try:
        r = requests.delete(url, headers={"Accept": "application/json"}, timeout=30)
    except requests.RequestException as e:
        _exit(1, f"Request failed: {e}")
    if r.status_code in (200, 204):
        sys.stdout.write(json.dumps({"deleted": id}) + "\n")
        sys.stdout.flush()
        return
    if r.status_code == 404:
        _exit(3, f"404 NOT_FOUND: Curriculum not found: {id}")
    if r.status_code == 409:
        try:
            err = r.json()
            counts = err.get("error", {}).get("counts", {})
            _print_json({"error": "FORBIDDEN_DELETE", "counts": counts})
        except Exception:
            _exit(4, f"409 FORBIDDEN_DELETE: {r.text}")
        _exit(4, "409 FORBIDDEN_DELETE")
    body = r.text
    try:
        body = json.dumps(r.json(), indent=2)
    except Exception:
        pass
    _exit(1, f"HTTP {r.status_code}: {body}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
