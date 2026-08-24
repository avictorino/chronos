@echo off
REM Part of a 4-way parallel split (see ingestion/scripts/README.md).
REM Covers civilizations at index i %% 4 == 1 of data/civilizations.yaml —
REM includes Babylon (index 1). Runs alongside import_shard0.bat/2.bat/3.bat
REM at the same time, each in its own process with its own checkpoint DB,
REM so all four keep Ollama's OLLAMA_NUM_PARALLEL=4 slots busy. --continue:
REM skip civilizations already fully imported, resume the last interrupted
REM one automatically, start the next fresh one otherwise — safe to run
REM repeatedly, never redoes finished work.
cd /d "C:\Users\adema\OneDrive\Documentos\chronos\ingestion"
set INGESTION_CHECKPOINT_DB_PATH=.data\checkpoints_shard1.db
set LLM_CONCURRENCY=1
"C:\Users\adema\.local\bin\uv.exe" run python -m app.main ingest --all --continue --shard 1/4 >> logs\shard1.log 2>&1
