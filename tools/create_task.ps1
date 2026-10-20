# Register a per-user logon task that starts DeskIsle from this checkout.
# Paths are derived from the script location, so nothing machine-specific is
# stored in the repository.
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
    exit
}

$taskName = "DeskIsle"
$workDir = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))

# Prefer a virtual environment, then the interpreter running this script.
$candidates = @(
    (Join-Path $workDir "venv\Scripts\pythonw.exe"),
    (Join-Path $workDir ".venv\Scripts\pythonw.exe")
)
$pyPath = $null
foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate) { $pyPath = $candidate; break }
}
if (-not $pyPath) {
    $pyPath = Join-Path (Split-Path -Parent (Get-Command python -ErrorAction Stop).Source) "pythonw.exe"
}
if (-not (Test-Path -LiteralPath $pyPath)) { throw "pythonw.exe not found: $pyPath" }

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction -Execute $pyPath -Argument "main.py" -WorkingDirectory $workDir
$trigger = New-ScheduledTaskTrigger -AtLogon
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 0)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force

Write-Host "Done" -ForegroundColor Green
