@echo off
REM Part of a 4-way parallel split (see ingestion/scripts/README.md).
REM Covers civilizations at index i %% 4 == 1 — includes Babylon (index 1).
REM Runs alongside import_shard0.bat/2.bat/3.bat, each in its own process
REM with its own checkpoint DB, so all four keep Ollama's
REM OLLAMA_NUM_PARALLEL=4 slots busy. Being re-tested with qwen3.5:4b (much
REM smaller than the gemma4:12b used when 4-parallel first measured worse
REM than 2 — see README.md; if this regresses again, drop back to 3 or 2).
REM --continue: skip civilizations already fully imported, resume the last
REM interrupted one automatically, start the next fresh one otherwise.
cd /d "C:\Users\adema\OneDrive\Documentos\chronos\ingestion"
set INGESTION_CHECKPOINT_DB_PATH=.data\checkpoints_shard1.db
set LLM_CONCURRENCY=1
"C:\Users\adema\.local\bin\uv.exe" run python -m app.main ingest --all --continue --shard 1/4 >> logs\shard1.log 2>&1
