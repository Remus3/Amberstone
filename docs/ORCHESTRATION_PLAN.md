# Orchestration Plan - Directed Fanout Run

LIVING DOC. The director reads this each cycle and picks the next OPEN
session (top-to-bottom, phase order A -> F). The executor cycle updates it:
flip the picked session OPEN -> WIP -> DONE, fill the Commit sha, and append any
newly discovered work to the Findings log at the bottom. When no session is OPEN,
the director emits NO_WORK and the loop self-terminates.

**The director is CLAUDE, not Gemini.** That vendor was retired 2026-08-01 and
the loop has been single-vendor since - director, executor, adjudicator and
auditor are all Claude. This header said "Gemini-Directed" until 2026-08-16
while the operator-directive paragraph further down already recorded the
retirement ("NO gemini director - that vendor is retired (2026-08-01)"), so the
file refuted itself, and `ROADMAP.md` designates this doc "machine-read each
cycle" - making the stale header the first thing a director read.

Per-cycle contract (enforced by ops/loop/director_prompt.md):
orchestrator multi-agent fanout (disjoint-file worktree subagents, sole merger,
verifier-gate each slice before merge) -> TDD (failing test first) -> py_compile
before any restart -> full pytest suite green -> UI sessions also pass the 5-phase
fixture audit (STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY) + a
overlay visual check via the Playwright ui_recon harness + :8810 static preview (NOT Claude_Preview vs :8888, cannot attach per R2) -> commit with a descriptive message ->
push to origin/main -> /done ritual (append docs/LEDGER.md, sync ROADMAP + this
file) -> "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" ops/loop/done_sentinel.py. No AskUserQuestion; auto-pick safest option.

ASCII only. No em-dashes, en-dashes, or smart quotes.

## Sessions

NOTE (2026-11-07, RM-712): every DONE round that sat here, the duplicated
`## Sessions - DIRECTOR REFILL 2026-07-21` heading, the old findings entries,
the DONE rows R222-R225 and the R229 findings block now live VERBATIM in
`docs/ORCHESTRATION_PLAN_HISTORY.md` under "Relocated 2026-11-07 (RM-712)",
each block with its original line range and sha256 (guard:
`tests/test_orchestration_plan_relocation_rm712.py`). What stays: this header,
the EXCLUDED list, the WIP row R221 with its round, the newest round and the
newest findings block. The plan now fits inside PLAN_CTX_CAP, so the director
reads it whole. With zero OPEN sessions the director emits NO_WORK until a
new round is appended.

## EXCLUDED (live-game / operator-gated; the director MUST NOT pick these)

- DS Phase-D default-ON flag flips (apply_passive_damage, non-every-AA on_hit, per-stack assumed_stacks) - need real-game re-ranking validation.
- Live caster-stat producer for /anti-tank P3.2 activation + live survivability scorer (egg-resist / Orianna E) - need a live AbilitiesSnapshot / game.
- Champ-select brief Haiku -> deterministic flip - needs live shadow-log accrual + operator OK.
- Game-PC :8892 visual screenshot captures (machine retired post-1PC, ADR-011). C-phase / overlay visual validation uses the Playwright `ui_recon` harness + the `:8810` static preview (the Chrome `:8888` dashboard cannot be attached per R2 and is retired as an audit surface 2026-06-27; the Electron overlay is the sanctioned surface).
- Anything in the CLAUDE.md "Settled - do not re-litigate" set.
- Haiku-to-ZERO LIVE coach flips: removing/replacing a live Haiku call with the HZ-* precompute tables. Per charter 4b "do not flip blind" - needs real/replayed-game validation + operator OK. The HZ-* sessions BUILD + PERSIST + SHADOW-LOG only; Haiku stays the interim floor until validated.
- DSP/DSV default-OFF seam live default-ON flips in rank.py/burst.py + every row in docs/LIVE_GAME_GATED_SYNC.md - need a real game. The DSP* sessions ship the seam DEFAULT-OFF + offline-validate it; the executor APPENDS each new seam's live flip to docs/LIVE_GAME_GATED_SYNC.md and NEVER flips blind.
- Electron IN-GAME overlay 2026-07-05 LIVE-RECON punch-list (drag/move system, item context-menu/radial tooltip crop+position, PR enemy-spell click-to-timer, objective-gauges 1-line layout, the round-1 missing-in-game cluster rn-lead/rn-choices/rn-callouts/w-spike, the build-META-static / DMG-SURV-UTIL knob-stepper / item right-click radial bugs, the am-statspanel clarify). The operator LIVE-GATED the ENTIRE remaining punch-list in ROADMAP.md (2026-07-05 LIVE-GATED WRAP): "Do NOT ship these blind headless; root-cause is fine, but each fix needs the operator's live Ctrl+Alt+A overlay verify before it lands." The agent cannot see the Electron overlay (only ?overlay=1 headless capture, which does NOT reproduce these). Root-cause investigation is allowed; SHIPPING any of them blind is forbidden. Do NOT pick an overlay punch-list item as a directive - overlay drains route through the operator's live Ctrl+Alt+A session (docs/LIVE_GAME_GATED_SYNC.md). This is DISTINCT from dashboard Post-Game-Review UI slices (ORUN3/ORUN4), which audit headless via ui_recon + the :8810 static preview with pixel-capture OWED and ARE shippable this loop.

