# Riot Commander - Technical Audit (deep / strict)

Auditor framing: evidence-first outside review. Sources of truth = files on disk + git +
in-repo docs ONLY (no day-one memory claimed). Every finding tagged GROUNDED (cited /
command-run this audit) or INFERRED (reasoned, not independently verified). Generated
2026-06-17 against `main` @ 6541778a.

This revision is deliberately run on the STRICT bar (less "N/A by design" leniency) and is
deeper: the figures below were independently re-derived from git, not carried from the
subagent sweep. Where a number differs from a subagent claim, git wins (Appendix A).

---

## 0. Calibration and Method

### Two bars, scored separately
RC is a solo-developer, single-user, single-machine local tool (1-PC, ADR-011). Pillar 3 gives
**two** ratings: the solo-tool bar (fair) and the strict bar (what an enterprise reviewer would
demand regardless of team size). On the strict bar the following are NOT excused as "N/A by
design," because they bite a single operator too: dependency reproducibility, static typing,
CI honesty, fail-safe error handling, and authn on any network-reachable surface. Genuinely
N/A even on the strict bar: multi-tenant isolation, RBAC for multiple users, horizontal scale,
SOC2, on-call rotation.

### Evidence base (commands actually run THIS audit, GROUNDED)
git census (file/LOC counts); grep counts for `except`, `assert`, `eval`/`exec`, `pickle`,
mutable-default args, locks, threads, `ssl.CERT_NONE`, `print`, type-annotated defs; Glob for
build/lint/CI config; targeted Reads of `requirements.txt`, `core/anthropic_client.py`,
`dashboard/server.py`, route registration. 5 read-only Explore subagents seeded the map; their
high-value numbers were re-verified (Appendix A).

### The numbers (GROUNDED)
| Metric | Value | Note |
|---|---|---|
| Tracked files | 3,672 | |
| Python files / LOC | 1,668 / 529,774 | non-Share 1,338 / 389,823; Share mirror dup 330 / 139,951 |
| Runtime source (non-Share, non-test) | 637 files / 195,418 LOC | the hand-authored core |
| Test files / `def test_` (non-Share) | 701 / **14,364** | all incl. Share: 21,606 |
| JS / JSON / MD | 81 / 808 / 370 files | JSON = 2,253,214 LOC (DS registries + autogen) |
| Largest source | `_effects_data.py` 5,406 (autogen) ; `ehp.py` 2,151 ; DS `server.py` 1,951 ; `burst.py` 1,784 | |
| Locks (`Lock()`/`RLock()`) | 134 occ / 96 files | vs 73 `threading.Thread/Timer` spawns |
| `except Exception` | **1,137 / 250 files** | bare `except:` = **1** |
| `assert` in runtime paths | **405** | core/app/dashboard/coaches/lcu/DS; stripped under `-O` |
| `eval(`/`exec(` | **0** | clean |
| `pickle.load/dump` | **0 files** | clean |
| mutable default args (`=[]`/`={}`) | **0** | clean |
| return-annotated defs (core/+DS) | 7,630 / 9,727 = **~78%** | hints present, NOT type-checked |
| `# type: ignore` | 11 | |
| TODO/FIXME/XXX/HACK | 11 | very low |
| `print(` in runtime modules | 63 | should be logging |
| TLS verify disabled (`CERT_NONE`/`check_hostname=False`) | 8 sites | see D13 |
| Declared deps | 5, all floating `>=` | no lockfile - see D10 |
| Lint / type / CI config | `ruff.toml` Y / mypy N / `ci.yml` Y | CI runs ~5% of suite |
| Dashboard bind | `HOST="::"`, `IPV6_V6ONLY=0` | all interfaces, tailnet-reachable |

The prompt's "250k LOC" ~= authored source (195k py + 40k js = 235k). The 530k-py / 2.25M-json
bulk is tests, the checked-in Share mirror, and generated data, not authored logic.

---

## 1. Architectural Sanity and Pattern Adherence

