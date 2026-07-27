# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

## 2026-07-27 - R198 Arena coach overlay UI audit (ENGINE-IMPACT NONE, `964f3be1`)

**The UI audit found a backend bug, and it was the most valuable thing in the run.**
`core/lead_projection.py` had no ARENA weight profile, so Arena silently inherited SR -
whose heaviest axis is `cs: 0.40`. Arena has no lane CS, so `cs_sig` sat at a permanent
`-1.0` and every Arena composite carried a fixed `-0.40` drag. A level-16 12/1/10 player
was told "Behind: scale, only fight with your team", at the top-centre eye-line anchor,
in a mode with no team. Fixed by deriving an ARENA row from ARAM (already `cs: 0.0`) and
adding `_ARENA_LINES` so no SR line naming CS / waves / towers reaches an Arena tick.

**A code comment claimed a check that had never been run.** The overlay WIDGETS registry
said every default position was "deliberately checked against EVERY other default". It
had only ever checked the others against `w-arambalance`. The guard found EIGHT
overlapping pairs plus one widget 58px off the right edge of the viewport. Six defaults
moved. `_clampXY` could never have caught the off-screen one - it only keeps the
top-left CORNER on-screen, so a wide widget anchored near the right edge is invisible to
it. Worth an operator glance: `w-stats` and `w-nextbuy` left the bottom-left quadrant
because `w-build`'s 412x594 box owns it and cannot share.

**Two guard weaknesses are filed, not fixed** (BACKLOG, from the verifier): the collision
guard's HEIGHT budgets are 7 measured / 6 estimated, and `w-enemyspells: 210` is an
unmeasured estimate carrying only 20px of the clearance that keeps the guard green. And
the hit-target guard honors a `HIT-MIN-EXCEPTION` inline comment, unused today but a
one-line silencer. Both are ways a green guard stays green over a real regression.

**Honest scope.** The headless Arena capture showed the four visible overlay defects are
IDENTICAL in the SR capture - shell-wide, not Arena regressions. No Arena-specific widget
renders on the overlay at all; none of the CHERRY round/placement data reaches it. The
9px build pips and the 13/12px sub-floor tokens are enumerated and logged FUTURE rather
than bumped, because raising a 9px pip on a 44px icon is a layout change, not a token fix.

DS 10052 / 1 skipped / 5585 subtests; RC `tests/` 13504 / 106 skipped / 460 subtests;
ruff clean. CSS auto-reloads via ADR-008 - no RC restart, no DS bounce, no Share sync.

---

## 2026-07-27 - R197 enchanter Heal/Shield Power sweep (ENGINE 1.261.0, `946da292`)

**What the directive asked vs what was true.** It asked for a DS sweep of enchanter HSP +
mana-regen magnitudes with an Arena/ARAM mirror audit. All 34 curated rows already matched
DDragon 16.14.1 exactly - zero drift. That is the THIRD consecutive cycle where the stated
scope was already closed, so measuring it first and re-aiming is now the reliable opening
move, not a one-off.

**Shipped (4 slices, Claude sole merger, 4 verifier gates).**
- Derived magnitude drift guard - expectations parsed from `items.json` at test time.
- `_scaling_hsp.py` DEFAULT-OFF lane: Dawncore First Light off base mana regen, floor steps.
- Route + client reachability for `assume_hsp_amp`, which was STRANDED (0 hits in server.py).
- Seam-reachability guard deriving its universe from the ENGINE via `inspect.signature`.

**The find worth remembering.** The headline was NOT in the directive - it came from a recon
grep. `assume_hsp_amp` had 0 occurrences in `server.py` while its sibling had 4. Enumerating
the class gave 195 seam-parameter occurrences / 74 names, 23 route-facing stranded. The
existing reachability guards were GREEN and structurally could not see it, because they
enumerate the keys server.py already parses - circular by construction.

**What the verifier gates caught that green suites did not.**
- A mis-transcribed EHP pair in commit prose (6966.71 -> 7440.21, not 7120.49 -> 7607.77).
  The test asserts direction, not an exact value, so no suite could have caught it.
- A FALSE CLAIM SHIPPED IN A DOCSTRING - `sustain_for` named `matchup` as a zero-caller
  function; it has two live callers. Struck at merge.
- Two overstatements about how "derived" the scaling coefficients are (they are literals
  pinned by a derived test - a real but different guarantee), and "Meraki has no mirror ids"
  (it has 6). I would have filed the absolute version as a durable fact and been wrong.