## Findings log (executor appends; newest first)
> Older findings entries are relocated (relocate-only, immutable) to
> docs/ORCHESTRATION_FINDINGS_ARCHIVE.md when this log outgrows the
> director-context byte budget (loop_controller PLAN_CTX_CAP). Newest ~10 stay here.

## Sessions - DIRECTOR REFILL 2026-07-28

| Item | Slug | Scope | Status | Commit |
|---|---|---|---|---|
| R221 | live-wave-clock | MinionsSpawning extract (`dashboard/_liveclient.py:387-402`, 11 tests) + `dashboard/_wave_timing.py` pure spawn clock (42 tests / 801 subtests). RM-124 F1 backend, BOTH slices shipped, verifier CONFIRM 7/7 then 9/9. **The directive's wave_top/wave_mid/wave_bot target was REFUSED as fabrication** - those are the lane push-percentage state machine RM-124 declares data-blocked; the module ships the TIMING subset only, with an anti-fabrication test pinning the key set. Panel wiring still deferred behind live-gate G2-45 (nobody has seen real MinionsSpawning bytes; the cannon-cadence table is unvalidated). ENGINE-IMPACT NONE. | WIP | 7121ca85 + `<this commit>` |

## Sessions - DIRECTOR REFILL 2026-09-11

| Id | Slug | Notes | Status | Commit |
|---|---|---|---|---|
| R226 | suite-live-tree-writes | DIRECTOR REFILL 2026-09-11, cycle 68. Census of the defect class "a test writes / deletes / replaces a path that is the operator's LIVE state instead of `tmp_path`". Filed as R226 and not R225 because the directive's own id was already occupied by `ds-rm97-pet-damage-probe` (DONE). **LANDED cycle 69** - cycle 68 measured and shipped nothing, so the deliverable was an uncommitted tree. AFTER re-measured on the final tree: **13 units over 1 path, and that path is the declared EXCEPTION**, against 201079 over 17 BEFORE. Both adversarial slices returned findings that changed the commit (slice 1 BLOCK, slice 2 SHIP-with-misses); the overclaims they refuted were deleted rather than softened. ENGINE-IMPACT NONE. | DONE | `c00b9af89` |
| R227 | ci-orphan-test-trees | RM-407: wire the test trees no CI job collects, after a vacuity sample, with a nonzero-collected assert. ENGINE-IMPACT NONE. **LANDED cycle 71.** Cycle 70 measured and adjudicated this correctly but never committed, so the deliverable sat as an uncommitted tree while HEAD `c00e2f1d6` still ran the agent3 step BARE - a 1-in-3 flake inside a push-blocking job. This cycle landed the repair. `tools/tests` (348 collected) WIRED into the push `check` job behind a nonzero-collected assert; `agents/agent3_testing/suite` (359) EXCEPTED on a verifier-measured 1-in-3 flake (`test_supervisor.py::test_supervisor_starts_and_binds_ports`, heartbeat never refreshes, `test_supervisor.py:203`) and declared as an EXCEPTED row carrying that mechanism. Per the cycle's own adjudication rule, one tree wired plus one BLOCKED-with-evidence is a complete cycle, but the row stays WIP until the flake is fixed at source. Class guard `tests/test_ci_collects_orphan_suite_trees.py`, 17 arms, 7 of 7 verifier mutations RED. Two findings filed as their own ids: RM-408 (the live-write tracer has no planted control) and RM-409 (the suite mutates the live supervisor over a socket, a route RM-406 cannot see). The EXCEPTED row is not a shortfall against the plan: the gate and the audit doc now use the SAME word, and the guard binds it - a mutation re-adding an agent3 step while the row reads `_EXCEPTED` was driven RED this cycle on `test_excepted_roots_are_absent_from_ci`, then reverted to green. | DONE | `2df4d10e0` |
| R228 | docs-budget-red | DIRECTOR REFILL 2026-09-11, cycle 73. Cleared the `tools/drift_guard.py` RED that LEDGER 1394 left as pre-existing. `ROADMAP.md` 74881 -> 65475 bytes, 91.4 -> 79.9 percent of 81920, guard exit 1 -> exit 0 / 0 breaches, landing under 80 percent rather than back on the 90 percent warn line. Nine rows relocated VERBATIM to a new `docs/ROADMAP_HISTORY.md` `## 2026-09-11` block, proved by sha256 on three blocks AND independently by the verifier diffing line sets (9 of 9 removed lines byte-identical among the 28 added, 0 paraphrased); 213 distinct RM ids reachable before and after, set difference empty both directions; nothing OPEN / WIP / BLOCKED moved and the JOINT RE-PIN row byte-identical to HEAD. Doc-budget defect class population 2 = the whole `DOC_BUDGETS` table: `ROADMAP.md` RELOCATED, `CLAUDE.md` 86.2 percent OUT-OF-SCOPE and named as the next row to fall due. Second half fixed a docstring in `tests/test_ci_collects_orphan_suite_trees.py` that staled inside its own commit, rewritten to state the arm's LOGIC so a root flip in either direction cannot re-stale it. **The directive's own defect-class grep under-measured its population and the verifier REFUTED the figure**: pattern said 1, a wider digit/number-word scan found 3 more of the same shape (4 FIXED total, including the lowercase TWIN at `:276` the pattern could not see), with the dated measurement block and the ci.yml citations held OUT-OF-SCOPE with reasons and one remaining falsifiable claim NAMED at `:133-134`. Ran SERIALIZED per the executor override; the override's stated collision did NOT hold on inspection (file sets genuinely disjoint, and its list names "AGENT 1 and AGENT 1"), but serialization was kept as strictly safer. ENGINE-IMPACT NONE; DS suite not run and no DS count claimed, zero files under `agents/daemon_slayer/`. | DONE | `23c1bca31` |
| R229 | lf-writer-direct-coverage | DIRECTOR REFILL 2026-09-11, cycle 74. RM-410. **The directive's headline premise was REFUTED before any code was written, by the verifier and then by an independent re-probe.** It asserted "NO test anywhere calls `lib/ddragon/fetch.py`'s own writer" and that the RM-406 class guard "asserts the TARGET files' git attributes and sweeps tracked bytes" only. False: `tests/test_tracked_json_producers_emit_lf_bytes.py` has a BEHAVIOURAL half - `_invoke` at `:115` calls `fn(target, _PAYLOAD)`, `:137` reads `raw = out.read_bytes()`, `:141` asserts `pairs == 0`, `:146` asserts `b"\r" not in raw`, parametrised over all six `_PRODUCERS` rows; `-k fetch` -> 3 passed, 17 deselected. All six producers already had direct CRLF coverage. **The premise's ORIGIN was found and fixed at the root**: `docs/ORCHESTRATION_PLAN.md:916-919` said the fetch writer was "exercised by no test of its own ... carried in the new class guard's table and nowhere else", a sentence that SELF-STALED inside `c00b9af89`, the very commit that added the 229-line guard, because its author read a `_PRODUCERS` row as inert bookkeeping rather than a call site. That sentence is struck and corrected in this commit, so the next director cannot re-derive the same false premise from it. **The cycle still shipped, on the REAL residual gap.** `tests/test_ddragon_fetch_writer_emits_lf.py`, 6 tests, adds the five properties the guard does NOT assert: the exact compact-encoding byte pin, the measured finding that a compact dump holds no literal LF, an `indent=2` positive control, no surviving `.tmp`, and an `os.replace`-raises fault injection proving a pre-existing target keeps its bytes. **The TDD red-proof the directive ordered was REFUSED as unprovable and replaced with a positive control, which is the finding of the cycle**: the historical pre-fix line `tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")` is BYTE-IDENTICAL to today's `write_bytes` for any JSON payload, because compact separators emit no literal newline (newlines inside strings are escaped), so a claimed red-proof against the real pre-fix line would have been a false claim. The reachable regression is an `indent=`, and the control measures 20 CRLF pairs against the real writer's 0. DEFECT-CLASS ENUMERATION, population 6 measured two ways (AST over `_PRODUCERS` -> 6, `--collect-only` -> 20 = 3 x 6 + 2): 2 COVERED, 4 PARTIAL and named (`daemon_slayer_extract._atomic_write_json` / `_atomic_write_text`, `daemon_slayer_abilities_extract._atomic_write_json` CRLF-only with no dedicated test; `core/polled_json.atomic_write_json` has direct tests that round-trip through `read_text` and pin no bytes), 0 out of scope. `data/meta_build/ddragon/16.18.1/_assets_manifest.json` disposed explicitly - untracked, gitignored at `.gitignore:160`, 1839391 bytes, 42318 CRLF pairs, every newline a CRLF, bytes deliberately NOT rewritten. Census at `docs/audits/LF_WRITER_DIRECT_COVERAGE_2026-09-11.md`. Both slices verifier-gated and both came back REFUTE the first time - slice 1 on the false WHY paragraph, slice 2 on two `ORCHESTRATION_PLAN.md` citations that were correct at the slice's own worktree HEAD `8ad4b6678` and off-by-one at the merge target `ca6f42554`; both were corrected before merge rather than softened. Ran SERIALIZED per the executor override; as in R228 the override's stated collision did NOT hold (its list names "AGENT 1 and AGENT 1"), but a real ordering dependency did - the census cites the test file - so serialization was correct for the wrong reason. ENGINE-IMPACT NONE. | DONE | `7ff5fc853` |
| R230 | wrap-r229-plus-scoped-fault-injection | Land + wrap RM-410, retarget the process-wide os.replace patch, census the class. **Two halves.** (1) `7ff5fc853` was committed in cycle 74 but never pushed or wrapped, and its R229 row carried an unresolved `<this commit>` placeholder - resolved here, which is the self-staling defect this cycle exists to repair. (2) `test_atomic_write_json_leaves_target_intact_when_replace_fails` was patching `os.replace` PROCESS-WIDE; the shim is now DESTINATION-SCOPED, raising only for a destination at or under `tmp_path` and otherwise delegating to a `_real_replace` captured before patching, with a CONTROL `os.replace` into a `tempfile.mkdtemp()` dir OUTSIDE `tmp_path` asserted INSIDE the armed window. **Red-before-green OBSERVED:** unconditional shim -> `1 failed, 6 passed in 1.31s` with the control as the FIRST failure; scoped shim -> `7 passed in 1.10s`. A second new test patches NOTHING and provokes the real `OSError` by pre-creating the destination as a non-empty directory (Windows: `PermissionError [WinError 5]`). Advisory 2 landed as CHARACTERIZATION, not a fix - both fault arms assert the `.tmp` sibling LEAKS, because `lib/ddragon/fetch.py:33-44` has no `try`/`finally` and no unlink; that file was deliberately NOT edited, so a future `finally` must flip those assertions deliberately. **CENSUS of the defect class, run twice (orchestrator pre-edit, verifier post-edit): 29 lines pre-edit all real call sites, 30 post-edit of which 29 are call sites and 1 is net-new DOCSTRING PROSE at `tests/test_ddragon_fetch_writer_emits_lf.py:188` - the grep matched its own documentation.** DESTRUCTIVE subset 8 call sites across 6 files, 1 FIXED here and 7 filed as **RM-411** under BACKLOG "Reliability / hardening" - filed rather than swept because 8 is above the directive's threshold of 5. **THE DIRECTIVE'S STATED REASON IS REFUTED:** "this repo runs `-n 8`" is the wrong mechanism - xdist workers are separate PROCESSES each running its tests SERIALLY, so `-n 8` does not widen the exposure at all; the real window is same-process callers, threads above all. The fix is still correct; its reason was not. Gate: `pytest tests/test_ddragon_fetch_writer_emits_lf.py tests/test_tracked_json_producers_emit_lf_bytes.py -q -p no:randomly` = 27 passed in 3.09s, ruff clean, 0 non-ASCII in 13954. Tier-1, ENGINE-IMPACT NONE. Commit cell cites `eb440accf`, the code-plus-wrap commit this row describes, NOT the one-line docs commit that fills this cell - a two-commit close is what keeps a self-staling `<this commit>` placeholder out of the tree, which is the defect R230 exists to repair. | DONE | `eb440accf` |