**Implemented paradigm (GROUNDED).** Supervised multi-process system. Frozen process supervisor
`ops/rc_supervisor.py` keeps `main.py` alive via `restart_trigger.txt` + `ops/runtime/health.json`;
a separate Phase-3 supervisor `agents/supervisor.py` (:8890/:8891) runs the agent framework. The
in-process app is an **asyncio loop** - `app/_loop.py` wraps `asyncio.new_event_loop()` in an
`AppLoop` with thread-safe `schedule()`/`spawn_task` (5 asyncio refs). State flows worker-queue ->
`app/_game_lifecycle.process_game_state()` -> single authoritative `GameEnvelope`
(`app/_state_authority.py`), read via defensive deep-copy. HTTP: :8888 HTTPS dashboard, :8889
vision, :8893 DS - each self-healing. DS engine is a data-driven scorer (706 items + 172 champs
JSON -> 6 archetype scorers).

**Pattern drift (GROUNDED).** Doc-level only: the loop is asyncio but a memory + docs still call
it `tk.after`; 13 files retain `.after(` (residual tk scheduling) - the asyncio migration is
mostly-but-not-fully complete. See D6.

**Separation of concerns - largely clean (GROUNDED).** Route handlers are thin (validate -> call
`core.*` loader -> JSON); math lives in `core/` + `agents/daemon_slayer/`. `core/build_order.py`
takes an injectable `rank_fn` and does not import coaches (correct direction). The DS JSON
registries are deliberate data-driven design, NOT a layering failure.

**Coupling traps (GROUNDED + INFERRED).** `core/game_snapshot.py` (frozen) is the central schema -
changes cascade. `app/_game_lifecycle.py:85-135` hardcodes the mode->coach map - the one real
tight-coupling trap, and it is FROZEN (D5, approval-gated). Two supervisors coexist with an
under-documented boundary (D7). The ~30-file frozen set is narrow vs 637 source files - deliberate
stability on load-bearing modules, not pervasive fragility.

---

## 2. Quality of Implementation and Code Hygiene

**Footgun-clean (GROUNDED, strong).** Zero `eval`/`exec`, zero `pickle`, zero mutable-default
args, exactly one bare `except:`. Three of the most common Python correctness/security footguns
are absent repo-wide. Debt-marker density is trivially low (11). Frozen dataclasses and pure
function families (`smoothed_rates`) dominate the engine.

**Strict-bar hygiene gaps (GROUNDED).**
- **405 `assert` statements on runtime paths.** Under `python -O` every one is stripped; asserts
  used as validation/invariant checks then silently vanish. RC runs under `pythonw.exe` (no `-O`)
  so they fire today, but it is a latent fragility and the assert-as-control-flow antipattern. See
  D11.
- **63 `print(` in runtime modules** (core/app/dashboard/coaches/DS) instead of the `rc.*` loggers.
  Output goes nowhere useful under `pythonw`. See D12.
- **1,137 `except Exception`** across 250 files. Most log-and-continue, but the breadth means real
  failures are routinely demoted to warnings; `game_reader/snapshot_normalizer.py` alone has ~29
  swallows. See D4.

**Clever/brute-force (GROUNDED).** The big modules are inherent-complexity math (`ehp.py` 2,151,
`burst.py` 1,784, `ability_dps.py` 1,384), not gratuitous cleverness. `_effects_data.py` (5,406)
and `_passive_damage_overrides.py` (938) are generated tables - do not hand-edit.

**Dead / redundant (GROUNDED).** `web/js/dashboard.js` (dead, no `<script>` ref), `web/css/stub.css`
(unimported), legacy brawl backend (deadcode pending cleanup), `tools/gamepc_*.py` (2-PC-era,
retained). Largest single redundancy: the checked-in `Share/` mirror (330 files / 139,951 LOC). The
`str(exc)[:200]` error envelope is copy-pasted across 30+ route handlers (D8).

---

## 3. Comparison to Standards

### Genuinely exceeds norms (GROUNDED)
Atomic writes everywhere (`tmp.replace(target)`); test mass (14,364 `def test_`, hermetic autouse
fixtures that fail the suite if a prod artifact mutates); footgun-clean (eval/exec/pickle/mutable-
default all 0); minimal dependency surface (5 declared deps, stdlib-heavy `http.server`/`sqlite3`/
`ssl`/`asyncio` = small attack surface); disciplined concurrency (134 locks/96 files vs 73 thread
spawns; SQLite WAL + RLock; generation-counter worker restarts); self-healing daemons; deterministic
Share mirror with a CI drift gate; injection-safe shell (no `shell=True` in app code); ADR trail +
ASCII/EOL CI guards + anti-fabrication process encoded in hooks.

