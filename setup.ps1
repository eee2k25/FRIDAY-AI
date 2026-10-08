<#
.SYNOPSIS
    FRIDAY AI — one-shot Windows installer.

.DESCRIPTION
    Run this once (double-click setup.bat, or right-click > Run with PowerShell).
    It self-elevates (asks for admin permission ONE time, at setup) and then:

      1. Finds Python 3.10+, creates .venv, installs all requirements
      2. Creates .env from .env.example and (optionally) asks for your API key
      3. Installs a global `friday` command on your PATH
         -> type  friday  in ANY PowerShell / CMD window and she starts
      4. Registers "FRIDAY AI" scheduled task (daemon at logon, admin level,
         no UAC prompts ever again)
      5. Registers "FRIDAY Maintenance" scheduled task — daily system
         performance check + cleanup, runs automatically with admin rights
      6. Runs a first maintenance pass so you start with a clean machine

    Uninstall everything it added:   .\setup.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [switch]$Uninstall,
    [switch]$NoDaemon,          # skip the always-on daemon task
    [string]$MaintenanceTime = '10:00'
)

$ErrorActionPreference = 'Stop'
$FridayDir = $PSScriptRoot
if (-not $FridayDir) { $FridayDir = (Get-Location).Path }

$BinDir     = Join-Path $env:LOCALAPPDATA 'FRIDAY\bin'
$Shim       = Join-Path $BinDir 'friday.cmd'
$VenvPython = Join-Path $FridayDir '.venv\Scripts\python.exe'
$TaskDaemon = 'FRIDAY AI'
$TaskMaint  = 'FRIDAY Maintenance'

function Write-Step([string]$msg)  { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok  ([string]$msg)  { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Warn2([string]$msg) { Write-Host "    [!] $msg" -ForegroundColor Yellow }

# ------------------------------------------------------------- elevation ---
$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $IsAdmin) {
    Write-Host 'FRIDAY setup needs administrator rights (one time only) to:' -ForegroundColor Yellow
    Write-Host '  - register her scheduled tasks with highest privileges'
    Write-Host '  - let daily maintenance clean system temp files and caches'
    Write-Host 'Approving the next UAC prompt grants this once, at setup.' -ForegroundColor Yellow
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$($MyInvocation.MyCommand.Path)`"")
    if ($Uninstall) { $argList += '-Uninstall' }
    if ($NoDaemon)  { $argList += '-NoDaemon' }
    $argList += @('-MaintenanceTime', $MaintenanceTime)
    Start-Process -FilePath 'powershell.exe' -ArgumentList $argList -Verb RunAs
    exit
}

# ------------------------------------------------------------- uninstall ---
if ($Uninstall) {
    Write-Step 'Uninstalling FRIDAY integration (code and venv are kept)'
    foreach ($t in @($TaskDaemon, $TaskMaint)) {
        if (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $t -Confirm:$false
            Write-Ok "removed scheduled task '$t'"
        }
    }
    if (Test-Path $Shim) { Remove-Item $Shim -Force; Write-Ok 'removed friday command' }
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ($userPath -and ($userPath -split ';' -contains $BinDir)) {
        $newPath = ($userPath -split ';' | Where-Object { $_ -and $_ -ne $BinDir }) -join ';'
        [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
        Write-Ok 'removed FRIDAY from PATH'
    }
    Write-Host "`nFRIDAY uninstalled. Delete the folder to remove her completely." -ForegroundColor Green
    Read-Host 'Press Enter to close'
    exit
}

Write-Host ''
Write-Host '  ============================================' -ForegroundColor Cyan
Write-Host '     F.R.I.D.A.Y  —  automatic setup'            -ForegroundColor Cyan
Write-Host '  ============================================' -ForegroundColor Cyan
Write-Host "  Install dir : $FridayDir"
Write-Host "  Running as  : administrator"

# ---------------------------------------------------------------- python ---
Write-Step 'Checking Python 3.10+'
$python = $null
foreach ($candidate in @('py -3', 'python', 'python3')) {
    try {
        $v = Invoke-Expression "$candidate -c `"import sys; print('%d.%d' % sys.version_info[:2])`"" 2>$null
        if ($v -and ([version]$v -ge [version]'3.10')) { $python = $candidate; break }
    } catch { }
}
if (-not $python) {
    Write-Warn2 'Python 3.10+ not found — trying to install it via winget...'
    try {
        winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                    [Environment]::GetEnvironmentVariable('Path', 'User')
        $python = 'py -3'
    } catch {
        throw 'Could not install Python automatically. Install Python 3.10+ from python.org and re-run setup.'
    }
}
Write-Ok "using: $python"

# ------------------------------------------------------------------ venv ---
Write-Step 'Creating virtual environment and installing dependencies'
if (-not (Test-Path $VenvPython)) {
    Invoke-Expression "$python -m venv `"$FridayDir\.venv`""
}
& $VenvPython -m pip install --upgrade pip --quiet
& $VenvPython -m pip install -r (Join-Path $FridayDir 'requirements.txt') --quiet
if ($LASTEXITCODE -ne 0) { throw 'pip install failed — check your internet connection and re-run setup.' }
Write-Ok 'all Python dependencies installed'

Write-Step 'Verifying Python dependencies import cleanly'
$depCheck = "import google.genai, groq, rich, docx, openpyxl, pptx, pdfplumber, sympy, pint, ddgs"
& $VenvPython -c $depCheck 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Warn2 'some dependencies failed to import — reinstalling requirements once more...'
    & $VenvPython -m pip install -r (Join-Path $FridayDir 'requirements.txt')
    & $VenvPython -c $depCheck 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw 'dependency verification failed — run ".venv\Scripts\pip install -r requirements.txt" manually and read the errors.'
    }
}
Write-Ok 'all core dependencies import cleanly'

