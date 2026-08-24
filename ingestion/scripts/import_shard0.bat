@echo off
REM Launched daily at 01:00 by the "ChronosImportShard0" Windows Scheduled
REM Task (see ingestion/scripts/README.md). Covers civilizations at even
REM indexes of data/civilizations.yaml (index 0, 2, 4, ...) — includes
REM Assyria. Runs at the same time as import_shard1.bat (odd indexes,
REM includes Babylon), each in its own process with its own checkpoint DB,
REM so both keep Ollama's OLLAMA_NUM_PARALLEL slots busy. --continue: skip
REM civilizations already fully imported, resume the last interrupted one
REM automatically, start the next fresh one otherwise — safe to run nightly
REM forever, never redoes finished work.
cd /d "C:\Users\adema\OneDrive\Documentos\chronos\ingestion"
set INGESTION_CHECKPOINT_DB_PATH=.data\checkpoints_shard0.db
set LLM_CONCURRENCY=1
"C:\Users\adema\.local\bin\uv.exe" run python -m app.main ingest --all --continue --shard 0/2 >> logs\shard0.log 2>&1
