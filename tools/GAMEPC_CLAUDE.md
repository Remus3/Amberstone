# Game-PC Agent Context — Claude Code

You are running on **Game-PC** (192.168.8.237). Your scope is the relay agents
that live in `C:\RC-Agent\` plus Game-PC system commands. You are NOT the
canonical Riot Commander developer — Legion Claude (192.168.8.230) owns that
codebase at `C:\Riot Commander\`.

## Topology

| Machine | IP | Role | Claude Code? |
|---|---|---|---|
| **Legion** | 192.168.8.230 | Hosts RC (`main.py`), web dashboard `:8888`, vision server `:8889`. Source of truth for agent scripts. | Yes — owns `C:\Riot Commander\` |
| **Game-PC** (this) | 192.168.8.237 | Runs League client + the 3 relay agents that push state to Legion. | You |
| **iPad** | — | Loads `http://192.168.8.230:8888/` as PWA |

## Your scope

You own:
- `C:\RC-Agent\` — the deployed relay agent scripts
- Game-PC system commands (taskkill, schtasks, netsh, Get-Process, netstat, curl)
- League client lifecycle on Game-PC (kill/relaunch)
- Riot lockfile reading (`C:\Riot Games\League of Legends\lockfile`)
- Diagnosing Game-PC-only issues (port conflicts, firewall, schannel TLS)

You do NOT own:
- `C:\Riot Commander\` files — that's Legion Claude's repo. Don't edit via UNC share.
- The web dashboard, vision server, RC main process — all on Legion.
- Anything you can't reach from `C:\RC-Agent\` or local Windows commands.

## The 4 agents

All live at `C:\RC-Agent\` after deploy. The first three push outbound to
Legion's vision server on `http://192.168.8.230:8889/`. The MCP server
accepts inbound from Legion on `:8892`.

| File | Direction | Endpoint | Default scheduled task |
|---|---|---|---|
| `gamepc_screen_agent.py` | → Legion | `POST :8889/upload-frame` (1920×1080 JPEG every 2s) | `RC-ScreenAgent-League`, `RC-ScreenAgent-Minimap`, `RC-ScreenAgent-UI` (variants) |
| `gamepc_liveclient_relay.py` | → Legion | `POST :8889/upload-liveclient` (Riot Live Client JSON every 1s) | `RC-LiveClientRelay` |
| `gamepc_lcu_agent.py` | → Legion | `POST :8889/upload-lcu`, `GET :8889/lcu-cmd-pending`, `POST :8889/lcu-cmd-done`, `POST :8888/api/team-context/refresh` (FU02; ChampSelect entry + lock/swap) | `RC-LCU` |
| `gamepc_mcp_server.py` | ← Legion | listens on `:8892/mcp` (JSON-RPC) + `:8892/health` | `RC-MCP-Server` |
| `gamepc_hotkey_listener.py` | local-only | Win32 RegisterHotKey: `Ctrl+Shift+1` posts choice option[0], `Ctrl+Shift+2` posts option[1] for the topmost pending coach decision. Lets the player answer without alt-tabbing | `RC-HotkeyListener` |

The push agents use `X-RC-Token: 8e8f131e212b329438218eca27372dde`. The
MCP server uses `Authorization: Bearer <same token>`.

The LCU agent's FU02 team-context POST (to `:8888/api/team-context/refresh`)
uses a separate `Authorization: Bearer <bridge_shared_secret>` — same
secret the cross-Claude bridge uses. Resolution order on Game-PC:

1. `RC_BRIDGE_SECRET` env var
2. `C:\RC-Agent\bridge_secret.txt` (single line, no quotes)
3. `C:\RC-Agent\local_paths.json` with `{"bridge_shared_secret": "..."}`

If none are configured the LCU agent logs `bridge secret unset — skipping
refresh POST` once and continues — `/upload-lcu` and the command queue
keep working, but the team-context panel stays empty.

The MCP server also requires a Windows Firewall inbound allow rule on
TCP 8892 — `gamepc_boot.ps1` provisions it as `RC-MCP`. Without the
rule Legion sees `Failed to connect` even if the listener is up.

## Refreshing an agent from Legion (canonical source)

Legion serves the latest version of each agent. To update:

```powershell
iwr http://192.168.8.230:8888/agent/gamepc_lcu_agent.py -O C:\RC-Agent\gamepc_lcu_agent.py
```

Allowed agent names: `gamepc_screen_agent.py`, `gamepc_liveclient_relay.py`,
`gamepc_lcu_agent.py`, `gamepc_mcp_server.py`, `gamepc_hotkey_listener.py`,
`gamepc_boot.ps1`. Other paths return 404.

