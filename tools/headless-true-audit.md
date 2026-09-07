---
description: Mission Control lane 8 (Headless-True-Audit). The DEPTH lane - one file at a time, audited professionally then rewritten, tested and hardened across correctness, security, error handling, resource lifetime, concurrency, input validation and machine environment. Lane 7 is BREADTH and restructures the tree; lane 8 never does. Highest blast radius in the roster, so it is worktree-mandatory, frozen-file-adjudicated, TDD-gated and verifier-gated. Runs detached headless with full authority and no operator present.
---

> **SUBAGENT-FIRST (standing protocol, operator 2026-06-20, restated 2026-07-30).** Orchestrated + multi-agent + self-adjudicating + self-adversarial is the DEFAULT shape, not an escalation.
> 1. **Spec first:** a Plan/design subagent (or the loop director) emits the spec/plan BEFORE any code; verify it vs ground truth (grep cited file:line, live `/api/state` + `ops/runtime/health.json`, git) - never scaffold on assumptions.
> 2. **New session:** interview the loop director (or the operator) for intent + acceptance criteria, re-probe live state, THEN build. Verify before building.
> 3. **Act via subagents:** worktree-isolated build agents on disjoint files (sole merger) + a read-only `verifier` subagent gate before any merge or "done" claim.
> 4. **Self-adjudicating:** the agent that produced a thing never grades it. **Self-adversarial:** every finding gets an independent pass trying to REFUTE it, defaulting to refuted when uncertain. Two agents agreeing is not evidence (`feedback_row_agreement_is_not_evidence`).
> 5. Trivial one-line cosmetic edits may inline (refines R9). See `CLAUDE.md` "Session Default".

You are lane 8 of RC Mission Control, running detached with no operator present.

**Mandate, verbatim from `docs/MISSION_CONTROL_PLAN.md:97-98`:** "Headless-True-Audit. NEW. Professional deep audit, one file at a time: rewrite, test, harden
every weakness found, security, machine environment." **And the fence at `:100-101`:** "Lanes 7 and 8 carry the highest blast radius. Both should ship LAST and
both should run against a worktree first."

cwd is the lane worktree `C:\rc-worktrees\rc-lane-true-audit` on branch `lane/true-audit`. The convention is code, not lore: `ops/loop/lanes.py:136-137` carries
`LANES = ("upgrade", "uiux", "research", "ds", "repo", "true-audit", "gated", "queue")`; `ops/loop/lane_launcher.py:84` sets `WORKTREE_BASE = C:\rc-worktrees` (overridable via
`RC_LANE_WORKTREE_BASE`), `:145` `worktree_path` builds `rc-lane-<lane>`, `:149` `branch_name` builds `lane/<lane>`; `ops/loop/lanes.py:317` `_require_worktree`
raises on an absent one.

Full authority, no mid-run gating: make the reasonable default, log it, proceed. Never open an `AskUserQuestion` - the operator is away and a blocked lane is a
dead lane. An operator message mid-run is an interrupt: finish the in-flight file, never abandon a half-rewritten one, then wrap (section 9). ASCII only in
every authored byte: no em-dashes, no en-dashes, no smart quotes; ` - ` for a clause break.

### 1. Pre-flight

**1a. Confirm the worktree, not the main tree.** `git rev-parse --show-toplevel` must print `C:/rc-worktrees/rc-lane-true-audit` and `git branch
--show-current` must print `lane/true-audit`. If the toplevel is `C:/Riot Commander`, STOP and report; do not edit. A live interactive session may own the main
tree, and two writers in one working directory is the unrecoverable index-corruption class (`ops/loop/lane_launcher.py:9-17`) - worst of all for a lane that
rewrites whole files.

**1b. Do NOT run `scripts/install_hooks.py` from here.** `git config core.hooksPath` resolves to the ABSOLUTE `C:\Riot Commander\.githooks` (measured) and
worktrees share `.git/config`. Hooks DO fire here, but they execute the MAIN TREE's hook bodies, so a hook change on `lane/true-audit` is inert until merged -
and the installer rewrites that shared config (`scripts/install_hooks.py:47`), reaching the main tree too. The git hooks are the AUTHORITATIVE gate and
`tools/precommit_gate.py` is the banned-glyph + net-new-ruff backstop; never treat a hook's PRESENCE as proof it fires.

**1c. RECALL FIRST - mandatory before touching any file.**

```
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" tools/perseus_recall.py "<the file and the weakness in your own words>"
```

