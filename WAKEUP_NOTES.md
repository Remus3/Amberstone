# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-08-04i - orchestrated 3-slice pass: RM-117 retention, RM-118 shields, RM-36 Ezreal (ENGINE 1.275.0)

Operator asked why open items were running one at a time instead of orchestrated
multi-agent. Answer: serial was drift, not policy - CLAUDE.md "Session Default" and
memory `feedback_standing_five_item_parallel_loop` both make orchestrated the baseline.
The exacting next-session prompt carries CONTENT, not cardinality. Ran the pass to prove it.

SHIPPED - two commits, both pushed (`9907dca3..b510ce20`):
- `1772c8d5` RM-117 (ii) `core/data_retention.py`, 4 classes, report-first. NOTHING DELETED.
  RM-117 (iv) closed as STALE (fixed by `baecb54b` 68 min after filing, never recorded).
- `b510ce20` merge, ENGINE 1.274.0 -> 1.275.0: RM-118 five per-item shield seams reach
  `/ehp` (exposure only, `ehp.py` untouched); RM-36 AD-axis dual-scaling split credit,
  Ezreal 0.0 -> 14.1067.

THE THREE FINDINGS THAT MATTER MORE THAN THE CODE:
1. Probing killed 2 of 5 proposed rows BEFORE any build. Filed rows are suspect until probed.
2. RM-118 was filed as "10 seams declined by design". An adversarial pass tasked with
   REFUTING that found 5 were live headless debt - their reason conflated route EXPOSURE
   with a DEFAULT FLIP. An operator-gated live flip blocks ONLY the flip. My own two kills
   were BOTH refuted by that pass; the reasoning I used to close RM-117 (iv) was vacuous
   even though the conclusion held.
3. MERGE HAZARD unique to parallel work: both DS slices recomputed the parity debt ledger
   against a baseline the other invalidated (54 vs 60; truth is 55). Two individually
   correct numbers, jointly wrong. Take the count by PARSING THE DICT.

DO NOT REDO:
- RM-35..RM-48 is CLOSED, all 14 resolved, narrative relocated to `docs/ROADMAP_HISTORY.md`.
  Do not re-open the roster.
- RM-117 (iv) is closed. `skipped: []` and `accounts_per_cohort: 14` are NOT evidence
  about MASTER - both traps are recorded on the ROADMAP row.
- The 5 seams remaining in `STRANDED_TODAY` are the s232 operator-CLOSED arc. Genuinely
  declined. `assume_lifeline_shield` is one of them despite the name.
- Neither new flag's default-ON flip is proposed. RM-36's rides G2-46 (blocked on RM-98).

FLAGGED, NOT FIXED: `tools/ship-batch.md` says "about 14 files" assert the ENGINE pin.
Real number is 125 files / 146 literals. Anyone trusting it ships a bump with ~110 red
tests and assumes breakage. Worth a one-line correction next session.

OPERATOR DECISION PENDING: 3.72 GB of `rewind_history.db` backups (11d/16d, zero readers)
plus 24.6 MB tier-2 and 137 MB tier-3. Reported, deliberately not deleted.

---

# 2026-08-04h - RM-42 CLOSED: the follow-on REFUTED the row it was built for (ENGINE 1.274.0)

LEDGER 1194. The aa-empower follow-on LEDGER 1193 filed as owed.

**Shipped.** New `agents/daemon_slayer/_extra_shot_overrides.py` - the extra
shot's ON-HIT APPLICATION and its own CRIT, the two halves a damage registry
cannot express. DEFAULT-OFF `apply_extra_shot_procs`, reachable from
`compute_dps` / `rank_items` / `/dps` / `/rank` / both client functions.

**The answer refutes RM-42.** Both flags armed at depth: weighted DPS
142.06 -> 257.05 (+80.9 pct), and ON-HIT ITEMS RISE while crit does not -
Guinsoo's #7 -> #6, Terminus #7 -> #5, Yun Tal DOWN #6 -> #7, Hexoptics C44
only #19 -> #17, Runaan's/BotRK keep #1/#2. The row predicted the opposite.
It could never have been right: DDragon says the shot APPLIES ON-HIT, so a
faithful model necessarily makes on-hit items better, and the more completely
it is modelled the more on-hit wins. RM-42 is CLOSED - damage half shipped,
ordering half refuted. Do NOT re-file it as "the model is still incomplete".

