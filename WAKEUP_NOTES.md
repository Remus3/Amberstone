# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

---

# 2026-07-26m - RM-91 T2, drift guard, 4-phase /done, git-hook gate. 11 commits.



**IS a DS session.** ENGINE 1.258.0 -> 1.259.0, Share mirror regenerated, `:8893`

bounced and live-probed, both build-order keyspaces regenerated at exactly 2 lines

per file.



## The hand-off task closed, and the headline is finally fixed

T1 shipped monotone in `delta_hp` and could not reorder two health items, so

Randuin's Omen 3143 still ranked #1 for five tanks. **T2 credits the candidate

ITEM's own caster-HP proc, keyed by ITEM ID, so the factor is INDEPENDENT of the

health delta** - a zero-proc item earns nothing however durable it is. Measured

live on `:8893`: Titanic Hydra 3748 walks **#13 -> #8 (strength 2) -> #5 (4) ->

#4 (6) -> #2 (8) -> #1 (10)**, Randuin's falls to #2, and **every `delta_ehp` is

byte-identical across the flip** - the sort-only proof. Acceptance pinned at

strength 12 for all five tanks, and the FLOOR pinned too (strength 4 must NOT

flip) so the test cannot go vacuous.



## The design decision worth keeping: T2 is DERIVED, not hand-authored

T1 needed a hand-seeded champion table because ability data needs human

adjudication. T2 does not - the coefficient already lives in `_effects_data.py`

as executable code, so the module **differentiates each

`PeriodicProc.resolve_damage` against its own `CallContext`**. Consequences: a

coefficient edit propagates automatically; **the irregular mirror prefixes the

hand-off warned about (2502 -> 222502 ARAM but 2501/447111 Arena) stop

mattering**; and it CAUGHT that **Heartsteel's cadence is NOT mirrored** (SR 3084

every 30s, Arena 223084 every 3.5s), which a by-name table would have flattened.



## The filed row was wrong about its own size, again

**Population is 16 credited of 17 sensitive, not the 21 filed** - the 21 was a

COMMENT count. 4645 and 6675 name `caster_max_hp` in prose only; 4015 Perplexity

has no `periodics` at all.



## THE TRAP - T2's equivalent of T1's double-count trap

**A finite-difference probe reports a confident, linear slope for any proc that

MENTIONS caster health, including one where caster health is not the damage

SOURCE.** `4017` Hellfire Hatchet probes as a clean 6 percent converter and is

not one - its Char reads `caster_max_hp - target_max_hp`, a tankiness COMPARISON

rewarding out-tanking the target. A linearity guard does NOT catch it. Denied by

ID, with a test asserting the deny is non-vacuous.



## Two process traps that cost real time

- **Running the DS suite from `agents/daemon_slayer/` produces 13 FALSE

  failures** (CWD-relative path opens + 2 ASCII-hygiene tests). All 159 pass from

  the repo root. **Run the DS suite from the repo root.**

- **`schtasks /End` then an immediate `/Run` leaves :8893 DEAD.** `/End` kills the

  server but the port is still bound when the launcher fires, so

  `start_daemon_slayer.py` logs "port 8893 already bound - skipping (exit 0)" and

  exits clean while nothing ends up listening - and the task reports

  `Last Result: 0`. A second `/Run` after the port frees is the fix. Also

  `schtasks /End /TN ...` cannot be issued from the Bash tool at all (Git Bash

  rewrites `/End` into `C:/Program Files/Git/End`); use PowerShell.

- **There is a FOURTH ENGINE doc-anchor site** beyond the three known Share ones:

  `docs/HEXCORE_offline.html` carries the version AND the test count in a HUD

  tooltip and a node description, guarded by 3 tests in

  `tests/test_hexcore_offline_dust.py`. The dual suite caught it; the ritual

  checklist did not mention it.



## SECOND THEME - the /done ritual, rebuilt on measurements

Operator: "a future session doesn't need to be ran to correct 10 sessions of

closures when it could have been done for 30 seconds each session."



**`tools/drift_guard.py` is that 30 seconds** (+ `tests/test_drift_guard.py`, 22

tests asserting BOTH the breach and the clean path per check). Runs in /done

