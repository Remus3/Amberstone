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
| `RC-DS-MatchDB-MCP` | At logon (operator-gated) | Administrator | Local DS + match-DB MCP (:8894) |
| `RC-Bridge-MCP` | STALE - not installed live (verify vs RC-BridgeDaemon) | Administrator | Local cross-Claude bridge MCP (:8895) |
| `RC-BridgeDaemon` | At logon | Administrator | Zero-cost bridge task sentinel (`tools/legion_bridge_daemon.py`) |
| `RC-CostHealthWatchdog` | At startup + periodic | SYSTEM | Self-healing cost + health watchdog (`tools/cost_health_watchdog.py`) |
| `RC-GeminiAudit` | Daily | Administrator | Gemini read-only auditor (`tools/gemini_audit.ps1`) |
| `RC-HotkeyListener` | At logon | Administrator | Global hotkey listener (`tools/gamepc_hotkey_listener.py`) |
| `RC-LCUAgent` | At logon | Administrator | LCU relay agent (`tools/gamepc_lcu_agent.py`) |
| `RC-LiveClientRelay` | At logon | Administrator | Live Client `:2999` relay agent (`tools/gamepc_liveclient_relay.py`) |
| `RC-PostmortemAnalyze` | Weekly | Administrator | Postmortem analyze + restart (`ops/run_postmortem_with_restart.ps1`) |
| `RC-UpstreamDriftCheck` | Daily | Administrator | Upstream content-drift detector ddragon/meraki/cdragon (`tools/upstream_drift_check.py`) |
| `RC-DDragonMirrorRefresh` | Daily 03:30 | Administrator | `tools/ddragon_mirror_refresh.py --check-changed` |
| `RC-RewindCatchup` | Weekly Sunday 04:00 | Administrator | `scripts/rewind_catchup.py` (pull new Match-V5 records into rewind_history.db) |
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

DS wiki_stats sidecar (AA windup / missile / mode-modifiers) is re-extracted separately - run from the repo root after a patch bump:

```powershell
python tools/daemon_slayer_wiki_stats_extract.py   # writes data/daemon_slayer/<patch>/wiki_stats.json
```

It re-derives the offset windup tier (109 champs via the wiki attack_delay_offset, provenance `wiki_offset`); rerun `python tools/ds_windup_offset_compare.py` to find newly-recoverable champs on a new patch. Do NOT commit a run reporting `_with_cast_measured == 0` (host could not reach the wiki / CDragon).

### Data extractors (full list)

Every pipeline that pulls external data into the repo. The first two run on patch day; the DS sidecars are re-extracted per patch (see the per-patch refresh chain order in `reference_patch_refresh_workflow` / the patch-refresh section above - it documents the canonical command sequence; do not duplicate it here).

