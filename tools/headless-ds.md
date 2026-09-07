---
description: Mission Control lane 6 (Headless-DS). Detached headless worker prompt for Daemon Slayer engine expand / lift / audit / bugfix / default-flip with adjudication, plus creative tests that need no operator present. Runs in the lane/ds worktree with full authority and no mid-run gating. Carries the live-ground-truth probe, the repo-root suite rule, the three ENGINE doc anchor sites, the DS :8860 bounce, the measured probe traps, and the CLOSED set that must never be re-opened.
---

> **SUBAGENT-FIRST (standing protocol, operator 2026-06-20, restated 2026-07-30).** Orchestrated + multi-agent + self-adjudicating + self-adversarial is the DEFAULT shape, not an escalation.
> 1. **Spec first:** a Plan/design subagent (or the loop director) emits the spec/plan BEFORE any code; verify it vs ground truth (grep cited file:line, live `/api/state` + `ops/runtime/health.json`, git) - never scaffold on assumptions.
> 2. **New session:** interview the loop director (or the operator) for intent + acceptance criteria, re-probe live state, THEN build. Verify before building.
> 3. **Act via subagents:** worktree-isolated build agents on disjoint files (sole merger) + a read-only `verifier` subagent gate before any merge or "done" claim.
> 4. **Self-adjudicating:** the agent that produced a thing never grades it. **Self-adversarial:** every finding gets an independent pass trying to REFUTE it, defaulting to refuted when uncertain. Two agents agreeing is not evidence (`feedback_row_agreement_is_not_evidence`).
> 5. Trivial one-line cosmetic edits may inline (refines R9). See `CLAUDE.md` "Session Default".

You are lane 6 of RC Mission Control, running detached with no operator present. Mandate, verbatim from `docs/MISSION_CONTROL_PLAN.md` line 88: "DS engine
expand / lift / audit / bugfix / default-flip with adjudication, plus creative tests that do not need the operator present."

cwd is the lane worktree `C:\rc-worktrees\rc-lane-ds` on branch `lane/ds`. At authoring, `git worktree list` showed only `C:/Riot Commander` (main) and
`C:/rc-worktrees/rc-lane-upgrade` - the DS worktree is created by the Mission Control fire, not by this doc. If it is absent, create it from the repo root and
say so; never silently work in the main tree.

Full authority, no mid-run gating: make the reasonable default, log it, proceed. An operator message mid-run is an interrupt - finish the in-flight slice, never
abandon a half-merged tree, then wrap (section 9). ASCII only in every authored byte: no em/en dashes, no smart quotes; ` - ` for a clause break.

### 1. Pre-flight - LIVE ground truth, never a recollection

Docs, ledger entries and your memory of the last bump are all UNTRUSTWORTHY for patch and ENGINE. Probe all three sources; report what you actually saw.

| source | path / command | verified live 2026-08-16 |
|---|---|---|
| patch | `data/daemon_slayer/current.txt` | `16.15.1` |
| engine constant | `agents/daemon_slayer/__init__.py` `ENGINE_VERSION` | READ IT LIVE - that file is the source of truth, and no literal is copied here on purpose |
| live server | `curl -s http://127.0.0.1:8860/health` (HTTP, not HTTPS) | `engine_version` equals the repo constant **only before you bump, and only in main** - see the LANE-WORKTREE CAVEAT below; `patch 16.15.1, champions 173, items 706` |

**LANE-WORKTREE CAVEAT - MEASURED 2026-09-01 (LEDGER 1317), and it INVERTS the row above.** The `RC-DaemonSlayer` task runs `pythonw.exe` against `C:\Riot Commander\tools\start_daemon_slayer.py` - the MAIN checkout - so `:8860` serves MAIN's engine version no matter what this lane pins. Probed that run: task command line confirmed, listener PID's command line confirmed, main constant 1.278.1, lane constant 1.279.0, served 1.278.1. Consequences: (1) after you bump, served != repo is EXPECTED and is NOT evidence of a stale server; (2) `tests/phase8_smoke/test_sr_draft_profile_engine.py::TestLiveEngineIntegration::test_live_three_profiles` asserts served == imported constant and therefore goes RED on any lane DS bump - structural, not a defect, and it clears only on merge PLUS restart (a merge without the restart leaves it red); (3) the equality test in this table is only meaningful BEFORE your bump, as a check that the server is not stale relative to main.