### Falls below the strict bar (GROUNDED unless noted)
- **No authn on network-reachable control endpoints (D9).** `/api/command` + `/api/input`
  (`routes_state.py:847-848`) accept POSTs with only Pydantic shape-validation; the listener binds
  `HOST="::"` all-interfaces (`server.py:35`), reachable as `legion-rc:8888` across the tailnet. The
  documented trust model (`routes_loop_control.py:9-11`) is "single-operator tailnet" - a trust
  assumption, not an enforced control.
- **Non-reproducible builds (D10).** All 5 deps are floating `>=` with no lockfile; a new
  `anthropic`/`pydantic`/`Pillow` release can change behavior silently.
- **No static type checking (D3).** `ruff` only; ~78% of core/+DS defs are return-annotated, but
  nothing verifies them. Latent type bugs ship unless a test happens to catch them.
- **CI does not run its own suite (D2).** `.github/workflows/ci.yml` runs `py_compile` + `ruff` +
  `ds_share_sync --check` + ASCII hygiene + a smoke/regression/panel subset (~50-70 files). ~95% of
  the 14k-function suite is gated by local discipline only.
- **Stripped-under-`-O` validation (D11)** and **broad-except sprawl (D4)** as in pillar 2.
- **TLS peer verification disabled at 8 sites (D13)** - mostly justified (Riot self-signed LCU,
  localhost), the bridge sites lean on Tailscale WireGuard for transport auth.
- **Data-fragile tests** read gitignored `data/rewind_history.db` and fail on clean checkout; one
  supervisor test is port-contention-flaky. (GROUNDED via subagent E + memory.)

### Health rating (dual)
- **Solo-tool bar: B+ / "Disciplined Solo-Operator Production Tool."** Not a fragile prototype
  (test mass + atomic writes + footgun-clean + self-heal rule that out).
- **Strict bar: B- / "Robust-but-unguarded."** The gap to A is dominated by ~5 mechanical fixes:
  pin deps (D10), add a token to control endpoints (D9), turn on a type checker (D3), make CI run
  the suite (D2), and ratchet down broad-except + asserts (D4/D11). None require an architectural
  rewrite. Debt is concentrated and namable, not diffuse rot.

---

## 4. Deficiencies and Road-to-Excellence Roadmap

Each: severity, tag, strategy, blast radius (frozen / tests / ENGINE_VERSION / Share / CI).

- **D1 - Share mirror duplication (MED, GROUNDED).** 330 files / 139,951 LOC duplicate the DS
  engine; every `agents/daemon_slayer/**` edit must re-sync or CI fails; test surface doubled.
  *Strategy:* generate the distributable at release time (git-subtree/submodule/build step) instead
  of committing it; OR accept and document the tax. *Blast:* `tools/ds_share_sync.py`, CI
  `ds_share_sync --check`, all DS files, Share test mirror. Own session.
- **D2 - CI runs ~5% of the suite (HIGH-value, LOW-risk, GROUNDED).** *Strategy:* add a nightly
  full-suite job and/or sharded matrix; keep the PR gate fast. *Blast:* `ci.yml` only (additive).
- **D3 - No static type checking (MED, GROUNDED).** *Strategy:* add `mypy` lenient
  (`--ignore-missing-imports`), scope `core/` then `agents/daemon_slayer/`, ratchet. *Blast:* new
  config + 1 CI step; surfaces latent issues - triage, do not block initially.
- **D4 - Broad-except sprawl 1,137/250 (MED, GROUNDED).** *Strategy:* ruff `BLE001` as a baseline
  ratchet (allow existing, fail new); convert silent swallows (`snapshot_normalizer.py` first) to
  logged + narrowed types. *Blast:* wide but mechanical, per-module Tier-1.
