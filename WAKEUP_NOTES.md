# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-09-12, the SESSION WRAP doc-sync (relocated `2026-09-11d`, the lane-8 pre-flight, VERBATIM via `scripts/wakeup_prune.py --keep 3`, which reported "moving 1 session(s)" and left the archive at 959 - read that count off the tool's own output, never off a recollection; newest 3 = `2026-09-12c` this wrap, `2026-09-12b` the five-slice merge, `2026-09-12a` RM-412 C1 OSS extraction). The pass before this one relocated `2026-09-11c`, and the one before that `2026-09-11b` and `2026-09-11a`, the same way. The 2026-09-11k RELOCATION DUE note that sat here is DISCHARGED and deleted - the file is back at keep-3. The letter suffixes are PER FILE and have diverged from `docs/LEDGER.md` - RM-385 is `c` there and `d` here; do not reconcile them. NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`4a707962`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-09-12d - Fleet tooling-tier: RC's OWN gate proposal back-tested and REFUTED, nine defects conceded, bands WITHDRAWN

Four commits, ALL PUSHED to `origin/main`: `e69266ca0` (back-test of RC's own re-grounding gate - it does not survive), `a87400677` (deliver the retraction to four trees), `89721455b` (corrections and the pinned re-score, published as a band), `d47d3dfb4` (attack v1.3, withdraw our own bands, upgrade the delivery check). LEDGER 1413.

**RC'S HIGHEST-LEVERAGE PUBLISHED RECOMMENDATION DID NOT SURVIVE ITS OWN BACK-TEST.** Cost arm: 18 of 20 sampled rows refused (90 pct), ZERO genuinely stale, ~91 benign false positives over 11 mechanisms, RM-id closure false positives 26 of 30 - refusal tracked citation DENSITY, not staleness. Back-test arm, 7 located instances: 3 CAUGHT, 3 MISSED, 1 PARTIAL, 2 UNGRADEABLE. The generalising result: **EVERY RESOLVER IS A PRESENCE CHECK OVER TOKENS A ROW NAMES, AND THIS DEFECT CLASS IS AN ABSENCE.** Evidence: `docs/REFUTATION_GATE_BACKTEST_2026-09-12.md`.

**NINE defects were established in RC's published measurement** (five found by peers, each re-derived independently here). WITHDRAWN: the "rot still compounds" inference (1.805 to 1.943 pct is constant), the "29 of 33" novelty claim (z = 1.81 against a chunk-size null), the claim that RC's window is a natural unit, and a back-test limit that was too generous to RC.

**RE-SCORE under the sibling contract:** 198 per-event rows, four independent scorers over disjoint LEDGER chunks 1365-1406, machine tally with ZERO claimed-versus-actual discrepancies, independently adjudicated 40-row sample (148 of 160 field comparisons agree). Gate-or-contract 85.4 pct fine; inherited 48.5 pct; BORN-WRONG to DECAYED 2.62 to 1; fix-of-a-fix 12.1 pct. **It CONTRADICTS two of RC's own published headlines:** the 30.1 pct "record decay" axis is the MINORITY half (decay alone 10.6 pct), so the sibling reframe to RECORD TRUST is right; and "the constraint is WHEN checks run, not WHICH exist" is contradicted by GATE-ABSENT to GATE-EXISTING at 3.82 to 1.

**CONTRACT.** RC audited the sibling scoring contract v1.2 and found 5 FATAL underspecifications, led by **THE CONTRACT NEVER DEFINES WHAT ONE EVENT IS**, so it never defines the denominator of every ratio it publishes; the owner conceded all five, priced that one at 22.5 points on their own corpus, and shipped v1.3. RC then ATTACKED v1.3 as its owner asked: 2 FATAL on clause 1, 3 FATAL on clauses 2-5. Worst: clause 2's precedence order is total as a RANKING but not as a DECISION PROCEDURE (predicates exist for ranks 1-4 only, and 126 of 198 rows, 63.6 pct, fall in an un-predicated tail), and clause 1 contradicts the unwithdrawn v1.2 section 6, moving N from 198 to 226.

**RC WITHDREW ITS OWN BANDS.** An aggregation sweep showed all four intervals NON-MONOTONIC, and the rule RC published for the ratio (any-of, 1.73) sits BELOW RC's fine value (2.62), so the interval ran backwards. Aggregation dominates individuation 4 of 4 here. **DELIVERY:** RC's self-check is clean (100 distinct notes, 0 delivery faults, 0 address-list omissions), and was upgraded to the stronger roster-versus-address-list check after a sibling showed the adopted check cannot see an OMITTED addressee.

**DO NOT REDO.** (1) Do NOT re-propose the pre-dispatch re-grounding gate - it was built as a proposal, back-tested, and measured-REFUTED; the evidence is `docs/REFUTATION_GATE_BACKTEST_2026-09-12.md`. (2) Do NOT re-score RC's corpus against v1.3 - RC deliberately has not, because the contract is still under attack and its owner asked that it be attacked BEFORE anyone scores against it. (3) Do NOT quote RC's bands - they are WITHDRAWN; only the fine-grain figures are quotable, and only with the aggregation rule named. (4) Do NOT "repair" the nine baselined citations in `BACKLOG.md` - they sit deliberately in `_KNOWN_BROKEN` in `tests/test_citation_drift_guard_rm171.py` with written reasons, and a repair attempt this session was REVERTED after the guard caught it. (5) RM-422 and RM-423 remain OPEN and untouched; RM-423 is OPERATOR-GATED.

**NEXT SESSION - two operator steers were DRAINED here and belong in the hand-off, not in this session's work:** (a) the live-write row gets NO separate recovery pass - fold a regeneration assertion into the SAME row, with an anti-vacuous positive control; (b) `tools/live_write_tracer.py` ALREADY patches `io.open` for the pathlib route, so do NOT re-plumb it - confirm with a MUTATION arm instead.

---

# 2026-09-12c - SESSION WRAP doc sync: LEDGER 1407-1412, two rows filed, and three of the merger's OWN errors written into the record

LEDGER 1407-1412. DOCS ONLY - six markdown files, zero production files, zero
test files, ENGINE-IMPACT NONE. Nothing pushed. The six unpushed commits this
wrap covers are `86e4d4f0f`, `93f0e3efc` + merge `910cf8204`, `1d6d1e882` +
`2dc0cff76`, `3b5038fcb`, `14c0eadd2` + merge `dd0f43f78`, `54743bec0`.

**WHAT SHIPPED, one line each.** 1407 - `tools/outbound_reciprocity_check.py`,
RC's own answer to a sibling's delivery defect: **0 undelivered of 87**, scored
on a CONTENT DIGEST never a name, read-only across the boundary pinned at the
syscall by `sys.addaudithook`. 1408 - the fifth sibling-name escape CLOSED
UNILATERALLY and `KNOWN_EXCEPTIONS` retired to `{}`. 1409 -
`docs/REFUTATION_COST_MEASUREMENT_2026-09-12.md`, N = 42 ledger entries. 1410 -
the sweep's TREE arm wired into CI behind a gate that cannot emit an unearned
green. 1411 - the RM-296d regression fixed by grading behaviour instead of
source text. 1412 - this wrap.

**THE DURABLE PART IS THAT THREE ERRORS WERE THE MERGER'S OWN, and all three
are in `docs/LEDGER.md` rather than smoothed away.**
1. **A CRLF defect was ASSERTED into `oss/win32_atomic_io/LICENSE` and it does
   not exist.** Re-measured: **12115 bytes, CR 0, LF 219**. The "219 CR" was the
   file's LINE COUNT from a `grep -c` whose pattern degraded to empty. The
   FIRST measurement was right and said 0; the second was run because the first
   disagreed with a hypothesis already held, and was promoted over it without a
   cross-check. **`feedback_empty_grep_is_a_claim_about_the_pattern` INVERTED -
   a FULL-COUNT grep is equally a claim about the pattern**, and a count that
   matches a plausible expected magnitude is the most dangerous output the tool
   produces. Re-derive by a different mechanism whenever a re-measurement
   overturns an earlier one in the direction you wanted.
2. **Two agents were dispatched into the MAIN TREE concurrently**, against
   `feedback_verifier_needs_a_frozen_tree`. One saw the other's writes, watched
   the modified-file count move under it, and **misattributed them to an
   unrelated interactive session**. Numbers were re-derived and stand, but the
   second pass is what is relied on. **The main tree is a shared mutable
   resource; if two agents must run, at most one of them writes.**
3. **"Roughly 10 tree-scope findings" was the wrong SCOPE and reads as a live
   leak.** Those were **DIFF-arm** hits over **200-plus commits of
   ALREADY-PUBLISHED history** - commit messages and historical added lines.
   **Tree scope is 0 before and 0 after.** Re-measured at the end of this wrap
   with the sweep FULLY ARMED (4 name slots, 4 counterparty codes from
   per-host config): **clean, 630763605 bytes, 4762 files, 0 commit messages,
   482 binary/LFS blobs not content-scanned, exit 0.**

**TWO ROWS FILED to `BACKLOG.md` ("Reliability / hardening"), pin advanced by
TWO in `docs/DS_SWEEP_TRACKER.md` and `ROADMAP.md` in the same commit.**
**RM-422** - `core.longpaths` UNSET at local, global AND system scope; longest
tracked path **154 chars** (all five longest under
`docs/_archive/2026-07-26-orphaned-audit-drops/`); clone-ROOT budget therefore
**105 chars** at MAX_PATH 260. The session scratchpad root is 114, which is why
a checkout there aborted partway - and a later enumeration over the directory
the abort left MISSING printed a clean total, **a vacuous measurement arriving
through the filesystem rather than through a glob**. Fix has a CONFIG half and
a PATH-LENGTH half; the row refuses to pick one. **RM-423** - OPERATOR-GATED,
**no default recommended**: the lane refs cannot be pushed while the sweep
re-scans already-published history on every lane push. The bytes are already on
`origin/main` and all six lane worktrees sit at `86e4d4f0f`, an ancestor of it,
so nothing is stranded today.

**`CLAUDE.md` corrected at EXACTLY ONE sentence** - the Session Default block
still claimed the fifth escape "remains as a KNOWN, NAMED, VISIBLE exception
(declared in the tool)" while the tool's register is `{}`. Replaced with the
measured close plus an explicit do-not-restore. 53296 bytes, budget 61440.

**`ROADMAP.md` 72941 -> 75744 bytes** (budget 81920). Three rows relocated
VERBATIM to a new `## 2026-09-12b` block in `docs/ROADMAP_HISTORY.md`: the
FIFTH ESCAPE row, the five-slice announcement row, and the RM-420 FILED row -
**6261 chars relocated against six new rows added, so the pass ended NET
POSITIVE by 2803 bytes and is recorded as such rather than being forced to a
net reduction by gutting fences.** Every id and every fence stayed reachable.

**NEXT SESSION.** Nothing is blocked. The six commits above are still UNPUSHED
by instruction - **read RM-423 before pushing anything**, because the lane refs
and `main` are different questions and only one of them is gated. Do NOT
re-spell the next-free id in a ledger entry; a bare mention classifies as an
ALLOCATION and collides with the pin it announces
(`tests/test_rm_id_registry_drift.py`).

---

# 2026-09-12b - FIVE slices merged (RM-233 / RM-296d / RM-313 / RM-318 / RM-295a+b), and THREE filed specs were wrong in ways that mattered

LEDGER 1400-1404. Five `--no-ff` merges on `main`: `14c5b4571` (RM-233),
`adfcb195a` (RM-296d), `d7596d3d2` (RM-313), `8b688761f` (RM-318),
`1cb82683e` (RM-295a+b). All Tier-1, ENGINE-IMPACT NONE across all five - no
`ENGINE_VERSION` move, no DS `:8860` bounce, no Share mirror, no frozen file.
This session was DOCS ONLY: no source file was touched and nothing was pushed.

**WHAT SHIPPED, one line each.** RM-233 - `core/match_db.py` reads the WAL
pragma result, `save_match` widened to `-> bool` (still never raises), negative
`get_recent` limit clamped at the MODULE boundary. RM-296d - the three
`push_*` flags on `/api/loadout/apply` are PARSED, not bare-truthy. RM-313 -
`championId` routed through `_as_int`. RM-318 - a coercion seam over the six
decision detectors, NOT a bare except. RM-295a+b - `health()` exposing the
three staleness globals, `coverage()` adopted rather than deleted.

**THE DURABLE PART IS THAT THREE FILED SPECS WERE WRONG, and each was
corrected rather than followed.**
1. **RM-295a's `stale_for_s` parenthetical said "now minus `_LOADED_AT`".**
   `_LOADED_AT` is the **RETRY** stamp and is bumped by a refresh that landed
   nothing, so following the spec literally ships a staleness signal reading
   **`0` during the exact outage it exists to report**. Shipped code measures
   from `_LAST_GOOD_AT` and keeps the row's two key names.
2. **RM-295a's `source()` fence gave a REASON that is false in both halves.**
   "`dashboard/routes_duo_synergy.py` and the UI badge both read them" - that
   file has **ZERO** `source()` calls and there is no non-test `.source()`
   caller on the module repo-wide (re-probed at merge, independently of the
   slice). **The FENCE STANDS anyway**, on the row's own second reason plus the
   guard-widening ground. A dead reason is not a dead fence.
3. **RM-260 is STALE IN ALL THREE CITATIONS** - `performance_tracker.py:406`
   is not the key read (`:500` is), `experimental_builder.py:237` is not the
   `%s` site (`:241` is), and both hook functions moved. Its premise holds; its
   headline does not, because a `_redact` helper is now live at `:531`. Filed
   as RM-418 for RE-FILING, not building.
   **RM-255 is outright REFUTED at HEAD** - `lib/http/client.py` FAILS CLOSED
   (`:30`, `:111-113`) and `certifi==2026.2.25` IS at `requirements.txt:2`;
   closed same-day by lane 8 cycle 27, LEDGER 1293. Filed as RM-419 so nobody
   re-attempts it.

**A REFUSAL WORTH MORE THAN THE FEATURE: the `stale:live` / `stale:static`
prefix on `source()` was BUILT, MEASURED and DELIBERATELY REFUSED at merge.**
It shipped in `95c5fa2fa` and was reverted in `b51b05092`. The ground is not
taste - **shipping it REQUIRED widening the guard at
`tests/test_smoothed_rates_101qq_lock.py:375` so the change could pass**, and a
change whose cost is editing the test that exists to forbid it is a change the
guard already answered. Now guarded from BOTH sides: that lock test is
untouched and byte-identical across both slice commits, plus an inverted test
asserts the prefix is ABSENT and the domain is still exactly `live|static|none`.
**DO-NOT-RE-PITCH.**

**THREE CAVEATS RECORDED RATHER THAN SMOOTHED AWAY.**
- **RM-233's non-`wal` WARN branch is UNFALSIFIABLE on this host.** This
  platform returns `wal`, so the verifier confirmed the branch READS the
  pragma - **not that it ever EMITS**. RM-413 inherits this limit for its 8
  sibling sites; do not claim the emit half is covered.
- **"byte-for-byte" on the `source()` revert was REFUTED as worded.** The
  function text grew **162 -> 1573 chars** (docstring only); executable body
  AST-identical, return domain unchanged. **The overstatement was the MERGER's,
  introduced in the verifier's own prompt** - the worst place to put one.
- **RM-313's one-pass acceptance is deliberately UNMET.** Only `championId`
  shipped, because the census found TWO LIVE consumer defects on ONE field
  (`champ_select.js:3516` badged the WRONG ARENA PLAYER AS ME; `:3523`/`:3612`
  read `"0"` as truthy) and that does not generalise by assumption. Siblings are
  RM-417, each needing its own census - and `arena_teams() :195` PARTIALLY
  LIMITS the `:3516` repair, since that line reads `arena_teams[].cells[]` first.

**TWO SUITE FIGURES, BOTH RECORDED WITH THE REASON so nobody later reads them
as a contradiction.** Merger's own run over the merged tree and all five slice
suites = **518 passed, 63 subtests**. Independent verifier's narrower combined
run = **394 passed, 60 subtests**. The **entire** delta is one directory versus
one file: the merger ran all of `tests/phase_b_champ_select`, the verifier ran
the single file inside it (12+145+**171**+151+25+14 = 518 against
12+145+**47**+151+25+14 = 394). Same tree, same result, different scope.

**SEVEN NEW ROWS FILED, ids RM-413..RM-419, pin advanced to RM-420.** RM-413
(8 more WAL-discard sites), RM-414 (5 more bare-truthiness route sites, two
inverting intent into the dangerous direction - `routes_state.py:773` turns the
seam ON with the correct `_parse_tristate` helper sitting FOUR LINES BELOW;
`routes_coach.py:226` engages the coach kill-switch AND PERSISTS it), RM-415
(the `or {}` idiom, 17 sites / 4 modules), RM-416 (wire `health()` - it shipped
with NO consumer, which is RM-295b's own mistake, so it is filed rather than
repeated silently), RM-417, RM-418, RM-419. **Each carries its
EXCLUDED-AFTER-CHECKING set** so the ruled-out candidates are not re-filed.

**DOC-SIZE NOTE, stated because the first pass got it backwards.** Appending
five closures plus a seven-id filing row GREW `ROADMAP.md` 67973 -> 70938. The
pass continued until it showed a net reduction rather than stopping there: six
rows relocated VERBATIM to `docs/ROADMAP_HISTORY.md` (`## 2026-09-12` block),
each proved byte-identical against `git show HEAD:ROADMAP.md` rather than
eyeballed. Final **68372 bytes**, 83.5 percent of the 81920 budget, +399 on the
session. RM-295 and RM-296 were edited IN PLACE, not relocated, because each
closed only PARTIALLY (RM-295c and RM-296a/b/c/e remain OPEN).

---

# 2026-09-12a - RM-412 SHIPPED: C1 of the OSS extraction blueprint is EXECUTED, and the verifier refuted the builder's "all green"

LEDGER 1399. Code commit `48ac8986a`, 17 files, +1619/-23. Tier-1,
ENGINE-IMPACT NONE, no RC restart required.

**WHAT SHIPPED.** `oss/win32_atomic_io/` - a stdlib-only src-layout package
holding `_replace_with_retry`, `_scratch_path`, `_write_then_replace`,
`atomic_write_json` / `_bytes` / `_text` and `read_json_dict`, extracted from
`core/polled_json.py`. **`core/polled_json.py` is UNMODIFIED and its diff is
empty** - 20-plus live importers, so the package is a SIBLING, not a
replacement. `PolledJsonFile` deliberately EXCLUDED (`core/polled_json.py:204`,
ZERO production instantiations; RM-264 holds adopt-or-remove). New guard
`tests/test_oss_win32_atomic_io_drift.py` pins the two copies by
AST-normalized EXECUTABLE LOGIC over 7 functions plus the retry-delay
constant - docstrings and comments ignored, because the RC-specific prose was
deliberately scrubbed for sharing - and declares exactly ONE textual
allowance, the log-message prefix, with an arm asserting EQUAL hit counts on
both sides so it cannot widen into a blanket forgiveness. Also touched:
`.github/workflows/ci.yml`, `docs/OPERATIONS.md`,
`tests/test_ci_collects_orphan_suite_trees.py`,
`tests/test_skip_condition_hygiene.py`.

**FINDINGS - these are the durable value, not the code.**
1. **An independent verifier REFUTED the builder's "all green"** and found a
   hard red the builder never reported: adding a tree to `_TEST_TREES` obliges
   a same-commit row in the `docs/OPERATIONS.md` test-scope table, which calls
   itself authoritative. Fixed in the same commit.
2. **The empty-enumeration false green, hit LIVE.** 16 repo-root-enumerating
   guards returned **317 passed** and proved nothing - they enumerate the GIT
   INDEX (ADR-015) and the new files were untracked, hence invisible.
   `git add -N` surfaced **2 real failures**.
3. **The one real sibling-name leak was in `__pycache__`, not source.** Source
   swept clean over 31 banned identifiers x 3 variants plus a 17-term domain
   probe; the `.pyc` files embedded the absolute repo path and leaked the
   project name - invisible to a `git` publish, SHIPPED by `tar` / `cp -r`.
   Deleted, and the package now carries its own `.gitignore`. **Residual: that
   sweep is TRANSIENT - any pytest run repopulates `__pycache__`.**
4. **A self-contradicting license, built by this session.** The package
   declared itself all-rights-reserved and "not yet distributable" inside a
   PUBLIC repo whose root `LICENSE` grants Apache-2.0 - the exact
   self-contradicting-repo trap CLAUDE.md's own license gate warns about,
   committed against our OWN tree. Fixed with a byte-identical Apache-2.0 copy
   (sha256 `5bfe6fb7f5a2`, grantor line `Copyright 2026 Moonbeam` present and
   unedited), declared in `pyproject.toml`, plus three guards.
5. **Docs corrected to match real behaviour, not the reverse** (the drift guard
   pins logic, so prose moved): TWO degraded inputs are silent, not one; a bare
   `PermissionError` catch means `EACCES` DOES fire the retry on POSIX (4
   attempts / ~275 ms on an ACL denial); and "never left behind" is false for
   `SIGKILL` / `taskkill /F` / power loss.

**TWO LIMITS STATED, NOT PAPERED OVER.** `py.typed` is verified STRUCTURALLY
only - `setuptools` is absent from this interpreter, so no wheel was ever
built and the marker has never been observed inside an artifact. And a
package-local `.gitattributes` pinning `eol=lf` was REQUIRED: `core.autocrlf=true`
plus a root `.gitattributes` covering only `*.py` / `*.md` would have checked
the new `.gitignore` out as CRLF in a fresh clone - green locally, red on clone.

**MEASURED on a frozen tree after every agent exited:** package suite 38
passed; drift guard 51 passed; `tests/test_docs_operations_test_scope_rm322.py`
3 passed; `tests/test_polled_json_lane8_cycle24.py` +
`tests/test_atomic_write_fault_injection_is_portable.py` 37 passed;
index-dependent guards 75 passed once staged; `ruff check` clean; 0 CR / 0
non-ASCII; `core/polled_json.py` diff empty; pre-commit `py_compile OK (9 files)`.

**NEXT SESSION**
(a) Narrow the `PermissionError` catch to WinError 5 / `EACCES` - a LOGIC
    change, so it needs a SAME-SLICE edit to BOTH copies (the drift guard pins
    them) and its blast radius is `core/polled_json.py`'s 20-plus importers.
(b) Install `setuptools`, build a wheel, and OBSERVE `py.typed` inside the
    BUILT artifact. Re-reading the source layout is the check that already passes.
(c) DECIDE whether `core/polled_json.py` should ADOPT the package rather than
    duplicate it - that retires the drift guard, and it inverts the
    "sibling, not a replacement" property RM-412 shipped on purpose. Do NOT do
    it as a tidy-up inside another slice.
(d) Still carried from `2026-09-11d`: Slice D block-mode follow-up, Slice E
    residuals, `ops/loop/control/STOP` still present, and the
    `moon_sync_inbox` Apache-2.0 file awaiting license-gated evaluation.
