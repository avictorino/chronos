# Stops every shard ingestion process (however started — manually via the
# import_shard*.bat files, or a scheduled task), so you can reclaim the
# GPU/Ollama for other work. Safe to run any time: LangGraph checkpoints
# after every completed graph node, so at most the in-flight item's call is
# lost — the next run picks back up from there via --continue. See README.md.

$procs = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*app.main ingest*--shard*"
}

if (-not $procs) {
    Write-Host "No running ingestion process found."
    exit 0
}

foreach ($p in $procs) {
    Write-Host "Stopping PID $($p.ProcessId): $($p.CommandLine)"
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}

Write-Host "Stopped. Resume any time with:"
Write-Host "  ingestion\scripts\import_shard0.bat"
Write-Host "  ingestion\scripts\import_shard1.bat"
Write-Host "  ingestion\scripts\import_shard2.bat"
Write-Host "  ingestion\scripts\import_shard3.bat"
