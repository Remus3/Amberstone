# RC Lean - Budget-Saver Mode

Live League coaching dashboard. Reads Riot Live Client API, serves :8888 HTTPS.
1-PC Legion (ADR-011). Scheduler is asyncio; no tkinter.

## Paths

- Project root: `C:\Riot Commander\`
- Python: `C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe`
- API key: `C:\Riot Commander\API-Key-Claude.txt` (gitignored)
- Health: `C:\Riot Commander\ops\runtime\health.json`
- Logs: `C:\Riot Commander\logs\YYYY-MM-DD.log`

## Hard rules

- **py_compile before restart.** Syntax errors crash silently under pythonw.exe.
- **Atomic writes only:** `tmp.write_text(...); tmp.replace(target)`.
- **Never Stop-Process.** Use `taskkill /F /PID`.
- **Commit messages:** use `git commit -F <tmpfile>` (Write file, ASCII-only).
- **Restart via `restart_trigger.txt`** (write any content; supervisor clears + restarts ~5s).
- **No em-dashes or en-dashes - ever.** ASCII only. No smart quotes.
- **Frozen files** (do not modify): `main.py`, `core/log_setup.py`, `core/moon_proxy.py`,
  `lcu/lcu_client.py`, `core/game_snapshot.py`, `ops/rc_dev_runtime.py`, `ops/rc_supervisor.py`,
  `app/__init__.py`, `app/_loop.py`, `app/_health_monitor.py`, `app/_remediation.py`,
  `app/_state_authority.py`, `app/_overlay_manager.py`, `app/_game_lifecycle.py`,
  `tools/diagnose.md`, `tools/caveman.md`.

## Topology

| Machine | Tailnet / IP | Role |
|---|---|---|
| **Legion** | `legion-rc` / `100.70.22.55` | 1-PC: runs League + RC + supervisor + vision + dashboard |

## Filesystem rules

- `agents/` - sub-agents (daemon_slayer engine, coaches, LCU agent)
- `web/` - dashboard frontend (served by web_dashboard.py, ADR-008 auto-reload)
- `core/` - shared Python modules
- `tools/` - scripts (hotkey_listener.py, start_daemon_slayer.py)
- `docs/` - architecture, operations, ADRs, specs
- `ops/` - runtime, supervisor, budget_saver
- `data/` - JSON coaching data, DDragon, daemon_slayer snapshots
- `Share/` - lolmath mirror (DS engine, docs, tests)

## Style

- Python: dataclasses, type hints, no tkinter, asyncio for scheduling
- JavaScript (web/): ES modules, idempotent renderers, design tokens in CSS
- Tests: TDD first (write failing test, then implement). DS tests in `agents/daemon_slayer/tests/`,
  RC tests in `tests/`. Use pytest.
- py_compile check before restart.
- Ruff/lint clean before commit.

## Useful commands

```
# RC health
curl -k https://127.0.0.1:8888/api/health/all

# Restart RC
echo restart > restart_trigger.txt

# DS health
curl http://127.0.0.1:8893/health

# Restart DS
taskkill /F /PID <pid>
pythonw "C:\Riot Commander\tools\start_daemon_slayer.py"

# Run DS tests
python -m pytest agents/daemon_slayer/tests/ -q

# Run RC tests
python -m pytest tests/ -q

# git
git log --oneline -15
git status
```

## Budget-saver context

This is a lean CLAUDE.md for local-model sessions. Full context is in `CLAUDE.md`,
`docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, and memory files. Use those for deep
reference; this file keeps the local 8B model from drowning in 150+ memory files and
dense convention prose. DeepSeek escalation is wired in config.yaml context_window_fallbacks.