# ------------------------------------------------------------------- .env ---
Write-Step 'Configuring .env'
$envFile = Join-Path $FridayDir '.env'
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $FridayDir '.env.example') $envFile
    Write-Ok '.env created from .env.example'
    $key = Read-Host '    Paste your GEMINI_API_KEY (Enter to skip, you can add it later in .env)'
    if ($key) {
        (Get-Content $envFile) -replace '^\s*#?\s*GEMINI_API_KEY\s*=.*$', "GEMINI_API_KEY=$key" |
            Set-Content $envFile -Encoding UTF8
        if (-not (Select-String -Path $envFile -Pattern '^GEMINI_API_KEY=' -Quiet)) {
            Add-Content $envFile "GEMINI_API_KEY=$key"
        }
        Write-Ok 'API key saved'
    }
} else {
    Write-Ok '.env already exists — keeping your settings'
}
New-Item -ItemType Directory -Force -Path (Join-Path $FridayDir 'logs')   | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $FridayDir 'memory') | Out-Null

# ------------------------------------------- global `friday` command -------
Write-Step "Installing the global 'friday' command"
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
@"
@echo off
rem FRIDAY AI global launcher - generated by setup.ps1
"$VenvPython" "$FridayDir\friday.py" %*
"@ | Set-Content $Shim -Encoding ASCII

$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not ($userPath -split ';' -contains $BinDir)) {
    [Environment]::SetEnvironmentVariable('Path', "$userPath;$BinDir", 'User')
}
$env:Path += ";$BinDir"
Write-Ok "type 'friday' in any NEW PowerShell or CMD window to start her"

# ----------------------------------------------- scheduled task: daemon ----
if (-not $NoDaemon) {
    Write-Step "Registering '$TaskDaemon' (always-on daemon, admin level, starts at logon)"
    $action   = New-ScheduledTaskAction -Execute $VenvPython `
                  -Argument 'friday.py --serve --host 127.0.0.1 --port 8765' `
                  -WorkingDirectory $FridayDir
    $trigger  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                  -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
                  -ExecutionTimeLimit (New-TimeSpan -Days 3650)
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
    Register-ScheduledTask -TaskName $TaskDaemon -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal `
        -Description 'Always-on FRIDAY AI daemon (installed by setup.ps1)' -Force | Out-Null
    Write-Ok 'daemon runs elevated automatically — no more UAC prompts'
}

# ------------------------------------------ scheduled task: maintenance ----
Write-Step "Registering '$TaskMaint' (daily at $MaintenanceTime, admin level)"
$mAction   = New-ScheduledTaskAction -Execute $VenvPython `
               -Argument 'friday.py --maintain' -WorkingDirectory $FridayDir
$mTrigger  = New-ScheduledTaskTrigger -Daily -At $MaintenanceTime
$mSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
               -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$mPrincipal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName $TaskMaint -Action $mAction -Trigger $mTrigger `
    -Settings $mSettings -Principal $mPrincipal `
    -Description 'FRIDAY daily system performance check and maintenance (installed by setup.ps1)' -Force | Out-Null
Write-Ok "daily tune-up every day at $MaintenanceTime (catches up if the PC was off)"

# -------------------------------------------------- first maintenance ------
Write-Step 'Running the first system performance check and maintenance pass'
try {
    & $VenvPython (Join-Path $FridayDir 'friday.py') --maintain
} catch {
    Write-Warn2 "first maintenance pass reported an issue: $_"
}

# ----------------------------------------------------------------- done ----
if (-not $NoDaemon) {
    try { Start-ScheduledTask -TaskName $TaskDaemon } catch { }
}
Write-Host ''
Write-Host '  ============================================' -ForegroundColor Green
Write-Host '   FRIDAY is installed and fully set up.'       -ForegroundColor Green
Write-Host '  ============================================' -ForegroundColor Green
Write-Host ''
Write-Host '   Open a NEW PowerShell window and type:' -ForegroundColor White
Write-Host ''
Write-Host '       friday' -ForegroundColor Cyan
Write-Host ''
Write-Host "   - She starts instantly, from any folder."
Write-Host "   - She already has admin-level scheduled tasks: no UAC nagging."
Write-Host "   - '$TaskMaint' tunes your PC every day at $MaintenanceTime."
Write-Host "   - Ask her any time:  'check system performance'  or  'run maintenance'."
Write-Host ''
Read-Host 'Press Enter to close'