**Three slices refuted my own spec, each correctly:** the four-route wiring was impossible,
my cited test node IDs were not class-qualified, and "zero callers" is not this module's bar
for declining a wire. Writing "a REFUTE is an allowed deliverable" into every slice prompt is
what made that happen - keep doing it.

**Honest scope.** The seam is EXPRESSIBLE, not live. Zero non-test callers; the ranker lanes
still cannot express it. Do not let this read as a live-path win in a later summary.

**Trap re-confirmed:** BOTH build-order keyspaces need regen. `core.build_order_variants` is
a SEPARATE entry point from `core.build_order_precompute`; running only the latter leaves 6
stamp guards red.

DS 10052 / 1 skipped / 5585 subtests. RC 13485 / 106 skipped / 460 subtests.

---




# 2026-07-27b - F1 queue drain, paired with Sibling-A. RC-owned items all closed.

Ran alongside the LW session on the shared 11-item f1-phase6 queue, coordinating
through the per-repo `moon_sync_inbox/` dirs. Operator was asleep for the whole
run; nothing was gated on them.

RC-OWNED, ALL DONE: 1 (exec bit), 2 (gate reads the index mode), 4 (anchor-site
rule), 5 (skip audit -> RM-119), 6 (CI arms the gate + e2e), 7 (disjointness),
9 + 5a (shared-file apply and pins), 10 (defect-class rule), 11 (invariance as a
test). LW owned and closed 3 and 12.

## The four things the queue did not know about

**The hooks were inert on Linux AND one was missing entirely.** Item 1 was the
exec bit. Fixing it armed the gate in CI for the first time, and the very first
armed run went red on something else: git-lfs installs FOUR hooks and only three
had ever been ported to `.githooks/`, so `git lfs post-merge` had never run on
any clone - a `git pull` left LFS pointers unsmudged. It was invisible locally
because Legion's clone never ran `git lfs install` and therefore had no file to
orphan; the runner does. THE LOCAL PASS WAS THE MISLEADING ONE.

**The "xdist shared-state failures" were never shared state.** WAKEUP has waved
these off run after run on a diagnosis nobody ever tested. Real cause: pytest 9
puts raw `subTest` kwargs in the report and emits one per subtest, execnet
serializes only builtins, so a bare `object()` raises DumpError inside
`subTest.__exit__` and fails the PARENT test. Serially there is no channel, so
the same matrix passes. Fixed by labelling with `repr()` - the hostile inputs
are byte-identical, because the garbage IS the test. A fifth instance in the DS
suite was found by ENUMERATING the class, which is the rule this same session
codified as item 10.

**The DS "flaky live tests" were a 5-deep listen queue.** One defect, not eleven.
`agents/daemon_slayer/server.py` never raised `request_queue_size`, so past 5
pending connects the OS REFUSES - unfixable by any client timeout. And
`core/daemon_slayer_client.py` maps every transport failure to `None`, which
callers read as an engine verdict, so a dropped socket surfaced as "this control
champion moved" and "expected 6 slots, got []". Backlog 128. DS suite `-n 8`
went 11 failed -> **9963 passed / 1 skipped / 0 failed in 44s**; live re-measure
500 POSTs at 16-way, zero failures. ENGINE-IMPACT NONE.

**A fourth instance of the same shape, found by CI on my own new guard.** The
strict table reader I added to close the corrupt-vs-absent conflation went red in
CI: `actions/checkout` does not fetch LFS objects and the laning_scenarios
tables are ~64MB LFS blobs, so on a runner the path EXISTS and holds a pointer
stub, which is legitimately not JSON. An unfetched pointer is a CAPABILITY gap,
not a corrupt table - it now skips, while a materialized-but-malformed file still
fails hard. The skip holds even when the require-flag is armed, because that flag
asserts the tables were GENERATED and LFS FETCH is a different question with a
different owner and ~190MB of cost. Clean on Legion (LFS smudges locally), broken
on the machine that never fetched - the same asymmetry as the post-merge hook.

**The ENGINE-IMPACT anchor count is SEVEN, not five.** The queue note omitted the
`ENGINE_VERSION` literal itself and `CLAUDE.md`; two memory files said four. The
derived list with file:line evidence now lives in `ops/loop/director_prompt.md`,
which is the template the controller reads EVERY cycle - deliberately not in
`directive_suffix`, which is transient run context and would take the rule with
it on the next rewrite.

