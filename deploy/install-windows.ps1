param([string]$FridayDir = (Resolve-Path "$PSScriptRoot\.."))
$python = Join-Path $FridayDir '.venv\Scripts\python.exe'
if (!(Test-Path $python)) { throw "Create the venv first: py -m venv .venv; .venv\Scripts\pip install -r requirements.txt" }
$action = New-ScheduledTaskAction -Execute $python -Argument 'friday.py --serve --host 127.0.0.1 --port 8765' -WorkingDirectory $FridayDir
$trigger = New-ScheduledTaskTrigger -AtLogOn
Register-ScheduledTask -TaskName 'FRIDAY AI' -Action $action -Trigger $trigger -Description 'Always-on FRIDAY AI daemon' -Force
Write-Host 'FRIDAY installed. Start it with: Start-ScheduledTask -TaskName "FRIDAY AI"'
