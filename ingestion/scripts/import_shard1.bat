@echo off
REM Runs half of data/civilizations.yaml (index i %% 2 == 1 — includes
REM Babylon at index 1 and Akkadian Empire at index 3). Runs alongside
REM import_shard0.bat at the same time, each in its own process with its
REM own checkpoint DB, so both keep Ollama's OLLAMA_NUM_PARALLEL=2 slots
REM busy (measured: this was the best-performing setup — 4 parallel
REM processes tested worse in practice, ~3x less aggregate throughput, see
REM ingestion/scripts/README.md). --continue: skip civilizations already
REM fully imported, resume the last interrupted one automatically, start
REM the next fresh one otherwise — safe to run repeatedly, never redoes
REM finished work.
cd /d "C:\Users\adema\OneDrive\Documentos\chronos\ingestion"
set INGESTION_CHECKPOINT_DB_PATH=.data\checkpoints_shard1.db
set LLM_CONCURRENCY=1
"C:\Users\adema\.local\bin\uv.exe" run python -m app.main ingest --all --continue --shard 1/2 >> logs\shard1.log 2>&1