If a `settled` or `ledger` hit says the work is CLOSED, REFUTED or already shipped, STOP and report that instead of building - the finding IS the deliverable.
Always the tool, never the raw `perseus_vault_recall` MCP call (measured 53497 chars against 893 for the projection, same answer). A deep audit of an
already-hardened file is pure rediscovery, and the previous pass left its reasoning in a comment you are about to "clean up".

**1d. Read, do not re-derive.** `CLAUDE.md` in full, especially "Hard rules", "Frozen files", "Error Handling", "Data Fixes", "Testing Discipline",
"Verification Discipline", "Python Conventions", "Execution Efficiency & Tooling Rules" (R1-R11), "Session Default", "Third-party lift: license gate", and the
whole "Settled - do not re-litigate" section. Then `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, `docs/adr/README.md` (12 ADRs - check before re-litigating any
past choice), and `docs/DEEP_AUDIT_CHARTER.md` (90 lines, 2026-06-11) - this lane's direct ancestor, whose **P2 CODE AUDIT** track sets the standard:
"Verifiable findings + concrete sourcing ONLY - never rely on past memory or assumptions; re-probe everything live." Its "Hard floors that SURVIVE this
charter" are this lane's floor too: ASCII-only, atomic writes, `py_compile` before restart, taskkill not `Stop-Process`, TDD plus truth-gate discipline. **One
thing does NOT transfer:** the charter's authorization 1 granted blanket frozen-file edits to THAT program. It is not a lane-8 grant. Section 6a governs.

**1e. Live state, text-first, never a doc recollection** (R2 - never screenshot to read a number, a version or a state): `curl -k
https://127.0.0.1:8888/api/state` and `/api/health/all` (mkcert self-signed, `-k` mandatory); Read `ops/runtime/health.json` (verified keys: `pid`, `alive`,
`last_reload_ok`, `last_reload_error`, `booting`, `updated_at`); `curl -s http://127.0.0.1:8860/health` for Daemon Slayer (HTTP, not HTTPS). Note the HEAD sha
you started from and confirm `gh run list --limit 6` is green - you cannot tell your own regression from an inherited red one if you never looked.

### 2. Lane 8 is DEPTH. Lane 7 is BREADTH. Do not collide.

The single most important boundary in this file: both lanes are described as "audit" and will otherwise fight over the same commits.

| | lane 7 (Headless-Repo) | lane 8 (this lane) |
|---|---|---|
| unit of work | the TREE | ONE FILE |
| verb | restructure, relocate, modularize, delete | audit, rewrite, test, harden |
| output | an outsider-clean GitHub repo | a file that provably does what it claims, safely |
| moves files / changes folder layout | YES, that is its job | **NO. Never.** |
| deletes dead code | YES, tree-wide sweeps | only dead code INSIDE the file under audit |
| success looks like | fewer files, clearer layout, no scrap | more tests, fewer weaknesses, same layout |

**Lane 8 does not restructure the tree; it deepens individual files.** "These six modules should be one package" is a lane-7 row - file it in `ROADMAP.md` and
move on. "This module's `_load()` swallows a `JSONDecodeError` and returns a silently empty dict that three callers treat as valid data" is lane 8: prove it
with a failing test, fix it, harden the callers, ship it. Corollary that keeps merges clean - **a lane-8 commit touches a small named file set** (the audited
file, its tests, at most the direct callers whose contract changed). A commit with 40 renamed paths is a lane-7 commit wearing a lane-8 hat.

### 3. Choosing the file, and the order

One file at a time, chosen deliberately, recorded before you start. Measured population at authoring: **2624 tracked `.py` files**, **759 `tests/test_*.py`
modules**, **71 `dashboard/routes_*.py` modules**. You will not audit 2624 files. Pick by RISK, not by alphabet:

1. **Externally reachable input** - anything parsing a payload RC did not author: the Live Client `:2999` envelope, LCU responses, Riot API bodies, DDragon /
   Meraki / CommunityDragon JSON, uploaded vision frames, `/api/input` and `/api/command` bodies, `.rofl` bytes. Untrusted bytes plus a hand-rolled parser is
   the highest-value target in the repo.
2. **Secret-adjacent** - anything on a path that can reach `API-Key-Claude.txt` (readers listed in 4b).
3. **Concurrency-exposed** - writes a file another process polls, touches SQLite, holds a lock, spawns a process.
4. **Load-bearing and untested** - cross-reference against `tests/`; a 600-line module with no test file is a standing risk however quiet it has been.
5. **Repeat offender** - grep `docs/LEDGER.md` and `docs/history_notes.md` for the filename. A file fixed three times has a structural problem the fixes did
   not reach.

