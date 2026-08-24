@echo off
REM Part of a 4-way parallel split (see ingestion/scripts/README.md).
REM Covers civilizations at index i %% 4 == 3 of data/civilizations.yaml —
REM starts with Akkadian Empire (index 3). Runs alongside
REM import_shard0.bat/1.bat/2.bat at the same time, each in its own process
REM with its own checkpoint DB, so all four keep Ollama's
REM OLLAMA_NUM_PARALLEL=4 slots busy. --continue: skip civilizations already
REM fully imported, resume the last interrupted one automatically, start the
REM next fresh one otherwise — safe to run repeatedly, never redoes finished
REM work.
cd /d "C:\Users\adema\OneDrive\Documentos\chronos\ingestion"
set INGESTION_CHECKPOINT_DB_PATH=.data\checkpoints_shard3.db
set LLM_CONCURRENCY=1
"C:\Users\adema\.local\bin\uv.exe" run python -m app.main ingest --all --continue --shard 3/4 >> logs\shard3.log 2>&1
