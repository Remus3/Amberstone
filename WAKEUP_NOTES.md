# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-08-30, merger + RM-227(a) pass (relocated `2026-08-29b` RM-222 flat-pen layout guard; newest 3 = merger + RM-227(a) `2026-08-30b` + lane-7 headless-repo `2026-08-30` + port-block collision `2026-08-29c`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-09-04i - HEADLESS: RM-291 FULLY closed, and a Settled CLAUDE.md line was wrong (ON MAIN)

STATE. Ninth unit of the day, headless (LEDGER 1332). ENGINE 1.280.0 unchanged,
Tier-1. No `web/` change, no digest re-stamp. Worktree removed.

RM-291 IS NOW FULLY CLOSED (Sweep A 1331, Sweep B 1332).

**THE FILED COUNT WAS WRONG BY AN ORDER OF MAGNITUDE AND IT DID NOT MATTER.**
Sweep B filed "~20 sites"; an AST scan finds 535 matching the literal shape and
1815 matching the wider one. Fifth corrected count today. But the row's
acceptance is PROVENANCE-TIERED, and by that measure the third-party tier held
exactly ONE unhardened boundary. **Shape is not the discriminator; where the
data comes from is.** Hardening a DDragon read buys nothing.

THE ONE REAL SITE, and its failure mode is the point: `core/smoothed_rates_101qq.py`
consumes raw 101.qq.com rows. Verified against the captured payload -
`championid1` is a STRING in 200/200 rows and `itemp1` is `'4.78%'`. Six sibling
fields used bare `int()`/`float()` inside `except (TypeError, ValueError):
continue`, so an upstream reformat would not raise - it would silently DROP the
row, and enough drops fires the static fallback, **serving a 15-month-old
May-2025 seed as live with nothing saying so.** Non-regression proven on the
real 200-row seed: 200 -> 200, byte-identical.

**A SETTLED LINE IN CLAUDE.md WAS FACTUALLY WRONG AND IS NOW FIXED.** The Meraki
carve-out claimed Meraki is "correct and preferred for `aram_modifiers`". It is
LOLMATH-sourced. Verified at four independent sites before editing a rule-bearing
auto-loaded file: `tools/daemon_slayer_extract.py:503` declares it on the
`LolmathExtract` dataclass under "Sourced from the data chunk", `:970` assigns
`lolmath.aram_modifiers.get(champ_id)`, all eight engine consumers read
`champ_rec["lolmath"]["aram_modifiers"]`, and `ehp.py:930` says so in prose. The
OTHER half of the carve-out (Meraki for item PASSIVE FORMULAS) still stands.
**A wrong line in a Settled section is worse than no line - Settled is exactly
what nobody re-checks.**

TWO METHOD NOTES.
1. **Mutation testing changed the outcome.** Two survivors were NOT equivalent:
   deleting the `isfinite` guard and deleting the `isinstance(value, bool)`
   branch both left the suite green, because a negative assertion ruled out a
   failure without pinning the value down. NaN is invalid JSON and blanks the
   panel; `isinstance(True, int)` is True so a JSON `true` publishes as rate 1.0.
   Four tests added, all 9 mutants now die - re-verified independently.
2. **A grep-based provenance sweep has a structural blind spot.** The adversarial
   pass found `core/rank_tier_source.py`, whose endpoint lives in GITIGNORED
   config, so no host grep can ever find it. It was checked by hand and is
   already guarded.

NEXT SESSION
------------
Task: Pick the next open row. Next free id is RM-343.
      Open: RM-261..264, RM-266..269, RM-292..295, RM-301, RM-303, RM-312/313,
      RM-315/316. Bodies + acceptance in BACKLOG.md.
      A clean follow-up nobody has filed: all 17 `anthropic.Anthropic(...)`
      constructions pass only `api_key` + `base_url`, so the RM-302/RM-314
      timeouts are PER ATTEMPT and the SDK retries twice - true ceiling is 3x
      the value. `max_retries` at construction would close it.

Context: ENGINE 1.280.0, patch 16.15.1, :8860 serving. ROADMAP 88.3 pct.

Do NOT redo: RM-291 (both sweeps), RM-302, RM-314, RM-287(+sibling), RM-214,
      RM-342, RM-212, RM-322, RM-339, RM-340, RM-341(refuted), RM-286.
      Do not re-attribute `aram_modifiers` to Meraki - that was corrected on
      measured evidence. Do not "fix" the RM-291A sites that DEGRADED or the
      Riot-authored / RC-internal coercion tiers; both were probe-proven safe.

Start with: /clear, then bootstrap from CLAUDE.md + MEMORY.md + WAKEUP_NOTES +
      git log.

---

# 2026-09-04h - HEADLESS batch 2: RM-291 sweep A closed, RM-302 + RM-314 shipped (ON MAIN)