### Findings log - R230 (2026-09-11)

- **A module-attribute handle READS like containment and is not - `mod.os` IS the stdlib `os` singleton.** `setattr(mod.os, "replace", ...)` looks narrower than `setattr(os, "replace", ...)` and is identical in blast radius, because `mod.os` is a reference to the one module object every importer in the process shares. Proved by identity, four for four, not argued: `lib.ddragon.fetch.os is os` -> `True`, `core.polled_json.os is os` -> `True`, `agents._supervisor_common.os is os` -> `True`, `tools.inbox_responder_export.os is os` -> `True`. The handle spelling is cosmetic. **And one census instance already skips the pretence entirely:** `tests/test_rofl_archive_lane8_download_bounds.py:259` is a bare `monkeypatch.setattr(os, "replace", flaky)` with no handle at all. The exposure is not hypothetical in the affected files - `tests/test_p2w1_core_f.py:30`, `tests/test_polled_json_lane8_cycle24.py:49` and `tests/test_p2w2_ds_h.py:47` each `import threading`, so same-process concurrent callers exist in the very files doing the patching. **Transferable:** when auditing a monkeypatch for blast radius, probe `mod.attr is stdlib_attr`; do not infer scope from the dotted spelling.
- **A directive can order the RIGHT fix for a REFUTED reason, and the refutation has to be written down or the wrong mechanism propagates into the next filing.** R230 justified retargeting the process-wide patch with "Serial run contains it; this repo runs `-n 8`". That mechanism is WRONG: pytest-xdist workers are separate PROCESSES, and each worker runs its own tests SERIALLY, so `-n 8` gives you eight independent processes each holding its own `os` module object - it does not widen the exposure by one bit. The real exposure window is other callers **inside the SAME process** during the patched interval, background threads above all. The fix shipped anyway because it is correct on the true mechanism. **Transferable:** grading a directive's CONCLUSION green is not grading its PREMISE; record the refuted premise on the row, or the next director re-derives it as fresh justification - exactly the self-staling failure R229 was already about.
- **A census grep can COUNT ITS OWN DOCUMENTATION.** The class census moved 29 -> 30 between the pre-edit and post-edit runs, and the entire delta is `tests/test_ddragon_fetch_writer_emits_lf.py:188` - a net-new DOCSTRING line that names the very pattern the census matches on. Zero new call sites were added; one sentence of prose was. **Transferable:** a census whose search pattern appears in the prose describing the census drifts upward every time someone documents it, and by TALLY that drift is indistinguishable from a real new instance. Read the matched LINES at both ends, never the count, and state the call-site figure separately from the grep figure (here: 29 call sites, 30 matched lines).