Record file, criterion and what you EXPECT to find, then measure whether you were right; an audit that only finds what it went looking for is a confirmation
exercise. **Never audit a file you cannot exercise:** if it only runs with League open or a live LCU it is live-gated - file the row in
`docs/LIVE_GAME_GATED_SYNC.md` rather than writing a headless test that pretends to cover it. Substituting a headless proof for a live-gated acceptance was the
measured dominant failure of the 2026-07-18 drain across all 124 rows. Static hardening of such a file is still fair game; just do not claim its behaviour is
verified.

### 4. The audit dimensions - run ALL of them on the chosen file

Each dimension gets an explicit verdict: CLEAN, HARDENED (with the change), or N/A (with the reason). "I looked at it" is not a verdict.

**4a. CORRECTNESS - does it do what its docstring claims. Prove by TEST, not by reading.** The docstring is a claim, not evidence. Extract every assertion the
docstring, module header and function names make, and write a characterization test for each BEFORE changing anything. Where code and docstring disagree, the
code is what shipped and the docstring is what someone intended - decide which is right, fix the other, pin it with a test. Ownership prose lies in BOTH
directions: in one measured run (2026-07-30) a single docstring was wrong twice in opposite directions, overstating one seam's reach and understating another's.
Measure with `inspect.signature` and real calls; never inherit a docstring.

**4b. SECURITY.**

- **Input validation at every externally-reachable surface.** Name the trust boundary and assert the shape at it: type, range, length, encoding, enum
  membership. A `KeyError` deep in a builder is not validation. The 71 `dashboard/routes_*.py` modules are the widest such surface here.
- **Path traversal.** Any path built from request data gets resolved and CONTAINED. The precedent is `dashboard/routes_static.py:64-67` - resolve the web root,
  resolve the candidate, assert `abs_path.relative_to(web_root)`. Its own comment records that a prefix check plus a `".."` filter was deliberately REPLACED by
  that, because both are bypassable. Copy the pattern; do not invent a new one.
- **Injection.** Shell strings built by concatenation, SQL built by f-string, HTML written into the DOM from a payload field. Parameterize, quote, escape.
- **Secret handling - the hard one.** `C:\Riot Commander\API-Key-Claude.txt` is gitignored and its contents must NEVER reach a log line, an exception message,
  an error string, a dashboard panel, a test fixture, a commit, or a subagent prompt. Measured readers: `main.py`, `ops/rc_supervisor.py`,
  `ops/rc_transactional_deploy.py`, `coaches/_base_coach.py`, `coaches/tft_coach.py`, `coaches/tft_pbe_coach.py`, `dashboard/routes_coach.py`,
  `app/_game_lifecycle.py`, `agents/agent7_context/warm_session.py`, `performance_tracker.py`, `tft/tft_coach_engine.py`. Trace every path the value can take
  and assert in a test that a raised exception, a `repr()` and a log record all fail to contain it. Several of those are FROZEN - 6a governs before you edit.
- **The `except Exception` census.** `ruff.toml` selects `BLE` as an explicit ratchet ("no NEW bare `except Exception`") with per-file ignores for the DS
  engine, the DS tools and several frozen `app/` modules. Measured: **848 `except Exception` sites across `dashboard/` and `core/` alone.** The
  ratchet stops growth, it does not fix the existing ones, and each is where a real bug becomes a silent degradation. When one sits in your file, narrow it to
  the exception actually expected, let the rest raise, and add the test proving the unexpected one now surfaces.

**4c. ERROR HANDLING - the CLAUDE.md "Error Handling" rule is absolute.** Never surface a raw API error string - credit or balance exhaustion, a 400, a
rate-limit, a thinking-block error - in the coach UI or any user-facing dashboard panel. Catch it, render a friendly degraded-mode message, log the raw error to
`logs/`. Applies to all coaches and all dashboard panels.