Phase 1. **First run found 10 live breaches - more than my hand audit did:

8 mirrored command docs diverged, not just `done.md`.** Also 6 unindexed

memories (4 indexed; 2 `_`-prefixed are transient scratch, now exempt) and

ROADMAP at 96%.



**`tools/done.md` is now FOUR PHASES** and re-mirrored: fast gate + guard ->

commit/push/**dispatch CI** -> paperwork WHILE CI runs -> collect. The overlap is

the whole trick.



## The measurements, because two of them reversed my own advice

- local dual suite **1642s / 23,250**; CI nightly **1007s / 22,749 (97.8%)** -

  **CI is FASTER than this box** and already runs the same suite.

- **push CI covers only 941 tests = 4%.** `nightly-full-suite` is gated on

  `schedule || workflow_dispatch`. Fire it with `gh workflow run ci.yml`.

  ONCE PER SESSION - private repo, metered minutes, already tripped once.

- **slowest 40 tests = 176s = 10.7%, mean 71ms.** No slow minority exists, so

  "fix the slow tests" CANNOT reach 5 min. I recommended that before measuring

  and was wrong.

- **`-n 8 --dist loadfile` = 144.65s, an 11.4x speedup**, with 6 failures /

  23,272 - all shared-state artifacts serial was hiding (5 of 6 are fail-soft

  "never raises" tests, 1 asyncio event-loop conflict). **Fix those 6 and the

  wrap collapses to ~2 min. Do NOT adopt by suppressing them.**



## Traps found the hard way this session

- `schtasks /End` + immediate `/Run` leaves `:8893` DEAD reporting

  `Last Result: 0` (launcher self-skips on the not-yet-released port). And

  `schtasks /End` is unusable from the Bash tool - Git Bash rewrites `/End` into

  a path. Use PowerShell.

- DS suite from `agents/daemon_slayer/` = **13 FALSE failures** that read like

  registry regressions. Run from the REPO ROOT.

- A **4th** ENGINE anchor site exists: `docs/HEXCORE_offline.html` carries the

  version AND the test count, guarded in `tests/`, so a DS-only run misses it.

- `CLAUDE.md` topology is STALE: hostname is **DESKTOP-LCA3EBI** (not

  DESKTOP-JKZECV9) and **Tailscale is not installed** - so the `legion-rc` /

  100.70.22.55 row is wrong too. `rc_facts.py` echoes the same stale values.

- PS7 7.6.4 installed MSI-only at `C:\Program Files\PowerShell\7\`. winget

  ships MSIX-only for this version; `--installer-type msi` returns "no

  applicable installer". **Claude Code binds its PowerShell binary at SESSION

  START** - sessions opened after the install get pwsh 7, this one stayed 5.1.

  Desktop docs: `POWERSHELL_7_MIGRATION.md`, `DONE_RITUAL_OPTIMIZED.md`.



## THIRD THEME - the git-hook gate, and three self-inflicted regressions

Measured: a headless `claude -p --permission-mode bypassPermissions` COMMITTED a

banned em-dash. **Claude PreToolUse hooks do not survive that channel; git hooks

do.** So the authoritative gate moved into the tracked git hooks. Full detail +

the four ways a hook can be present and do nothing: memory

`reference_git_hooks_authoritative_and_traps`.



**Three things I broke and fixed in the same session - the pattern is that each

fix created the next hole:**

1. `core.hooksPath` pointed at untracked `.git/hooks`, so three TRACKED guards

   had silently stopped (py_compile, archmap, state_schema) and both generated

   artifacts had drifted. Root cause: `scripts/install_hooks.py` WROTE a

   Share-sync-only hook, clobbering the rest. Fixed - it now sets the pointer.

2. Porting the gate to `pre-commit` **silently dropped the commit-MESSAGE check**

   (git prepares the message AFTER pre-commit). Sibling-A predicted this

   before RC probed it. Now split across both hooks.

3. Flipping `core.hooksPath` **orphaned `post-checkout`, `pre-push` (both Git LFS

   - 7 LFS files here, so pushes would look clean while LFS content never

   uploaded) and `post-commit`** (Share gist mirror). Ported; `drift_guard`

   now treats an orphaned hook as a BREACH.



**Do NOT use LW's bare probe on RC.** `gate < /dev/null` exits 0 here too, but

RC's hook pipes `echo "git commit"` in deliberately - the gate is proven live

three ways. The only valid test is end-to-end: stage a glyph, commit, assert HEAD

unchanged.



## Also

- Two Desktop hand-off docs were LOST (no copy on disk, cause unknown). Rebuilt

  and now version-controlled at `docs/handoff/` - Desktop holds copies only.

- PS7 7.6.4 MSI at `C:\Program Files\PowerShell\`. Claude Code binds its

  PowerShell binary AT SESSION START, so sessions opened after the install get

  pwsh 7 and older ones stay 5.1. Both are right; probe, never assume.



## LEFT OPEN deliberately

**ROADMAP.md is at 94%** (warn at 90). The clearing move is relocating RM-117

(26KB, dense with measurement traps). Rushing that at wrap risks losing exactly

the trap content LEDGER 1063 says a pointer must carry. **Next session's item 1.**



## Do NOT redo

- RM-91 is CLOSED, both halves. Do not re-file the health axis, do not re-scan

  for caster-HP items - the population is machine-derived and pinned in BOTH

  directions, so a "missing item" claim must first fail the census guard test.

- Do not re-pitch merging T1 and T2 onto one flag (different payers, different

  pools). Do not "fix" 4017 into the registry.

- T1's known-limit pin was KEPT, not deleted - it still constrains T1's own flag.

---



# 2026-07-26l - RM-117 cohort bands CLOSED, RM-91 SHIPPED (ENGINE 1.258.0), repo md cleanup. 9 commits.



**IS a DS session.** ENGINE 1.257.0 -> 1.258.0, Share mirror regenerated, `:8893`

bounced and live-probed, both build-order keyspaces regenerated.



## The hand-off task closed, but not for the predicted reason

`build_rank_baselines` finished at **30 cohorts, not 31** - MASTER logged

"no accounts resolved - SKIPPED". The file landed and the absent-baselines warning

went away, but all 14 metrics still read "no cohort table". **The real defect was a

producer/consumer shape mismatch, not a missing file:** `cohort_baseline.load()` did

`.get("roles")` at the TOP level (the single-cohort shape) while the renderer defaults

to `rank_baselines.json`, which is `{"tiers": {COHORT: {"roles": ...}}}`. It returned

`{}` and every band was omitted silently. Fixed with `--cohort`; a tiers-shaped file

with no cohort named now RAISES and lists all 30 (`ecf59a29`).



**Then reading the now-working output found a worse bug.** `rank_of` kept the LAST

threshold a value cleared, so on a metric where p10..p90 are all 0.0 a 0.0 cleared

every band and kept p90 - a TOP laner who healed nobody was told they were 90th

percentile. Three of fourteen live metrics were wrong. Ties now take the LOWEST

percentile sharing the threshold plus a `tied` marker (`ec4d1e15`).



## RM-91 shipped, and the filed row was wrong about its own size

Population is **11 tank-routed champions, not the 5 filed**. Sett and Sion are

REFUTED - they scale off the TARGET's health. Built by a worktree agent, merged by

Claude, every claim re-verified independently (all 11 seeded values re-derived,

DS suite re-run 9900 passed, seam live-probed on `:8893`). **The double-count trap is

the thing to remember:** most of these kits emit sub-component AND Total blocks for

one ability (Sejuani W 4.0 + 8.0 with a Total of 12.0 that IS their sum), so a naive

sum triple-counts. **KNOWN LIMIT, pinned as a test:** T1 is monotone in `delta_hp`,

so it does NOT fix the Randuin's headline - that needs T2 (the item's own caster-HP

proc), which is unbuilt.



## RM-118 filed - and "file it as RM-99" would have been a collision

RM-99 was already allocated 2026-07-19 and shipped as `assume_item_health_stacks`.

**TWO id-allocation lines were stale** (ROADMAP said next-free RM-99, the tracker said

RM-105); both corrected to RM-119, and the tracker now says to check ITSELF, never

ROADMAP prose, before taking an id. RM-118 is mana-as-damage on `/rank-tank`,

population exactly 1 (Blitzcrank). Kassadin and Ryze are NOT defects.



## Repo cleanup - the inventory agent was wrong twice and counting caught both

27 orphans archived by `git mv`, each verified individually. That check saved a

`proposal.md` and a nested `README.md` (basename collision with root README), and

refuted the "archive the P0..P6 set" recommendation - 8 of 9 still carry 2-7 inbound

refs. 11 `.claude/commands/*.md` had ZERO version control and are now tracked.

ROADMAP gained a "WHERE WORK LIVES" table; three rival "single source of truth"

claims scoped.



## Do NOT redo / traps that cost time this session

- `agents/agent6_auditor/reports/` LOOKS dead but `_supervisor_ephemeral.py:86` writes

  failure stubs there. It is live.

- `docs/_archive` is gitignored yet its ~300 files are TRACKED. Archive with `git mv`

  ONLY - `cp` + `git add` silently fails and can drop a file from version control.

  Now recorded in `.gitignore`.

- DS champion-coverage: count from the nested `champions` key. A flat top-level count

  returns 2. The doc's old "196 entries / 125 champions / 73%" was that mis-parse plus

  block_index's own count mistaken for the distinct total. **True: 132 champions / 167

  entries / 77.2%.**

- **Share has THREE doc sites.** README got the 1.258.0 note, CHANGELOG.md was missed,

  and `ds_share_sync --check` reads GREEN anyway because it deliberately does not

  rewrite changelog history.

- An ENGINE bump REQUIRES regenerating BOTH build-order keyspaces. Diff should be

  exactly 2 lines per file (engine_version, generated_at) - that is the byte-identical

  proof for a DEFAULT-OFF lever.

- The "tracked tools/ copy always wins" mirror rule was WRONG and had preserved the

  ADR-012-decommissioned bridge in `done.md` for a month. Corrected in sync-all-md

  section 9: promote the NEWER side, ASCII-clean it, and normalize glyphs BEFORE

  diffing or the s244 em-dash purge hides whether content actually diverged.



## Console flash FIXED (`e872d9c9`) - and the diagnosis is the reusable part

Operator reported cmd/PS windows flashing, "3 in a row sequenced". **It was NOT the

task config** - every frequent RC-* task already uses `pythonw.exe`. **`pythonw`

suppresses the console of the process IT hosts, not of any child it spawns.**

`tools/replay_chain_watch.py` calls `_ps()` from THREE sites every 15 min, each

spawning `powershell` with no `creationflags` - exactly 3 windows, 4x an hour.

`tools/ci_watchdog.py:315` already had the guard AND a comment naming this symptom.

Fix = `creationflags=0x08000000` (CREATE_NO_WINDOW). Swept siblings: `rofl_archive`,

`replay_roster`, `cost_health_watchdog`, `replay_roster_pull` spawn nothing.

`tests/test_no_console_flash_scheduled_tools.py` pins it by AST (verified NOT a

tautology - it flags `timeline_ingest.py:119`). **If a flash reappears, look for a

CHILD process, never the task's own executable.**



## OPEN, not started

- **`ops/rc_dev_runtime.py` spawns unguarded too** but is on the CLAUDE.md FROZEN

  list - needs explicit operator approval before touching. Same one-line fix.

- **Share standalone has 13 REAL failures** (7832 passed / 13 failed). None is an

  engine failure - each opens a CWD-relative path that exists only at the source-repo

  root. They are host-dependent by exactly the `_HOST_DEPENDENT_TESTS` definition and

  were never added to it. Documented in `Share/README.md`, NOT fixed. Fix = anchor on

  `__file__`; excluding them would drop 13 files of real coverage.

- RM-91 **T2** (item's own caster-HP proc) - the half that actually fixes Randuin's.

- RM-118 build (mana axis, population 1).

- `objective_participation` REFUTED verdict is recorded in LEDGER but

  `docs/REPLAY_T2_PARSE_CRITERIA.md:309` still has the sign backwards ("would inflate

  these rows" - measured, it DEFLATES them), plus two ELITE_MONSTER_KILL field-list

  corrections (`assistingParticipantIds` carries ENEMY participants; `monsterSubType`

  is DRAGON-only).

- MASTER cohort missing from `rank_baselines.json`.
