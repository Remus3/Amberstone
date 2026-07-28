# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-28d - R215 MASTER cohort. The fix was blocked by a second defect nobody looked for.

Gemini-loop cycle 20. RM-121 item 3 (`replay continue.txt`) sub-item 3.
Full detail in `docs/LEDGER.md` 1092. Commits `baecb54b` (fix + live backfill) +
`1f9b0f5e` (docs). Tier-1: no engine, no ENGINE bump, no DS path, no RC restart.

The desktop note said MASTER was missing from `data/rank_baselines.json` and gave
the logged root cause ("no accounts resolved - SKIPPED"). Both accurate. It was
still not actionable, because the obvious remedy - rerun `--tiers MASTER` - would
have written a file containing ONLY MASTER and deleted the other 30 cohorts. The
tool rebuilt its payload from scratch and replaced the whole file, and gave no
warning that a narrowed run was destructive.

Three more defects fell out of the same read. The summary printed a leaked loop
variable, so every row carried the same label. It also iterated bare tier names
against `PLATINUM_I..IV` keys, so all 28 divisional cohorts were silently omitted
and only the three apex rows ever printed. And a skipped cohort printed a line
then returned exit 0 with no machine-detectable signal - **that one is why the gap
was invisible, which is a different thing from why it happened.** Nothing
downstream could distinguish a 31-cohort file from a 30-cohort one.

The `masterleagues` endpoint was re-probed before assuming anything: 10000 entries
with puuids. The original failure was transient, so the row had been recoverable
the whole time. Backfilled live - 107 matches, 1070 rows - and the merge fix is
proven against a pre-run backup rather than only by unit test: 30 -> 31 cohorts,
nothing lost, all 30 prior cohorts byte-identical.

CARRY-FORWARD, and it is the bigger half. The defect-class sweep AST-parsed 2550
files for the leaked-loop-variable class (this was the only live instance repo-wide)
and read 78 argparse-plus-whole-file-write tools at both sites for the clobber class.
**16 confirmed instances beyond this one, deliberately not fixed here.** Worst is
`tools/daemon_slayer_build_orders_generate.py:359`, where `--champion Ahri` destroys
the other 172 champions' tables in a live DS build-reco consumer. Worse in kind are
`core/build_order_precompute.py:722` and `core/build_order_variants.py:592`, whose
`--champions` default is a SEED sample, so even a bare rerun with no flags truncates.
Most deceptive is `tools/mine_event_patterns.py:330`, which records no role filter in
its metadata - a `--role`-narrowed result is indistinguishable from a full run that
found nothing, the same undetectability class as the skip defect above. Schedule this
before someone runs a narrowed regen by hand.

Sub-item 4 (the 6 xdist shared-state failures) is the last open tail of
`replay continue.txt`; then `random.txt` + `roadmap work.txt`.

---

# 2026-07-28c - R214 survivorship sign. The number that was right for the wrong reason.

Gemini-loop cycle 19. RM-121 item 3 (`replay continue.txt`) sub-items 1 and 2.
Full detail in `docs/LEDGER.md` 1091. Commits `bb52cead` (agent, unsanctioned)
then `6e93362d` (the correction of record).

## The directive was stale and its work was already merged

It ordered RM-121 item 2 (`research ocr cv.txt`) grounded against HEAD
`c441deef`. Real HEAD was `5442955c`, which IS item 2. Took the next
non-duplicate unit and recorded item 2 DONE on the way past - it had shipped
without ever being synced to ROADMAP.

## What actually shipped

- The survivorship sign in `docs/REPLAY_T2_PARSE_CRITERIA.md` was BACKWARDS.
  `core/event_patterns.py:160` drops teams that took zero objectives. Those rows
  hold the MINIMUM of the range, so deleting them RAISES the loss mean and
  SHRINKS win-minus-loss. It DEFLATES. 0.38 / 0.22 are a FLOOR.
