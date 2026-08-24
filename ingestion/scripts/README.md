# Scripts — nightly full import (all 42 civilizations, 2 shards in parallel)

Imports every civilization in [`data/civilizations.yaml`](../data/civilizations.yaml)
as **two separate processes running at the same time**, each covering half
the list (`--shard 0/2` = even indexes, `--shard 1/2` = odd indexes — see
`app/main.py::_parse_shard`), each with `LLM_CONCURRENCY=1` and its own
LangGraph checkpoint DB (`.data/checkpoints_shard0.db` /
`checkpoints_shard1.db` — two processes must never share one checkpoint
file, or they can hit "database is locked"). Running two shards concurrently
keeps both of Ollama's `OLLAMA_NUM_PARALLEL=2` slots busy more consistently
than one process alone: several ingestion stages (civilization profile,
`discover_events`, `discover_people`, `discover_places`, `discover_polities`)
are a single LLM call, not a batch — with only one shard running, the second
Ollama slot sits idle during those; with two shards running, the other one
usually fills it.

Both shards use `--continue`: for each civilization, skip it if already
fully imported, resume its last interrupted run automatically (no need to
know the run_id), or start fresh otherwise. Safe to invoke repeatedly,
including nightly forever — it only ever advances what's left, never redoes
finished work. Each civilization's own `importance_score` (0-10, see
`data/civilizations.yaml`) still controls how much of it gets ingested — see
`app/services/civilization_service.py::scaled_budgets`.

## Scheduled tasks (run daily at 01:00)

- `ChronosImportShard0` → `import_shard0.bat`
- `ChronosImportShard1` → `import_shard1.bat`

Logs: `ingestion/logs/shard0.log` / `ingestion/logs/shard1.log` (appended
to, not rotated — trim/delete periodically if they grow large).

To (re)create the tasks:

```powershell
schtasks /create /tn "ChronosImportShard0" /tr "C:\Users\adema\OneDrive\Documentos\chronos\ingestion\scripts\import_shard0.bat" /sc daily /st 01:00 /f
schtasks /create /tn "ChronosImportShard1" /tr "C:\Users\adema\OneDrive\Documentos\chronos\ingestion\scripts\import_shard1.bat" /sc daily /st 01:00 /f
```

To check them:

```powershell
schtasks /query /tn "ChronosImportShard0" /v /fo list
schtasks /query /tn "ChronosImportShard1" /v /fo list
```

To remove them entirely:

```powershell
schtasks /delete /tn "ChronosImportShard0" /f
schtasks /delete /tn "ChronosImportShard1" /f
```

## Stopping manually

Whenever you need the GPU back (before the next 01:00 run, or mid-run):

```powershell
powershell -File "C:\Users\adema\OneDrive\Documentos\chronos\ingestion\scripts\stop_import.ps1"
```

Safe at any point — LangGraph checkpoints after every completed graph node,
so at most the one item being processed at that instant is redone next time.
Nothing needs to be undone in Firestore; the next 01:00 run (or a manual
re-run of the `.bat` files) picks back up automatically via `--continue`.

## Running it right now instead of waiting for 01:00

```powershell
C:\Users\adema\OneDrive\Documentos\chronos\ingestion\scripts\import_shard0.bat
C:\Users\adema\OneDrive\Documentos\chronos\ingestion\scripts\import_shard1.bat
```

Each opens/runs in its own process — run both to get the two-shards-at-once
behavior described above, or just one if that's all you want running.
