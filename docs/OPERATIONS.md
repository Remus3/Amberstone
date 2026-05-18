# Riot Commander - Operations Reference

_Living document. Full ops command set for Legion sessions._

---

## Quick health check

```powershell
# Full health JSON
python -c "import json; print(json.dumps(json.loads(open(r'ops/runtime/health.json').read()), indent=2))"

# Log tail (today)
python -c "import time; from pathlib import Path; print(Path('logs/'+time.strftime('%Y-%m-%d')+'.log').read_text(encoding='utf-8',errors='replace')[-4000:])"
```

Via HTTP (dashboard must be up):
```
curl -k https://127.0.0.1:8888/api/health/all   # fleet health (RC + peers)
curl -k https://127.0.0.1:8888/api/state         # current game state
curl -k https://127.0.0.1:8888/metrics           # Prometheus counters
curl http://127.0.0.1:8889/health                # vision server health
```

---

## Restart RC

**Normal restart** (supervisor picks up within ~5s):
```
echo restart > restart_trigger.txt
```

**Verify:** read `ops/runtime/health.json` - confirm new `pid`, `alive=true`, `last_reload_ok=true`.

**Hard fallback** (if supervisor is also dead):
```powershell
taskkill /F /PID <pid>        # never Stop-Process - hangs MCP pipe
schtasks /Run /TN "RC-Supervisor"
```

**Do NOT use** `Stop-Process` or `restart.bat` from an interactive shell - use `taskkill /F /PID`.

---

## Scheduled tasks (Legion)

| Task | Trigger | Context | Description |
|---|---|---|---|
| `RC-Supervisor` | At logon | Administrator / HIGHEST | Runs `pythonw.exe ops/rc_supervisor.py` |
| `RC-VisionServer` | At system startup | SYSTEM / HIGHEST | Runs `python.exe moon_vision_server.py` |
| `RC-BridgeWatcher` | At logon | Administrator | Silent bridge poll daemon |
| `RC-DaemonSlayer` | Manual / on demand | Administrator | DS engine server |
| `RC-PatchRefresh` | Weekly Wednesday | Administrator | `data_pipeline.py all` |
| `RC-Phase3-Supervisor` | At logon | Administrator | Phase 3 agent supervisor |
| `RC-Phase3-PeriodicAudit` | Scheduled | Administrator | Phase 3 periodic audit |
| `RC-VerifyBridgeRoundtrip-Once` | Manual | Administrator | One-shot bridge smoke test |

Check state: `Get-ScheduledTask -TaskName "RC-*" | Select TaskName, State`

---

## Data pipeline (patch day)

```powershell
cd scripts
python data_pipeline.py all       # full refresh (items + builds + meta)
python data_pipeline.py meta      # meta only (faster)
python data_pipeline.py aram_builds
```

Run from `C:\Riot Commander\scripts\`. Patch releases typically Wednesdays - `RC-PatchRefresh` fires automatically.

---

## Vision server

```
curl http://127.0.0.1:8889/health
curl http://127.0.0.1:8889/latest-frame     # check if frames flowing
```

Vision token is in `config/vision_token.txt` (Legion) and `tools/vision_token.txt` (Game-PC). Rotate quarterly - next rotation ~2026-08-01.

---

## Bridge operations

Check pending escalations:
```
curl -k https://127.0.0.1:8888/api/bridge/pending
```

Watcher health:
```
curl -k https://127.0.0.1:8888/api/health/all    # peers block shows watcher_alive, queue_depth
```

Bridge cadence:
```
curl -k https://127.0.0.1:8888/api/bridge/cadence          # GET - current mode
curl -k -X POST https://127.0.0.1:8888/api/bridge/cadence  # POST - toggle active/sleep
```

Or use `/sleep` and `/wake` skills from the Claude session.

---

## TLS certificate

Dashboard cert: `tools/regen_rc_cert.ps1` (run elevated, restarts dashboard).

Game-PC's Riot CA: `install-cert.cmd` on Game-PC (admin-elevated). RC itself uses `verify=False`; browsers need it for port 2999.

---

## Python path

```
C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe
```

Use `pythonw.exe` for background daemons (no console window). Use `python.exe` for scripts that need stdout.

---

## Pre-flight before any restart

```powershell
# 1. py_compile all modified files
python -m py_compile <file.py>

# 2. Atomic write (don't hand-roll):
#    tmp.write_text(...); tmp.replace(target)
#    (atomic_write_json already retries WinError 5)

# 3. Coach prompt edits: batch all edits, then restart once
```

---

## Useful file locations

| Path | What it is |
|---|---|
| `ops/runtime/health.json` | Live PID + mode + alive flag |
| `ops/runtime/bridge_watcher_health.json` | Watcher daemon health |
| `ops/runtime/bridge_inbox_pending.json` | Escalation queue |
| `ops/runtime/bridge_log.jsonl` | Last 1000 bridge messages (persisted) |
| `data/{aram,arena,brawl,tft}_coaching_data.json` | Current game state per mode |
| `logs/YYYY-MM-DD.log` | Daily log (30-day retention) |
| `config/vision_token.txt` | Vision server auth token |
| `ops/local_paths.json` | Bridge secrets (gitignored) |
