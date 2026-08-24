# Scripts — full import (all 42 civilizations, 4 shards in parallel)

Imports every civilization in [`data/civilizations.yaml`](../data/civilizations.yaml)
as **four separate processes running at the same time**, each covering a
quarter of the list (`--shard 0/4`, `1/4`, `2/4`, `3/4` — index i modulo 4,
see `app/main.py::_parse_shard`), each with `LLM_CONCURRENCY=1` and its own
LangGraph checkpoint DB (`.data/checkpoints_shard0.db` .. `checkpoints_shard3.db`
— processes must never share one checkpoint file, or they can hit "database
is locked"). Sized to match `OLLAMA_NUM_PARALLEL=4` — if that's changed,
add/remove shards to match (see "Changing the shard count" below).

Running N shards concurrently keeps Ollama's parallel request slots busy
more consistently than fewer processes: several ingestion stages
(civilization profile, `discover_events`, `discover_people`,
`discover_places`, `discover_polities`) are a single LLM call, not a batch —
with fewer shards running, some slots sit idle during those; with one shard
per slot, another shard usually fills it. Diminishing returns apply once GPU
*compute* (not VRAM) saturates — check Task Manager's GPU "3D" utilization;
if it's already ~90%+ with fewer shards running, adding more won't help much.

All shards use `--continue`: for each civilization, skip it if already fully
imported, resume its last interrupted run automatically (no need to know the
run_id), or start fresh otherwise. Safe to invoke repeatedly, including
nightly forever — it only ever advances what's left, never redoes finished
work. Each civilization's own `importance_score` (0-10, see
`data/civilizations.yaml`) still controls how much of it gets ingested — see
`app/services/civilization_service.py::scaled_budgets`.

Assyria (index 0) and Babylon (index 1) are kept first in
`data/civilizations.yaml` specifically so shard0/shard1 reach them before
anything else.

## Running

```powershell
C:\Users\adema\OneDrive\Documentos\chronos\ingestion\scripts\import_shard0.bat
C:\Users\adema\OneDrive\Documentos\chronos\ingestion\scripts\import_shard1.bat
C:\Users\adema\OneDrive\Documentos\chronos\ingestion\scripts\import_shard2.bat
C:\Users\adema\OneDrive\Documentos\chronos\ingestion\scripts\import_shard3.bat
```

Each opens/runs in its own process — logs go to `ingestion/logs/shard0.log`
.. `shard3.log` (appended to, not rotated — trim/delete periodically if they
grow large). Run all four for the full parallel setup, or fewer if that's
all you want running (just make sure `OLLAMA_NUM_PARALLEL` covers however
many you run at once).

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

If `OLLAMA_NUM_PARALLEL` changes, the shard count should roughly match it.
To go from N to M shards, each `.bat` file just needs its `--shard I/N` and
`INGESTION_CHECKPOINT_DB_PATH` updated — but a civilization already
mid-import under the old split must have its checkpoint carried over to
whichever *new* shard file now owns it (index i %% M), or that civilization
looks "never started" and gets reset. For Assyria/Babylon this isn't an
issue as long as they stay at index 0/1 (any M still assigns them to
shard0/shard1) — for anything else with in-flight progress, copy its
`assyria:%`-style thread rows (see `app/main.py::_find_resumable_run_id`)
from the old checkpoint DB into the new one first.

## Scheduling it (optional)

Not currently scheduled — was set up once via Windows Task Scheduler
(`schtasks /create ... /sc daily /st 01:00`) and later removed in favor of
running manually. To recreate a nightly schedule, register each `.bat` as
its own task pointed at a fixed time, e.g.:

```powershell
schtasks /create /tn "ChronosImportShard0" /tr "C:\Users\adema\OneDrive\Documentos\chronos\ingestion\scripts\import_shard0.bat" /sc daily /st 01:00 /f
```
