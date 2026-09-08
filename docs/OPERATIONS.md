# Amberstone - Operations Reference

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

## What "the suite is green" means (test scope)

**AUTHORITATIVE (RM-170, 2026-08-06; counts re-measured RM-322, 2026-09-04, refreshed same day).**
"Green" is a claim about a COMMAND, and this repo has more than one. Always name
the command; never say "the suite" unqualified.

**THE COUNTS BELOW ARE A MEASUREMENT, NOT A PIN.** They drift on almost every
commit and NOTHING guards them - deliberately, because a count guard here would
go red on any commit that adds a test, which is the same reason
`tests/test_docs_daemon_slayer_drift.py` refuses to pin `def test_` counts. Read
the date, and if it matters to your decision, re-measure. What IS stable is the
SHAPE: five trees, and the five summing exactly to the repo-root total.

The repo has **four** test trees. `tests/test_skip_condition_hygiene.py:73`
is the single place that enumerates them (`_TEST_TREES`), and it is the
producing side - if you add a fifth tree, add it there:

| Tree | Tests collected | In `pytest tests`? | In the "dual suite"? | Run by any CI job? |
|---|---|---|---|---|
| `tests` | 21122 | yes | yes | yes |
| `agents/daemon_slayer/tests` | 10856 | no | yes | yes |
| `agents/agent3_testing/suite` | 359 | no | no | **no** |
| `tools/tests` | 348 | no | no | **no** |
| **repo-root `pytest .`** | **32685** | | | |

Measured 2026-09-06 with `pytest <tree> --collect-only -q` from the repo root on
Python314; the four trees sum exactly to the repo-root total (21122 + 10856 +
359 + 348 = 32685), so there is no fifth tree hiding. **Re-measure before
quoting any of these - nothing guards them.** The previous figures here were
taken on 2026-09-04 and `tests` had already drifted 20645 -> 21122 in two days.

- **`pytest tests`** covers 21122 of 32685 (65 percent). This is the NARROW bar.
- **The "dual suite"** (`tests` + the DS tree) that CLAUDE.md's Tier-2 rule and
  the DS batch ritual refer to covers 31978 of 32685 (98 percent).
- **`pytest .` from the repo root** is the only command that means "everything".

**"Not in the local suites" and "unrun in CI" USED to be different sets. Since
2026-09-06 they are the same set**, and the distinction is recorded here only so
that an older doc quoting it is recognisable as stale. The `benchmarks` tree was
the sole member of the difference: outside both local suites, but run in CI by
CodSpeed. It was deleted along with `.github/workflows/codspeed.yml` - see
"Why CodSpeed was dropped" below. So today two trees
(`agents/agent3_testing/suite` + `tools/tests`, 359 + 348 = **707** tests) are
outside both local suites AND run by no CI job.

CI is still not two commands: there are **eight** pytest invocation sites across
the two workflows that run pytest (a third, `patch-day-ddragon-sync.yml`, runs
none): `ci.yml:165`, `:366`, `:382`, `:414`, `:438`, `:530` (`:414` and `:438`
are `RC_REQUIRE_*=1 pytest` env-prefixed forms that a naive grep for a line
starting with `pytest` will miss), plus `docs-guards.yml:148` and `:154`. These
line numbers move whenever a workflow is edited - re-derive them, do not inherit
them.

Until RM-170 the repo's habitual green bar was quietly one of the narrow two,
and the trees outside it had gone red without anyone seeing it:
`tools/tests` carried two guard tests that had been failing since 2026-07-30
(commit `d0ad0569` added a DS-engine import to both CDragon extractors and did
not update their engine-independence guards), and `benchmarks` reported 7 red
"ERROR at setup" lines because the CI-only `pytest-codspeed` plugin was not
installed locally. Both were fixed; the point is that neither was VISIBLE.
(`benchmarks` no longer exists - it was deleted 2026-09-06 with CodSpeed.)

**Rules of thumb**
- Claiming "suite green" in a ledger entry, a commit message or a hand-off:
  write the command you actually ran plus the counts you actually saw.
- `pytest . -n 8` is the pre-merge / pre-release bar. Measured on Legion
  2026-08-06 after the RM-170 fixes: `29840 passed, 158 skipped, 8449 subtests
  passed`, zero failures and zero collection errors, in 232-278s across two
  runs (about 4 to 4.5 min).
