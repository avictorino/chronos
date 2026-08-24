"""CLI entrypoint.

    python -m app.main ingest --civilization sumer --dry-run
    python -m app.main ingest --civilization sumer
    python -m app.main ingest --all --max-events 100 --max-people 200 --max-places 200
    python -m app.main ingest --civilization sumer --resume <run_id>
    python -m app.main ingest --all --force
    python -m app.main ingest --all --continue --shard 0/2   # run alongside --shard 1/2

`ingest --civilization X` always does a fresh re-import: any previous data
belonging only to X is deleted first (see
app/services/civilization_reset.py::reset_civilization) — *unless* `--resume`
is also passed, in which case the reset is skipped so the LangGraph
checkpoint can actually resume against the data already written, instead of
resuming into an emptied civilization. `ingest --all`
instead skips any civilization that already has a completed run recorded in
Firestore's `ingestion_runs` — which makes it resumable after a crash midway
through a batch — unless `--force` is passed, in which case every
civilization gets the same fresh-reimport treatment as a single
`--civilization` run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

from app.config import get_settings
from app.persistence.firestore import FirestoreConnection
from app.services.civilization_reset import civilization_already_imported, reset_civilization
from app.services.civilization_service import load_civilizations
from app.services.ingestion_service import run_ingestion
from app.utils.logging import configure_logging, get_logger

log = get_logger("cli")


def _find_resumable_run_id(civilization_id: str, checkpoint_db_path: Path) -> str | None:
    """Looks in the LangGraph SQLite checkpoint db for the most recently
    active run of this civilization (any thread_id prefixed
    f"{civilization_id}:") — used by `ingest --continue` to resume an
    interrupted run without the caller needing to know/type the exact
    run_id. Returns None if the checkpoint db doesn't exist yet, or has no
    thread for this civilization (i.e. it was never started)."""
    if not checkpoint_db_path.exists():
        return None
    conn = sqlite3.connect(str(checkpoint_db_path))
    try:
        # checkpoint_id is a monotonically-sortable id (langgraph uses a
        # UUID7-like scheme) — the globally latest one across every thread
        # for this civilization is its most recently active run.
        row = conn.execute(
            "SELECT thread_id FROM checkpoints WHERE thread_id LIKE ? ORDER BY checkpoint_id DESC LIMIT 1",
            (f"{civilization_id}:%",),
        ).fetchone()
    except sqlite3.OperationalError:
        return None  # no `checkpoints` table yet — nothing has ever run
    finally:
        conn.close()
    return row[0].split(":", 1)[1] if row else None


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
    ingest.add_argument("--max-polities", type=int, default=None)
    ingest.add_argument(
        "--depth",
        type=int,
        default=None,
        help="Max recursive expansion hops from the civilization root (overrides MAX_EXPANSION_DEPTH)",
    )
    ingest.add_argument("--dry-run", action="store_true", help="Call the LLM and print results, write nothing")
    ingest.add_argument("--resume", metavar="RUN_ID", default=None, help="Resume an interrupted run by its id")
    ingest.add_argument(
        "--force",
        action="store_true",
        help="With --all: re-import every civilization (fresh reset + reingest) instead of "
        "skipping the ones already completed. Ignored with --civilization, which always "
        "does a fresh re-import.",
    )
    ingest.add_argument(
        "--continue",
        dest="continue_run",
        action="store_true",
        help="For each target civilization: skip it if already fully imported, resume its "
        "most recent interrupted run if one exists (no need to know the run_id), or start "
        "fresh otherwise. No-op/safe to run repeatedly — meant for an unattended/scheduled "
        "re-invocation (e.g. a nightly task) that continues wherever the last one left off. "
        "Mutually exclusive with --resume/--force.",
    )
    ingest.add_argument(
        "--shard",
        metavar="I/N",
        default=None,
        help="With --all: only process civilizations at index i (mod N) of the full "
        "data/civilizations.yaml list — e.g. --shard 0/2 and --shard 1/2 run as two "
        "separate processes covering disjoint halves at the same time, so both keep "
        "Ollama's parallel request slots busy instead of one process idling between "
        "single-item stages (civilization profile, discover_events, ...). Ignored with "
        "--civilization.",
    )

    return parser


def _parse_shard(shard: str) -> tuple[int, int]:
    try:
        index_str, total_str = shard.split("/", 1)
        index, total = int(index_str), int(total_str)
    except ValueError:
        raise SystemExit(f"--shard must be I/N (e.g. 0/2), got {shard!r}") from None
    if total < 1 or not (0 <= index < total):
        raise SystemExit(f"--shard I/N needs 0 <= I < N, got {shard!r}")
    return index, total


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
    is_batch = not args.civilization
    civilization_ids = [args.civilization] if args.civilization else [c.id for c in load_civilizations()]
    if args.resume and len(civilization_ids) > 1:
        raise SystemExit("--resume requires a single --civilization, not --all")
    if args.continue_run and (args.resume or args.force):
        raise SystemExit("--continue is mutually exclusive with --resume/--force")
    if args.shard and is_batch:
        shard_index, shard_total = _parse_shard(args.shard)
        civilization_ids = [cid for i, cid in enumerate(civilization_ids) if i % shard_total == shard_index]
        log.info(
            "INGESTION",
            f"Shard {shard_index}/{shard_total}: {len(civilization_ids)} civilization(s)",
            civilizations=civilization_ids,
        )

    # Firestore connection used only for the reset-before-reimport (C1) and
    # skip-if-already-imported (C2) bookkeeping below — run_ingestion() opens
    # its own connection internally for the actual ingestion writes.
    reset_conn = FirestoreConnection(settings) if not args.dry_run else None
    if reset_conn is not None:
        await reset_conn.connect()

    try:
        failures: list[str] = []
        for civilization_id in civilization_ids:
            resume_run_id = args.resume
            if reset_conn is not None:
                if args.continue_run:
                    if await civilization_already_imported(reset_conn.db, civilization_id):
                        log.info("INGESTION", f"{civilization_id}: already imported, skipping")
                        continue
                    found_run_id = _find_resumable_run_id(civilization_id, settings.checkpoint_db_path)
                    if found_run_id:
                        resume_run_id = found_run_id
                        log.info("INGESTION", f"{civilization_id}: resuming existing run", run_id=found_run_id)
                    else:
                        await reset_civilization(reset_conn.db, civilization_id)
                elif not args.resume:
                    if is_batch and not args.force:
                        if await civilization_already_imported(reset_conn.db, civilization_id):
                            log.info("INGESTION", f"{civilization_id}: already imported, skipping")
                            continue
                    if not is_batch or args.force:
                        await reset_civilization(reset_conn.db, civilization_id)

            try:
                final_state = await run_ingestion(
                    civilization_id,
                    settings=settings,
                    dry_run=args.dry_run,
                    resume_run_id=resume_run_id,
                    max_events=args.max_events,
                    max_people=args.max_people,
                    max_places=args.max_places,
                    max_polities=args.max_polities,
                    max_depth=args.depth,
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
    finally:
        if reset_conn is not None:
            await reset_conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)

    if args.command == "ingest":
        asyncio.run(_cmd_ingest(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
