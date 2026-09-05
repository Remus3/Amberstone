# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-30, merger + RM-227(a) pass (relocated `2026-08-29b` RM-222 flat-pen layout guard; newest 3 = merger + RM-227(a) `2026-08-30b` + lane-7 headless-repo `2026-08-30` + port-block collision `2026-08-29c`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-09-05c - ROW EXECUTION: RM-344 / RM-345 / RM-361 shipped, and the gate refuted one

STATE. LEDGER 1335, pushed `cfb46f99b..f459e56eb`. Three worktree slices merged
`--no-ff` with zero conflicts, worktrees + branches cleaned. CI green at STEP
level on `f459e56eb`: `check` -> `full dual suite (RM-119) => success`, and
`docs-guards` success. Local dual suite measured THIS run from the merged tree:
`pytest tests -n 8` **20625 passed / 96 skipped / 4859 subtests**, `pytest
agents/daemon_slayer -n 8` **10856 passed / 13662 subtests**, both exit 0. RC
bounced pid 24988 -> **16220**, `last_reload_ok=true`. Next free id **RM-367**,
moved in BOTH pointers in one commit.

THE THING WORTH CARRYING FORWARD: **RM-345 shipped PARTIAL, and only the
adversarial gate caught it.** The slice was green, its tests were real, and its
claim was still wrong. The pool now sends a non-idempotent method exactly once -
but `lcu/lcu_client.py:191` reads the give-up `None` as "pool unavailable" and
falls through to urlopen at `:200`, re-sending the identical body. True effect is
3 sends to 2, NOT to 1. This is the `feedback_verified_claim_vs_measured_
downstream` class: the slice proved its change happened, not that it mattered
end-to-end. Docstring was scoped and the residual disclosed BEFORE merge; residual
is RM-366 and needs operator approval because `lcu_client.py` is FROZEN.

THE OTHER ONE: **two independent censuses of the sanitizer population DISAGREED**
(16 sites / 14 builders vs 19 sites / 14 modules + 3 `moon_proxy` relay paths).
Recorded unaveraged in RM-364 as probes. The structural finding is the valuable
half - the SDK `messages.create` is the FALLBACK for the top TFT sites, the
primary leaving via `moon_proxy`, so **a fix at the API call would be dead code**;
patches belong at prompt ASSEMBLY. Census 2 also sharpened the threat model: no
summoner name / riot ID / chat / queue name reaches any prompt (identity-match
keys, discarded), so the unconstrained bytes are VISION/OCR MODEL OUTPUT - a
self-inflicted model-to-model channel. And it killed three non-exposures a naive
reading of RM-361's acceptance would have had someone "fix":
`modes/shared_vision.py:400` (image + RC-authored constant only),
`warm_session.py:222` (operator text), `aram_team_analyzer.py:201` (no caller).

TWO TRAPS THAT COST TIME:
1. **A serial `pytest tests` ran 15 min and wrote ZERO bytes** (`-q` buffers), so
   it looked wedged. Killed and re-run under `-n 8`: 377s. Always `-n 8`.
2. **The stop-claim gate blocked twice on TRUE statements** about
   subagent-authored commits. `tools/stop_claim_gate.py:322` derives `did_commit`
   from THIS session's own Bash, so `git show` corroboration cannot satisfy it by
   design. Do not rephrase around it - do the real commit work; a merge session
   whose commits were all authored in worktrees will hit this every turn.

NEXT. Queue is RM-346..RM-360 + RM-362/363 still open from the lane-5 refill,
plus RM-364/365/366 filed today. RM-366 is operator-gated (frozen file).

---

# 2026-09-05b - MERGE SESSION: both cycle-48 lanes are ON MAIN, ids assigned, MC bounced

STATE. LEDGER 1334. `lane/research` then `lane/true-audit` merged in plan order
(`e173e6ab2`, `ea45ff5be`), then `8263bb311` for ids + a CI fix, then the wrap
commit. Main is green: dispatched run 33968377531 on `8263bb311`, `check` job
`full dual suite (RM-119) => success` verified at STEP level, `nightly-full-suite
=> success`. `RC-MissionControl` pid 2092 -> **20600**, `/api/loop-status` 200.