- **D5 - Coach-dispatch hardcode in FROZEN `_game_lifecycle.py:85-135` (MED, GROUNDED,
  APPROVAL-GATED).** *Strategy:* extract a coach-factory/registry so adding a mode is data, not a
  frozen-file edit. *Blast:* frozen file -> requires explicit human approval; update lifecycle
  tests.
- **D6 - Doc/memory drift (LOW, GROUNDED).** "1300+ tests" vs actual 14,364; `tk.after` vs asyncio.
  *Strategy:* doc-sync + memory correction. *Blast:* docs only (Tier-0).
- **D7 - Supervisor boundary undocumented (LOW, INFERRED).** *Strategy:* document
  `ops/rc_supervisor.py` (process) vs `agents/supervisor.py` (agent framework) in ARCHITECTURE.md;
  do NOT merge. *Blast:* docs.
- **D8 - Duplicated route error-envelope x30+ (LOW, GROUNDED).** *Strategy:* one shared
  `dashboard` error-envelope helper. *Blast:* `routes_*.py` (Tier-1).
- **D9 - Unauthenticated control endpoints on tailnet-reachable bind (HIGH on strict bar,
  GROUNDED).** *Strategy:* add a shared-secret header (env-loaded token) checked on
  `/api/command`,`/api/input`,`/api/analyze`,`/api/loop-control`; reject missing/mismatch with 401;
  defense-in-depth even single-operator. Optionally bind localhost-only and reach via Tailscale
  Serve. *Blast:* `dashboard/_dispatch.py` / `_handler.py` + the POST routes; not frozen. Add
  tests.
- **D10 - Floating unpinned deps, no lockfile (MED on strict bar, GROUNDED).** *Strategy:* pin `==`
  in `requirements.txt` (or add `requirements.lock` via `pip freeze`); cap majors at minimum.
  *Blast:* `requirements.txt` + CI install step. Verify suite still green on pinned set.
- **D11 - 405 runtime asserts stripped under `-O` (MED on strict bar, GROUNDED).** *Strategy:*
  convert validation asserts (those guarding external/untrusted input or invariants whose failure
  must raise) to explicit `if ... raise`; leave pure internal sanity asserts. *Blast:* per-module
  Tier-1; mechanical.
- **D12 - 63 `print()` in runtime modules (LOW, GROUNDED).** *Strategy:* replace with module
  `rc.*` loggers. *Blast:* per-file Tier-0/1.
- **D13 - TLS peer verification disabled at 8 sites (LOW-MED on strict bar, GROUNDED).** *Strategy:*
  keep the Riot-LCU + localhost ones (justified); for the bridge sites (`core/bridge.py`,
  `lessons_receiver.py`, `lessons_ack_watcher.py`) add an inline comment that transport auth is
  delegated to Tailscale WireGuard, and consider pinning the peer cert if app-layer auth is ever
  wanted. *Blast:* comments + optional cert-pin; `lcu/*` is frozen - leave.
- **D14 - Raw API errors propagate by design; per-consumer leak risk (LOW, GROUNDED mechanism /
  INFERRED risk).** `core/anthropic_client.py:24-27` deliberately does NOT eat real API errors, so
  every coach/route must catch or a raw 400/credit-exhaustion string can reach the UI (violates the
  CLAUDE.md rule). *Strategy:* a thin "safe coach output" wrapper that guarantees friendly-degrade,
  analogous to the telemetry shim. *Blast:* coach_integration + coaches; Tier-1.

Suggested order: D6, D12, D8 (fast/safe) -> D2, D10 (CI + repro, additive) -> D9 (security) -> D3,
D4, D11 (ratchets) -> D13, D14 (hardening) -> D5, D1 (frozen / heaviest, own approval-gated session).

---

## 5. Autonomous-Agent Execution Specs (Antigravity)