## Cross-repo

Both sessions independently invented a NEW sync channel before finding the
existing `moon_sync_inbox/` one, and LW sat blocked on a reply RC was writing to
the wrong place. Now pinned in CLAUDE.md so the next session does not invent a
third. `slots.py` + `winmutex.py` are byte-identical again and `SHARED_SHA256`
is non-provisional on both sides. **Re-pinning is a JOINT act - both trees
hashing equal IS the acceptance, not a note claiming it.** LW's first status note
reported a divergence read from a stale snapshot and had to be withdrawn, while
the guard itself had already caught the real one.

`8986418f` in RC's history is LW's, not a mystery: they were authorized to
restart RC's stopped loop, committed two setup files with a pathspec, then saw
RC's file mtimes and STOOD DOWN rather than run a second driver.

## Also closed

Both drift_guard breaches that were open at the last wrap. The version-anchor
check now has line-level context (a line is history if it carries a
`N.N.N -> N.N.N` transition or a closure marker) - all three 1.259.0 sites it
had been reporting were correct history. The CHECK was fixed, not loosened: a
live claim next to real history in the same file still breaches, pinned by test.
ROADMAP relocation took it 94 percent -> 79 percent of budget.

## Open / owed

- **RM-119 needs an OPERATOR DECISION.** Push CI collects 85 of 807 RC test
  files and ZERO of 397 DS files; everything else is nightly-only and gates
  nothing. Not actioned unilaterally because it spends CI minutes. The cheapest
  option is now concretely cheap: the DS suite is parallel-safe at 44s.
- Skip audit buckets B2 / B4 / B5 filed in RM-119, not fixed.
- `docs/LIVE_GAME_GATED_SYNC.md` carries six `SOURCE: ROADMAP.md:<line>` tags;
  all six were ALREADY stale before this session's relocation. Line numbers into
  a file that gets relocated every few sessions is a provenance scheme that
  cannot hold - it wants a stable anchor, not a repair.

---

# 2026-07-26b - F1 cross-repo concurrency + the headless executor seam. 8 commits.

Paired session with Sibling-A. RC could not run headless at all before this: the
executor was inlined in the controller and hard-wired to the AHK GUI bridge, a
machine-wide singleton keyed on a window title. Full narrative in `docs/LEDGER.md` 1069.

SHIPPED
- `ops/loop/slots.py` + `ops/loop/winmutex.py` - BYTE-IDENTICAL-BY-CONTRACT with
  Sibling-A (`95077a62...` / `c21bfe4f...`). NEVER edit one repo's copy alone; both
  loops coordinate through `C:/ProgramData/lw-loop/slots` + the OS mutex namespace.
- `ops/loop/executor.py` - the channel seam. `channel` config key, sdk is now the DEFAULT.
- `claude_gui_bridge.ahk` double-Enter - a single `{Enter}` was being swallowed, leaving
  the directive typed-but-unsent until the deadline with no error.
- `{{FINAL_STEP}}` substitution - the two channels need OPPOSITE completion steps.
- Dollar cap REMOVED everywhere (Max 20x is a subscription; TIME is the only real budget).
- P5 concurrent run PASSED 4/4; phase-6 gate run PASSED 7/7.

DO NOT REDO
- Do NOT delete `done_sentinel.py`, `meter()`, `claude_gui_bridge.ahk` or the ahk path.
  Operator HELD the phase-6 deletions. Rollback is the one `channel` key.
- Do NOT re-derive the shared-file hashes from whatever is on disk later - they were
  pinned while both trees were provably in sync.

NEXT - an 11-item queue, agreed with LW, UNSTARTED:
1 `git update-index --chmod=+x .githooks/*` (all five are 100644, so hooks are INERT on
  any Linux clone) - 2 `gate_inactive_reason` checks the exec bit, not just presence -
3 log the sdk `session_id` on EVERY executor log path incl. success - 4 `ENGINE-IMPACT:
BUMP` must require a numbered step naming every anchor site (there are FIVE: the gate run
found `agents/daemon_slayer/CHANGELOG.md` is a different file from `Share/CHANGELOG.md`) -
5 `skipif` audit for preconditions that should be FAILURES - 5a pin the shared-file
sha256s as constants so CI enforces parity without the sibling tree - 6 CI arms the hook
gate then asserts it end-to-end, replacing the `skipUnless` that blinded RC - 7 directives
naming N parallel agents must assert disjoint files; the executor serializes AND RECORDS
the deviation - 9 `winmutex` POSIX branch emits `UNSERIALIZED` (today it is unserialized
AND untraced, so every guard passes vacuously off Windows) - joint edit, needs LW - 10
enumerate the defect class WITHIN the file before committing the fix - 11 score-invariance
claims ship as a test (the 171-champion claim was measured but left no durable artifact).

