# Registers the TFS local narration worker as a Windows scheduled task that starts at logon (hidden, restarts on
# failure). Bryce chose this on 2026-11-24 ("I'll add an Avast exception").
#
# Before running:
#   1. The task runs the venv's BASE interpreter (pythonw.exe in the pyvenv.cfg home, C:\Python313) with -I, and
#      voice_worker.py loads the venv's packages itself. Avast exceptions exist for both pythonw.exe paths (2026-11-24).
#      Verified 2026-11-24 from a Terminal tab: the real log shows "voice worker started". Agent shells see Avast's
#      sandbox copy of C: files, so check the log from a Terminal tab, not from an agent's Bash/PowerShell tool.
#   2. Put the R2 values in this repo's .env (git-ignored): S3_ENDPOINT_URL, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY,
#      S3_BACKUP_BUCKET (the same values as the GitHub secrets). Never commit them.
#   3. Test once:  .venv\Scripts\python.exe tools\voice_worker.py --once   (log: %LOCALAPPDATA%\TFS\voice_worker.log)
#
# Run:    powershell -ExecutionPolicy Bypass -File tools\install_voice_worker.ps1
# Remove: Unregister-ScheduledTask -TaskName "TFS voice worker" -Confirm:$false
$repo = Split-Path -Parent $PSScriptRoot
$base = ((Get-Content (Join-Path $repo ".venv\pyvenv.cfg")) -match "^home\s*=") -replace "^home\s*=\s*", ""
$py = Join-Path $base.Trim() "pythonw.exe"
$worker = Join-Path $repo "tools\voice_worker.py"
if (-not (Test-Path $py)) { throw "Missing $py" }
if (-not (Select-String -Path (Join-Path $repo ".env") -Pattern "^S3_BACKUP_BUCKET=" -Quiet)) {
    throw "Add the R2 values to $repo\.env first (see the header of this script)."
}
$action = New-ScheduledTaskAction -Execute $py -Argument "-I `"$worker`"" -WorkingDirectory $repo
if (Get-ScheduledTask -TaskName "TFS voice worker" -ErrorAction SilentlyContinue) { Stop-ScheduledTask -TaskName "TFS voice worker" }
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName "TFS voice worker" -Action $action -Trigger $trigger -Settings $settings `
    -Description "TFS narration on the local GPU first (Modal fallback). Repo: $repo" -Force | Out-Null
Start-ScheduledTask -TaskName "TFS voice worker"
Write-Host "Registered and started 'TFS voice worker'. Log: $env:LOCALAPPDATA\TFS\voice_worker.log"