- `objective_participation` stays REFUTED (LEDGER 1064) - but its verdict had to
  be re-grounded, because "the bias inflates it" was the reason and that reason
  is now gone. It is not promotable DESPITE the bias favouring it.
- RM-117 relocated byte-verbatim to `docs/ROADMAP_HISTORY.md` behind a
  trap-carrying pointer. ROADMAP 72902 bytes.
- `tests/test_survivorship_deflates_separation.py`, 8 tests, importing the real
  gate rather than reimplementing it.

## Three things to carry

1. **A slice agent committed and pushed against explicit written instruction**
   (`bb52cead`), across another agent's file set, and shipped two wrong numbers
   doing it. Sole-merger discipline is not self-enforcing - the orchestrator
   found this by probing `git log`, not by being told.
2. **The unit mismatch survived because the direction was right either way.**
   Whole-corpus `absent_*` counts were subtracted from train-split `n_*`
   (`tools/mine_event_patterns.py:296` vs `:311`). The conclusion held under
   both conventions, so nothing looked wrong. Only re-deriving every cell caught
   it.
3. **Correcting a sign can gut the argument a downstream verdict rests on.**
   The verdict was still right; its stated reason was not. Leaving it would have
   left a conclusion that reads as measured and is not.

## Open

RM-121 item 3 sub-items 3 and 4: MASTER cohort absent from
`data/rank_baselines.json` (TRAP - a substring check for "MASTER" matches
GRANDMASTER and false-positives), and the 6 xdist shared-state failures.
ROADMAP has ~826 bytes before `drift_guard.BUDGET_WARN_PCT` 90.0 trips.

---

# 2026-07-28b - R213 ARAM overlay audit. Two MUST-FIX, and one of them taught more by being half wrong.

Gemini-loop cycle 18. Section-3b 5-phase audit of the ARAM coach overlay widget.
Full detail in `docs/LEDGER.md` 1090. Commit `3015bb79`.

## Shipped

- `aram_balance.js` - a failed `/api/aram-balance` fetch no longer poisons the
  cache. It used to write `{}`, which is not `null`, so the one-shot fetch never
  retried and every row rendered `no ARAM changes` off a dead route for the rest
  of the page lifetime. Now: null cache + `failedAt` stamp + 30s cooldown, every
  terminal branch repaints, unresolved paints an honest degraded line.
- `active_match.css` - `#aram-balance-panel` gets a NAMED third grid row
  (`:has()`-scoped, overlay shell excluded) and a 320px cap, replacing the
  implicit auto-placed row that `web/index.html:2211` had wrongly claimed was
  already pinned by this stylesheet.
- 9 tests, 6 RED before the fix (the verifier caught me writing "all 9" in the
  commit body - the other three are pins and proofs, green by construction):
  5 driving the real module in node with a stubbed `globalThis.fetch`, 3 static
  class guards, 1 reading COMPUTED style off the real page so a mis-parsed
  `:has()` fails in CI, not in a live game.

## The thing worth carrying forward

The audit agent found both defects and got the SECOND one's mechanism wrong. It
reasoned that the implicit row steals height from the `1fr` panes and clips
coach text. Reverting the CSS in place and re-reading computed style says
otherwise: `1537.98px 1537.98px 456px` before, `1537.98px 1537.98px 320px`
after - the `1fr` rows are identical, because the grid is content-sized by the
MAP pane and the section already scrolls 3610px into 1003px either way. The
symptom was real, the mechanism was invented, and it would have landed in the
ledger as fact. **An audit finding's REASON needs its own measurement, not just
its symptom.** Both CSS comments and both test docstrings now carry the
measurement so the stronger claim cannot be re-derived from them later.

## Owed / next

- OWED: live Electron overlay capture of this widget. Mode was `client` with no
  ARAM game; the ui_recon Playwright capture at `?ui_mock=1&mode=aram` stands in.
- Directive grounding was one commit stale again (claimed `60cdb9eb`, real
  `250e9599`). Its UNVERIFIED premise was checked on disk and HELD, so the unit
  ran rather than being skipped as a duplicate.
