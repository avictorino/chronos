# Scripts — full import (all 42 civilizations, 2 shards in parallel)

Imports every civilization in [`data/civilizations.yaml`](../data/civilizations.yaml)
as **two separate processes running at the same time**, each covering half
the list (`--shard 0/2` = even indexes, `--shard 1/2` = odd indexes — see
`app/main.py::_parse_shard`), each with `LLM_CONCURRENCY=1` and its own
LangGraph checkpoint DB (`.data/checkpoints_shard0.db` /
`checkpoints_shard1.db` — two processes must never share one checkpoint
file, or they can hit "database is locked").

**Measured, not assumed: 2 is the sweet spot on this GPU (RTX 3080 Laptop,
16GB VRAM) for a 12B local model.** 4 shards (`OLLAMA_NUM_PARALLEL=4`) was
tested directly and performed *worse*, not better — GPU compute saturated
around 2 concurrent decode streams, so 4 streams competing for it dropped
per-item latency from ~20-40s to 5-6+ minutes, and aggregate throughput fell
to roughly a third of the 2-parallel rate (measured via Firestore write
counts over comparable windows). Match `OLLAMA_NUM_PARALLEL` to 2, not
higher, unless you've measured otherwise on different hardware.

Both shards use `--continue`: for each civilization, skip it if already
fully imported, resume its last interrupted run automatically (no need to
know the run_id), or start fresh otherwise. Safe to invoke repeatedly,
including nightly forever — it only ever advances what's left, never redoes
finished work. Each civilization's own `importance_score` (0-10, see
`data/civilizations.yaml`) still controls how much of it gets ingested — see
`app/services/civilization_service.py::scaled_budgets`.

Assyria (index 0) and Babylon (index 1) are kept first in
`data/civilizations.yaml` specifically so shard0/shard1 reach them before
anything else.

## Running

```powershell
C:\Users\adema\OneDrive\Documentos\chronos\ingestion\scripts\import_shard0.bat
C:\Users\adema\OneDrive\Documentos\chronos\ingestion\scripts\import_shard1.bat
```

Each opens/runs in its own process — logs go to `ingestion/logs/shard0.log` /
`shard1.log` (appended to, not rotated — trim/delete periodically if they
grow large). Requires `OLLAMA_NUM_PARALLEL=2` (Windows user env var — needs
a full Ollama restart, not just closing the window, to take effect).

## Stopping manually

Whenever you need the GPU back:

```powershell
powershell -File "C:\Users\adema\OneDrive\Documentos\chronos\ingestion\scripts\stop_import.ps1"
```

Safe at any point — LangGraph checkpoints after every completed graph node,
so at most the one item being processed at that instant is redone next time.
Nothing needs to be undone in Firestore; re-running the `.bat` files picks
back up automatically via `--continue`.

## Changing the shard count

If you do want to experiment with a different `OLLAMA_NUM_PARALLEL`, each
`.bat` file just needs its `--shard I/N` and `INGESTION_CHECKPOINT_DB_PATH`
updated to match the new N — but a civilization already mid-import under the
old split must have its checkpoint carried over to whichever *new* shard
file now owns it (index i %% new_N), or it looks "never started" and gets
reset. Copy its `<civilization_id>:%`-style thread rows (see
`app/main.py::_find_resumable_run_id`) from the old checkpoint DB into the
new one first — see the git history of this file for the exact migration
script used when this was tested at N=4.

## Scheduling it (optional)

Not currently scheduled. To set up a nightly run via Windows Task Scheduler:

```powershell
schtasks /create /tn "ChronosImportShard0" /tr "C:\Users\adema\OneDrive\Documentos\chronos\ingestion\scripts\import_shard0.bat" /sc daily /st 01:00 /f
schtasks /create /tn "ChronosImportShard1" /tr "C:\Users\adema\OneDrive\Documentos\chronos\ingestion\scripts\import_shard1.bat" /sc daily /st 01:00 /f
```