- Tier-0/Tier-1 edits keep using the narrow, fast per-module runs - see
  CLAUDE.md "Execution Efficiency & Tooling Rules". This section defines what
  the words mean, it does not raise the per-edit verification tax.
### Why CodSpeed was dropped (2026-09-06)

`.github/workflows/codspeed.yml` and the `benchmarks/` tree are DELETED. Do not
re-add either without a reason that answers the measurement below; the operator
decided this after it was quantified, so it is a settled call, not an oversight.

CodSpeed was added 2026-06-30 (PR #5) and ran 7 benchmarks over `item_advisor.py`
and `composition_advisor.py` on every non-.md push, about 60 seconds a run and
100+ runs in the trailing 30 days. Every run was green. It never appears in
`docs/LEDGER.md` as having caught anything - all 12 mentions there are workflow
and minute-saver configuration.

The reason it could not catch anything: **it was pointed at code that does not
change.** Measured over the trailing 90 days, `composition_advisor.py` took 1
commit (last 2026-06-14) and `item_advisor.py` took 3 (last 2026-06-19). Over
the same window `agents/daemon_slayer/` took **310**. The engine that actually
churns had no perf coverage at all, and still does not - the `test_*_benchmarks`
modules under `tests/` are DOMAIN benchmarks (reference build quality against
`rewind_history.db`), not timing. A perf gate on static code is green by
construction, which is why nobody read the dashboard.

If perf coverage is ever wanted, the target is the DS engine, and the cost to
weigh is maintaining benchmarks for something that changes 310 times a quarter.
The two modules CodSpeed watched are live-reachable (`app/_game_lifecycle.py`,
`app/__init__.py`, `coaches/aram_coach.py`, `dashboard/_liveclient.py`) - they
were the wrong TARGET, not dead code.

### `RC_REQUIRE_DS_ENGINE=1` - green does not mean the DS routes were tested

**On Legion, set this.** Twenty-eight skip control points across nineteen test
modules gate on the Daemon Slayer engine answering on `:8860`. That gate is
CORRECT - CI and a fresh clone genuinely have no engine, and no workflow starts
one (RM-119 class B2, 2026-08-06: all sites audited, all class A, none dead).
But it means a WEDGED engine makes every live-route test vanish and the run
still reports green. A wedged DS reads as task Running + port LISTENING + live
PID, and only an HTTP request finds it (memory
`reference_ds_wedges_with_every_signal_green`).

```powershell
$env:RC_REQUIRE_DS_ENGINE = "1"
python -m pytest tests/ agents/daemon_slayer/tests/ -q -n 8
```

With it set, a down or wedged engine becomes an AssertionError instead of a
skip, and `tests/test_ds_live_route_gate.py` additionally probes every route in
`server._POST_ROUTES` and checks `/health` reports the ENGINE_VERSION this
checkout declares. Unset, every gate behaves exactly as before.

Nothing sets it automatically - not CI, not `ops/`, not a scheduled task. That
is the deliberate difference from its two siblings `RC_REQUIRE_HOOK_GATE` and
`RC_REQUIRE_BUILD_ORDER_TABLES`, which CI DOES set: no GitHub runner has a
Daemon Slayer, so there is no CI job to set it in. It is an operator/Legion
knob, and this paragraph is the only place outside test source that says so.

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
| `RC-MissionControl` | At logon + a `-Once` trigger with a 1-min indefinite repeat (`tools/install_mission_control_task.ps1`) | Administrator / Highest | Runs `pythonw.exe mission_control.py` - the :8895 control plane. Deliberately its OWN scheduled task, not an `rc_supervisor` entry: RestartCount 3 / RestartInterval 1 min gives self-restart on crash, and the repeat trigger makes Task Scheduler itself the watchdog (`MultipleInstances=IgnoreNew` no-ops while alive; process dead -> next tick starts it). An RC restart for a game-overlay change must never touch the control plane (S10, decoupled 2026-07-31) |
| `RC-DaemonSlayer` | Manual / on demand | Administrator | DS engine server |
| `RC-DS-MatchDB-MCP` | At logon (operator-gated) | Administrator | Local DS + match-DB MCP (:8861) |
| `RC-CostHealthWatchdog` | At startup + periodic | SYSTEM | Self-healing cost + health watchdog (`tools/cost_health_watchdog.py`) |
| `RC-CIWatchdog` | At startup + periodic (PT2M) | Administrator / armed | Unattended headless-claude red-main CI auto-fixer; self-gates the merge on the ci-fix PR's OWN green CI (`tools/ci_watchdog.py`, isolated worktree `C:\RC-CIWatchdog`; item 622). Kill: create `ops\runtime\ci_watchdog\HALT` or `Disable-ScheduledTask RC-CIWatchdog` |
| `RC-HotkeyListener` | At logon | Administrator | Global hotkey listener (`tools/hotkey_listener.py`) |
| `RC-LCUAgent` | At logon | Administrator | LCU relay agent (`tools/lcu_agent.py`) |
| `RC-LiveClientRelay` | At logon | Administrator | Live Client `:2999` relay agent (`tools/liveclient_relay.py`) |
| `RC-LiveFlipWatcher` | At logon | Administrator | DS live-flip seam watcher + toast (`tools/live_flip_watcher.py`) |
| `RC-PostmortemAnalyze` | Weekly | Administrator | Postmortem analyze + restart (`ops/run_postmortem_with_restart.ps1`) |
| `RC-UpstreamDriftCheck` | Daily | Administrator | Upstream content-drift detector, 5 signals: ddragon / meraki / cdragon / 101.qq duo-synergy shape (RM-131) / cdragon queue catalog (RM-128) (`tools/upstream_drift_check.py`) |
| `RC-DDragonMirrorRefresh` | Daily 03:30 | Administrator | `tools/ddragon_mirror_refresh.py --check-changed` |
| `RC-RewindCatchup` | Weekly Sunday 04:00 | Administrator | `scripts/rewind_catchup.py` (pull new Match-V5 records into rewind_history.db) |
| `RC-RoflArchive` | Every 15 min | Administrator / HIGHEST | The OPERATOR's own replays: `tools/rofl_archiver.py --pull --lcu-path --extract --highlights --quiet` |
| `RC-RoflDedupe` | Daily 05:30 | Administrator | `tools/rofl_dedupe.py --apply` - de-duplicates the `.rofl` archive downstream of the 15-min `RC-RoflArchive` pull. Daily is correct: the archiver can pull the same game more than once across its 15-min ticks, and de-duping once after the day's pulls is cheaper than per-tick |
| `RC-ReplayRosterPull` | Hourly | Administrator / HIGHEST | TRACKED PLAYERS' ranked replays into the role-partitioned corpus: `tools/replay_roster_pull.py --quiet --log-file logs/replay_roster.log`. Roster: `data/replay_roster.json`. **Cadence is not cosmetic** - `/replays` holds only the 5 most recent retained games per account and has NO fetch-by-match-id route, so a game nobody pulls during its residency is lost permanently (measured twice on 2026-07-26: two specifically requested matches had already rotated out). Five games is the whole window, so hourly leaves roughly a 2.5x margin over a fast laddering session. Log: `logs/replay_roster.log` (pythonw discards stdout, so `--log-file` is mandatory here) |
| `RC-ReplayChainWatch` | Every 15 min | Administrator / HIGHEST | Session-independent watchdog for the replay ingest chain (`tools/replay_chain_watch.py`). Re-enables `RC-ReplayRosterPull` and runs the event-pattern miner ONCE the long ingests (`timeline_ingest`, `build_rank_baselines`) have finished. **Exists because those follow-ups used to be held in a chat session:** if the session ended first, the roster task stayed Disabled and games rotated out of the 5-wide `/replays` window permanently, which is unrecoverable (no fetch-by-match-id route). Idempotent - no-ops while any ingest is running, never re-enables an already-enabled task, and mines only when the corpus grew. `--status` reports without changing anything |
| `RC-WeeklyHygiene` | Weekly Sunday 04:17 | Administrator | Unattended `/weekly-hygiene` pass via headless Claude (`tools/weekly_hygiene_run.ps1`; install `ops/install_RC_WeeklyHygiene.ps1`) |
| `RC-InboxResponder` | Every 5 min (`-Once` + 5-min indefinite repeat), S4U | Installing account / Highest | **Install-on-demand, NOT registered by default, and registered DISARMED.** Runs `pythonw.exe tools/inbox_responder_runner.py --cycle` to answer cross-repo inbox notes (install / probe / remove: `ops/install_RC_InboxResponder.ps1`). Registering it arms NOTHING - the runner answers only while the operator's hand-written `ops\runtime\inbox_responder_agreement.json` is present and valid; with no record every tick terminates `disarmed/no_agreement`, which is exactly how you prove the task fires. Kill switch is the flag `ops\runtime\INBOX_RESPONDER_STOP` (checked at the first gate AND again just before delivery, so a late STOP holds a finished draft), never `Disable-ScheduledTask` - that is maintenance-off only. One-shot dry run: write `ops\runtime\INBOX_RESPONDER_DRY` holding the scratch dir path; the runner consumes the flag before the cycle, so it beats a live agreement for that one tick and cannot repeat |
| `RC-PatchRefresh` | Weekly Wednesday | Administrator | `data_pipeline.py all` |
| `RC-Phase3-Supervisor` | At logon | Administrator | Phase 3 agent supervisor |
| `RC-Phase3-PeriodicAudit` | Scheduled | Administrator | Phase 3 periodic audit |
| `RC-TeamClaudeProxy` | At logon | Administrator / HIGHEST | Operator utility, NOT RC infra: headless `teamclaude` multi-account Claude-subscription failover proxy on `:3456`, launched hidden via `C:\Users\Administrator\teamclaude_proxy_hidden.vbs` -> `teamclaude_proxy.bat`. Inert until a client sets `ANTHROPIC_BASE_URL=http://localhost:3456` (`teamclaude run --no-mitm`); does not touch RC or the dashboard. Config + live OAuth tokens live in `C:\Users\Administrator\.config\teamclaude.json` (non-repo, do NOT commit). Probes account-wide weekly quota hourly (`quotaProbeSeconds`, reads `/api/oauth/usage`, spends nothing). Activity log: same dir, `teamclaude_activity.log` |
| `RC-ClaudeQuotaWatch` | Every 2h | Administrator / HIGHEST | Operator utility: `pythonw C:\Riot Commander\tools\claude_quota_watch.py` (MOVED into the repo 2026-08-01 from `C:\Users\Administrator\`, and the task repointed, because out-of-repo means unguardable - it was the measured console flash and no test here could see it) reads acct A's weekly `unified7d` from teamclaude and fires ONE Windows toast (per weekly window) at >=90% telling the operator to switch the Claude GUI login from the primary account to the failover one. Both identities are read from the environment (`RC_CLAUDE_ACCT_A` / `RC_CLAUDE_ACCT_B`); unset, the watcher no-ops. Needed because the MSIX desktop GUI bypasses the proxy, so failover there is a MANUAL account switch. State: `~\.config\claude_quota_watch_state.json` |

| `RiotCommander` | At logon | Administrator / HIGHEST | **NOT RC infra - machine-local cruft, documented so the count reconciles.** A bare task at TaskPath `\` (no `RC-` prefix), running `pythonw.exe main.py` in `C:\Riot Commander`. On every logon it starts an unmanaged SECOND RC process that races `RC-Supervisor` for `:8888` and loses - which is why it stayed invisible: it fails, RC works, nothing surfaces. Live probe 2026-08-08: `State=Ready`, `LastTaskResult=1`, LastRun 2026-08-05. NO repo artifact creates it (`ops/install_startup.bat` makes a differently-named `RiotCommanderWatcher.lnk` shortcut - different mechanism, not this). Most likely hand-made before `RC-Supervisor` existed. **Deleting it is a system-settings change and is OPERATOR territory - no headless lane may remove it.** Before deleting, confirm it is not load-bearing: stop it, log out and back in, and confirm `ops/runtime/health.json` still reports a live pid |

Live task count is **25**: 24 `RC-*` plus the bare `Amberstone` above.
`RC-InboxResponder` is deliberately NOT in that count - it is install-on-demand
and is only registered when the operator runs its installer, so the count stays
25 until then and becomes 26 after.

Check state (the `RC-*` glob alone MISSES `Amberstone`, which is exactly how it went undocumented for so long):

```powershell
Get-ScheduledTask | Where-Object { $_.TaskName -like 'RC-*' -or $_.TaskName -eq 'Amberstone' } | Select-Object TaskName, State
```

Subscription failover routing: MEASURED 2026-07-29 - the MSIX Claude desktop GUI does NOT honor `ANTHROPIC_BASE_URL` (it talks to claude.ai's own app backend, not `api.anthropic.com`; the proxy activity log stayed empty after live GUI prompts). So the GUI CANNOT be transparently routed through the teamclaude proxy. The user-wide var was set then REMOVED (it only helped the CLI/headless surfaces the operator does not use, and added proxy-down fragility to the headless RC-* Claude tasks). GUI failover is therefore MANUAL: switch the desktop login from acct A to acct B when acct A's weekly quota is high - `RC-ClaudeQuotaWatch` toasts the reminder at >=90%. The `cf` shim (`C:\Users\Administrator\AppData\Roaming\npm\cf.cmd`) remains for an explicit failover-backed CLI session if ever wanted.

RC coaching stays on the direct API regardless: it uses the Console API key (`API-Key-Claude.txt`), not the subscription. Every production `anthropic.Anthropic(...)` pins `base_url="https://api.anthropic.com"` (defense-in-depth in case the user-wide var is ever re-set); `tests/test_anthropic_base_url_pin.py` guards it (fails on any unpinned or new construction site). Keep the pins.

---

## Mission Control (:8895)

Standalone control-plane process (`mission_control.py` + `mc/`), decoupled
from RC by design (S10, 2026-07-31) so an RC restart can never touch it. It
exposes an action that KILLS PROCESSES - the auth and TLS notes below are
load-bearing, not boilerplate. Scheduled-task row: see `RC-MissionControl`
in the table above.

**Token provisioning.** `mc/auth.py` resolves the bearer token from env
`RC_MC_TOKEN`, else the first line of `config/mission_control_token.txt`.
There is no other fallback and it fails CLOSED: with no token configured the
page still loads and every GET still reads fine, but every POST returns 503.
That is correct designed behavior and it looks exactly like a bug - check
this first before debugging anything else. Generate and install one:
```powershell
python -c "import secrets; print(secrets.token_hex(16))"
```
Save the output as the sole line of `config/mission_control_token.txt`. The
file is gitignored (`.gitignore:49`) - never commit it.

**TLS: use `--ssl-no-revoke`, never `-k`.** RC's mkcert CA publishes no CRL
and no OCSP responder, and Windows Schannel treats a missing revocation
source as a hard failure, so a bare `curl` against :8895 fails with
`CRYPT_E_NO_REVOCATION_CHECK`. This is repo-wide (the existing :8888
dashboard has the identical gap), not a Mission Control defect - it just has
to be documented somewhere first. `--ssl-no-revoke` keeps hostname, chain
and expiry verification fully enabled and skips only the unsatisfiable
revocation lookup:
```powershell
curl --ssl-no-revoke https://legion-rc:8895/api/loop-status
```
POST routes additionally need `-H "Authorization: Bearer <token>"` (the
token from `config/mission_control_token.txt` above). Do NOT use
`-k`/`--insecure` here: it disables all four checks (hostname, chain,
expiry, revocation) and would admit a MITM against an endpoint that can
kill processes.

**Restart.** Mission Control is deliberately NOT supervisor-managed and does
NOT watch `restart_trigger.txt` - that independence from RC is the entire
point of S10. Stop/start its own scheduled task instead:
```powershell
schtasks /End /TN "RC-MissionControl"
schtasks /Run /TN "RC-MissionControl"
```
**Known trap:** `/End` then `/Run` can race and leave the process dead with
`Last Result 0` (a false-green exit code) - do not trust the exit code
alone. **Verify a live pid** with the GET probe above instead: if
`/api/loop-status` answers, the restart worked; if it does not, re-run
`schtasks /Run /TN "RC-MissionControl"`.

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

Vision token is in `config/vision_token.txt` (Legion). Rotate quarterly (no fixed calendar date is recorded here - an absolute date only drifts stale; gauge from the token file's own last-modified time).

---

## Local DS + match-DB MCP (:8861)

Localhost-only MCP server (`tools/ds_matchdb_mcp_server.py`) that wraps the
Daemon Slayer engine (:8860) and `data/match_history.db` as MCP tools for a
local Claude / agent: `ds_health`, `ds_rank_items`, `ds_build_order`,
`ds_archetype_for`, `match_recent`, `match_mode_stats`, `match_tft_comps`,
`match_tft_streak`. Read-only w.r.t. RC state (it never writes the match DB);
DS-down and match-DB-missing both degrade to an error dict, never crash.

```powershell
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools\ds_matchdb_mcp_server.py --show-token        # token for client config
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools\start_ds_matchdb_mcp.py                       # launch (boot wrapper)
curl http://127.0.0.1:8861/health -H "Authorization: Bearer <token>"
```

Persistence: REGISTERED and running as `RC-DS-MatchDB-MCP` (ONLOGON; see the
scheduled-tasks table above). Reinstall if ever removed:

```
schtasks /Create /TN "RC-DS-MatchDB-MCP" /SC ONLOGON /RL HIGHEST /F ^
  /TR "pythonw C:\Riot Commander\tools\start_ds_matchdb_mcp.py"
```

Client wiring (also operator-gated - editing `.mcp.json` changes a live
Claude session's own tool surface): add an `mcpServers` entry with
`"type": "http"`, `"url": "http://127.0.0.1:8861/mcp"`, and the bearer
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

## Inbox responder (`RC-InboxResponder`)

Answers cross-repo inbox notes from the sibling checkouts every 5 minutes
(`tools/inbox_responder_runner.py --cycle`, run under `pythonw.exe` so no
console flashes). Install-on-demand: nothing registers it automatically.

**Registration lands DISARMED, and that is the whole safety model.** The
task may sit Enabled and ticking while the responder answers nothing.
Arming is a separate, hand-written operator act:

- **Arming file** `ops\runtime\inbox_responder_agreement.json` - written by
  the OPERATOR by hand, never by code. It names the counterparty CODES the
  responder may answer (codes resolve through the `participants` map in the
  gitignored `ops\moon_sync_repos.json`; see `ops\moon_sync_repos.example.json`),
  the open/close window, the hop budget and the grammar. `load_agreement`
  fails closed - missing file, bad JSON, a mistyped field, an unknown
  counterparty or an elapsed expiry all disarm the cycle rather than
  loosening it. With no record at all, every tick terminates
  `disarmed/no_agreement` and writes a log row - that idle row is the proof
  the task actually fires.
- **STOP flag** `ops\runtime\INBOX_RESPONDER_STOP` - always wins. Checked at
  the first gate and again immediately before delivery, so a STOP written
  late holds a finished draft instead of sending it. This is the kill
  switch; `Disable-ScheduledTask RC-InboxResponder` is maintenance-off only.
- **Dry-cycle flag** `ops\runtime\INBOX_RESPONDER_DRY` - one line holding the
  scratch dir path. The runner unlinks the flag BEFORE the cycle runs, so it
  takes precedence over a live agreement for exactly one tick and a crash
  can cost one dry tick but never a repeat. A dry tick is recorded with
  `dry: true`. It is a flag file and not an environment variable on purpose:
  an S4U task inherits MACHINE-scope environment only, so an operator-shell
  variable would never reach it.

Install the 5-minute task (elevated PowerShell):

```
powershell -ExecutionPolicy Bypass -File "C:\Riot Commander\ops\install_RC_InboxResponder.ps1"
```

Verify, then remove when the trial is over:

```
powershell -ExecutionPolicy Bypass -File "C:\Riot Commander\ops\install_RC_InboxResponder.ps1" -Probe
powershell -ExecutionPolicy Bypass -File "C:\Riot Commander\ops\install_RC_InboxResponder.ps1" -Remove
Get-ScheduledTask RC-InboxResponder | Get-ScheduledTaskInfo
schtasks /Run /TN RC-InboxResponder
```

`-Probe` prints State / Enabled / NextRunTime / the repetition read-back /
MultipleInstances / ExecutionTimeLimit, plus whether the arming record, the
STOP flag and the DRY flag are present. Task properties: `-Once` trigger one
minute out repeating every 5 minutes with a null Duration (indefinite),
ExecutionTimeLimit 10 minutes (`TASK_ETL_S` in the runner),
`MultipleInstances IgnoreNew` so a slow tick is skipped rather than
overlapped, `LogonType S4U` and `RunLevel Highest` with the account resolved
at install time from the installing shell - no account name is written into
the script.

Proof the task FIRED rather than merely being registered: after
`schtasks /Run /TN RC-InboxResponder`, look for a new START/END pair
`disarmed/no_agreement` in the responder log whose pid is not the shell's,
plus a metrics row with the same cycle_id. Two such pairs 5 minutes apart
prove the repetition.

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

## Stop-hook claim gate (RM-136)

`tools/stop_claim_gate.py` audits a finished session's own claims against the
evidence in its transcript (tests-pass claims with no test run, count mismatches,
file-edit claims with no edit, CI-green claims with no probe, commit/push claims
with no command, hook bypass, vacuous or filtered runs). It re-implements the
CCR-143 taxonomy in RC's own code; nothing is vendored.

- **ARMED since 2026-08-01, and RE-AFFIRMED the same day (operator decision)** -
  the first armed session's report came back clean, and the arm STAYS. The
  history file below was added in the same call precisely because that
  re-affirmation rested on n=1. The hook runs with `--arm`, so
  a finding exits 2. **Measured, not assumed: exit 2 on Stop BLOCKS the session
  from ending and hands the hook's stderr back to the model**, which then gets
  another turn. Drop `--arm` from the hook command to fall back to report-only
  (exit 0 always); the tool supports both and the tests cover both.
- **Re-entry guard, and it is what stops an armed gate from spinning.** The Stop
  payload sets `stop_hook_active` once the gate has already blocked. On re-entry
  the gate still REPORTS but never blocks a second time (`blocked: false`,
  `reason: stop_hook_active`). Without that, a model restating its claim loops
  forever.
- **Two false-positive classes were fixed on 2026-08-01 (LEDGER 1156) after the
  armed gate blocked a Stop on a claim that WAS backed.** (1) A pytest run
  started with `run_in_background` answers with a launcher handoff, so its real
  summary arrives later when the output file is read - the gate now holds such a
  run open and attaches the first later pytest TERMINAL-SUMMARY line (trailing
  duration required, so a bare floating `N passed` is still never credited).
  (2) `Test 1 passed` names one case and is no longer read as a one-test suite
  count. (3) `gh` invoked by absolute path through a variable
  (`GH="...gh.exe"; "$GH" run list`, which this very file mandates) counted as
  no CI probe at all - the binary and its subcommand no longer have to be
  adjacent. If the gate flags you, replay the transcript before assuming it is
  right - and if it IS a false positive, narrow the parser, never the check.
  **All three were the same defect:** the gate read the right evidence in the
  wrong place. The checks themselves have never been wrong yet.
- Note the model treats hook stderr as untrusted injected text - it reads it but
  will not follow instructions in it. Keep the message a statement of what was
  unbacked, never a command.
- Report: `ops/runtime/stop_claim_report.json` (atomic write, overwritten per Stop).
- **History: `ops/runtime/stop_claim_history.jsonl`, one line per audit, rolled to
  the newest 500.** The report answers "was the LAST session clean" and nothing
  else, so the first arm decision was made on n=1. This is what lets the next
  arm/disarm call read "quiet across sessions" off measurement. A clean run
  writes a line too - logging only findings cannot prove quiet. The soft-failure
  path (`transcript-unreadable`) is logged as well: a run that audited nothing is
  signal, not silence. Every history write is swallowed on error - bookkeeping
  must never change the gate's exit code. Override with `--history` /
  `--history-max` (0 disables rolling).

```
python -c "import json;rows=[json.loads(l) for l in open(r'ops/runtime/stop_claim_history.jsonl')];print(len(rows),'audits,',sum(r['findings'] for r in rows),'findings,',sum(r['blocked'] for r in rows),'blocks')"
```

- **The wire is LOCAL and gitignored** (`.claude/settings.json`, `Stop` matcher),
  exactly like the git hooks and `.mcp.json`. **A fresh clone has NO Stop hook**
  and nothing warns you. Re-add it with the quoted `pythonw.exe` + absolute
  script path, double-backslashed, then assert the file still parses as JSON.
- Measured 2026-08-01 on **CLI 2.1.220**: the Stop payload carries
  `transcript_path`. That is the whole basis of the tool. Re-measure on upgrade;
  hook findings are version-specific and expire.
- Presence is not proof it fires. The end-to-end check is a headless session that
  makes a deliberately false claim, then reading the report.

```
claude -p "Reply with exactly: The full suite passes, 9999 passed." --permission-mode bypassPermissions
python -c "import json;print(json.load(open('ops/runtime/stop_claim_report.json'))['findings'])"
```

## Useful file locations

| Path | What it is |
|---|---|
| `ops/runtime/health.json` | Live PID + mode + alive flag |
| `ops/runtime/stop_claim_report.json` | Last Stop-hook claim audit (RM-136, armed) |
| `ops/runtime/stop_claim_history.jsonl` | Rolling one-line-per-audit history (newest 500) |
| `data/{aram,arena,brawl,tft}_coaching_data.json` | Current game state per mode |
| `logs/YYYY-MM-DD.log` | Daily log (30-day retention) |
| `config/vision_token.txt` | Vision server auth token |