THE TWO THINGS THAT COST TIME, so they do not cost it twice:
1. The merge went in RED and the lanes could not have known. `docs-guards` +
   `ci` both failed on `ea45ff5be` on ONE test - the RM-171 citation guard, on
   `coach_integration/_sr_prompt.py:308` in the refill doc, written there with a
   leading dot-slash. That prefix reads as an untracked path. Content was
   correct; the prefix was dropped. Do NOT write the dot-slash form in a doc,
   not even when quoting the defect - this entry tripped the same guard once.
2. **A docs-only fix cannot prove itself.** `ci.yml:24` path-ignores `**/*.md`,
   so the fix commit ran ONLY `docs-guards`. Believing that green would have left
   the full suite unverified on HEAD. `ci.yml:31` has `workflow_dispatch` and
   `:143` runs `check` on every event but `schedule` - dispatch is the close, and
   this is NOT the RM-157 ban (that bans DUPLICATING a push run; none existed).

IDS. RM-344..RM-363 assigned to the 20 rows in `docs/_research_refill_2026-09-05.md`,
re-derived from the tree (max live = RM-343), NOT minted from the tracker on faith.
Both pointers now RM-364 (`docs/DS_SWEEP_TRACKER.md` + `ROADMAP.md`), in one commit.

DO NOT REDO. RM-250 stays closed. RM-343 stays open and is NOT closed by
re-materializing 1884 files in a branch. MC is HTTPS on `:8895` - an http probe
returns 000 and reads like a dead process. RC needs no bounce for loop-route
changes (`dashboard/_errors.py:6`).

---

# 2026-09-05 - LANE 8 cycle 48 + LANE 5 refill, HEADLESS (NOT on main - two lane branches ready)

STATE. Lane 8 (`lane/true-audit`) and lane 5 (`lane/research`), both run detached
with the operator away. LEDGER 1333. ENGINE 1.280.0 unchanged, Tier-1, no
`:8860` bounce, no Share sync, no `web/` change. **Neither branch is merged** -
lane 8 ships LAST by the Mission Control plan, and the merge is the merger's.

WHAT LANDED. RM-250: seven `ops/loop/` writers now route through
`core.polled_json.atomic_write_bytes` (bounded ~275 ms PermissionError retry,
per-writer scratch name, cleanup on every failure path). 15 tests in
`tests/test_loop_control_sibling_writers_lane8_cycle48.py`, five distinct
mutations. RM-343 filed. `docs/DS_SWEEP_TRACKER.md:72` corrected. Lane 5 filed
20 rows to `docs/_research_refill_2026-09-05.md` (`0d2545c19`, pushed).

THE THREE THINGS WORTH CARRYING FORWARD.
1. **The filed row was wrong in three separate ways and only measurement found
   it.** Its acceptance was unshippable as literally written (a plain
   `core.polled_json` import crashes a controller loaded by absolute file path);
   its SECOND HALF was already false the day it was filed, fixed hours earlier by
   cycle 24; and its sibling count was three when the truth was seven. Execute a
   filed row by re-measuring it, never by following it.
2. **The lane's own first guard was VACUOUS and the adversarial pass proved it.**
   `_bind_path` short-circuits on `if modname in sys.modules`, so seeding the
   bind name with a stub made the test pass while only one of three fallbacks
   ever executed. A guard that asserts "a name resolved" is not asserting the
   right file was found. This is why the author never grades its own work.
3. **AST, not grep, for a structural guard.** A text scan for `os.replace` over
   `ops/loop` returns TEN hits here and every one is prose - including the
   comments this cycle wrote explaining the removal.

FOR THE MERGER. Bounce `RC-MissionControl` after merging: nothing in
`dashboard/`, `app/` or `mc/` imports these modules at import time, Mission
Control late-binds them, so the running process holds the old code until it
restarts. Assign research-row ids from **RM-344** upward (cycle 48 consumed
RM-343); do NOT mint from `docs/DS_SWEEP_TRACKER.md` without re-deriving - it was
six ids stale this run and is corrected but unguarded. Three RC suite failures
are INHERITED and proven independent (RM-343 CRLF; two DS-share env failures) -
do not read them as this branch's regressions.