| Script | Source | Data piece pulled | Output | Consumed by |
|---|---|---|---|---|
| `scripts/data_pipeline.py` | DDragon CDN + Aggregator B (ARAM) | champion meta, item catalog, runes, summoner spells, ARAM tier rankings | `data/meta/ddragon_*.json`, `web/data/{items,champions,spells}_index.json` | dashboard UI, DS data_loader, abilities extractor |
| `tools/daemon_slayer_extract.py` | DDragon + lolmath.net JS chunks + Meraki bulk + CDragon Arena | champion base stats + lolmath scenarios/skill-orders/aram_modifiers + Arena augments + Meraki item passives | `data/daemon_slayer/<patch>/{champions,items,scenarios,arena_augments,items_meraki,manifest}.json` + `current.txt` | DS engine snapshot, combo sim, scenario scorer |
| `tools/daemon_slayer_abilities_extract.py` | Meraki bulk champions endpoint | per-champion ability schema: damage blocks w/ typed scaling (AD%/AP%/HP%), cast_time, cooldown[], cost[] | `data/daemon_slayer/<patch>/champion_abilities.json` | DS damage evaluator, ability_dps/hps/burst, CC scorer |
| `tools/daemon_slayer_wiki_stats_extract.py` | LoL wiki ChampionData (wiki.leagueoflegends.com action=raw) + CDragon character bins | attack_cast_time (AA windup s), attack_total_time, missile_speed, attack_delay_offset, per-mode balance mode_modifiers | `data/daemon_slayer/<patch>/wiki_stats.json` | combo.py AA-windup |
| `tools/daemon_slayer_cdragon_spell_extract.py` | CDragon character bins (raw.communitydragon.org) | per-spell ammo/recharge, missile speed, coarse CC tags (Stun/Root/Knockup/...), AOE geometry | `data/daemon_slayer/<patch>/cdragon_spell_stats.json` | DATA-ONLY sidecar (no consumer wired yet) |
| `tools/daemon_slayer_wiki_ability_extract.py` | LoL wiki Template:Data MediaWiki batch query API | per-ability static-cooldown flag, recharge, typed CC booleans, geometry | `data/daemon_slayer/<patch>/wiki_ability_stats.json` | DATA-ONLY sidecar (no consumer wired yet) |
| `tools/ddragon_mirror_refresh.py` | DDragon bundle JSON + per-asset CloudFront | champion/ability/passive/item/profileicon/map/perk images + bundle JSONs; atomic ETag delta sync | `web/data/ddragon/<patch>/img/*`, `data/meta_build/ddragon/<patch>/*` | dashboard local asset serving (no network mid-match) |

The two DATA-ONLY sidecars (`cdragon_spell_stats`, `wiki_ability_stats`) write per-patch JSON but have no engine consumer wired yet - they are forward-staged for future CC/geometry scorers. `ddragon_mirror_refresh.py` has its own section below (flags + scheduled task).

---

## Vision server

```
curl http://127.0.0.1:8889/health
curl http://127.0.0.1:8889/latest-frame     # check if frames flowing
```

Vision token is in `config/vision_token.txt` (Legion) and `tools/vision_token.txt` (Game-PC). Rotate quarterly - next rotation ~2026-08-01.

---

## Local DS + match-DB MCP (:8894)

Localhost-only MCP server (`tools/ds_matchdb_mcp_server.py`) that wraps the
Daemon Slayer engine (:8893) and `data/match_history.db` as MCP tools for a
local Claude / agent: `ds_health`, `ds_rank_items`, `ds_build_order`,
`ds_archetype_for`, `match_recent`, `match_mode_stats`, `match_tft_comps`,
`match_tft_streak`. Read-only w.r.t. RC state (it never writes the match DB);
DS-down and match-DB-missing both degrade to an error dict, never crash.

```powershell
py tools\ds_matchdb_mcp_server.py --show-token        # token for client config
py tools\start_ds_matchdb_mcp.py                       # launch (boot wrapper)
curl http://127.0.0.1:8894/health -H "Authorization: Bearer <token>"
```

Persistence (operator-gated - it is a new always-on listener; only register
once a local Claude is actually pointed at it):

```
schtasks /Create /TN "RC-DS-MatchDB-MCP" /SC ONLOGON /RL HIGHEST /F ^
  /TR "pythonw C:\Riot Commander\tools\start_ds_matchdb_mcp.py"
```

