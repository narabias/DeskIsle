# Check admin
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
    exit
}

# Step 1: Remove VSCode.py ProgId from registry
Write-Host "Step 1: Removing VSCode.py ProgId..." -ForegroundColor Yellow
Remove-Item -Path 'HKCU:\Software\Classes\VSCode.py' -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -Path 'HKLM:\Software\Classes\VSCode.py' -Recurse -Force -ErrorAction SilentlyContinue

# Step 2: Use ftype to set system-level association
Write-Host "Step 2: Setting .py system association..." -ForegroundColor Yellow
$notepad = "$env:SystemRoot\notepad.exe"

# First create a custom ProgId for Notepad handling .py
New-Item -Path 'HKLM:\Software\Classes\PyEdit' -Force | Out-Null
Set-ItemProperty -Path 'HKLM:\Software\Classes\PyEdit' -Name '(default)' -Value 'Python Script'
New-Item -Path 'HKLM:\Software\Classes\PyEdit\shell\open\command' -Force | Out-Null
Set-ItemProperty -Path 'HKLM:\Software\Classes\PyEdit\shell\open\command' -Name '(default)' -Value "`"$notepad`" `"%1`""

# Step 3: Set .py and .pyw to use our ProgId via assoc/ftype
Write-Host "Step 3: Running assoc/ftype commands..." -ForegroundColor Yellow
cmd /c "assoc .py=PyEdit"
cmd /c "assoc .pyw=PyEdit"

# Step 4: Remove the UserChoice hash-protected key via PowerShell
Write-Host "Step 4: Removing UserChoice via reg command..." -ForegroundColor Yellow
cmd /c "reg delete `"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.py\UserChoice`" /f 2>nul"
cmd /c "reg delete `"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.pyw\UserChoice`" /f 2>nul"

# Step 5: Kill and restart Explorer to clear cache
Write-Host "Step 5: Restarting Explorer..." -ForegroundColor Yellow
Stop-Process -Name explorer -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

Write-Host ""
Write-Host "Done! Reboot and verify." -ForegroundColor Green
Write-Host ""
pause
