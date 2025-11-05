import sys
import json
import hashlib
import uuid
import mimetypes
from typing import Any, List, Tuple
from pathlib import Path
from contextlib import ExitStack

import typer
import requests
import logging

from app.core.config import get_settings, settings_log_summary


app = typer.Typer(add_completion=False, no_args_is_help=True, help="Admin ingestion CLI")

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger("supertutor.cli.ingest")


def _base_url() -> str:
    s = get_settings()
    return (getattr(s, "BACKEND_BASE_URL", "http://localhost:8000") or "http://localhost:8000").rstrip("/")


def _is_allowed_ext(path: Path) -> bool:
    return path.suffix.lower() in {".pdf", ".txt"}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _filesize(path: Path) -> int:
    return path.stat().st_size


def _mb_to_bytes(mb: int) -> int:
    return int(mb) * 1024 * 1024


def _print_json(obj: Any) -> None:
    sys.stdout.write(json.dumps(obj, indent=2) + "\n")
    sys.stdout.flush()


def _exit(code: int, message: str) -> None:
    sys.stderr.write(message.rstrip("\n") + "\n")
    sys.stderr.flush()
    raise typer.Exit(code)


def _is_uuid(s: str) -> bool:
    try:
        uuid.UUID(s)
        return True
    except Exception:
        return False


def _mime_type(path: Path) -> str:
    mt, _ = mimetypes.guess_type(str(path))
    if mt:
        return mt
    suf = path.suffix.lower()
    if suf == ".txt":
        return "text/plain"
    if suf == ".pdf":
        return "application/pdf"
    return "application/octet-stream"


def _upload_cap_bytes_from_settings() -> int | None:
    """Return router-aligned upload cap in bytes for optional CLI preflight.

    Mirrors FILES_UPLOAD_MAX_MB semantics: None => no cap.
    """
    s = get_settings()
    up_mb = getattr(s, "FILES_UPLOAD_MAX_MB", None)
    if up_mb is None:
        return None
    try:
        mb = float(up_mb)
    except Exception:
        return None
    if mb <= 0:
        return None
    return int(mb * 1024 * 1024)


@app.command("upload")
def upload(
    curriculum_id: str = typer.Option(
        ..., "--curriculum-id", help="UUID of the curriculum"
    ),
    files: List[Path] = typer.Argument(
        ..., exists=False, dir_okay=False, readable=True,
        help="One or more local file paths (.pdf/.txt)"
    ),
) -> None:
    try:
        logger.info("cli.ingest.settings %s", settings_log_summary(["FILES_UPLOAD_MAX_MB", "FILES_INGEST_MAX_MB"]))
    except Exception:
        pass
    if not _is_uuid(curriculum_id):
        _exit(1, f"Invalid UUID: {curriculum_id}")
    cap_bytes = _upload_cap_bytes_from_settings()
    # Workaround: drop any stray 'upload' tokens that are not files (some shells/Typer edge-cases)
    files = [p for p in files if not (p.name == "upload" and not p.is_file())]
    to_send: List[Tuple[Path, str, str, str, int]] = []
    had_missing = False

    for p in files:
        p = Path(p)
        if not p.exists() or not p.is_file():
            sys.stderr.write(f"skip upload: not found or not a file -> {p}\n")
            sys.stderr.flush()
            had_missing = True
            continue
        if not _is_allowed_ext(p):
            sys.stderr.write(f"skip {p.name}: extension not allowed; only .pdf and .txt\n")
            sys.stderr.flush()
            continue
        try:
            size = _filesize(p)
        except Exception as e:
            sys.stderr.write(f"skip {p.name}: cannot read file: {e}\n")
            sys.stderr.flush()
            continue
        if cap_bytes is not None and size > cap_bytes:
            sys.stderr.write(f"skip {p.name}: size {size} exceeds cap {cap_bytes}\n")
            sys.stderr.flush()
            continue
        try:
            sha = _sha256_file(p)
        except Exception as e:
            sys.stderr.write(f"skip {p.name}: cannot read file: {e}\n")
            sys.stderr.flush()
            continue

        sys.stdout.write(f"sending {p.name} size={size} sha256={sha}\n")
        sys.stdout.flush()
        to_send.append((p, p.name, _mime_type(p), sha, size))

    if not to_send:
        _exit(5, "No files to upload: all files failed preflight")

    url = f"{_base_url()}/files:ingest"

    with ExitStack() as stack:
        files_param = []
        for p, base, mime, sha, size in to_send:
            fobj = stack.enter_context(open(p, "rb"))
            files_param.append(("files", (base, fobj, mime)))
        try:
            r = requests.post(
                url,
                headers={"Accept": "application/json"},
                data={"curriculum_id": curriculum_id},
                files=files_param,
                timeout=60,
            )
        except requests.RequestException as e:
            _exit(1, f"Request failed: {e}")

    if r.status_code in (200, 201):
        try:
            obj = r.json()
            _print_json(obj)
        except Exception:
            sys.stdout.write((r.text or "").rstrip("\n") + "\n")
            sys.stdout.flush()
        if had_missing:
            _exit(6, "One or more input files were missing or not regular files")
        return

    if r.status_code == 404:
        _exit(1, f"/files:ingest not mounted at BASE_URL: {_base_url()} (HTTP 404)")
    body = r.text
    try:
        body = json.dumps(r.json(), indent=2)
    except Exception:
        pass
    _exit(1, f"HTTP {r.status_code}: {body}")


@app.command("version")
def version() -> None:
    sys.stdout.write("ingest CLI 0.1.0\n")
    sys.stdout.flush()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