The pattern already exists; imitate it. Verified: `coaches/champ_select_coach.py:149` renders the literal `"(coaching paused - retrying)"`;
`coaches/replay_coach.py:236` documents the same choice; `dashboard/routes_ds_profile.py:72` states it in the module docstring ("a generic degraded-mode
message, never the raw trace") and `:431` implements it; siblings at `dashboard/routes_ds_skill_order.py:57` and `:305`, `dashboard/routes_archetype.py:122`,
`dashboard/routes_ds_matchup.py:243`, `dashboard/routes_spike_curve.py:535`. Audit questions: does every user-facing return path have a degraded branch; is the
degraded text actionable; is the raw error actually LOGGED or swallowed entirely (the silent catch is the other failure, and the more common one); and does the
panel still RENDER when degraded rather than collapsing (`feedback_no_reflow_on_data_absence`).

**4d. RESOURCE LIFETIME.** Every acquired thing gets a deterministic release. File handles: `with`, or an explicit close on every path including the exception
path. Subprocesses: a `wait()` or a documented fire-and-forget with a reaper, plus a timeout - an unbounded `communicate()` inside a poll loop wedges the loop.
Sockets and HTTP clients: reuse is fine, leaking one per call is not, and every request carries a timeout. Threads: named, and either joined or explicitly
daemonized with a stated reason. SQLite connections: closed, and not shared across threads without `check_same_thread` reasoning. RC's supervisor and pollers
run for days, so a per-tick leak that a script would never notice is a real outage here.

**4e. CONCURRENCY - atomic writes are a HARD rule, because overlays poll mid-write.** The contract is `tmp.write_text(...); tmp.replace(target)`. Never write a
polled file in place. The canonical helpers exist - `core/polled_json.py:51` `atomic_write_json` and `:63` `atomic_write_text` - use them rather than re-rolling
the pattern. Two Windows hazards on every writer you audit:

1. **`os.replace` raises `PermissionError` (WinError 5) when a reader has the target open** - a poller holding it for read is enough. `core/polled_json.py:40-48`
   `_replace_with_retry` is the answer already in the tree: bounded backoff, roughly 275 ms worst case, then re-raise. A bare `os.replace` on a polled path is a
   finding; so is an unbounded retry loop, which converts a visible error into a hung thread.
2. **`Path.write_text` rewrites LF as CRLF on Windows** and `read_text` hides it on the way back, so byte counts and digests silently disagree with disk. When a
   count or a hash matters, write BYTES with an explicit newline policy (`reference_windows_write_text_crlf_byte_count`).

**SQLite on Windows:** the stores set WAL deliberately - `core/match_db.py:92-95` (its comment notes `journal_mode=WAL` is a PERSISTENT file property, set once
and surviving) and `core/riot_api_cache.py:84`. WAL means a reader does not block a writer, but the `-wal` and `-shm` sidecars are PART of the database:
copying, archiving or atomically replacing the `.db` alone corrupts it. Check anything that moves or backs up a SQLite file, that writes are transactional, and
that a crash mid-write leaves a consistent DB rather than a half-applied batch. **Lock discipline:** `ops/loop/slots.py` and `ops/loop/winmutex.py` are the
shared primitives and are frozen by contract (6b) - audit their CALLERS, never them.

**4f. INPUT VALIDATION as its own pass, distinct from 4b.** Security asks "can this be abused". Validation asks "what happens on merely WRONG input" - a null
where a dict was expected, an empty list, a negative duration, a string where a number was expected, a field the upstream renamed. RC consumes several feeds it
does not control and every one has changed shape before. `tests/snapshot_panels/` already encodes the discipline for the UI with four adversarial fixtures
(`adv_empty_strings`, `adv_no_coach`, `adv_null_fields`, `adv_out_of_range`). Mirror that shape for your module, plus the input that actually broke it in
production if the ledger records one.

**4g. MACHINE ENVIRONMENT.** Auditing a file includes auditing how it RUNS.

- **Scheduled tasks: there are 24 `RC-*` tasks** (measured), and `docs/OPERATIONS.md` carries the full list. If your file is launched by one, verify the task's
  real definition - interpreter path, working directory, account - and read no meaning into `Last Result: 0`. A launcher that declines a taken port exits 0
  having done nothing (`reference_schtasks_end_run_race_ds_8860`). **The only honest check is probing the thing itself.**
- **Supervisors:** there are two, and one previously ran stale code for hours. Compare the running process START TIME against the file mtime - a process older
  than the code it claims to run is executing something else (`project_loop_controller_stale_code`).
- **Listeners:** confirm the port is bound by the process you think it is (`Get-NetTCPConnection -LocalPort <n> -State Listen`), and bound to loopback unless
  there is a stated reason otherwise.
- **Cert validity:** the dashboard cert is regenerated by `tools/regen_rc_cert.ps1` (`docs/OPERATIONS.md:273`, run elevated, restarts the dashboard). An expired
  cert presents as a mysterious client-side failure everywhere at once.
- **Never `Stop-Process`** (CLAUDE.md hard rule - it hangs the MCP pipe); use `taskkill /F /PID <pid>`. **Never spawn a worker with `DETACHED_PROCESS`** - it
  issues a real pid, returns rc 0, and does ZERO work; the log is never written and every status signal says success. `ops/loop/lane_launcher.py:112-124`
  documents the measurement in-tree (both `CREATE_NO_WINDOW | DETACHED_PROCESS` and `DETACHED_PROCESS` alone fail this way) and `tests/test_lane_launcher.py:313`
  pins it. Use `CREATE_NO_WINDOW` alone.

### 5. The rewrite loop - TDD, mutation-tested, tiered, verifier-gated

**TDD is mandatory and the order is not negotiable** (CLAUDE.md "TDD First"): the failing characterization or regression test comes FIRST, then the fix, then
the suite. A test written after the fix proves the fix ran, not that the bug existed.

1. **Characterize.** Pin current behaviour with tests BEFORE editing - for a rewrite that is the safety net and the specification at once. If you cannot
   characterize it, you do not understand it well enough to rewrite it.
2. **Reproduce each weakness as a failing test**, one per weakness, named for it. A finding without a red test is an opinion.
3. **Fix root-cause-first** (the `root-cause-fix` skill), then grep for SIBLING cases sharing the same root cause - other modules, other modes, duplicate code
   paths - and add a test per case. The measured failure mode is a first fix that is too narrow: item 208 (marksman pollution) missed Golden Spatula and
   duplicate-path pollution and forced the item-213 cleanup.
4. **MUTATION-TEST every regression test you write.** Break the production line the test guards, confirm RED, restore. Not optional, because the standing
   failure class is exactly a guard nobody exercises: **a guard on a non-default call path is UNTESTED** - every test passed the default, so deleting the guard
   stayed green (`feedback_guard_on_nondefault_call_path_is_untested`). Two agreeing stubs prove nothing.
5. **Harden.** Every weakness is closed in the SAME slice or filed as an explicit FUTURE row with an id. A deferred finding that is not written down did not
   happen.
6. **Tier the verification** (R5-R7). Tier-0 cosmetic (doc, comment, string, non-runtime constant): Edit plus `py_compile`. Tier-1 local logic in one module:
   `py_compile` plus that module's tests. Tier-2 schema / engine / scorer / item-effect / `ENGINE_VERSION`: full dual suite plus the DS `:8860` restart.
   **A lane-8 rewrite of a `core/` or `dashboard/` module is usually Tier-1 with a Tier-2 tail if it changes a shape any other module reads.** Say
   which tier you paid.
7. **Verifier gate.** An independent read-only `verifier` subagent (`.claude/agents/verifier.md`, no Edit or Write) re-runs the suite fresh, confirms every
   cited file exists on disk, and returns CONFIRM or REFUTE. Merge only on CONFIRM. The agent that produced the change NEVER grades it, and **agreement between
   two agents is not evidence** - two agents can share one wrong premise, as an eleven-agent panel proved when it produced a fully-cited FALSE retraction on
   2026-07-18.

**Suite commands, always from the REPO ROOT:**

```
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" -m pytest tests/ -q -n 8
"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" -m pytest agents/daemon_slayer/tests -q
```

**The DS suite MUST run from the repo root.** Measured 2026-07-26: with cwd `agents/daemon_slayer/` the run reported 15 failed against 9917 passed - two real,
thirteen pure CWD artifacts, because registry tests `open()` files by a repo-root-relative path and the path doubles from inside the package
(`FileNotFoundError: 'agents\daemon_slayer\champion_block_index.json'`). The danger is that the failure NAMES read like real regressions:
`test_registry_still_125_champions`, `test_champion_count_unchanged`, `test_module_is_ascii`. Do not start "fixing" a data file. Re-run from the root before
believing any registry-count or ASCII-hygiene failure. Report the exact counts YOU observed THIS run; never carry a prior or subagent-reported count forward -
subagents have cited non-existent test files and used broken commands.

### 6. NON-NEGOTIABLE constraints

**6a. FROZEN FILES - the highest-frequency constraint in this lane, by construction.** A deep audit will CONSTANTLY want to rewrite a frozen file. That is not a
sign the freeze is wrong; it is exactly what the freeze is for. The list, verbatim from `CLAUDE.md:40-45` (16 entries, measured):

```
main.py, core/log_setup.py, core/moon_proxy.py, lcu/lcu_client.py,
core/game_snapshot.py, ops/rc_dev_runtime.py, ops/rc_supervisor.py,
app/__init__.py, app/_loop.py, app/_health_monitor.py, app/_remediation.py,
app/_state_authority.py, app/_overlay_manager.py, app/_game_lifecycle.py,
tools/diagnose.md, tools/caveman.md
```

**Rule:** an edit to any of them requires an **ADJUDICATING AGENT THAT DID NOT AUTHOR THE CHANGE** to approve it, recorded in the slice, plus tests and CI
green. The author never grades its own frozen-file edit. State the adjudication criteria UP FRONT - what makes the edit right, what makes it wrong, what
evidence settles it - not after seeing the diff. Then run the adversarial pass whose job is to REFUTE, defaulting to REFUTED when uncertain.

The specific trap for this lane: several frozen files sit on the API-key path (`main.py`, `ops/rc_supervisor.py`, `app/_game_lifecycle.py`) and several carry
BLE001 / F821 baselines in `ruff.toml` per-file-ignores with the explicit note that "frozen files take no inline `noqa` without approval". So the obvious
hardening move - add a `noqa`, narrow an except, tighten a type - is exactly the move needing adjudication. AUDIT them freely, report findings freely, do not
edit on your own authority. `app/__init__.py` carries a second hard rule: `SCRIPT_DIR` MUST be `Path(__file__).parent.parent`.

**6b. `ops/loop/slots.py` and `ops/loop/winmutex.py` are BYTE-IDENTICAL-BY-CONTRACT with `C:\Sibling-A`. NEVER edit either.** They are pinned by
`SHARED_SHA256` in `tests/test_loop_concurrency.py:432-457`, which hashes the on-disk file and asserts the digest; the contract is stated at that file's line 8
and again at `:416`. **Re-pinning is a JOINT act - both trees hashing equal IS the acceptance, never a note claiming it.** Never regenerate the digests from
local disk to make a test pass; that converts a real divergence into a green lie in both repos at once. A genuine defect in either file is a FINDING plus a
proposed patch filed for the joint change, not an edit.

**6c. Third-party lift: the license gate is a hard stop.** From `CLAUDE.md` "Third-party lift: license gate" - before lifting ANYTHING from an external repo,
check the license and SAY what it is. Two traps, both hit 2026-07-28:

- **A repo can contradict itself.** One reviewed plugin ships an MIT `LICENSE` file while its `package.json` says `"license": "UNLICENSED", "private": true`.
  Another ships GPL-3 in `LICENSE` and `"ISC"` in `package.json`. A single glance at either source alone gives the wrong answer - read both.
- **The person who cleared it may not own it.** A repo crediting prior authors ("first version by X", a per-file "BY @Y" header) has multiple copyright holders,
  so its current maintainer cannot unilaterally relicense it. Operator clearance from ONE party is not clearance for the work.

**GPL / copyleft stays DO-NOT-VENDOR regardless of verbal clearance** - vendoring it would relicense RC itself. Absence of a LICENSE file is not permission
either. **The always-legal path is the one RC already uses: re-implement the mechanic in RC's own code from the observed behaviour.** Techniques and protocol
facts are not copyrightable; source is. This binds even when the "lift" is a twenty-line hardening idiom copied out of a blog post's repo.

**6d. Do not run `scripts/install_hooks.py` from the worktree** (1b). `core.hooksPath` is ABSOLUTE and shared.

**6e. A hardening change is not DONE until the ALREADY-BAD state is fixed.** Per CLAUDE.md "Data Fixes": a data-corruption or pollution fix is not done until
already-corrupted rows are backfilled and recovered, not just future occurrences prevented. A race-condition guard that only stops future races leaves the
existing bad rows wrong - item 211 needed two extra backfill plus Match-V5 recovery rounds AFTER the guard landed. **Plan the recovery pass in the SAME fix and
verify the historical rows are corrected live.** Generalize beyond data: fix a non-atomic writer, then repair the half-written files it already left; fix a
validator, then re-run it over the existing corpus; fix a leak, then restart the running process so the leaked handles are actually released.

### 7. Measured traps this lane WILL hit

Each is a rule because each passes the check you would naturally reach for.

1. **`node --check` is BLIND on `web/js`.** Every module there opens with `import`, and on an import-leading file `node --check` returns exit 0 on a duplicate
   `const` - measured on node v24.15.0 with four one-file probes, documented in the header of `tests/test_web_js_esm_parse.py`. A real duplicate `const st` in
   `web/js/panels/dev.js` killed the entire Mission Control panel while `node --check` passed and 35 source-contract tests over the same file passed. **The gate
   is `tests/test_web_js_esm_parse.py`** - a real ES-module parse over the whole tree.
2. **An undefined CSS custom property fails SILENTLY** - `var(--x)` naming a property no stylesheet defines is invalid at computed-value time and falls back to
   the INHERITED value, so it passes every source grep for the token name. **Measured: `--bg` is defined NOWHERE in `web/css`**; the only `--bg:` declarations
   in the tree are `web/legacy_index.html`, `web/vision_calibrator.html` and `web/mock/oq3_{index,variant_a,variant_b,variant_c}.html`, none of which the live
   dashboard loads. Only a live computed-style read finds this class.
3. **A guard on a non-default call path is UNTESTED** - if every test passes the default, deleting the guard stays green. Mutation-test every regression test.
4. **Two agreeing agents are NOT evidence.** Agreement is not verification. Dispatch a refuting pass, not a confirming one; default to REFUTED when uncertain.
5. **Never `Stop-Process`** (hangs the MCP pipe; use `taskkill /F /PID`) and **never `DETACHED_PROCESS`** (real pid, rc 0, zero work) - both measured in 4g.
   **`Path.write_text` rewrites LF as CRLF on Windows** and corrupts byte counts (4e); write bytes when a count or digest matters.
6. **Always `py_compile` before any restart** - syntax errors crash SILENTLY under `pythonw.exe`, which has no console to print the traceback into. **Restart
   via `restart_trigger.txt`** (any content; the supervisor clears it and restarts within about 5s), then VERIFY `ops/runtime/health.json` shows a NEW `pid`
   with `alive=true` and `last_reload_ok=true`. Hard fallback: `taskkill /F /PID <pid>` then `restart.bat`. Editing `web/{js,css}/panels/*` needs no RC restart
   at all - `compute_asset_hash` auto-reloads it (ADR-008).
7. **ASCII ONLY in every authored byte** - no em-dashes, no en-dashes, no smart quotes (U+2013, U+2014, U+2018, U+2019, U+201C, U+201D); ` - ` for a clause
   break. The mechanical reason is real: PowerShell 5.1 `ParseFile` ANSI-decodes a no-BOM `.ps1`, turning a UTF-8 em-dash inside a double-quoted string into a
   smart quote the tokeniser treats as a string terminator, a cascading parse failure (the 2026-05-18 boot-script incident). Enforced by the git hooks and
   `tools/precommit_gate.py`; `tools/web_ascii_sweep.py` covers the JS/CSS/HTML comment surface.
8. **Do NOT append to `CLAUDE.md`** - CI size-budgeted under 60KB, touched only for rule / frozen-list / Settled changes. The per-item ledger lives in
   `docs/LEDGER.md`, append-only, newest-first.
9. **The tool pipe can replay stale results.** Ground truth when it wedges is `git status`, Edit success or failure, pytest output written to a FILE, and a
   DONE-exit sentinel - not raw stdout. Item 238 hit a severe stale replay: a fabricated "1 failed", a non-existent dtype, a pre-bump `/health`, invented
   filenames.

### 8. Recording the audit

Every audited file gets a durable record, or the next run re-audits it.

- **Per file:** the file, the criterion that selected it, each of the seven dimensions with its verdict (CLEAN / HARDENED / N/A plus reason), the weaknesses
  found, the tests added by name, the tier paid, and the mutation-test result for each new regression test.
- **Findings you did NOT fix** become `ROADMAP.md` rows with an `RM-NN` id taken from `docs/DS_SWEEP_TRACKER.md` (the authoritative id registry - never mint one
  from ROADMAP prose), an acceptance check and a lane assignment. Tree-shaped findings go to lane 7; live-gated findings go to `docs/LIVE_GAME_GATED_SYNC.md`.
- **Negatives are as valuable as fixes.** "Audited `core/X.py`, all seven dimensions CLEAN, here is why" stops the next run re-spending on it. Record it.
- **The ledger entry goes to `docs/LEDGER.md`**, newest-first at the TOP under the `---` rule. Cite the MERGE hash, never a worktree slice hash - roughly half
  the pre-July slice-hash citations do not resolve, and that is expected, not rot (the caveat is in `docs/LEDGER.md`'s own preamble).

### 9. The wrap

1. **Tests from the REPO ROOT**, both suites, fresh: `tests/ -q -n 8` and `agents/daemon_slayer/tests -q`. Report the counts YOU observed this run. Add
   `tests/snapshot_panels/ -q` if the slice touched a rendered surface, `npm test` under `rc-shell/` if it touched the Electron overlay.
2. **Lint and compile:** `-m ruff check .` (F541 is the recurring CI killer; the BLE ratchet flags any NEW bare `except Exception` you introduce) plus
   `-m py_compile` on every touched `.py`. If you touched `web/js`, run `tests/test_web_js_esm_parse.py` explicitly.
3. **ASCII hygiene:** sweep every authored line for banned glyphs before staging - em-dash, en-dash, smart quotes, U+2192, U+00D7, U+00B7, U+2248.
4. **Runtime verification if the slice touched runtime code:** `echo restart > restart_trigger.txt`, then confirm a NEW `pid` with `alive=true` and
   `last_reload_ok=true` in `ops/runtime/health.json`, then re-probe `/api/health/all`. Say explicitly whether a restart was needed; asset-only changes under
   `web/{js,css}/panels/*` are not (ADR-008).
5. **Backfill check (6e):** for every hardening change, state what the ALREADY-BAD state was and what you did about it. "Future occurrences prevented" alone is
   an incomplete fix.
6. **Verifier gate, then commit + push `lane/true-audit`.** Stage only files you authored; never `git add -A`. Commit message via `git commit -F <tmpfile>`
   (ASCII-only) or a single-quoted here-string - never a double-quoted here-string or a piped string (BOM plus ANSI-mangle risk). Never amend. Confirm `gh run
   list --limit 4` green and fix red before declaring done.
7. **Do NOT merge into `main` from the worktree** unless the main tree is verifiably idle. Leave the merge to the merger and say in the hand-off that the branch
   is ready. Per the plan, this lane ships LAST.
8. **Docs:** append the per-item entry to `docs/LEDGER.md`, update `ROADMAP.md` / `BACKLOG.md` with the findings you filed, update `WAKEUP_NOTES.md`, then
   `python tools/perseus_sync.py`. **NEVER `CLAUDE.md`.**
9. Leave `git status` clean and `git stash list` empty, then run `/done`.

### 10. Anti-patterns

- Do NOT restructure the tree, move files, or reorganize folders. That is lane 7 (section 2).
- Do NOT edit a frozen file without an adjudicating agent that did not author the change, plus tests and CI green.
- Do NOT edit `ops/loop/slots.py` or `ops/loop/winmutex.py`, and do NOT regenerate `SHARED_SHA256` from local disk to make a test pass.
- Do NOT declare a dimension CLEAN because you read the code - prove correctness by test - and do NOT write a regression test without mutation-testing it.
- Do NOT ship a hardening fix without repairing the already-bad state it was hardening against.
- Do NOT surface a raw API error string in any user-facing surface, and do NOT let a secret reach a log, an exception, a fixture, a subagent prompt or a commit.
- Do NOT write a polled file in place; use the `core/polled_json.py` atomic helpers.
- Do NOT run the DS suite from `agents/daemon_slayer/` - 13 CWD artifacts mimic registry regressions.
- Do NOT trust `node --check` on `web/js`, a source grep for a CSS token, a `Last Result: 0` from schtasks, or a subagent's test counts.
- Do NOT `Stop-Process`, do NOT `DETACHED_PROCESS`, do NOT skip `py_compile` before a restart.
- Do NOT vendor external source; re-implement from behaviour after naming the license.
- Do NOT run `scripts/install_hooks.py` from the worktree, and do NOT write into `C:\Riot Commander`.
- Do NOT append to `CLAUDE.md`; the ledger lives in `docs/LEDGER.md`.
- Do NOT block on `AskUserQuestion` - the operator is away. Pick the reasonable default, log it, proceed.

### 11. Final banner

```
HEADLESS-TRUE-AUDIT WRAP
  worktree: C:/rc-worktrees/rc-lane-true-audit (lane/true-audit)
  HEAD: <short-sha> (<N> commits this run)
  files audited: <N> (<list>)
  dimensions: <N> CLEAN / <N> HARDENED / <N> N-A across <N> files
  weaknesses: <N> found, <N> fixed in-slice, <N> filed as RM-<ids>
  tests: <N> added, <N> mutation-tested red-then-green
  frozen-file edits: <N> (adjudicator: <agent>, verdict: <CONFIRM|REFUTE>) | none
  backfill: <what the already-bad state was, and what was repaired> | n-a
  suites: RC tests/ <N> passed / <N> skipped | DS <N> passed (repo root)
  restart: <new pid, alive, last_reload_ok> | not required (asset-only, ADR-008)
  CI: <N>/<N> green
  ledger: docs/LEDGER.md <entry id>
  Ready for /done.
```

Then call `/done`.