STATE. Eighth unit of the day, headless (LEDGER 1324 six-slice, 1325 RM-339,
1326 RM-340, 1327 RM-341, 1328 RM-322, 1329 RM-212, 1330 four-slice batch, 1331
this one). ENGINE 1.280.0 unchanged, Tier-1 throughout. No `web/` change, no
digest re-stamp. All three slice worktrees removed.

WHAT SHIPPED.
- **RM-291 SWEEP A** - 29 read sites where a non-UTF-8 byte escaped the handler,
  fixed AT THE READ SITE (never by widening a caller). 4 candidates DEGRADED and
  were correctly left alone; 0 unprobeable. **Four of the 29 run at MODULE
  IMPORT** - one bad byte was an unimportable module, not a degraded panel.
  **SWEEP B (numeric coercion) REMAINS OPEN** - different acceptance, different
  severity model, do not merge them.
- **RM-302** - both `tft_live_analysis` fallback calls bounded at 20.0 s.
- **RM-314** - the four untimed `messages.create` sites bounded with four
  ARGUED values (20/15/10/10 s), not one copy-pasted constant.

FOUR THINGS WORTH CARRYING.
1. **THE ACCEPTANCE NAMED A DATA SOURCE THAT DOES NOT EXIST.** RM-302 required
   the timeout be set from the p99 of the `Live analysis in %dms` log line.
   That line has NEVER been emitted (n=0 across all 46 log files) - it sits
   inside the fallback branch and moon_proxy answers first. The slice did not
   guess: it substituted `data/coach_trace.jsonl` (n=200, p99 10950 ms,
   re-measured independently by me) and disclosed the substitution and its
   limits in the code. **Read an acceptance's data source before trusting it.**
2. **A DISPUTED POPULATION IS SETTLED BY PROBING THE UNION.** RM-291's row said
   33, my AST scan said 31, a strict innermost-try walk says 33 and a full
   ancestor-chain walk says 30. The slice probed the UNION of 33 instead of
   arguing - a site that degrades is not a defect whichever scan named it.
3. **THE OBVIOUS TEST WOULD HAVE BEEN VACUOUS, AGAIN.** RM-302's degraded-marker
   test looked trivial, but the existing handler already publishes on a RAISED
   error and an existing cycle-43 test already proves that - it passes against
   unfixed code. **A call that never returns never raises.** The shipped test
   models the HANG against a join deadline instead.
4. **RM-314's "12 constructions" IS REFUTED - it is 17** (independently
   AST-confirmed, still ZERO passing `timeout=`). Fourth filed count corrected
   today. The substantive claim survived; the number did not.

KNOWN LIMIT ON RM-302/314, disclosed not hidden: these bounds are PER ATTEMPT
and the SDK retries twice, so the true wall-clock ceiling is 3x the value (60 s
for RM-302). Closing that fully means passing `max_retries` at client
construction - all 17 constructions pass only `api_key` + `base_url`. That is a
clean follow-up row for whoever wants it.

NEXT SESSION
------------
Task: Pick the next open row. Next free id is RM-343.
      **RM-291 SWEEP B** is the natural follow-on: ~20 bare numeric-coercion
      sites, and its acceptance is explicitly provenance-tiered - classify each
      by whether the dict comes from RC-internal, Riot-authored or third-party
      data and harden ONLY the third-party tier. `core/augment_external_source.py`
      has a tolerant `_as_int`/`_as_float` pair to copy. `core/synergy_external_source.py`
      is explicitly OUT of scope (verified clean, and the pattern came from it).
      Also open: RM-261..264, RM-266..269, RM-292..295, RM-301, RM-303,
      RM-312/313, RM-315/316.

Context: ENGINE 1.280.0, patch 16.15.1, :8860 serving. ROADMAP at 88.3 pct after
      a relocation pass this session. Lane worktrees at C:\rc-worktrees\rc-lane-*
      were NOT touched today and still sit at a55ece97e.

Do NOT redo: RM-291 sweep A, RM-302, RM-314, RM-287(+sibling), RM-214, RM-342,
      RM-212, RM-322, RM-339, RM-340, RM-341(refuted), RM-286(already shipped).
      Do not re-derive the RM-291 candidate population or re-measure the
      coach_trace p99. Do not reuse moon_proxy's 8 s as a WAN timeout - 4 pct of
      measured real calls already exceed it. Do not "fix" the 4 DEGRADED
      RM-291 sites; they were probe-proven safe.

Start with: /clear, then bootstrap from CLAUDE.md + MEMORY.md + WAKEUP_NOTES +
      git log.

---

# 2026-09-04g - HEADLESS four-slice batch: RM-287 / RM-214 / RM-342 shipped, RM-286 was already done (ON MAIN)

STATE. Seventh unit of the day, run headless with the operator away (LEDGER
1324 six-slice batch, then 1325 RM-339, 1326 RM-340, 1327 RM-341, 1328 RM-322,
1329 RM-212, 1330 this batch). ENGINE 1.280.0 unchanged, Tier-1 throughout. No
`web/` change, so no digest re-stamp. All four slice worktrees removed.

