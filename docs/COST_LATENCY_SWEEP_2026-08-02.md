# S5 - Runtime cost / latency sweep (7 levers)

Read-only audit, 2026-08-02. Every claim below was probed against the live tree
or the live machine; docs were used only to cross-check, never as evidence.

Live measurement window for all log-derived rates: `logs/2026-08-02.log`,
17:29:14 -> 18:14:53 = 2739 s, 12516 lines.

---

## Roll-up

| # | Lever | Verdict | Evidence | Proposed fix |
|---|---|---|---|---|
| 1 | Prompt-cache coverage | CLEAN | 21 runtime `messages.create()` sites enumerated; 13 carry `cache_control: ephemeral`, 6 are below-threshold user-only prompts already documented exempt, 2 are image-first vision calls with no stable prefix, 1 is the tracking shim | none |
| 2 | Route TTL | FINDING | `/api/health/all` (`dashboard/routes_state.py:1142` -> `:328`) has no cache and re-parses the whole 4.6 MB `agents/state/task_queue.jsonl` on every hit; measured 43.8 ms live, of which 41.4 ms is that parse | memoize `_agent6_audit_outcomes` on (mtime_ns, size) - exact, not a TTL |
| 3 | Polling cadences | CLEAN | Every network poll is >= 500 ms; the only sub-500 ms sleeps in the tree are local-device or bounded-retry, not network | none |
| 4 | Log spam | FINDING | `_SUPPRESS_LOG_PATHS` needles themselves are clean (no trailing space, guard test asserts it) and no single HTTP path exceeds 0.42/s. But 762 of 813 WARNINGs (93.8 %) in 45 min come from one benign line, `dashboard/routes_ds_relscore.py:253` | demote to `log.debug` + cache the negative result |
| 5 | Model tier | CLEAN | Every live coach `messages.create()` pins `claude-haiku-4-5-20251001`; the only Sonnet/Opus in runtime code is vision (`modes/shared_vision.py:99`) and the Phase-3 dev-agent roster (`agents/_supervisor_common.py:46`), both charter-scoped | none |
| 6 | Scheduled-task catalog | CLEAN | 24 live RC-* tasks == 24 documented in `docs/OPERATIONS.md` == 24 with an existing owning file on disk. Zero orphans, zero ghosts | none |
| 7 | Bundle parity | CLEAN | 64 files in `web/css/panels/` == 64 `@import './panels/...'` in `web/css/dashboard.css`; `tests/test_dashboard_css_panel_imports_parity.py` run fresh: 4 passed in 0.20 s | none |

---

## Lever 1 - prompt-cache coverage (CLEAN)

Enumerated by `grep messages.create` across the repo, excluding `docs/_archive/`,
`docs/*.md`, `tests/` and `agents/*/suite/`. 21 runtime call sites in 15 files.

COVERED (carries `cache_control: {"type": "ephemeral"}` on the stable system prefix):

| Call site | Marker |
|---|---|
| `coach_integration/_coach.py:377` | `:384` |
| `coaches/replay_coach.py:218` | `:222` |
| `coaches/experimental_builder.py:214` | `:218` |
| `coaches/champ_select_coach.py:130` | `:134` |
| `coaches/brawl_coach.py:488` | `:491` |
| `coaches/arena_coach.py:793` | `:796` |
| `coaches/aram_team_analyzer.py:201` | `:205` |
| `coaches/aram_coach.py:1078` | `:1082` |
| `agents/agent7_context/warm_session.py:154` | `:159` |
| `vision_server/_inference.py:150` | `:153` |
| `vision_server/_inference.py:185` | shares `_VISION_PROMPT` block, `:10` |
| `tft/tft_coach_engine.py:701` | `:705` |
| `tft/tft_pbe_engine.py:434` | `:438` |

EXEMPT - user-only prompt, no system block, static portion far below the cache
minimum. Each of these already carries an in-source item-286 exemption note or
passes `system=""` explicitly:

| Call site | Why exempt |
|---|---|
| `coaches/arena_coach.py:928` | `system=""` at `:933`; short augment-select prompt |
| `coaches/arena_coach.py:1067` | `system=""` at `:1072`; short anvil prompt |
| `coaches/aram_coach.py:1274` | `system=""` at `:1279`; short augment-select prompt |
| `tft/tft_live_analysis.py:302` | item-286 note at `:73` - static portion ~669 tok, below threshold |
| `tft/tft_live_analysis.py:337` | item-286 note at `:121` - static portion ~51 tok |
| `coaches/aram_coach.py` build block | item-286 note at `:422` - static portion ~62 tok |

EXEMPT - image-first, no cacheable prefix exists:

| Call site | Why exempt |
|---|---|
| `modes/shared_vision.py:378` | content list is `[image, text]`; the image block is first and changes every call, so no stable prefix precedes the prompt - a marker would never hit |
| `tft/tft_vision_reader.py:186` | same shape, `[image, text]` with `_EXTRACT_PROMPT` after the image |

EXEMPT - infrastructure, not a call:

| Site | Why |
|---|---|
| `core/anthropic_client.py:72,88` | the cost-tracking shim that rebinds `messages.create`; it forwards kwargs untouched |

No net-positive fix. Moving the prompt ahead of the image in the two vision
sites would enable caching in principle, but the prompt is the smaller half and
reordering a working vision transport for a marginal cache hit is a fidelity
risk, not a saving.

## Lever 2 - route TTL (FINDING)

The TTL discipline is broadly good: 11 route modules carry a module-level
`_CACHE` + `_CACHE_TTL_S` (`routes_item_wpa.py:69`, `routes_champ_benchmarks.py:53`,
`routes_duration_winrate.py:39`, `routes_cc_pairing.py:85`, `routes_duo_synergy.py:79`,
`routes_cc_conditional_pressure.py:133`, `routes_ds_sweep.py:89`,
`routes_ds_statcheck.py:66`, `routes_cc_blended_ehp_threat.py:112`,
`routes_ds_relscore.py:91`, plus the shared `/api/state` TTL at
`routes_state.py:92-136`).

The gap is `/api/health/all`.

- Registered `dashboard/routes_state.py:1142`, handler body `:328-397`.
- No `_CACHE` of any kind on this route.
- Every request calls `_agent6_audit_outcomes()` (`routes_state.py:370` ->
  definition `:28-58`), which does `q.read_text(...).splitlines()` over the
  ENTIRE `agents/state/task_queue.jsonl` and `json.loads` every line, to return
  the last 3 matching events.
- Measured file: 4,645,089 bytes / 5,813 lines.
- Measured parse cost standalone: 41.45 ms.
- Measured live route latency: 43.8 / 43.6 / 43.4 ms (three consecutive
  `curl -sk https://127.0.0.1:8888/api/health/all`). The parse is ~95 % of it.
- Measured call rate: 366 hits in the 2739 s window = 0.134/s (two open
  dashboard tabs at the `main.js:7548` 15 s cadence, plus `tools/rc_facts.py:119`).
- Therefore: ~1.68 GB of file reads and ~15 s of CPU per 45 minutes, to answer a
  question whose input changes maybe twice a day. The file is append-only and
  only grows, so this cost is monotonically increasing.

The fix is NOT a TTL. A TTL on health would be a fidelity trade (stale health is
exactly the thing you do not want stale). The correct fix is exact memoization
on the file's identity - see the ship-first section.

Also noted and rejected: `/api/vision-state` (`dashboard/routes_diag.py:29-33`,
registered `:273`) is polled at 500 ms from two independent places at once
(`web/js/main.js:6091` and `web/js/panels/active_match.js:1670`), so 4 Hz total.
It is a single small `read_json` + `json.dumps`; a TTL would save a negligible
amount and introduces a staleness question on live fog-of-war data. Not worth it.

## Lever 3 - polling cadences (CLEAN)

No network poll under 500 ms anywhere.

Frontend `setInterval` histogram over `web/js/`: 500, 1000, 2000 x3, 3000, 4000,
10000, 15000 x3, 20000. The three 500 ms timers were each opened and checked:

- `web/js/main.js:1581` `applyStaleness` - UI-local only, recomputes DOM classes
  from already-fetched timestamps. No fetch. Not a network poll.
- `web/js/main.js:6091` `refreshVisionOverlay`, `VT_INTERVAL_MS = 500` (`:5969`) -
  network, exactly 500 ms, not under.