## Findings log - older blocks relocated 2026-09-11

The R227 and R226 findings blocks, the "Older findings" doctrine block and the
R220 / R221 / R224 pointer stubs now live in
`docs/ORCHESTRATION_PLAN_HISTORY.md` - 12962 bytes, moved verbatim and proved
byte-identical by sha256, not eyeballed.

**2026-11-07 (RM-712).** Everything else the plan still carried - every DONE
round from 2026-06-17 to 2026-07-26 (with the duplicated 2026-07-21 heading),
the 2026-07-13 to 2026-07-28 findings entries, the DONE rows R222-R225 and the
R229 findings block - moved to the same history file under "Relocated
2026-11-07 (RM-712)", four blocks, each sha256-recorded there. The plan went
from 385551 bytes to under PLAN_CTX_CAP, so the director now reads it whole;
the steady-state rule below applies again once it outgrows the cap.

**Do not re-append old findings below this line.** The loop director reads this
file through `cap_bytes_head_tail(..., PLAN_CTX_CAP=24000, PLAN_CTX_HEAD=8000)`
(`ops/loop/loop_controller.py:473,488,756`), so it receives only the first 8000
bytes and roughly the last 16000; the middle is cut. The session table sits in
that middle and findings are appended AFTER it, so every block pushes the newest
`| R<n> |` row further from EOF until it drops into the cut and the director
mis-grounds the next cycle on a stale newest row. **Steady-state rule: as you
append your findings block, relocate the previous cycle's block verbatim into
the history file** - keep about one block at the tail and the newest row never
drifts. Two guards in
`tests/test_loop_director_context_caps.py` bind this:
`test_real_orchestration_plan_newest_row_survives` reds once the row is already
gone, and `test_real_orchestration_plan_newest_row_keeps_tail_headroom` reds
while there is still room to act. Relocate - never raise the cap, shrink the new
row, or relax the guard.