### HARD INVARIANTS - the agent MUST NOT violate these (authoritative source: CLAUDE.md)
1. **Frozen files** (verify the live list in CLAUDE.md before editing): `main.py`,
   `core/log_setup.py`, `core/moon_proxy.py`, `lcu/lcu_client.py`, `core/game_snapshot.py`,
   `ops/rc_dev_runtime.py`, `ops/rc_supervisor.py`, `app/__init__.py`, `app/_loop.py`,
   `app/_health_monitor.py`, `app/_remediation.py`, `app/_state_authority.py`,
   `app/_overlay_manager.py`, `app/_game_lifecycle.py`, the `tools/bridge_*` set,
   `dashboard/routes_bridge_pending.py`, `ops/RC-BridgeWatcher.xml`, listed `.md` command files. If
   a change needs one of these, STOP and surface it.
2. **Atomic writes only:** `tmp.write_text(...); tmp.replace(target)`. Never partial writes.
3. **ASCII only** - no em/en dashes, no smart quotes, anywhere. Use ` - ` for clause breaks.
4. **LF endings** (`.gitattributes *.py eol=lf`). Edit/Write emit CRLF on this host - normalize to
   LF before commit or the EOL guard trips.
5. **`py_compile` every changed .py before restart.** Restart via
   `echo restart > restart_trigger.txt`; verify `ops/runtime/health.json` -> new `pid`,
   `alive=true`, `last_reload_ok=true`. NEVER `Stop-Process`; use `taskkill /F /PID`.
6. **DS engine change ritual:** bump `ENGINE_VERSION` in `agents/daemon_slayer/__init__.py` (quoted
   literal ONLY), run the dual suite (DS dir + `tests/`), `taskkill` + relaunch DS :8893, then
   `ds_share_sync` AND stage every new `Share/src/.../tests/test_*.py` mirror in the SAME commit.
7. **Never surface a raw API error string** in any UI - catch, friendly-degrade, log raw to `logs/`.
8. **CLAUDE.md is size-budgeted (<60KB)** - ledger entries go to `docs/LEDGER.md`, never CLAUDE.md.

Constants for commands below: `PY="C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"`.
Verify tiers: **T0** doc/comment/string (py_compile if .py); **T1** one module (py_compile + that
module's tests); **T2** schema/engine/scorer/ENGINE_VERSION (full dual suite + DS :8893 restart +
Share re-sync).

