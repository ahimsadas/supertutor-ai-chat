import os
import sys
import json
from typing import Any

import requests
import typer


app = typer.Typer(add_completion=False, no_args_is_help=True, help="Admin files CLI")


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
def list_files(
    curriculum_id: str = typer.Option(..., "--curriculum-id", help="Curriculum UUID"),
) -> None:
    url = f"{_base_url()}/files"
    try:
        r = requests.get(
            url,
            headers={"Accept": "application/json"},
            params={"curriculum_id": curriculum_id},
            timeout=30,
        )
    except requests.RequestException as e:
        _exit(3, f"{e}; is the backend running at BASE_URL: {_base_url()}?")

    if r.status_code == 200:
        try:
            obj = r.json()
        except Exception:
            sys.stdout.write((r.text or "").rstrip("\n") + "\n")
            sys.stdout.flush()
            return
        _print_json(obj)
        # Optional count line
        try:
            files = obj.get("files") if isinstance(obj, dict) else None
            if isinstance(files, list):
                sys.stdout.write(f"count={len(files)}\n")
                sys.stdout.flush()
        except Exception:
            pass
        return

    if r.status_code == 404:
        _exit(1, "files: GET /files 404 (curriculum not found)")

    body = r.text
    try:
        body = json.dumps(r.json(), indent=2)
    except Exception:
        pass
    _exit(3, f"HTTP {r.status_code} {body}")


@app.command("delete")
def delete_file(
    id: str = typer.Option(..., "--id", help="File UUID"),
) -> None:
    url = f"{_base_url()}/files/{id}"
    try:
        r = requests.delete(url, headers={"Accept": "application/json"}, timeout=30)
    except requests.RequestException as e:
        _exit(3, f"{e}; is the backend running at BASE_URL: {_base_url()}?")

    if r.status_code == 200:
        try:
            obj = r.json()
        except Exception:
            sys.stdout.write((r.text or "").rstrip("\n") + "\n")
            sys.stdout.flush()
            return
        _print_json(obj)
        # Optional deleted summary
        try:
            deleted = obj.get("deleted") if isinstance(obj, dict) else None
            if isinstance(deleted, dict):
                fid = deleted.get("file_id")
                chunks = deleted.get("chunks")
                sys.stdout.write(f"deleted file_id={fid} chunks={chunks}\n")
                sys.stdout.flush()
        except Exception:
            pass
        return

    if r.status_code == 404:
        _exit(1, f"files: DELETE /files/{{id}} 404 (file not found)")
    if r.status_code == 409:
        _exit(2, f"files: DELETE /files/{{id}} 409 (conflict)")

    body = r.text
    try:
        body = json.dumps(r.json(), indent=2)
    except Exception:
        pass
    _exit(3, f"HTTP {r.status_code} {body}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