- `web/js/panels/active_match.js:1670`, `_AM_TICK_MS = 500` (`:1565`) - network,
  exactly 500 ms, not under.
- `web/js/main.js:5901` `MINIMAP_INTERVAL_FAST = 500` - the fast branch is 500 ms,
  the idle branch 2000 ms.

Python side, every sub-500 ms sleep in `core/ dashboard/ app/ ops/ agents/ modes/
vision_server/ coaches/ tools/` was opened:

| Site | Value | Classification |
|---|---|---|
| `core/hotkeys.py:84` | 0.05 | local keyboard state poll, no socket |
| `core/riot_api.py:184` | 0.05 | rate-limiter wait loop, in-process, bounded by a deadline |
| `dashboard/routes_vision_calibrator.py:146` | 0.05 | local capture wait |
| `tools/screen_agent.py:190` | 0.05 | one-shot bettercam cold-start retry, not a loop |
| `agents/_supervisor_common.py:227` | 0.06 | `os.replace` PermissionError retry, max 3 |
| `tools/lcu_agent.py:98` | 0.1 | `BENCH_CMD_FAST_INTERVAL`; used at `:1705` only in the `fast` branch after a latency-sensitive batch drains. Idle drains sleep the full `CMD_INTERVAL = 0.5`. Deliberate, bounded, documented at `:93-97` |
| `ops/rc_self_monitor.py:987` | 0.2 | result-file wait, bounded |
| `ops/rc_supervisor.py:453,936` | 0.25/0.2 | process wait loops |
| `ops/rc_transactional_deploy.py:45,87,91,95,111` | 0.2-0.25 | deploy-time only, not steady state |
| `tools/pseudo_screen_overlay.py:106,147` | 0.25/0.4 | local overlay redraw |

Nothing to fix.

## Lever 4 - log spam (FINDING, but not in the needles)

The item-171 trap was checked specifically and is NOT present.
`dashboard/_handler.py:125-137` declares 11 needles; every one is a bare prefix,
none ends with a space, so query-string variants like
`/api/minimap-crop?mode=sr` still match the `needle in msg` substring test at
`:143-145`. `tests/test_handler_log_spam_suppress.py:59-63` asserts exactly that
(`assertFalse(needle.endswith(" "))`) and `:56` pins the set.

Measured per-path HTTP log rates over the 2739 s window - the ceiling is
0.415/s, comfortably under the ~1/s bar:

| Path | Lines | Rate |
|---|---|---|
| `GET /data/ddragon/16.15.1/img/champion/Caitlyn.png` | 1136 | 0.415/s |
| `GET /api/ds-relscore` | 768 | 0.280/s |
| `GET /api/health/all` | 366 | 0.134/s |
| `GET /api/home/summary` | 275 | 0.100/s |

So the needle list itself is CLEAN.

The finding is on a different channel. Level counts for the window:
11470 DEBUG / 278 INFO / 813 WARNING. Of the 813 WARNINGs, **762 (93.8 %) are a
single line**:

`dashboard/routes_ds_relscore.py:253` -> `log.warning("api/ds-relscore compute: %s", exc)`
rendering as `current_item_ids has 6 items; slot_count=6 leaves no room for a new item`
(raised out of the DS engine, e.g. `agents/daemon_slayer/onhit_dps.py:437`).

This is a benign, expected, fully deterministic state - the player has a complete
6-item build - being reported at WARNING once every 3.6 s. It buries the WARNINGs
that matter: the same window contains only 3 + 2 + 1 `state-build slow` lines and
2 Riot 403s, all of which are now needles in a haystack.

Second-order: `routes_ds_relscore.py` has a 300 s TTL cache (`:91-93`) but it is
populated **only on success** (`:260-261`). The `except` branches at `:245` and
`:252` return 503 without caching, so a deterministic failure re-runs `_compute`
on every single poll forever. Measured cost of the failing path is low
(8-10 ms live, it raises before the expensive ranking work), so this is an
observability fix rather than a CPU fix - but the negative cache is one line and
kills the spam at the source.

## Lever 5 - model tier (CLEAN)

Every live coaching call is pinned to Haiku. Grepped `sonnet|opus` across
`core/ dashboard/ app/ ops/ agents/ modes/ vision_server/ coaches/ tft/` and
opened every hit:

- `modes/shared_vision.py:99` `SONNET_MODEL = "claude-sonnet-4-6"` and
  `:262` - vision OCR. Charter-exempt, explicitly out of scope.
- `dashboard/_screen_read.py:33,101` - consumes `SONNET_MODEL`; same vision surface.
- `coaches/aram_coach.py:750`, `coaches/arena_coach.py:1184`,
  `coaches/brawl_coach.py:628` - these read `r._model = "claude-sonnet-4-6"` but
  `r` is a `GameVisionReader.__new__(...)` being hand-constructed (see
  `aram_coach.py:746-748`). This is the vision tier, not a coach model pick, and
  it is not a post-call telemetry stamp either - it is a vision reader. Exempt.
- `agents/_supervisor_common.py:46-53` `AGENT_MODELS`: agents 2/3/4/5 Sonnet,
  6 Opus, 7 Haiku. Consumed at `agents/_supervisor_ephemeral.py:165` and passed
  as `--model` to a spawned `claude` CLI process, i.e. on the Max subscription,
  not per-token API spend. Agent 6 is the charter-exempt auditor; 2-5 are
  dev-framework agents with charters at `_supervisor_common.py:58-65`.
  Downgrading a backend/testing/UI dev agent to Haiku is a fidelity trade, not a
  saving, and is out of scope by the standing rule.
- `core/cost_tracker.py:93,97` - price-table entries only, not call sites.
- `ops/loop/adjudicator.py:32,77`, `ops/loop/loop_controller.py:693`,
  `ops/phase3_setup.py` - loop-director configuration, single-vendor Claude loop.

The three coach call sites that pass `model="claude-haiku-4-5-20251001"` inline
(`arena_coach.py:929`, `arena_coach.py:1068`, `aram_coach.py:1274`) were read
directly to confirm the literal. `tft/tft_vision_reader.py:92` documents in
source that it defaults to Haiku and the old "SONNET tier" comment was already
corrected on 2026-07-29.

No surface is above its charter tier.

## Lever 6 - scheduled-task catalog (CLEAN)

Live list via `schtasks /Query /FO CSV` filtered on `RC-`: 24 tasks.

`\RC-CIWatchdog`, `\RC-ClaudeQuotaWatch`, `\RC-CostHealthWatchdog`,
`\RC-DaemonSlayer`, `\RC-DDragonMirrorRefresh`, `\RC-DS-MatchDB-MCP`,
`\RC-HotkeyListener`, `\RC-LCUAgent`, `\RC-LiveClientRelay`,
`\RC-LiveFlipWatcher`, `\RC-MissionControl`, `\RC-PatchRefresh`,
`\RC-Phase3-PeriodicAudit`, `\RC-Phase3-Supervisor`, `\RC-PostmortemAnalyze`,
`\RC-ReplayChainWatch`, `\RC-ReplayRosterPull`, `\RC-RewindCatchup`,
`\RC-RoflArchive`, `\RC-RoflDedupe`, `\RC-Supervisor`, `\RC-TeamClaudeProxy`,
`\RC-UpstreamDriftCheck`, `\RC-WeeklyHygiene`.

Reconciliation against `docs/OPERATIONS.md` (names extracted by grep, not by
reading prose): the doc names exactly the same 24. **Zero ghosts.**

Orphan check: each task's `<Exec><Command>` + `<Arguments>` was dumped from the
task XML and the target file stat-checked on disk. All 24 resolve:

- 21 point at a tracked file under `C:\Riot Commander\` (`tools/*.py`,
  `scripts/*.py`, `ops/*.py|.ps1`, `mission_control.py`, `agents/supervisor.py`).
- 2 are `-m` module invocations (`ops.phase3_file_audit`, `agents.supervisor`),
  both of which exist as files.
- 1, `RC-TeamClaudeProxy`, runs `wscript.exe
  C:\Users\Administrator\teamclaude_proxy_hidden.vbs` - out of repo, but the file
  exists (199 bytes, mtime 2026-07-29). Not an orphan; flagged only because it is
  the one target that lives outside the tree and so is invisible to any repo-only
  guard.

**Zero orphans.** Nothing to fix.

## Lever 7 - bundle parity (CLEAN)

- `ls web/css/panels/*.css | wc -l` -> **64**
- `grep -c "@import './panels/" web/css/dashboard.css` -> **64**
- No stray non-.css files in the directory (`ls | wc -l` also 64).
- The four non-panel `@import` lines (`:12` Google Fonts, `:15` tokens.css,
  `:19` themes.css, `:36` hextech.css) account for the difference between the
  naive `grep -c "@import"` of 68 and the panel count of 64. That 68-vs-64 gap is
  an artifact of the loose pattern, not drift.

Drift guard located: `tests/test_dashboard_css_panel_imports_parity.py`.
Run fresh this session:

```
python -m pytest tests/test_dashboard_css_panel_imports_parity.py -q
....                                                                     [100%]
4 passed in 0.20s
```

---

## Ranked shortlist

Ranked by (savings x confidence) / risk.

**1. `/api/health/all` full-file re-parse (lever 2).**
Savings: high and measured - 41.4 ms CPU and 4.6 MB of I/O per request, at
0.134/s = ~1.68 GB read and ~15 s CPU per 45 minutes, growing monotonically as
`task_queue.jsonl` appends. Confidence: high - measured three ways (standalone
parse 41.45 ms, live route 43.8 ms, file 4,645,089 bytes / 5,813 lines).
Risk: near zero - the memo key is the file's own (mtime_ns, size), so a changed
file invalidates instantly and the returned value is byte-identical to today's.
No TTL, no staleness, no fidelity trade.

**2. `routes_ds_relscore` benign-WARNING flood (lever 4).**
Savings: moderate - restores the WARNING channel from 6 % signal to ~100 %
signal, plus a small CPU saving from the negative cache. Confidence: high -
762/813 lines measured. Risk: low, but it is two changes (log level + cache),
and demoting a log level always deserves a second look at whether any operator
alarm keys off that string. Ranked second only because the CPU saving is small
(8-10 ms measured, it raises early) - this is mostly an observability win.

Nothing else surfaced. Levers 1, 3, 5, 6 and 7 are clean on measurement, not on
assumption.

---

## Ship first

**Memoize `_agent6_audit_outcomes` on the source file's identity.**

File: `dashboard/routes_state.py`, function at `:28-58`, sole caller at `:370`
inside the `/api/health/all` handler.

Exact change - insert a module-level memo above the function and gate the scan:

```python
# Cost sweep 2026-08-02: task_queue.jsonl is append-only and 4.6 MB / 5813
# lines; a full read+json.loads per call measured 41.4 ms of the 43.8 ms
# /api/health/all latency. Memo on (mtime_ns, size) so an appended line
# invalidates immediately - this is exact, NOT a TTL, so health never goes
# stale.
_A6_MEMO: tuple | None = None   # (mtime_ns, size, max_count, outcomes)


def _agent6_audit_outcomes(max_count: int = 3) -> list:
    """Return the last ``max_count`` agent6-full-audit-pass final events from
    agents/state/task_queue.jsonl, oldest-first. Returns [] on any error."""
    global _A6_MEMO
    q = APP_DIR / "agents" / "state" / "task_queue.jsonl"
    if not q.exists():
        return []
    try:
        st = q.stat()
        sig = (st.st_mtime_ns, st.st_size, max_count)
    except OSError:
        sig = None
    if sig is not None and _A6_MEMO is not None and _A6_MEMO[:3] == sig:
        return list(_A6_MEMO[3])
    outcomes: list = []
    try:
        ...unchanged body, lines 36-57...
    except Exception:  # noqa: BLE001
        pass
    result = outcomes[-max_count:]
    if sig is not None:
        _A6_MEMO = (sig[0], sig[1], sig[2], list(result))
    return result
```

The body from `:34` (`outcomes: list = []`) through `:57` (`pass`) is untouched;
only the guard before it and the return at `:58` change.

Verification for whoever ships it: Tier-1 by R5 (one module, local logic).
`py_compile` + the routes_state tests, then
`curl -sk -o /dev/null -w "%{time_total}\n" https://127.0.0.1:8888/api/health/all`
three times - expect ~43 ms before, ~2-3 ms after, with an identical JSON body
(diff the two payloads to prove the memo is exact, not lossy). Then append a
line to `agents/state/task_queue.jsonl` in a scratch copy and confirm the memo
misses on the new mtime.

Not shipped here - this slice is read-only.
