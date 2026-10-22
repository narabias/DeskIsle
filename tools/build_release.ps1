[CmdletBinding()]
param(
    [string]$Python = 'python',
    [string]$Iscc = '',
    [string]$OutputDir = '',
    [switch]$NoOpen,
    # Skips the unit tests (the self-test of the finished EXE always runs).
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$workRoot = Join-Path $projectRoot 'work\package'
$logRoot = Join-Path $workRoot 'logs'
if (-not $OutputDir) { $OutputDir = Join-Path $projectRoot 'dist\installer' }
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
$bundleRoot = Join-Path $workRoot 'dist'
$version = (Get-Content -LiteralPath (Join-Path $projectRoot 'VERSION') -Raw).Trim()
if ($version -notmatch '^\d+(\.\d+){1,3}$') { throw 'Invalid VERSION file.' }
New-Item -ItemType Directory -Force $logRoot, $OutputDir | Out-Null

# The in-app updater compares GitHub release tags with deskisle.__version__,
# so keep it in sync with VERSION (otherwise every build would offer itself
# as an update).
$initPath = Join-Path $projectRoot 'deskisle\__init__.py'
$initText = [IO.File]::ReadAllText($initPath)
$stampedText = [regex]::Replace($initText, '__version__\s*=\s*"[^"]*"', ('__version__ = "' + $version + '"'))
if ($stampedText -ne $initText) {
    [IO.File]::WriteAllText($initPath, $stampedText, (New-Object Text.UTF8Encoding($false)))
    Write-Host "[version] deskisle/__init__.py -> $version" -ForegroundColor Yellow
}

function Invoke-Checked {
    param([string]$Program, [string[]]$ArgumentList, [string]$Stage)
    $logPath = Join-Path $logRoot ($Stage + '.log')
    Write-Host "[$Stage] Running..." -ForegroundColor Cyan
    $savedPreference = $ErrorActionPreference
    try {
        # Native tools often write ordinary progress to stderr, especially in
        # Windows PowerShell 5.1. Judge success by the exit code, not the stream.
        $ErrorActionPreference = 'Continue'
        & $Program @ArgumentList *> $logPath
        $stageExit = $LASTEXITCODE
    } finally { $ErrorActionPreference = $savedPreference }
    if ($stageExit -ne 0) {
        Get-Content -LiteralPath $logPath -Tail 30 | Write-Host
        throw "$Stage failed ($stageExit). Log: $logPath"
    }
}

Push-Location $projectRoot
try {
    $pythonCommand = Get-Command $Python -ErrorAction Stop
    $Python = $pythonCommand.Source
    $savedPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    # Everything the 2.0 bundle needs: Qt Quick + Multimedia, the lunar calendar,
    # the WinRT projections (now playing, location), pywin32 and the build tools.
    $probe = 'import PySide6, PySide6.QtQuick, PySide6.QtMultimedia, PyInstaller, PIL, win32gui, pythoncom, ' +
             'lunar_python, winrt.windows.foundation.collections, winrt.windows.media.control, ' +
             'winrt.windows.storage.streams, winrt.windows.devices.geolocation'
    & $Python -c $probe 2>$null
    $dependencyExit = $LASTEXITCODE
    $ErrorActionPreference = $savedPreference
    if ($dependencyExit -ne 0) {
        Invoke-Checked $Python @('-m','pip','install','--disable-pip-version-check','-r','requirements.txt','-r','requirements-build.txt') 'dependencies'
    }

    if (-not $Iscc) {
        $compilerCandidates = @(
            (Join-Path $projectRoot '.tools\inno6\ISCC.exe'),
            (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
            (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
        )
        foreach ($candidate in $compilerCandidates) {
            if (Test-Path -LiteralPath $candidate) { $Iscc = $candidate; break }
        }
    }
    if (-not $Iscc) {
        Write-Host '[compiler] Downloading official portable Inno Setup 6.7.3...'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $compilerSetup = Join-Path $workRoot 'innosetup-6.7.3.exe'
        Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe' -OutFile $compilerSetup
        $signature = Get-AuthenticodeSignature -LiteralPath $compilerSetup
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Pyrsys B\.V\.') {
            throw 'Inno Setup publisher signature verification failed.'
        }
        $compilerDir = Join-Path $projectRoot '.tools\inno6'
        $compilerProcess = Start-Process -FilePath $compilerSetup -WindowStyle Hidden -PassThru -Wait -ArgumentList @(
            '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/CURRENTUSER','/PORTABLE=1','/NOICONS','/TASKS=',('/DIR="'+$compilerDir+'"')
        )
        if ($compilerProcess.ExitCode -ne 0) { throw 'Could not prepare Inno Setup.' }
        $Iscc = Join-Path $compilerDir 'ISCC.exe'
    }
    if (-not (Test-Path -LiteralPath $Iscc)) { throw "Compiler not found: $Iscc" }

    if ($SkipTests) {
        Write-Host '[tests] Skipped (-SkipTests).' -ForegroundColor Yellow
    } else {
        Invoke-Checked $Python @('-B','-m','unittest','discover','-s','tests','-v') 'tests'
    }
    Invoke-Checked $Python @('-B','tools\gen_guide.py','--check') 'guide'
    Invoke-Checked $Python @('-B','tools\make_app_icon.py') 'icon'
    Invoke-Checked $Python @('-B','-m','PyInstaller','packaging\DeskIsle.spec','--noconfirm','--clean','--distpath',$bundleRoot,'--workpath',(Join-Path $workRoot 'build')) 'bundle'

    Write-Host '[verify] Testing the actual EXE, CLI and native context menu...' -ForegroundColor Cyan
    $exePath = Join-Path $bundleRoot 'DeskIsle\DeskIsle.exe'
    foreach ($required in @('DeskIsle.exe', 'deskisle-cli.exe', 'DeskIsleShellMenu.exe',
                            '_internal\deskisle\qml\Layer.qml', '_internal\deskisle\qml\glyphs.js',
                            '_internal\deskisle\agent\GUIDE.md', '_internal\CHANGELOG.md')) {
        if (-not (Test-Path -LiteralPath (Join-Path $bundleRoot ('DeskIsle\' + $required)))) {
            throw "The bundle is incomplete: $required is missing."
        }
    }
    $reportPath = Join-Path $logRoot 'exe-check.json'
    $testProcess = Start-Process -FilePath $exePath -WindowStyle Hidden -PassThru -ArgumentList @('--self-test',('"'+$reportPath+'"'))
    # Starts the whole Qt Quick app offscreen, compiles every QML file, opens all
    # settings pages and talks to the agent pipe - give slow machines time.
    if (-not $testProcess.WaitForExit(180000)) {
        $testProcess.Kill()
        throw 'EXE self-test timed out. No installer was produced.'
    }
    if ($testProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $reportPath)) {
        throw "EXE self-test failed. Report: $reportPath"
    }
    $report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
    if ($report.status -ne 'passed') { throw "EXE self-test failed: $($report.error)" }

    Invoke-Checked $Iscc @(('/DAppVersion='+$version),('/DBuildDir='+(Join-Path $bundleRoot 'DeskIsle')),('/DOutputDir='+$OutputDir),'packaging\installer.iss') 'installer'
    $setupPath = Join-Path $OutputDir ("DeskIsle-Setup-$version-x64.exe")
    if (-not (Test-Path -LiteralPath $setupPath)) { throw 'Installer output is missing.' }
    $digest = (Get-FileHash -Algorithm SHA256 -LiteralPath $setupPath).Hash
    [IO.File]::WriteAllText(($setupPath+'.sha256'), ($digest+'  '+[IO.Path]::GetFileName($setupPath)+[Environment]::NewLine))
    Write-Host "SUCCESS: $setupPath" -ForegroundColor Green
    Write-Host "Logs: $logRoot"
    if (-not $NoOpen) { Start-Process explorer.exe -ArgumentList ('"'+$OutputDir+'"') }
} finally { Pop-Location }
