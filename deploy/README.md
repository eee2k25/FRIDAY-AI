# Running FRIDAY continuously

FRIDAY binds to localhost by default. Put it behind an authenticated reverse proxy before exposing it publicly.

## Linux systemd

From the repository root, run the one-shot installer (creates `.venv`, installs
dependencies, creates `.env`, and installs the global `friday` command):

```sh
./setup.sh
```

Or do it by hand:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
mkdir -p logs
```

Copy `deploy/friday.service` to `~/.config/systemd/user/friday.service`, replace `friday-ai` in `WorkingDirectory` and `ExecStart` with the absolute checkout path, then:

```sh
systemctl --user daemon-reload
systemctl --user enable --now friday.service
curl http://127.0.0.1:8765/health
journalctl --user -u friday.service -f
```

Use `loginctl enable-linger "$USER"` if it must run without an interactive login. `deploy/watchdog.sh` can be run by cron to alert on failure; systemd normally restarts the process automatically.

## macOS launchd

Replace `__FRIDAY_DIR__` and `__PYTHON__` in `com.friday.ai.plist`, create the logs directory, copy it to `~/Library/LaunchAgents/`, then run:

```sh
launchctl load -w ~/Library/LaunchAgents/com.friday.ai.plist
curl http://127.0.0.1:8765/health
```

## Windows

**Preferred:** run the one-shot installer at the repository root — it self-elevates,
creates the venv, installs the global `friday` command, and registers both the
always-on daemon task and the daily "FRIDAY Maintenance" task with highest privileges:

```powershell
.\setup.ps1
```

Legacy daemon-only install (venv must already exist):

```powershell
.\deploy\install-windows.ps1
Start-ScheduledTask -TaskName "FRIDAY AI"
```

The task starts at login and restarts can be configured in Task Scheduler's **Settings** tab. The daemon writes its PID to `friday.pid` and removes it during clean shutdown.

## Authentication and network exposure

Set `FRIDAY_DAEMON_TOKEN` in `.env` to require `Authorization: Bearer <token>` for `/`, `/status`, and `/chat`. `/health` intentionally remains public for local watchdogs. Keep `--host 127.0.0.1` unless a firewall or reverse proxy protects the service.