Client wiring (also operator-gated - editing `.mcp.json` changes a live
Claude session's own tool surface): add an `mcpServers` entry with
`"type": "http"`, `"url": "http://127.0.0.1:8894/mcp"`, and the bearer
token from `--show-token`. Full snippet in the server-file docstring.
Token resolution mirrors the Game-PC MCP (env `RC_MCP_TOKEN` ->
`tools/mcp_token.txt` -> `tools/vision_token.txt` -> dev fallback) so one
token covers both RC MCP servers.

---

## Local cross-Claude bridge MCP (:8895)

Localhost-only MCP server (`tools/bridge_mcp_server.py`) that wraps the
local `/api/bridge` surface and `ops/runtime/bridge_inbox_pending.json` as
MCP tools for a local Claude / agent: `bridge_search`, `bridge_post_note`,
`bridge_post_task`, `bridge_post_result`, `bridge_post_lesson`,
`bridge_pending`, `bridge_status`. Reads via GET shuttle to
`https://127.0.0.1:8888/api/bridge`; `bridge_pending` reads the JSON file
directly so a pure status probe never requires the dashboard process to
be up. Writes shuttle to POST `/api/bridge` (the deque + JSONL backup
are kept in sync there); dashboard-down degrades to a structured error
dict, never crashes.

```powershell
py tools\bridge_mcp_server.py --show-token             # token for client config
py tools\start_bridge_mcp.py                            # launch (boot wrapper)
curl http://127.0.0.1:8895/health -H "Authorization: Bearer <token>"
```

Persistence (operator-gated - new always-on listener; only register once
a local Claude is actually pointed at it):

```
schtasks /Create /TN "RC-Bridge-MCP" /SC ONLOGON /RL HIGHEST /F ^
  /TR "pythonw C:\Riot Commander\tools\start_bridge_mcp.py"
```

Client wiring (operator-gated; same caveat as RC-DS-MatchDB-MCP): add an
`mcpServers` entry with `"type": "http"`,
`"url": "http://127.0.0.1:8895/mcp"`, and the bearer token from
`--show-token`. Full snippet in the server-file docstring. Token chain is
the same as the two existing RC MCP servers so one `RC_MCP_TOKEN` covers
all three.

---

## DDragon mirror refresh (`RC-DDragonMirrorRefresh`)

Keeps `web/data/ddragon/<patch>/img/{champion,passive,spell,item,profileicon,map,perk-images}/`
synced with the live CDN so the dashboard never depends on the network during
a match. `tools/ddragon_mirror_refresh.py` resolves the latest version from
`https://ddragon.leagueoflegends.com/api/versions.json`, pulls the bundle
JSONs (champion summary + per-champion detail + item + summoner + runesReforged
+ profileicon), and downloads any deltas with atomic writes. Per-asset ETag /
Content-Length stored in `data/meta_build/ddragon/<patch>/_assets_manifest.json`
so `--check-changed` only re-fetches mid-patch revisions; first cold run on a
new patch fetches ~6.7k files (~30 MB).

```powershell
py tools\ddragon_mirror_refresh.py --check-only       # exit 1 = flip pending
py tools\ddragon_mirror_refresh.py --dry-run          # plan, no writes
py tools\ddragon_mirror_refresh.py                    # default - idempotent fetch
py tools\ddragon_mirror_refresh.py --check-changed    # mid-patch HEAD probe
py tools\ddragon_mirror_refresh.py --full             # ignore manifest, refetch all
py tools\ddragon_mirror_refresh.py --version 16.10.1  # pin a version
py tools\ddragon_mirror_refresh.py --workers 8        # default 8 parallel fetchers
```

Install the daily 03:30 task (elevated PowerShell):

```
powershell -ExecutionPolicy Bypass -File "C:\Riot Commander\ops\install_RC_DDragonMirror.ps1"
```

Augment icons are NOT in DDragon; CommunityDragon serves them via
`cherry-augments.json`. Out of scope for this task - flagged for a separate
cdragon adapter.

---

## Rewind history catchup (`RC-RewindCatchup`)

Pulls new Match-V5 records into `data/rewind_history.db` (5-table schema:
matches / participants / teams / timeline_frames / timeline_events). The
catchup paginates `/lol/match/v5/matches/by-puuid/{puuid}/ids` forward
from the newest `game_creation_ts` in the DB, fetches detail + timeline
for each missing match. Idempotent (INSERT OR IGNORE) and resumable via
`data/rewind_catchup.state.json`. Auto-resolves the current PUUID through
Account-V1 by Riot ID (handles PUUID rotation).

```powershell
py scripts\rewind_catchup.py                # full catch-up
py scripts\rewind_catchup.py --dry-run      # list IDs only, no writes
py scripts\rewind_catchup.py --limit 50     # cap detail fetches
py scripts\rewind_catchup.py --no-timeline  # skip timeline (faster)
py scripts\rewind_catchup.py --puuid X      # override operator PUUID
```

Install the weekly Sunday 04:00 task (elevated PowerShell):

```
powershell -ExecutionPolicy Bypass -File "C:\Riot Commander\ops\install_RC_RewindCatchup.ps1"
```

Operator's play cadence is sparse (`5 games / 5 months 2026-05`), so a
weekly cadence is enough. ExecutionTimeLimit caps each run at 20 minutes.

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

Peer watcher drift check (Game-PC / Peer side):
```
iex (iwr -UseBasicParsing `
  https://legion-rc:8888/agent/bridge_watcher_update_check.ps1).Content
```

This pulls `/agent/_watcher_manifest.json` (sha256+size for the 7-file watcher runtime set), diffs against the local install copy, prints any stale or missing files, and exits 0 (up-to-date), 1 (stale), 2 (manifest fetch failed), or 3 (install dir not found). Pass `-Apply` to re-pull stale files, `-Restart` to bounce the watcher's scheduled task, or `-Quiet` for cron-friendly output. Auto-detects install dir from `C:\RC-Agent` (Game-PC) or `.\tools` (Peer) when not passed explicitly.

The manifest covers the full runtime fileset the watcher imports at module load (`bridge_watcher.py` + `classify` + `actions` + `history` + the config json + hook ps1 + action prompt md), which is wider than the original `bridge_watcher_install.ps1` 4-file pull set - drift in any of the 7 is caught.

### Fresh peer install ritual (2-step)

`bridge_watcher_install.ps1` is frozen (CLAUDE.md hard-rule) and only pulls 4 of the 7 files the daemon imports at module load. A fresh peer install on Game-PC or Peer therefore needs a second step to fill the gap (`bridge_watcher_actions.py`, `bridge_watcher_history.py`, `bridge_watcher_action_prompt.md`) before the watcher will boot.

```
# Step 1: installer (4 files + scheduled task + heartbeat verify)
iex (iwr -UseBasicParsing `
  https://legion-rc:8888/agent/bridge_watcher_install.ps1).Content

# Step 2: drift-check -Apply (catches + pulls the missing 3, no-op if covered)
iex (iwr -UseBasicParsing `
  https://legion-rc:8888/agent/bridge_watcher_update_check.ps1).Content `
  -Apply -Restart
```

Step 2 is idempotent: re-running it on an already-up-to-date peer exits 0 with no writes. The `-Restart` flag bounces the freshly-installed scheduled task so it picks up the 3 just-pulled files in the same shell. Without Step 2 the watcher's `bridge_watcher.py` import of `bridge_watcher_actions` / `bridge_watcher_history` would crash at module load (hard imports, not try/except).

Re-run `bridge_watcher_update_check.ps1` (no flags) periodically or from cron to verify the install stays in sync with the canonical Legion copy.

### Cross-Claude lessons (Phase 4 surface)

Lesson sync status (sender ledger + per-(peer, mem_type) smoothed confidence):
```
curl -k https://127.0.0.1:8888/api/lessons/status         # JSON (refreshes acks first)
curl -k "https://127.0.0.1:8888/api/lessons/status?refresh=0"  # snapshot only, skip bridge
```

CLI equivalent (also pokes the bridge for any new acks):
```
py tools/lessons_status.py            # JSON
py tools/lessons_status.py --plain    # tabular per-bucket view
py tools/lessons_status.py --no-refresh
```

Apply-with-revert wrapper (Claude/operator-driven; the receiver still
auto-handles only schema-reject + neg-match):
```
py -m core.lessons_revert <lesson_id> --commit-sha <sha> --tests tests/test_x.py
```
On post-apply test failure + commit_sha given: runs `git revert <sha>
--no-edit` and sends a follow-up `kind=result` ack with
`auto_reverted=true`. Without commit_sha the fallback is to queue the
lesson (no apply ack-took claim).

Auto-revert is intentionally NOT a daemon - it is a safety net invoked
by Claude when an applied lesson lands in a commit (vision section 5
Phase 4 framing).

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
