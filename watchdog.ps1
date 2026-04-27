# watchdog.ps1
# Monitors restart_trigger.txt. When Claude writes it, this script
# runs restart.bat and removes the trigger.
# Run once via:  run_watchdog.bat

$dir     = Split-Path -Parent $MyInvocation.MyCommand.Path
$trigger = Join-Path $dir "restart_trigger.txt"

Write-Host "[Watchdog] Monitoring $trigger"
Write-Host "[Watchdog] Running. Claude will auto-restart Riot Commander when needed."

while ($true) {
    if (Test-Path $trigger) {
        $reason = Get-Content $trigger -ErrorAction SilentlyContinue
        Write-Host "[Watchdog] Restart triggered: $reason"
        Remove-Item $trigger -Force
        & "$dir\restart.bat"
        Start-Sleep -Seconds 5
    }
    Start-Sleep -Seconds 1
}
