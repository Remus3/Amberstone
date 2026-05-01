# Riot Commander

Live coaching overlay + tablet dashboard for League of Legends and Teamfight Tactics. Reads Riot's local Live Client API, runs vision and LLM coaching, and serves a PWA-installable dashboard for second-screen viewing.

Personal project. Private repo. Not packaged for general use.

## What it does

- **Real-time coaching** — Claude Haiku for fast in-game tips, Claude Sonnet for screenshot-based vision reasoning, Tesseract OCR for cheap region reads
- **Web dashboard** (`:8888`, HTTPS) — home / lobby / last-match / session / history / replay / loadouts / settings / diagnostics views, installable as a PWA on iPad over Duet
- **Match history** — local SQLite (`rewind_history.db`, ~2,800 matches of full participant + timeline data) is the primary data source; no Riot API key required
- **Champion-select build chooser** — surfaces preferred keystone + items per matchup, writes runes via the LCU
- **TFT coaching** — separate worker for autobattler mode (vision pipeline pending refactor)
- **Cross-Claude bridge** — Legion and Game-PC each run a Claude Code instance; they coordinate via a JSONL bridge (auto-flow via `/loop /process-bridge-tasks`)

## Topology

| Machine | Role |
|---|---|
| **Legion** (`192.168.8.230`) | Hosts the main RC process, web dashboard `:8888`, vision server `:8889`, MCP client connecting to Game-PC |
| **Game-PC** (`192.168.8.237`) | Runs the League client + four relay agents (screen, LCU, Live-Client, MCP server) that feed Legion |
| **iPad** | Loads the dashboard PWA, mirrors the Game-PC display via Duet for split attention during games |

## Architecture

```
main.py                   entry: logging, key, supervisor, vision, dashboard, overlay
app/                      OverlayApp + decomposed managers
coaches/                  BaseCoach + per-mode variants (aram / arena / brawl / sr / tft)
modes/                    overlay UIs per mode
core/                     game_snapshot, theme, hotkeys, lcu helpers
tft/                      TFT engine + overlay
ui/                       OverlayWindow base + ClientPanel
ops/                      supervisor, self-monitor, runtime/health.json
lcu/                      LCU client, auto-accept, rune writer, postgame collector
data/                     coaching artifacts (atomic-written, polled by overlays + dashboard)
web/                      static dashboard assets (index.html, css/, js/)
web_dashboard.py          :8888 HTTPS dashboard server
moon_vision_server.py     :8889 vision server (Sonnet screenshots + Tesseract OCR)
tools/                    Game-PC agents, cross-Claude bridge tooling, boot scripts
scripts/                  data pipeline (patch-day refreshes)
```

See [`CLAUDE.md`](./CLAUDE.md) for live operational context (paths, hard rules, restart workflow, where the truth lives).

## Bring-up

### Legion (the brain)

1. Python 3.14 at `C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe`.
2. `python -m pip install -r requirements.txt` (Anthropic SDK + Pillow are the explicit deps; transitive ones come with).
3. Drop your Anthropic API key in `API-Key-Claude.txt` at the repo root (gitignored).
4. Run `start_claude.ps1` (or the **Claude RC** desktop shortcut) — it starts the `RC-Supervisor` and `RC-VisionServer` scheduled tasks idempotently and launches a Claude Code session in this repo.

### Game-PC (the eyes and hands)

One-line bootstrap from any Game-PC PowerShell session:

```powershell
iex (iwr https://192.168.8.230:8888/agent/gamepc_boot.ps1 -UseBasicParsing).Content
```

This fetches the four agents, provisions the inbound firewall rule for the MCP server (TCP 8892), kills any zombie listeners, starts whatever isn't already healthy, and installs the at-logon scheduled tasks for persistence.

### iPad

Open `https://192.168.8.230:8888/` in Edge, install as a PWA. The dashboard is HTTPS with a self-signed cert; flag `edge://flags/#unsafely-treat-insecure-origin-as-secure` to allow the origin.

## Vision pipeline

Frames are captured on Game-PC (`tools/gamepc_screen_agent.py`) and POSTed to Legion's vision server every two seconds. Coaches on Legion fetch the latest cached frame and route it by cost tier:

- **Tesseract** (region-bound OCR) for cheap, deterministic fields — gold, CS, level, KDA
- **Claude Sonnet** (full-frame visual reasoning) for anything that needs context — wave state, fog-of-war inference, item-spike timing
- **Fast-path heuristics** before either of the above when the answer is computable from the Live Client snapshot alone

## Cross-Claude bridge

Each machine runs its own Claude Code instance. They post JSON envelopes to `/api/bridge` and pull each other's output via hooks. Game-PC's `/loop /process-bridge-tasks` makes the round-trip hands-off in ~30–90s end-to-end. See `tools/process-bridge-tasks.md` for the canonical pull-and-post-result loop.

## Operational notes

- `API-Key-Claude.txt` and runtime state under `ops/runtime/` are gitignored
- All overlay file writes are atomic (`tmp.write_text(); tmp.replace(target)`) — overlays poll mid-write
- Restarts are signalled via `restart_trigger.txt`; the supervisor picks it up within a second
- `_HEADLESS = True` in `app/_overlay_manager.py` keeps the tkinter overlays hidden so the dashboard is the only UI; flip to `False` to restore on-screen overlays
- Frozen files in the architecture map (listed in `CLAUDE.md`) require explicit user approval to modify

## License

All rights reserved. Personal use only.