### Per-item checklist (PRECONDITION / EDIT / VERIFY / ROLLBACK)
```
[ ] D6a  doc drift: test count
    PRE  git clean; confirm `git grep -hE '^[[:space:]]*def test_' -- '*.py' ':!:Share/*' | wc -l` == 14364
    EDIT CLAUDE.md + WAKEUP/docs: "1300+ tests" -> cite the git figure
    VER  T0 (no .py); grep shows new text
    RBK  git checkout -- <files>

[ ] D6b  doc drift: scheduler
    PRE  confirm app/_loop.py uses asyncio (git grep -c asyncio app/_loop.py == 5)
    EDIT docs + memory note: scheduler is asyncio AppLoop; 13 residual .after( files
    VER  T0
    RBK  git checkout

[ ] D12  print -> logger  (per file, runtime dirs only)
    PRE  list sites: git grep -nE '^[[:space:]]+print\(' -- core/*.py app/*.py dashboard/*.py coaches/*.py agents/daemon_slayer/*.py   (SKIP any frozen file)
    EDIT replace with module logger (`logging.getLogger("rc.<mod>")`)
    VER  T1: %PY% -m py_compile <file>; run that module's tests
    RBK  git checkout -- <file>

[ ] D8   shared route error-envelope
    PRE  none; read all dashboard/routes_*.py uses of str(exc)[:200]
    EDIT add dashboard/_errors.py helper; swap call sites (skip frozen routes_bridge_pending.py)
    VER  T1: py_compile dashboard/*; pytest tests for routes + dashboard smoke
    RBK  per-file git checkout

[ ] D2   CI runs full suite
    PRE  suite green locally
    EDIT .github/workflows/ci.yml: add nightly (schedule:) job running the dual suite; keep PR gate fast
    VER  T1: yaml lint; dry-run trigger
    RBK  revert ci.yml

[ ] D10  pin deps
    PRE  suite green
    EDIT requirements.txt: float >= -> pinned ==  (anthropic, Pillow, portalocker, psutil, pydantic); add requirements.lock via `%PY% -m pip freeze`
    VER  T1: fresh venv install + import smoke + suite
    RBK  restore floating requirements.txt

[ ] D9   token on control endpoints
    PRE  read dashboard/_dispatch.py + _handler.py + the POST_ROUTES in routes_state.py:846
    EDIT load RC_DASH_TOKEN (env/gitignored file); check header on /api/command,/api/input,/api/analyze,/api/loop-control; 401 on miss
    VER  T1: new tests (200 w/ token, 401 w/o); dashboard smoke
    RBK  per-file git checkout
    NOTE single-operator default may set token empty=disabled; do NOT break the live dashboard JS - update its fetch() to send the header in the same slice

[ ] D3   mypy gradual
    PRE  none
    EDIT add mypy.ini (lenient, --ignore-missing-imports), scope core/ ; add non-blocking CI step
    VER  T1: mypy runs (triage, do not fail gate yet); suite unchanged
    RBK  rm mypy.ini + CI step

[ ] D4   broad-except ratchet
    PRE  none
    EDIT ruff.toml: enable BLE001 with a baseline; fix snapshot_normalizer.py silent swallows first (log + narrow)
    VER  T1: ruff clean on baseline; game_reader tests
    RBK  remove rule / per-file checkout

[ ] D11  assert -> raise (validation asserts only)
    PRE  enumerate: git grep -nE '^[[:space:]]+assert ' over runtime dirs; classify validation vs internal-sanity
    EDIT convert validation asserts to explicit if/raise; leave internal sanity
    VER  T1 per module; if any in agents/daemon_slayer/** -> T2 (engine)
    RBK  per-file checkout

[ ] D13  TLS comments + optional pin
    PRE  none; sites: bridge.py:137, lessons_receiver.py:53, lessons_ack_watcher.py:44 (NOT lcu/* frozen)
    EDIT add comment: transport auth delegated to Tailscale WireGuard; optional cert-pin
    VER  T0/T1
    RBK  git checkout

[ ] D14  safe-coach-output wrapper
    PRE  read coach_integration/_coach.py error handling + core/anthropic_client.py:24-27
    EDIT wrapper guaranteeing friendly-degrade text on any API exception; route all coaches through it
    VER  T1: coach tests + simulated 400/credit-exhaustion -> no raw string in output
    RBK  per-file checkout

[ ] D5   coach-factory extraction  (FROZEN FILE - APPROVAL REQUIRED)
    PRE  explicit human approval to edit app/_game_lifecycle.py
    EDIT extract mode->coach map (lines 85-135) into a registry/factory
    VER  T1: lifecycle tests + a live game-mode smoke
    RBK  git checkout -- app/_game_lifecycle.py

[ ] D1   Share mirror de-duplication  (HEAVIEST - own session, APPROVAL REQUIRED)
    PRE  human approval; full suite green; tag a rollback commit
    EDIT move Share/ to build-time generation; update tools/ds_share_sync.py + CI
    VER  T2: full dual suite + ds_share_sync --check + DS :8893 restart
    RBK  restore committed mirror from the rollback tag
```
Global ordering rule for the agent: never batch a T2 item (D1, possibly D11-in-DS) with anything
else; never touch a frozen file (D5) without the approval gate; run each item's VERIFY before
moving on; if `health.json` does not show `last_reload_ok=true` after a restart, STOP and roll back.

---

## Appendix A - subagent figures re-verified against git (transparency)
- "3,590 Python files" -> tracked **1,668** (3,590 counted vendored/untracked).
- "98% type-hint coverage / 8,254 signatures" -> return-annotated defs in core/+DS = **~78%**
  (7,630 / 9,727). Hints exist; no checker verifies them.
- "154 locks / 102 files" -> **134 / 96** (`Lock()`/`RLock()`).
- "70 bare `except: pass`" -> truly bare `except:` = **1**; broad `except Exception` = **1,137 /
  250 files** (the real signal).
- "2,213 test functions / 1,025 files" -> git `def test_` (non-Share) = **14,364 / 701 files**.
- TLS: subagent reported "no shell injection / safe"; this audit additionally found **8
  `ssl.CERT_NONE` sites** (D13) the sweep did not surface.
Method: where a subagent number drove a finding, the git figure above is authoritative.
```