**RM-286 WAS ALREADY SHIPPED AND ITS MARKERS WERE STALE.** Fixed 2026-08-31 by
lane 8 cycle 47 (`246af97dc`, LEDGER 1313) while `BACKLOG.md` and `ROADMAP.md`
still said OPEN - the SECOND stale-marker incident today (the session-start note
flagged the same for RM-329..336). The slice re-verified and wrote NOTHING,
which was right: the acceptance corpus it was asked to create already existed.
**Check the ledger before building a filed row.**

WHAT SHIPPED.
- **RM-287** - `safe_write` wrote CRLF into every coaching artifact (12 CR bytes
  measured at HEAD). Fixed to `write_bytes`. **The sibling was closed in the
  same pass**, not filed: `coaches/experimental_builder.py:122` had the identical
  live defect (6 CR bytes) and `:350` the latent one. Guard is now an AST sweep
  asserting NO `Path.write_text` call survives anywhere in `coaches/` - it MUST
  be AST, because the string `write_text` still appears there in a comment and a
  grep reports a false positive.
- **RM-214** - the `/monitor` redaction guard skipped itself whenever
  `moon_monitor.html` existed, and the server writes that file into its own CWD
  on any authenticated PUT. Now HERMETIC: isolates all six `/monitor` candidates
  and asserts in BOTH states. 11 passed + 1 skipped -> **14 passed, zero skips**,
  verified by me with the file planted AND absent. `_http.py` untouched - the
  row's "no live leak" scope fence holds.
- **RM-342** - rc-shell's 329 Node tests ran in NO CI job. Now run from
  `tests/test_rc_shell_node_suite_rm342.py`, riding the existing `pytest tests/`
  job with no workflow change. Zero third-party deps in those tests, and the
  runner was VERIFIED to carry Node 22.23.2 (not assumed). It ASSERTS rather
  than skipping when node is missing, on purpose: here CI *is* the subject, so a
  skip would report green over the exact gap being closed.

THE BEST FINDING OF THE BATCH came from the slice that wrote no code. Its
mutation probe showed per-key config independence was behaviourally correct but
**UNGUARDED** - every rejection test used a single-key dict and the hostile test
an all-bad dict, so a naive all-or-nothing validator passed all 48. I confirmed
it independently (`ast` over the test module: 43 config dicts, only 4 multi-key,
all uniformly good or uniformly bad - no mixed case), added the one missing
test, and planted the mutant: **it fails exactly the new test and no other.**

RM-291 RE-MEASURED, since the row invited it. Its "33 candidate sites" came from
a regex the row itself called the weak link. An `ast` walk over real try/except
structure gives **31** (167 sites scanned, 136 genuinely protected). Premise
confirmed live in the interpreter, not reasoned: `UnicodeDecodeError` and
`json.JSONDecodeError` are SIBLING `ValueError` subclasses, so
`except (json.JSONDecodeError, OSError)` lets a decode error straight through.

THREE INCIDENTALS, recorded not acted on: `vision_server/_http.py:57` and `:58`
are literally the same path, so the `/monitor` candidate list has a redundant
entry; an AST sweep found 4 untimed `messages.create` sites beyond the RM-302
pair, MATCHING RM-314's filed count so no re-file is needed; and
`rc-shell/test/store.test.js` carries a deliberate NUL byte in a path fixture.

CI CAUTION FOR WHOEVER IS NEXT. Pushing once per row cancelled `ci` three times
in a row today - GitHub supersedes an in-flight run when a newer commit lands.
Cancelled is NOT failed, and `gh run watch --exit-status` returns 0 on it, so
read `conclusion`. The last `ci` to run to completion was `9c6de1b68` (success).
**Batch the pushes.**

NEXT SESSION
------------
Task: Pick the next open row. Next free id is RM-343.
      Open: RM-291 (now a MEASURED population of 31, not a hypothesis - each
      candidate needs its own read before widening a handler), RM-261..264,
      RM-266..269, RM-292..295, RM-302, RM-314.
      Bodies + acceptance in BACKLOG.md; ROADMAP.md carries the pointers.

Context: ENGINE 1.280.0, patch 16.15.1, :8860 serving. ROADMAP at 89.0 pct of
      its 81920-byte budget (guard warns at 90) - **a relocation pass is owed
      before filing another row.** Only rows with NO open half may move; two of
      the largest closed-looking ones (RM-253, RM-254) carry OPEN sibling ids on
      the same line and must stay.

Do NOT redo: RM-287 + its experimental_builder sibling, RM-214, RM-342, RM-212,
      RM-322, RM-339, RM-340, RM-341(refuted), RM-286(already shipped 1313).
      Do not re-measure the RM-291 population, the rc-shell 329/0, or the
      test-scope table. Do not convert `rc-shell`'s test script to a directory
      glob (fenced, measured). Do not "simplify" the coaches AST sweep into a
      grep - it would report a false positive on its own comment.

Start with: /clear, then bootstrap from CLAUDE.md + MEMORY.md + WAKEUP_NOTES +
      git log.