**A process point worth keeping.** The 1.273.0 non-closure marker was authored
predicting it would GO RED when this shipped. It did not. That survival is
EVIDENCE about the claim, so the test was rewritten to pin the refutation
rather than quietly deleted. A marker that predicts its own death and lives
should be read, not removed.

**Placement was the whole correctness argument** and is worth re-reading before
touching `_periodic_proc_dps`: the multiplier is bound INSIDE the
`every_n_attacks` branch, so a time-driven proc cannot be accelerated (pinned by
a Sunfire-only difference test), and it deliberately does NOT touch `base_dps`
because the shot's own damage is owned by `_passive_damage_overrides` - folding
it in both places double-counts one hit.

**Refusal recorded:** no bespoke crit multiplier was authored. DDragon ships two
bracketed variants of the crit bonus in one string, so neither is quotable; the
shot gets the engine's standard crit expectation instead of an invented number.

**A guard earned its keep:** `test_route_seams_reach_the_client_per_route`
caught `/dps` parsing the seam while `dps_for` could not express it, and its
message says fix the client rather than widen the exclusion list. Done that way.

Suites at final state, repo root: DS 10413 passed / 6520 subtests; RC `tests/`
18225 passed / 108 skipped. Tables stamp-only. Ruff, ASCII, drift guard clean.
`G2-47` widened to cover BOTH flags - two halves of one event, flip together.

Three ENGINE bumps this session (1.272.0 / 1.273.0 / 1.274.0) across RM-36/38
and RM-42.

---

# 2026-08-04g - RM-42 Akshan: the passive modelled, the ordering claim NOT closed (ENGINE 1.273.0)

LEDGER 1193. Second Tier-2 slice of the day, same RM-35..RM-48 set.

**The lesson of the session is the same one as the last: a sweep filing can be
built on a mis-read of the ability text.** RM-42 describes Dirty Fighting as a
"200% crit double-shot" and prescribes a fix on that basis. DDragon 16.15.1 says
the second shot is a flat 50 pct AD PHYSICAL hit that APPLIES ON-HIT EFFECTS. So
a faithful model raises on-hit value on Akshan, which is the opposite of the
filed prescription. Read the shipped ability text before building to a filing -
this is now twice in one day (RM-36's AP-scaling gate was the other).

**Shipped.** The second shot is modelled (`_PASSIVE_DAMAGE_OVERRIDES` +
`_AA_ROUTED_ON_HIT_KEYS`) and `apply_passive_damage` now reaches the CARRY
ranker (`rank.rank_items` + `/rank` + client), DEFAULT-OFF. It is a large
correction - +48.9 per hit, weighted DPS 142.06 -> 212.19 at depth, +49.4 pct.
Before this, 33 registry entries were priced nowhere the item RANKING could see
them.

**A trap worth keeping.** The registry entry ALONE is inert - the consumer reads
a 5-member EVERY-AA allowlist, not the registry at large. Entry added and
nothing else: `compute_dps` byte-identical flag-ON, no note. Both edits needed.

**NOT closed, and deliberately so.** Armed, BotRK/Runaan's still take #1/#2 at
depth and Hexoptics C44 moves only #19 -> #18. Mechanism: the registry credits
the shot as flat damage on the AA cadence (`per_hit * effective_AS`), so it
raises ATTACK SPEED, which is what the on-hit items carry. The crit lift needs
the shot's on-hit APPLICATION + independent crit - the aa-empower machinery.
`test_rm42_ordering_claim_is_NOT_closed_by_this_slice` is designed to GO RED
when that ships; delete it then.

**Context measurement, taken before any code:** of 14 ranged marksmen at L16 on
the tanky target, THIRTEEN return a BotRK/Runaan's-led head; only Aphelios leads
crit. The on-hit lead is near-universal in `ds.dps`, so no champion-specific fix
can do more than move one champion relative to that floor. That is the real
shape behind the whole crit-marksman GAP family (RM-42 / RM-46 / RM-50 / RM-53 /
RM-60 / RM-68).

Suites at final state, repo root: DS 10396 passed / 6520 subtests; RC `tests/`
18225 passed / 108 skipped. Tables stamp-only. Ruff, ASCII, drift guard clean.
Live eyeball filed as `G2-47` - a default-ON flip would arm all 33 entries at
once and only 6 have ever been eyeballed.