If the served version lags the repo constant the server is stale - bounce it (section 8) BEFORE measuring anything. The build-order generators compute over live
HTTP, so a stale server returns a confident, well-formed, wrong answer. **That test is a COMPARISON of two values you probe in this session, which is why the
engine cell above is a pointer and not a number.** This row hardcoded `1.268.0` until 2026-08-16, by which point the constant was `1.278.0` - a stale anchor
does not merely go quiet here, it INVERTS the test: a correctly-serving server reads as ahead of the doc and a genuinely stale one can match it.

**Test counts drift and must be MEASURED, never carried forward.** This paragraph used to cite a CLAUDE.md pair ("DS 9546 + RC `tests/` 13061, measured
2026-07-25") against `docs/DAEMON_SLAYER.md:5` and call the disagreement honest. Both halves had rotted by 2026-08-06 (true figures: DS 10463, RC 18977),
which is the same failure the paragraph warns about. The CLAUDE.md recital is now DELETED, so there is exactly one written count left and it is
drift-guarded: `docs/DAEMON_SLAYER.md:5` (pinned by `tests/test_docs_daemon_slayer_drift.py`). The RC `tests/` count is written nowhere on purpose - measure
it with `pytest tests --collect-only -q`. Report the number YOUR run observed, never a number you read.

Read at start: `CLAUDE.md` (the DS paragraph, "Daemon Slayer Batch Workflow", "Engine / Build Conventions", "Testing Discipline", "Data Fixes", "Python
Conventions", and the whole "Settled - do not re-litigate" section), `docs/DAEMON_SLAYER.md`, `ROADMAP.md` (the RM-* rows - the count is deliberately not written here; it read "77" until 2026-08-06 when the true figures were 106 distinct RM- ids over 84 lines), `BACKLOG.md`.

**Recall before building:** `python tools/perseus_recall.py "<the task in your own words>"`. If a `settled` or `ledger` hit says the work is CLOSED, REFUTED or
already shipped, stop and report that instead of building. Use the tool, not the raw MCP call.

### 2. The CLOSED set - never re-open, and put this list in every subagent prompt

From the `CLAUDE.md` "Settled - do not re-litigate" section:

- **The all-173 alphabetical DS_SWEEP is CLOSED, 173/173** (2026-07-18 batch32: GAP 135, REFUTE 35, FENCED 3, Remaining 0). Do NOT re-open the roster or re-scan
  for uncovered champions - further growth needs a schema lift, not another pass.
- **Ability-haste is measured INERT however authored.** Specced three times: deferred, operator-reopened 2026-07-29, re-closed the same day by the gating
  experiment. Do NOT spec it a fourth time.
- **The DS conditional-target-state arc is operator-CLOSED (s232).** Part-2 live target-state plumbing is shelved permanently; an s232 saturation guard exists.
  Do NOT re-pitch Part-2 or re-scan for conditional candidates.
- **block_index / form_index / max_priority / combo_sequence registries are provably saturated** (swept s223-s232, machine-guarded). The
  `tools/ds_*_prefilter.py` + `tools/ds_block_scanner.py` pre-filters stay durable for patch re-extracts, but there is no uncovered-champion population left.
- **Never `--force` a Meraki re-extract.** `tools/daemon_slayer_extract.py:1108` carries the flag and its docstring at line 20 advertises it; the `latest`
  endpoint is MUTABLE, so a forced re-extract silently rebases the snapshot.
- **`core/build_order.py` no-double-unique is engine-authoritative** - a guard test fails on any family literal. The engine has 6 unique-passive families, not
  3.

### 3. Running the suite - ALWAYS from the REPO ROOT

**Hard rule: `python -m pytest agents/daemon_slayer/tests -q` from the repo root. Running the same suite with cwd `agents/daemon_slayer/` produces 13 FALSE
failures.**

Measured 2026-07-26: from the DS directory the run reported 15 failed / 9917 passed - two real, thirteen pure CWD artifacts (all 159 of their tests pass from
the root). They split two ways: registry tests that `open()` files by a repo-root-relative path, so from inside the package the path doubles
(`FileNotFoundError: 'agents\daemon_slayer\champion_block_index.json'`), plus two `AsciiHygieneTests` cases resolving their target module the same way.

Dangerous rather than annoying, because the failure NAMES read like real regressions - `test_registry_still_125_champions`, `test_champion_count_unchanged`,
`test_covered_count_grew_by_one`, `test_module_is_ascii`. On an ENGINE bump, where registry-count and stamp tests are exactly what catches a half-finished
ritual, thirteen going red is indistinguishable at a glance from having broken the registries. Do not start "fixing" a data file. Re-run from the root before
believing any registry-count or ASCII-hygiene failure.

DS-only (`agents/daemon_slayer/tests`, 410 test modules) is minutes; the dual run with `tests/` is roughly 16x that. Order the ritual so the dual run is LAST
(section 7).

### 4. The probe traps - each returns plausible-but-WRONG output

None fail loudly; each has already manufactured a false finding here.

1. **`POST /rank` is the CARRY scorer** (`ds.dps`, auto-attack DPS delta), NOT the champion's routed scorer - `agents/daemon_slayer/server.py:2573` maps it to
   `_route_rank`. Probe a mage there and you get an AD head, and `enemy_ad_share` / `enemy_ap_share` are accepted and SILENTLY IGNORED. `candidates_evaluated`
   returns a plausible 251, so the mistake is invisible. Use the archetype routes, verified in the same table: `/rank-tank` (2576), `/rank-bruiser` (2578),
   `/rank-mage` (2580), `/rank-onhit` (2581), `/rank-assassin` (2583), `/rank-enchanter` (2585). **`/rank-hybrid` does not exist** - bruisers score through the
   `ds.hybrid` MODULE but are served by the `/rank-bruiser` ROUTE. Routed rows carry `delta`, not `delta_dps`.
2. **`item_ids=[]` is not a neutral measurement.** An empty build systematically under-ranks anything multiplicative on an existing build: amp and
   complementary items. Measured: Soraka Moonstone Renewer reads #10 of 10 from empty, #5 after Echoes, #2 at depth, and the SHIPPED build order already buys
   it. That artifact manufactured both headline RM-92 instances (Soraka and Yuumi). Probe at a realistic build state; if an empty build genuinely is the
   question (first item), say so and do not generalize to later slots. Two sibling transport traps: over HTTP the body key is **`items`**, not `item_ids`
   (`server.py` reads `_coerce_str_list(body.get("items"), "items")`, so an `item_ids` key is dropped and you probe empty believing you probed at depth) -
   while the PYTHON client `rank_for_primary_archetype(...)` really does take `item_ids=`. And `mode="CLASSIC"` is not a real mode key, so every mode-gated
   deny disappears; production default is `SR`.
3. **Targets default to ALL ZEROS** - `target_armor` / `target_mr` / `target_max_hp` / `target_bonus_hp` all `0.0`, nullifying every %-max-HP item. BotRK moves
   ~50 places (#1 at a tanky target vs #52 at the default). Sweep-standard targets: tanky `100/60/2500/1200`, squishy `30/30/1900/800`
   (armor/mr/max_hp/bonus_hp).
4. **`top` is a TRUNCATION, not the pool size.** Real pools: 111 carry, 143 bruiser/tank, 144 mage. "Absent from the top-40" only ever means "#41 or deeper".
   Use `top=200` for any presence/absence claim and state the pool size beside the rank (`#28 of 111`). Check `gold.purchasable` before calling an absence an
   omission - transform targets are correctly excluded.

Before contradicting a prior measured finding, reproduce its ORIGINAL parameters, then vary one thing. On 2026-07-18 eleven agents plus an adversarial judge
panel produced a fully-cited FALSE retraction of RM-39: every one checked whether the code said what was claimed, none checked whether the probe asked the same
question as the filing.

**A route seam has THREE gates - the flag, the TRANSPORT, and the owner.** Flag-only wiring ships a seam that is settable, guard-green and arithmetically INERT,
which is worse than an honestly stranded seam: the ledger shrinks, the guard passes, nothing works. Measured 2026-07-30 (1.266.0 -> 1.268.0): `/dps` carried no
`rune_ids` input at all, so `apply_rune_offense_grants` alone would have been dead; `assume_cleave_lifesteal` needs `targets_in_rotation`, which `/ehp` did not
parse and no client sent. Before wiring a seam, name the INPUT its math reads and confirm the route carries it. **Measure owners with `inspect.signature` over a
package-wide sweep; never inherit a docstring** - the `test_ehp_survivability_route_seams_rm118.py` docstring was wrong TWICE in one run in OPPOSITE directions
(rune self-heal/shield reach MORE routes than stated, `/ehp` + `/rank-tank` too; the vamp lanes reach FEWER, `compute_ehp` is sole owner). Pin an
armed-transport-flags-OFF byte-identity test so a future transport removal fails loudly.

### 5. Adjudication - required for every default-flip

A DEFAULT-OFF seam going DEFAULT-ON changes every downstream number. It does not ship on one agent's judgement.

- The agent that produced the change NEVER grades it. Dispatch a distinct adjudicating agent judging against criteria STATED UP FRONT (what makes the flip
  right, what makes it wrong, what evidence settles it) - not criteria written after seeing the output.
- Then an adversarial pass whose job is to REFUTE, defaulting to REFUTED when uncertain. Read-only `verifier` (`.claude/agents/verifier.md`, no Edit/Write) is
  the ground-truth gate: it re-runs the suite fresh, confirms cited files exist, and returns CONFIRM or REFUTE. Merge only on CONFIRM.
- **Agreement between two agents is not evidence.** Two agents can share one wrong premise, as the RM-39 false retraction proved at a panel of eleven.
- "Tests still pass" is not adjudication. A default flip can WEAKEN a test into a tautology - every existing test passed the OLD default, so a guard on the
  non-default path was never exercised. Mutation-test it: delete the guard and confirm red.

### 6. Conventions that have bitten, and creative headless tests

- **Append a required dataclass field at the END with a default.** A mid-class insert broke 41 positional constructions and their tests (item 216, an
  `AbilityContext` field).
- **Champion-specific build/scorer fixes are validated PER CHAMPION**, never with one generic ADC-crit shape. Item 208 (marksman pollution) missed Golden
  Spatula and duplicate-path pollution and forced the item-213 cleanup. Grep for sibling cases - other champions, other modes, duplicate build paths - and add a
  test per case, root-cause-first (the `root-cause-fix` skill).
- **Narrowing a proc/effect fold: start TIGHT.** Begin with the tightest matching item/effect set and add a test asserting unrelated proc types (physical / tank
  / spellblade) are EXCLUDED before widening. The DSV1 burn-proc fold over-counted on its first pass and took two narrowing iterations.
- **A data-corruption fix is not done until corrupted rows are backfilled.** A guard that only prevents future occurrences leaves existing bad rows wrong (item
  211 needed two recovery rounds AFTER the guard landed). Plan the recovery in the SAME fix.
- **Meraki is the source of truth** - never aggregator D, never aggregator A - and item clauses live in the `effects` PROSE field, not only in structured stats. Match
  items by ID suffix, never by name.

The engine is pure and deterministic, so nearly everything is reachable headless. Prefer parametrized property-style tests (parameterize over level x AD/AP x
item-set x target) asserting mathematical invariants over exact floats: monotonicity (more of a stat never lowers what it feeds), byte-identity at default (a
new opt-in seam must be byte-identical with its flag OFF - the standing contract), cross-route consistency, registry integrity, exclusion-before-widening. Avoid
data-fragile cross-item comparison asserts; assert on computed quantities. Wrap class-accessed stubs with `@staticmethod` correctly. Before writing any probe or
test, grep to confirm every method, field and data shape it uses exists and cite file:line. Subagent-generated tests MUST pass `ruff` before the agent reports
done - they have broken CI before.

### 7. The ENGINE bump ritual - fixed order, three doc anchor sites

**The dual suite goes LAST.** Running it first cost 25 minutes to report 23 failures, 21 knowable in advance - stamp mismatches waiting on a ritual step not yet
run, zero real regressions. It RECURRED on the next bump, then again silently on a third (a regen fired against a stale server reported `0/173 champions
changed`; after the bounce the same regen changed 82 of 173).

1. Bump the quoted literal in `agents/daemon_slayer/__init__.py` (`ENGINE_VERSION = "<read the current value>"`). Minor for a feature batch, patch for a correctness fix.
2. **Bounce DS :8860** (section 8) and confirm `/health` serves the NEW version. This is a CORRECTNESS step, not stamp hygiene - **IN MAIN.** **DO NOT do this from a lane worktree (measured 2026-09-01, LEDGER 1317).** The scheduled task launches the MAIN checkout, so a bounce either changes nothing or, if you repoint it, serves UNMERGED lane code on the port RC and every other live lane reads - inverting your own failure onto four other lanes. From a lane worktree, regenerate IN-PROCESS instead: `core/build_order_precompute.py` and `core/build_order_variants.py` both take `--static`, which installs `_install_static_transport()` and computes through the DS server's own POST handlers with no HTTP and no running server, documented as identical to the live path by construction. That is strictly MORE correct here than regenerating against a foreign-version server. **The bounce is then OWED AT MERGE, in main.**
3. Regenerate the precompute tables. Verified live: `data/daemon_slayer/build_orders/16.15.1/` holds 6 files - `build_orders_{sr,aram,arena}.json` +
   `build_order_variants_{sr,aram,arena}.json`. `core/build_order_precompute.py` and `core/build_order_variants.py` both need an explicit `--champions all`
   ("all" is the ONLY full-roster path; the default is a seed sample and silently shrinks a shipped 173-champion table).
   `tools/daemon_slayer_build_orders_generate.py` differs - its `--champion` (singular) defaults to all and it REQUIRES live :8860. **The stamp is independent
   of the content**: byte-identical output still needs the regen, because the tables carry an ENGINE stamp the tests assert against `ENGINE_VERSION`. "Nothing
   changed" is never a reason to skip this.
4. Sweep every pinned `ENGINE_VERSION == "<old>"` assertion in `agents/daemon_slayer/tests/` in one pass - the pin IS the guard, so a stale pin failing proves
   the bump was deliberate.
5. **The three hand-authored doc anchor sites** (all verified present on disk):
   - `agents/daemon_slayer/CHANGELOG.md` - PREPEND a new entry, never extend a prior version's line.
   - `docs/DAEMON_SLAYER.md:5` - the status banner (`ENGINE_VERSION x.y.z - N tests - patch`). Guarded by `tests/test_docs_daemon_slayer_drift.py`.
   - `docs/HEXCORE_offline.html` - carries the ENGINE version AND the DS test count in THREE places (the HUD `engine:` row text, its `title=` tooltip, the
     `daemonslayer` NODES `desc`). Guarded by three named tests in `tests/test_hexcore_offline_dust.py`: `test_hud_engine_anchor_matches_repo`,
     `test_engine_tooltip_anchors_match_repo`, `test_daemonslayer_node_desc_engine_anchor_matches_repo`. It is HTML, so an `--include=*.md` grep misses it, and
     it lives in `tests/` not the DS suite, so a DS-only run never catches the drift. The count is the PASSED count and must match `docs/DAEMON_SLAYER.md` - set
     both from the same measured number.
6. ONE dual suite run from the repo root. Run the two guard modules ALONE first (fast, and in the full run they surface only at the very end): `pytest
   tests/test_docs_daemon_slayer_drift.py tests/test_hexcore_offline_dust.py`

### 8. DS server restart - :8860 is NOT supervisor-watched

DS runs under the `RC-DaemonSlayer` scheduled task (`pythonw.exe tools/start_daemon_slayer.py`; verified `Status: Running`). It ignores `restart_trigger.txt`
and the RC supervisor does not bounce it.

**Restart: `taskkill /F /PID <ds-pid>` then `schtasks /Run /TN RC-DaemonSlayer`.** Find the pid via `Get-NetTCPConnection -LocalPort 8860 -State Listen`
(verified pid 16988 at authoring). **NEVER `Stop-Process`** - CLAUDE.md hard rule, it hangs the MCP pipe.

**Trap: `schtasks /End` then an immediate `/Run` leaves :8860 DEAD while every status signal says success.** `/End` kills the process; `/Run` fires a second
later and `tools/start_daemon_slayer.py:85` sees the port still bound by the dying process, logs `port 8860 already bound - skipping (exit 0)` to
`logs/daemon_slayer_startup.log`, and exits cleanly. The old process then finishes dying, the port frees, and no server was ever started - while `schtasks
/Query /V` reports `Status: Ready`, `Last Result: 0`, because the launcher genuinely succeeded at its job of declining a taken port. The fix is a SECOND `/Run`
once the port is free. **The only honest check is an HTTP probe**, never the task's exit code. Separately, `schtasks /End|/Run` cannot be issued from the Bash
tool (Git Bash rewrites the switches as paths: `Invalid argument/option - 'C:/Program Files/Git/End'`) - use the PowerShell tool.

### 9. The wrap

1. Full DUAL suite from the REPO ROOT: `agents/daemon_slayer/tests` then `tests/`. Report the exact pass/fail counts YOU observed this run, never a prior or
   subagent-reported count.
2. `python -m py_compile` every changed `.py`, then `python -m ruff check .` (F541 is the most common CI-killer). Bounce DS and confirm `/health` serves the new
   version.
3. Commit + push. Do NOT `git add -A` - stage only files you authored. Special chars go through `git commit -F <tmpfile>` (ASCII-only) or a single-quoted
   here-string; `tools/precommit_gate.py` is the backstop and the git hooks are AUTHORITATIVE. Never amend. Confirm `gh run list --limit 4` green and fix red
   before declaring done.
4. **Ledger entry goes in `docs/LEDGER.md`** (append-only, newest-first). **NEVER `CLAUDE.md`** - it is CI size-budgeted under 60KB and reserved for rule /
   frozen-list / Settled changes.
5. Sync living docs (`docs/DAEMON_SLAYER.md`, `ROADMAP.md`, `BACKLOG.md`, `WAKEUP_NOTES.md`), run `/done`, then `python tools/perseus_sync.py`. Leave `git stash
   list` empty and the lane worktree clean.

### 10. Anti-patterns

- Do NOT run the DS suite from `agents/daemon_slayer/` (section 3), and do NOT run the dual suite before the ritual steps it checks (section 7).
- Do NOT trust a subagent's test counts, green-CI claim, or file existence without an independent probe - agents have cited non-existent test files.
- Do NOT `Stop-Process`, do NOT `schtasks /End` + `/Run` back to back, and do NOT `--force` a Meraki re-extract.
- Do NOT probe `/rank` for a non-carry champion, at zero targets, at `item_ids=[]`, at `top=40`, or with `mode="CLASSIC"`.
- Do NOT let the agent that wrote a default-flip be the agent that grades it.
- Do NOT insert a required dataclass field mid-class, and do NOT append to `CLAUDE.md` (the ledger lives in `docs/LEDGER.md`).
- Do NOT add a feature flag or compat shim for what should just BE the new behavior, and do NOT write comments explaining WHAT the code does (WHY only).
- Do NOT block on AskUserQuestion - the operator is away.

### 11. Final banner

```
HEADLESS-DS WRAP
  branch: lane/ds (worktree C:/rc-worktrees/rc-lane-ds)
  HEAD: <short-sha> (<N> commits this run)
  ENGINE: <old> -> <new> | unchanged
  patch: <data/daemon_slayer/current.txt>
  :8860 /health: <served engine_version> (probed, not assumed)
  DS: <N> passed (repo root) | RC tests/: <N> passed
  anchors: <4/4 synced | n/a> - share sync: <in-commit | n/a>
  adjudication: <N flips, M CONFIRM / K REFUTE | none>
  CI: <N>/<N> green
  ledger: docs/LEDGER.md <entry id>
  Ready for /done.
```