ALSO OPEN (drift_guard, 2 breaches, both pre-existing at wrap)
- `ROADMAP.md` at 94 percent of its 81920-byte budget - needs a relocation pass to
  `docs/ROADMAP_HISTORY.md`. Deliberately NOT grown this session because of it.
- version-anchor FALSE POSITIVE: the check excludes historical FILES by name but not
  historical LINES. `ROADMAP.md:98`, `docs/ORCHESTRATION_PLAN.md:649` and
  `Share/README.md:340,353` all name 1.259.0 as HISTORY, correctly. Fix the CHECK
  (line-level context) + add a `tests/test_drift_guard.py` case - do NOT loosen it.

---

# 2026-07-27a - R196 anti-tank kit-penetration tails. ENGINE 1.260.0. 3 commits.

**Loop cycle 6 (gemini director).** Closed the three R190 tails filed in `BACKLOG.md`:
Annie R uncredited, no AXIS field on `_ANTITANK_REGISTRY`, Amumu P mis-registered.

**The first decision was refusing the directive's shape.** It asked for 3 parallel
disjoint worktree slices; all three tails land in the same two files and slice 2's
AXIS field is a schema lift the other two consume, so they would have collided the
way R194's `_R194_TAIL` did. Auto-picked ONE worktree agent running 2 -> 1 -> 3 in
dependency order, still verifier-gated, Claude sole merger.

- **AXIS** - `AntiTankEntry.axis` (PHYSICAL / MAGICAL / BOTH, default BOTH) appended
  LAST with a default, stamped on all **31** resist-lowering rows across **30**
  champions (Mordekaiser carries two - the slice agent's commit prose said 30 rows and
  the verifier caught it). `_NON_GRANT_WITH_PHYSICAL_SIDE_ROW` + its companion test
  DELETED; the magic-side guard now reads `row.axis` instead of a hand-written K'Sante
  exemption. Metadata only, moves no score - measured twice independently (1368-dict
  digest before/after, plus the verifier's own 3-way mutation probe).
- **Annie credited** PERCENT_PEN / SUSTAINED / 0.7 / MAGICAL. **My `cond=True` premise
  was REFUTED and the refutation was right** - 16.14.1 prose is "Passive: Annie gains
  magic penetration." with no gate; "while Tibbers is alive" gates the RECAST.
- **Amumu removed** - the SHRED 0.6 row is wrong at 16.14.1 (10 pct bonus TRUE damage
  vulnerability, lowers no resist). He leaves the selective axis at 0.0, pinned by a
  tooltip-wording regression test.
- Registry totals UNCHANGED (103 mechanisms / 79 champions / 30 shreds_resist) because
  the add and the removal cancel; only `pen_count` 6 -> 7.

**TRAP WORTH REMEMBERING: there are TWO changelogs.** The DS guard reads
`agents/daemon_slayer/CHANGELOG.md` (paragraph entries keyed `1.260.0 (`), which is a
DIFFERENT file from `Share/CHANGELOG.md` release notes (`## old -> new` headers). I
edited the Share one first and the suite stayed red on exactly that test. Both need an
entry on every bump.

**Second trap:** the serial `tests/` run was at 6 percent after 10 minutes. `-n 8` did
it in 127s with 4 known xdist shared-state failures (`test_aram_action_rule.py`,
`test_aram_fight_risk.py`) that pass serially - re-ran them to confirm rather than
waving them off.

ENGINE 1.259.0 -> 1.260.0 in ritual order (126 .py bumped, DS bounce, `/health`
confirmed BEFORE regen, 9 tables, Share sync, docs, dual suite LAST). Regen was NOT
stamp-only: variants tables carry Amumu 0.51 -> 0.0.

DS **9949** / 1 skipped / 5311 subtests. RC `tests/` **13411** / 106 skipped / 442
subtests (-n 8). ruff clean, 0 non-ASCII, Share `--check` 505 files.
Still open: BACKLOG tails (d) max-rank-only magnitudes, (e) base/bonus armour split.