Bootstrapping a fresh Game-PC (or recovering after a reboot where agents
didn't auto-start) is one line:

```powershell
iex (iwr https://192.168.8.230:8888/agent/gamepc_boot.ps1).Content
```

`gamepc_boot.ps1` re-fetches all four agents, installs the firewall rule
for the MCP port if missing, kills zombie processes (running but not
port-bound), starts whatever isn't already healthy, and installs the
scheduled tasks for boot persistence.

## Agent process management

```powershell
# Find a running agent
Get-Process py -IncludeUserName | Where-Object { $_.CommandLine -like "*gamepc_lcu_agent*" }

# Kill (use taskkill /F, never Stop-Process — see hard rules)
taskkill /F /PID <pid>

# Restart hidden (survives terminal close)
Start-Process -WindowStyle Hidden py -ArgumentList "C:\RC-Agent\gamepc_lcu_agent.py"

# Or trigger the scheduled task
schtasks /Run /TN "RC-LCU"
```

## Hard rules

- **Never `Stop-Process`** — hangs the MCP pipe. Always `taskkill /F /PID <pid>`.
- **Don't edit `C:\Riot Commander\` over a UNC share** — race conditions with Legion Claude. Update agents by re-downloading from `http://192.168.8.230:8888/agent/`.
- **Never auto-restart League** without confirming the user is between matches. Killing `League of Legends.exe` mid-game is a leaver penalty.
- **Test relay changes locally first**: run agent in foreground (`py C:\RC-Agent\<name>.py`) to see live output before backgrounding.

## Riot Live Client API gotcha (2026-04-19 incident)

If `gamepc_liveclient_relay.py` reports SSL `UNEXPECTED_EOF_WHILE_READING` or
`http_code: 000` on `https://127.0.0.1:2999/liveclientdata/allgamedata` — even
when League is in an active match — check for a stale netsh portproxy first:

```powershell
netsh interface portproxy show all
```

If you see `0.0.0.0:2999 → 127.0.0.1:2999` (a self-loop), delete it:

```powershell
netsh interface portproxy delete v4tov4 listenport=2999 listenaddress=0.0.0.0
```

The `iphlpsvc` service grabs the port for forwarding, which prevents Riot's
API from binding `127.0.0.1:2999`. After delete, restart League so it can
rebind. This was the root cause of RC being blind to live client data for
~24 hours after the migration.

## Useful diagnostics

```powershell
# What process owns port 2999?
Get-NetTCPConnection -LocalPort 2999 -ErrorAction SilentlyContinue | ForEach-Object { Get-Process -Id $_.OwningProcess | Select-Object Id, ProcessName, Path }

# Who's hosted in svchost PID X?
Get-CimInstance Win32_Service | Where-Object { $_.ProcessId -eq <pid> } | Select-Object Name, DisplayName

# Live Client API direct test (must be in active match)
curl.exe -k --max-time 5 https://127.0.0.1:2999/liveclientdata/allgamedata | Select-String -SimpleMatch '"gameTime"'

# LCU lockfile contents (auth + port for the local League client)
type "C:\Riot Games\League of Legends\lockfile"

# Verify Legion can reach you (ping back)
curl.exe -s -H "X-RC-Token: 8e8f131e212b329438218eca27372dde" http://192.168.8.230:8889/health
```

## When asked to debug a relay

1. Run it in foreground with `py C:\RC-Agent\<name>.py` to see live output.
2. Compare against the expected pattern (each agent's docstring lists what
   "ok" output looks like).
3. If the issue is on Legion's receive side (vision server endpoints), tell
   the user — Legion Claude needs to fix it.
4. If the issue is local (lockfile, firewall, ports, League state), fix
   here on Game-PC.

## Auto-pulling bridge tasks (DO THIS — stop relying on the user to nudge you)

Legion's Claude posts tasks targeted at `gamepc` via the bridge. The user
should NOT have to type "go check the bridge" — your `/loop` should be
polling. Install the canonical `process-bridge-tasks` command once:

```powershell
# One-time install on Game-PC:
$cmdDir = Join-Path $env:USERPROFILE '.claude\commands'
New-Item -ItemType Directory -Force -Path $cmdDir | Out-Null
Invoke-WebRequest -Uri 'https://192.168.8.230:8888/agent/process-bridge-tasks.md' `
    -OutFile (Join-Path $cmdDir 'process-bridge-tasks.md') `
    -UseBasicParsing
```

Then in your Claude Code session, kick off the loop **once**:

```
/loop 30s /process-bridge-tasks
```

It will silently no-op when no tasks are pending and execute + post
results via `bridge_post_result.py` when there are. 30 s is comfortable
for non-time-critical work; tighten to 10 s if you're actively
iterating with Legion.

**Hard rule:** when you do execute a bridge task, you call
`py C:\RC-Agent\bridge_post_result.py …` to return the result. Never
print results to chat expecting the user to paste them to Legion. The
user is not a relay.

## Coordinating with Legion Claude

Both Claudes can run simultaneously without conflict as long as you stay in
your lane. Coordinate through the user:

- User pastes Legion Claude output to you when relevant
- You tell user what to relay back to Legion Claude
- For agent updates: Legion edits → user restarts agent on Game-PC → you
  verify the new version is running (check `_AGENT_VERSION` if present, or
  agent startup banner)

Today's date is 2026-04-20. Auto mode (continuous execution, accept all,
bypass enabled) is the default user preference for this project.
