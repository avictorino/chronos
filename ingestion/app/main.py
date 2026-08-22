"""CLI entrypoint.

    python -m app.main ingest --civilization sumer --dry-run
    python -m app.main ingest --civilization sumer
    python -m app.main ingest --all
    python -m app.main ingest --civilization sumer --resume <run_id>
    python -m app.main init-schema
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.config import get_settings
from app.persistence.postgres import PostgresConnection
from app.persistence.schema import ensure_schema
from app.services.civilization_service import load_civilizations
from app.services.ingestion_service import run_ingestion
from app.utils.logging import configure_logging, get_logger

log = get_logger("cli")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.main", description="Chronos ingestion CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="Run the ingestion pipeline")
    target = ingest.add_mutually_exclusive_group(required=True)
    target.add_argument("--civilization", help="Civilization id from data/civilizations.yaml")
    target.add_argument("--all", action="store_true", help="Ingest every civilization in data/civilizations.yaml")
    ingest.add_argument("--max-events", type=int, default=None)
    ingest.add_argument("--max-people", type=int, default=None)
    ingest.add_argument("--max-places", type=int, default=None)
    ingest.add_argument(
        "--depth", type=int, default=None, help="Reserved for future multi-hop expansion (not used in V1)"
    )
    ingest.add_argument("--dry-run", action="store_true", help="Call the LLM and print results, write nothing")
    ingest.add_argument("--resume", metavar="RUN_ID", default=None, help="Resume an interrupted run by its id")

    subparsers.add_parser("init-schema", help="Create Postgres extension/tables/indexes, then exit")

    return parser


def _print_dry_run_result(civilization_id: str, state: dict) -> None:
    print(
        json.dumps(
            {
                "civilization": civilization_id,
                "profile": state.get("profile"),
                "events": list(state.get("events", {}).values()),
                "entities": list(state.get("entities", {}).values()),
                "relationships": list(state.get("relationships", {}).values()),
                "claims": list(state.get("claims", {}).values()),
                "chunks": list(state.get("chunks", {}).values()),
                "errors": state.get("errors", []),
            },
            indent=2,
            default=str,
        )
    )


async def _cmd_ingest(args: argparse.Namespace) -> None:
    settings = get_settings()
    civilization_ids = [args.civilization] if args.civilization else [c.id for c in load_civilizations()]
    if args.resume and len(civilization_ids) > 1:
        raise SystemExit("--resume requires a single --civilization, not --all")

    failures: list[str] = []
    for civilization_id in civilization_ids:
        try:
            final_state = await run_ingestion(
                civilization_id,
                settings=settings,
                dry_run=args.dry_run,
                resume_run_id=args.resume,
                max_events=args.max_events,
                max_people=args.max_people,
                max_places=args.max_places,
            )
        except Exception as exc:  # noqa: BLE001 - one civilization's crash shouldn't stop --all
            failures.append(civilization_id)
            log.error("INGESTION", f"{civilization_id}: run crashed, continuing with the rest", error=str(exc))
            continue
        if args.dry_run:
            _print_dry_run_result(civilization_id, final_state)
        if final_state.get("errors"):
            log.warning("INGESTION", f"{civilization_id}: {len(final_state['errors'])} item(s) failed")

    if failures:
        log.error("INGESTION", f"{len(failures)} civilization(s) crashed entirely: {', '.join(failures)}")


async def _cmd_init_schema() -> None:
    settings = get_settings()
    conn = PostgresConnection(settings)
    await conn.verify_connectivity()
    await ensure_schema(conn)
    await conn.close()
    log.info("POSTGRES", "Schema initialized")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)

    if args.command == "ingest":
        asyncio.run(_cmd_ingest(args))
    elif args.command == "init-schema":
        asyncio.run(_cmd_init_schema())
    return 0


if __name__ == "__main__":
    sys.exit(main())
