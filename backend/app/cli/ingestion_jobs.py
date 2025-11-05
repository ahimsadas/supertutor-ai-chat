import sys
import json
import logging
from typing import Optional, Any

import typer
from app.core.config import settings_log_summary

from app.ingestion.runner import run_pending_jobs


app = typer.Typer(add_completion=False, no_args_is_help=True, help="Ingestion job runner")

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _is_uuid(s: str) -> bool:
    import uuid
    try:
        uuid.UUID(s)
        return True
    except Exception:
        return False



@app.callback()
def _root() -> None:
    pass


@app.command("run")
def run(
    curriculum_id: Optional[str] = typer.Option(None, "--curriculum-id", help="Filter by curriculum UUID"),
    file_id: Optional[str] = typer.Option(None, "--file-id", help="Process a specific file UUID"),
    limit: int = typer.Option(10, "--limit", help="Max recent files to scan"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Do not process; just list and validate"),
) -> None:
    try:
        logger.info("ingestion_jobs.settings %s", settings_log_summary(["FILES_INGEST_MAX_MB"]))
    except Exception:
        pass
    if curriculum_id and not _is_uuid(curriculum_id):
        logger.error("Invalid UUID for --curriculum-id: %s", curriculum_id)
        raise typer.Exit(1)
    if file_id and not _is_uuid(file_id):
        logger.error("Invalid UUID for --file-id: %s", file_id)
        raise typer.Exit(1)
    if limit <= 0:
        logger.error("--limit must be > 0")
        raise typer.Exit(1)

    try:
        summary = run_pending_jobs(
            curriculum_id=curriculum_id,
            only_file_id=file_id,
            limit=limit,
            dry_run=dry_run,
        )
    except Exception as e:
        logger.error("Runner error: %s", e)
        raise typer.Exit(1)

    typer.echo(json.dumps(summary, indent=2))
    raise typer.Exit(code=1 if int(summary.get("errors", 0)) > 0 else 0)


def main_cli() -> None:
    app()


if __name__ == "__main__":
    main_cli()
