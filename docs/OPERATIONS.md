# Riot Commander - Operations Reference

_Living document. Full ops command set for Legion sessions._

---

## Python interpreter

Canonical interpreter (the ONLY one with RC's dependency tree installed):

```
C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe
```

Bare `py` is BANNED on every Legion runnable/doc surface: PEP 514 resolves it
to a pymanager runtime (`AppData\Local\Python\pythoncore-3.14-64`) with ZERO
third-party packages, so a launcher-spelled pytest run silently executes a
pytest-less interpreter (a past incident zeroed the test suite). Always spell
the canonical absolute path (quoted) in commands, hooks, docs, and scheduled
tasks. Guard test: `tests/test_bare_py_ban.py`.

Use `pythonw.exe` for background daemons (no console window); `python.exe` for
scripts that need stdout.

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

**Never** `Stop-Process` (hangs the MCP pipe) - use `taskkill /F /PID`. `restart.bat` is the
documented hard fallback AFTER the taskkill (CLAUDE.md "Restart workflow"), not an interactive-shell
first resort.

---

## Scheduled tasks (Legion)

| Task | Trigger | Context | Description |
|---|---|---|---|
| `RC-Supervisor` | At logon | Administrator / HIGHEST | Runs `pythonw.exe ops/rc_supervisor.py` |
| `RC-DaemonSlayer` | Manual / on demand | Administrator | DS engine server |
| `RC-DS-MatchDB-MCP` | At logon (operator-gated) | Administrator | Local DS + match-DB MCP (:8894) |
| `RC-CostHealthWatchdog` | At startup + periodic | SYSTEM | Self-healing cost + health watchdog (`tools/cost_health_watchdog.py`) |
| `RC-CIWatchdog` | At startup + periodic (PT2M) | Administrator / armed | Unattended headless-claude red-main CI auto-fixer; self-gates the merge on the ci-fix PR's OWN green CI (`tools/ci_watchdog.py`, isolated worktree `C:\RC-CIWatchdog`; item 622). Kill: create `ops\runtime\ci_watchdog\HALT` or `Disable-ScheduledTask RC-CIWatchdog` |
| `RC-GeminiAudit` | Daily | Administrator | Gemini read-only auditor (`tools/gemini_audit.ps1`) |
| `RC-HotkeyListener` | At logon | Administrator | Global hotkey listener (`tools/hotkey_listener.py`) |
| `RC-LCUAgent` | At logon | Administrator | LCU relay agent (`tools/lcu_agent.py`) |
| `RC-LiveClientRelay` | At logon | Administrator | Live Client `:2999` relay agent (`tools/liveclient_relay.py`) |
| `RC-LiveFlipWatcher` | At logon | Administrator | DS live-flip seam watcher + toast (`tools/live_flip_watcher.py`) |
| `RC-PostmortemAnalyze` | Weekly | Administrator | Postmortem analyze + restart (`ops/run_postmortem_with_restart.ps1`) |
| `RC-UpstreamDriftCheck` | Daily | Administrator | Upstream content-drift detector ddragon/meraki/cdragon (`tools/upstream_drift_check.py`) |
| `RC-DDragonMirrorRefresh` | Daily 03:30 | Administrator | `tools/ddragon_mirror_refresh.py --check-changed` |
| `RC-RewindCatchup` | Weekly Sunday 04:00 | Administrator | `scripts/rewind_catchup.py` (pull new Match-V5 records into rewind_history.db) |
| `RC-RoflArchive` | Every 15 min | Administrator / HIGHEST | The OPERATOR's own replays: `tools/rofl_archiver.py --pull --lcu-path --extract --highlights --quiet` |
| `RC-ReplayRosterPull` | Hourly | Administrator / HIGHEST | TRACKED PLAYERS' ranked replays into the role-partitioned corpus: `tools/replay_roster_pull.py --quiet --log-file logs/replay_roster.log`. Roster: `data/replay_roster.json`. **Cadence is not cosmetic** - `/replays` holds only the 5 most recent retained games per account and has NO fetch-by-match-id route, so a game nobody pulls during its residency is lost permanently (measured twice on 2026-07-26: two specifically requested matches had already rotated out). Five games is the whole window, so hourly leaves roughly a 2.5x margin over a fast laddering session. Log: `logs/replay_roster.log` (pythonw discards stdout, so `--log-file` is mandatory here) |
| `RC-ReplayChainWatch` | Every 15 min | Administrator / HIGHEST | Session-independent watchdog for the replay ingest chain (`tools/replay_chain_watch.py`). Re-enables `RC-ReplayRosterPull` and runs the event-pattern miner ONCE the long ingests (`timeline_ingest`, `build_rank_baselines`) have finished. **Exists because those follow-ups used to be held in a chat session:** if the session ended first, the roster task stayed Disabled and games rotated out of the 5-wide `/replays` window permanently, which is unrecoverable (no fetch-by-match-id route). Idempotent - no-ops while any ingest is running, never re-enables an already-enabled task, and mines only when the corpus grew. `--status` reports without changing anything |
| `RC-WeeklyHygiene` | Weekly Sunday 04:17 | Administrator | Unattended `/weekly-hygiene` pass via headless Claude (`tools/weekly_hygiene_run.ps1`; install `ops/install_RC_WeeklyHygiene.ps1`) |
| `RC-PatchRefresh` | Weekly Wednesday | Administrator | `data_pipeline.py all` |
| `RC-Phase3-Supervisor` | At logon | Administrator | Phase 3 agent supervisor |
| `RC-Phase3-PeriodicAudit` | Scheduled | Administrator | Phase 3 periodic audit |
| `RC-TeamClaudeProxy` | At logon | Administrator / HIGHEST | Operator utility, NOT RC infra: headless `teamclaude` multi-account Claude-subscription failover proxy on `:3456`, launched hidden via `C:\Users\Administrator\teamclaude_proxy_hidden.vbs` -> `teamclaude_proxy.bat`. Inert until a client sets `ANTHROPIC_BASE_URL=http://localhost:3456` (`teamclaude run --no-mitm`); does not touch RC or the dashboard. Config + live OAuth tokens live in `C:\Users\Administrator\.config\teamclaude.json` (non-repo, do NOT commit). Activity log: same dir, `teamclaude_activity.log` |

Check state: `Get-ScheduledTask -TaskName "RC-*" | Select TaskName, State`

Subscription failover routing: a USER-scope `ANTHROPIC_BASE_URL=http://localhost:3456` is set (HKCU\Environment) so the Claude subscription GUI (MSIX desktop app) + any `claude` CLI + the headless RC-* Claude tasks all route through the teamclaude failover proxy and rotate across the two subscription accounts. This is deliberate - those are subscription surfaces. The `cf` shim (`C:\Users\Administrator\AppData\Roaming\npm\cf.cmd`) still exists as an explicit CLI entry but is now largely redundant given the user-wide var.

RC coaching is CARVED OUT and must stay on the direct API: it uses the Console API key (`API-Key-Claude.txt`), not the subscription, so routing it through the proxy would break auth / burn subscription quota. Every production `anthropic.Anthropic(...)` pins `base_url="https://api.anthropic.com"` to ignore the env var; `tests/test_anthropic_base_url_pin.py` is the guard (fails on any unpinned or new construction site). Do NOT remove those pins while the user-wide var is set.

---

## Data pipeline (patch day)

```powershell
cd scripts
python data_pipeline.py all       # full refresh (items + builds + meta + rank_tiers)
python data_pipeline.py meta      # meta only (faster)
python data_pipeline.py aram_builds
python data_pipeline.py rank_tiers  # overlay item 8: stamp live patch onto the rank-tier stats-panel artifact
```

Run from `C:\Riot Commander\scripts\`. Patch releases typically Wednesdays - `RC-PatchRefresh` fires automatically.

Overlay item 8 (in-game rank-tier stats panel): the panel benchmarks the operator against a SELECTED rank-tier average (mode-specific SR / ARAM; Arena shows "no benchmark", no seed). Pick the tier in the in-game DS Settings strip (or the Post Game Review / desktop Settings rank row - all three share the `rc-pgr-rank-tier` key). Backend: `GET /api/rank-tier-bench?tier=&mode=&bracket=` reads `core.rank_tier_bench` (committed estimate seed `data/rank_tiers/rank_tier_averages.seed.json`, tagged "estimate-not-measured"; the panel badges provenance). Live overlay is off by default - set `RC_RANK_TIER_LIVE=1` only once a real aggregate endpoint is wired in gitignored `config/rank_tier_source.json`. The deprecated-but-alive `GET /api/role-bracket-bench` (personal-corpus lens) is retained for existing consumers.

DS wiki_stats sidecar (AA windup / missile / mode-modifiers) is re-extracted separately - run from the repo root after a patch bump:

```powershell
python tools/daemon_slayer_wiki_stats_extract.py   # writes data/daemon_slayer/<patch>/wiki_stats.json
```

It re-derives the offset windup tier (109 champs via the wiki attack_delay_offset, provenance `wiki_offset`); rerun `python tools/ds_windup_offset_compare.py` to find newly-recoverable champs on a new patch. Do NOT commit a run reporting `_with_cast_measured == 0` (host could not reach the wiki / CDragon).

### Data extractors (full list)

Every pipeline that pulls external data into the repo. The first two run on patch day; the DS sidecars are re-extracted per patch (the patch-day sections above document the canonical command sequence; do not duplicate it here).

| Script | Source | Data piece pulled | Output | Consumed by |
|---|---|---|---|---|
| `scripts/data_pipeline.py` | DDragon CDN + Aggregator B (ARAM) | champion meta, item catalog, runes, summoner spells, ARAM tier rankings | `data/meta/ddragon_*.json`, `web/data/{items,champions,spells}_index.json` | dashboard UI, DS data_loader, abilities extractor |
| `tools/daemon_slayer_extract.py` | DDragon + lolmath.net JS chunks + Meraki bulk + CDragon Arena | champion base stats + lolmath scenarios/skill-orders/aram_modifiers + Arena augments + Meraki item passives | `data/daemon_slayer/<patch>/{champions,items,scenarios,arena_augments,items_meraki,manifest}.json` + `current.txt` | DS engine snapshot, combo sim, scenario scorer |
| `tools/daemon_slayer_abilities_extract.py` | Meraki bulk champions endpoint | per-champion ability schema: damage blocks w/ typed scaling (AD%/AP%/HP%), cast_time, cooldown[], cost[] | `data/daemon_slayer/<patch>/champion_abilities.json` | DS damage evaluator, ability_dps/hps/burst, CC scorer |
| `tools/daemon_slayer_wiki_stats_extract.py` | LoL wiki ChampionData (wiki.leagueoflegends.com action=raw) + CDragon character bins | attack_cast_time (AA windup s), attack_total_time, missile_speed, attack_delay_offset, per-mode balance mode_modifiers | `data/daemon_slayer/<patch>/wiki_stats.json` | combo.py AA-windup |
| `tools/daemon_slayer_cdragon_spell_extract.py` | CDragon character bins (raw.communitydragon.org) | per-spell ammo/recharge, missile speed, coarse CC tags (Stun/Root/Knockup/...), AOE geometry | `data/daemon_slayer/<patch>/cdragon_spell_stats.json` | DATA-ONLY sidecar (no consumer wired yet) |
| `tools/daemon_slayer_cdragon_ratio_extract.py` | CDragon character bins (raw.communitydragon.org, 2-segment patch e.g. `16.14`) | per-ability mechanical damage RATIOS (base, ap_pct, total/bonus_ad_pct, caster/target_max_hp_pct) + a drift report vs frozen Meraki | `data/daemon_slayer/<patch>/cdragon_ability_ratios.json`, `cdragon_ratio_drift.json` | **ENGINE INPUT** - `AbilitiesSnapshot.load(prefer_cdragon_ratios=True)` overrides Meraki ratios per-field (default ON since item 320) |
| `tools/daemon_slayer_wiki_ability_extract.py` | LoL wiki Template:Data MediaWiki batch query API | per-ability static-cooldown flag, recharge, typed CC booleans, geometry | `data/daemon_slayer/<patch>/wiki_ability_stats.json` | DATA-ONLY sidecar (no consumer wired yet) |
| `tools/ddragon_mirror_refresh.py` | DDragon bundle JSON + per-asset CloudFront | champion/ability/passive/item/profileicon/map/perk images + bundle JSONs; atomic ETag delta sync | `web/data/ddragon/<patch>/img/*`, `data/meta_build/ddragon/<patch>/*` | dashboard local asset serving (no network mid-match) |

The two DATA-ONLY sidecars (`cdragon_spell_stats`, `wiki_ability_stats`) write per-patch JSON but have no engine consumer wired yet - they are forward-staged for future CC/geometry scorers. `ddragon_mirror_refresh.py` has its own section below (flags + scheduled task).

**`cdragon_ability_ratios.json` is NOT in that data-only set - it feeds the engine, and it MUST be re-extracted on patch day.** It was omitted from this table until 2026-07-18, and the omission is why three consecutive patch refreshes copied it forward verbatim: as of 16.14.1 the committed sidecar is byte-identical across the 16.11.1 / 16.12.1 / 16.13.1 / 16.14.1 directories and its payload still reads `"patch": "16.11.1"`. `_load_cdragon_ratio_sidecar` now compares the payload's own `patch` against the requested one and logs a WARNING on any mismatch; `AbilitiesSnapshot.load(strict_cdragon_patch=True)` turns that into a hard drop (fail-soft to Meraki). Enforcement is default-OFF until the 16.14 re-extract lands, because dropping the stale sidecar today moves ratios on 49 of 171 champions (55 blocks / 75 fields).

---

## Git LFS (laning_scenarios artifact)

`data/daemon_slayer/laning_scenarios/**/*.json` is Git-LFS-tracked (`.gitattributes`). The full-roster `laning_scenarios_sr.json` is ~62MB and regenerates per patch; LFS keeps the git pack flat (pointer only). On a FRESH clone you need git-lfs or RC reads a 133-byte pointer and the precomputed laning coach fail-softs to live Haiku.

```
# one-time per machine after cloning:
git lfs install --local   # ABORTS "Hook already exists: post-commit" - that is BENIGN
                          # (filters + pre-push hook still configured). Do NOT --force
                          # (it clobbers the Share-sync post-commit hook).
git lfs pull              # materialize the real JSON into the working tree
```

Regenerate after a patch (the table is patch-pinned): `python -c "import core.laning_scenario_precompute as m; m.main(['--mode','sr','--champions','<csv-of-171-ability-ids>'])"` - the push auto-uploads the new content to LFS. Build tables (`build_orders_*`, `build_order_variants_*`) stay plain git (KB-sized).

---

## Vision server

```
curl http://127.0.0.1:8889/health
curl http://127.0.0.1:8889/latest-frame     # check if frames flowing
```

Vision token is in `config/vision_token.txt` (Legion). Rotate quarterly - next rotation ~2026-08-01.

---

## Local DS + match-DB MCP (:8894)

Localhost-only MCP server (`tools/ds_matchdb_mcp_server.py`) that wraps the
Daemon Slayer engine (:8893) and `data/match_history.db` as MCP tools for a
local Claude / agent: `ds_health`, `ds_rank_items`, `ds_build_order`,
`ds_archetype_for`, `match_recent`, `match_mode_stats`, `match_tft_comps`,
`match_tft_streak`. Read-only w.r.t. RC state (it never writes the match DB);
DS-down and match-DB-missing both degrade to an error dict, never crash.

```powershell
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools\ds_matchdb_mcp_server.py --show-token        # token for client config
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools\start_ds_matchdb_mcp.py                       # launch (boot wrapper)
curl http://127.0.0.1:8894/health -H "Authorization: Bearer <token>"
```

Persistence: REGISTERED and running as `RC-DS-MatchDB-MCP` (ONLOGON; see the
scheduled-tasks table above). Reinstall if ever removed:

```
schtasks /Create /TN "RC-DS-MatchDB-MCP" /SC ONLOGON /RL HIGHEST /F ^
  /TR "pythonw C:\Riot Commander\tools\start_ds_matchdb_mcp.py"
```

Client wiring (also operator-gated - editing `.mcp.json` changes a live
Claude session's own tool surface): add an `mcpServers` entry with
`"type": "http"`, `"url": "http://127.0.0.1:8894/mcp"`, and the bearer
token from `--show-token`. Full snippet in the server-file docstring.
Token resolution chain (env `RC_MCP_TOKEN` ->
`tools/mcp_token.txt` -> `tools/vision_token.txt` -> dev fallback) so one
token covers both local RC MCP servers.

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
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools\ddragon_mirror_refresh.py --check-only       # exit 1 = flip pending
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools\ddragon_mirror_refresh.py --dry-run          # plan, no writes
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools\ddragon_mirror_refresh.py                    # default - idempotent fetch
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools\ddragon_mirror_refresh.py --check-changed    # mid-patch HEAD probe
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools\ddragon_mirror_refresh.py --full             # ignore manifest, refetch all
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools\ddragon_mirror_refresh.py --version 16.10.1  # pin a version
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools\ddragon_mirror_refresh.py --workers 8        # default 8 parallel fetchers
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
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" scripts\rewind_catchup.py                # full catch-up
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" scripts\rewind_catchup.py --dry-run      # list IDs only, no writes
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" scripts\rewind_catchup.py --limit 50     # cap detail fetches
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" scripts\rewind_catchup.py --no-timeline  # skip timeline (faster)
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" scripts\rewind_catchup.py --puuid X      # override operator PUUID
```

Install the weekly Sunday 04:00 task (elevated PowerShell):

```
powershell -ExecutionPolicy Bypass -File "C:\Riot Commander\ops\install_RC_RewindCatchup.ps1"
```

Operator's play cadence is sparse (`5 games / 5 months 2026-05`), so a
weekly cadence is enough. ExecutionTimeLimit caps each run at 20 minutes.

---

## TLS certificate

Dashboard cert: `tools/regen_rc_cert.ps1` (run elevated, restarts dashboard).

Riot CA (browser-side only): `install-cert.cmd` (admin-elevated) on the game host. RC itself uses `verify=False`; only browsers need it for port 2999.

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
| `data/{aram,arena,brawl,tft}_coaching_data.json` | Current game state per mode |
| `logs/YYYY-MM-DD.log` | Daily log (30-day retention) |
| `config/vision_token.txt` | Vision server auth token |
