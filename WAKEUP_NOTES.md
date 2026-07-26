# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-26j - REPLAY ANALYSIS SUBSTRATE (RM-117, LEDGER 1062). 28 commits, 112 tests.

**NOT a DS session.** No ENGINE bump, no Share mirror, nothing under `agents/daemon_slayer/`.

## The one thing to carry forward
The brief assumed frame-level replay analysis needed the Settled `.rofl` Layer-2
fence opened. **It does not, and the fence stays CLOSED.** Four measurements:
1. The v2 container has NO encryption - plain zstd, stdlib-openable. The
   roflxd/Blowfish layout everyone cites is the OLDER v1 container. The fence's
   crypto rationale is void; its CHURN rationale stands (2 builds inside 16.14).
2. Positions come from the sanctioned replay API at **~19 map units** via an
   analytic ray/ground-plane solve. `cameraRotation` is `{x:YAW, y:PITCH}`, the
   camera looks `h/tan(p)` AHEAD of its own coords, and `cameraPosition` is
   writable ONLY in `cameraMode:"fps"`.
3. **Match-V5 60 s positions carry ~2000 units of error** (replicated on 2 games;
   8 of 33 samples wrong by more than the 2750-unit decision threshold). An
   earlier claim in this same session that the signal decay was "real behaviour"
   is RETRACTED in-file - it was sampling noise.
4. Paused renders are BIT-DETERMINISTIC (0 px), so flipping one entity toggle
   makes the pixel diff that entity class. **Wave state and ward coverage both
   unblock** with no ML. Buff camps untried.

## Running unattended - DO NOT ASSUME THESE FINISHED
- `timeline_ingest` pid 7580: **1092 / 3005** timelines at hand-off.
- `build_rank_baselines` pid 17616: waiting for idle, then 31 per-division cohorts.
- **`RC-ReplayChainWatch`** (new, PT15M) re-enables `RC-ReplayRosterPull` and runs
  the miner once both finish. `RC-ReplayRosterPull` is **Disabled** until it does.
- **GAP:** nothing restarts `timeline_ingest` if it died. Check the count first;
  it is resumable and skips existing files.

## Don't-redo
No fetch-by-match-id route exists (two requested matches rotated out of the
5-wide window mid-session, permanently gone) - never plan a `.rofl` backfill.
Summoner spells are LOADOUT ONLY (no Flash/TP/Smite timings anywhere). Buff
intervals and sharing are unrecoverable. Do not re-derive `FAR_UNITS` /
`SIGNAL_DECAY` as jungler facts.

## Owed / operator-gated
**B13** - Riot's acceptable-use position on bulk replay harvesting at
108-account scale is UNMEASURED. No retention policy on a 6.78 GB corpus
growing hourly. The win/loss promotion gate is BUILT but UNRUN at scale.

# 2026-07-26i - RM-95b residual SHIPPED: population 3 measured down to 1

**Shipped:** ENGINE 1.256.0 -> **1.257.0**, DEFAULT-OFF `apply_wiki_form_damage`. LEDGER 1061.
Tier-2 - new engine registry + an `abilities.py` seam, so the full dual suite, the Share
mirror, the DS `:8893` bounce and a four-family build-order regen all rode.

**The headline is that two thirds of the filed item was a refutation, and the row's own
filter is why.** RM-95b B2's closing sentence left a residual: "Three hand-authored registry
entries are the proportionate fix", naming Jayce W Hyper Charge, Mel W Rebuttal and Quinn R
Skystrike. That population came from a filter over the DATA ("names a real damage label AND
carries no `attribute_kind == "damage"` block"). Re-running it against the live snapshot
AND the live EVALUATOR - the question a build engine actually answers - collapses it to 1.

**The one that is real: Quinn's ultimate contributed exactly 0.0 to her own ability lane.**
Quinn R ships as two forms. Form 1 `Skystrike` carries ZERO blocks; form 0 `Behind Enemy
Lines` carries only a movement-speed modifier - and form 0 is the one the engine SERVES,
because `get_form_index_for("Quinn")` returns `({}, 'default')`. Measured at L13 against the
sweep-standard tanky target: R `raw_damage_per_cast` **exactly 0.0** while Q read 205.0 and E
read 40.0. The movement-speed modifier is correctly credited zero, so this was a silent
absence rather than a mis-credit - which is exactly why nothing caught it.

**Authoring onto the SERVED form is the load-bearing detail.** Putting the block on form 1 -
the form actually NAMED Skystrike - produces a block the evaluator never reads; re-routing R
to form 1 instead swaps in a form whose `cooldown` and `cost` are both `None`. So it is
PREPENDED onto form 0 (damage-first, since `_select_blocks` reads `damage_blocks[0]` and
Quinn carries no block-index override), labelled `Skystrike Physical Damage`, with a guard
pinning `get_form_index_for("Quinn")` at the default so a future form-registry change goes
RED instead of silently unreading the entry. Armed on Quinn L13 SR `[3031, 3006, 6672]`:
R **0.0 -> 132.0** raw, total ability DPS **4.1864 -> 4.5815**.

**The two refutations, both pinned as tests so the population-is-3 reading cannot come back.**
Jayce W Hyper Charge already has its numbers on disk (`[70, 78, 86, 94, 102, 110] % AD`), and
the served Jayce W form is `Lightning Field` at a real 380.0 raw - Hyper Charge is the
Mercury-Cannon alternate and an AUTO-ATTACK rider, so crediting it on the ability clock is the
face-value credit RM-86 fences. Mel W Rebuttal likewise has its numbers on disk
(`[40, 45, 50, 55, 60] %` OF THE ORIGINAL DAMAGE) but is a fraction of an incoming projectile
no registry can price - the RM-90 S3 assumed-prior class - so 0.0 is correct. Each refutation
asserts both the on-disk numbers AND that the registry carries no entry for that champion.

**DEFAULT-OFF, and the asymmetry with its sibling is deliberate.** `apply_wiki_ability_damage`
ships DEFAULT-ON because it INJECTS a champion with no prior behavior to preserve; this seam
MUTATES a served form, so OFF is the byte-identical contract. Blast radius proven by
construction - a full-snapshot OFF-vs-ON sweep over every champion and key returns exactly one
moved cell, `("Quinn", "R")`. Anti-double-apply: the entry applies only when the target form
has no damage block at all, so a future Meraki re-extract that ships Skystrike makes the
registry silently inert with no code change.

**Verification (fresh this session, measured AFTER the last edit):** DS **9861 passed / 1 skipped / 4661 subtests**;
RC `tests/` **13117 passed / 106 skipped / 460 subtests**; ruff clean across `agents/ tools/ core/ tests/`; the three
ASCII/mojibake/u2500 hygiene modules 15 passed / 7 skipped; doc-size budget 2 passed;
`ds_share_sync --check` in sync at 500 files; zero non-ASCII bytes added (CHANGELOG.md 590 and
CLAUDE.md 29 both unchanged against HEAD); live `:8893` `/health` re-probed at
**1.257.0 / 16.14.1 / 173 champions / 706 items**. All four build-order table families
regenerated against the restarted server across BOTH keyspaces - every diff is stamp lines
only, as a DEFAULT-OFF seam requires.

**Don't-redo:** do NOT author registry entries for Jayce W Hyper Charge or Mel W Rebuttal -
both are refuted with guards on disk. Do NOT re-file the RM-95b residual as a population of 3.

---

# 2026-07-26h - RM-95b B2 REFUTED on measurement + 2 stale ROADMAP rows corrected

**Shipped:** `4046b6d8` (tools) + `0216516d` (docs), pushed. Tier-1 - a `tools/` module only,
so no ENGINE bump, no DS bounce, no RC restart, no Share regen. LEDGER 1060.

**The deliverable is a refutation, and the session's real lesson is that my OWN measurement
was wrong twice before it was right.** Picked RM-95b "B2" (promote wiki `leveling` to typed
damage blocks) off ROADMAP NEXT. Two rows turned out stale before any build:

1. RM-99b's "NEW residual, OPEN: `3131` Sword of the Divine 15.0s vs 90s" is already SHIPPED
   (`3ad4d075`, ENGINE 1.246.0, guarded by `test_sword_of_divine_cadence.py`). Caught by a
   `git log -- <cited file>` age check.
2. B2's own justification - "closes Locke/Zaahen `baseline_burst=0.0`" - died with
   `e6b7b238` / ENGINE 1.250.0, which hand-authors both kits in
   `_ability_wiki_damage_registry.py` DEFAULT-**ON**. A spec subagent surfaced this; I
   re-probed it myself rather than taking its word (snapshot loads 173, Locke Q = Ritual
   Nails / MAGIC / 6 blocks).

**Then the surviving roster-wide half was MEASURED and it died too.** Against a live 16.14.1
`--full-roster` extract (1058 abilities, 0 errors, 688 with a leveling payload):
937 forms -> 361 with no damage block -> 146 with their own leveling -> **3** naming a real
damage label once stat grants are excluded (Jayce W Hyper Charge, Mel W Rebuttal, Quinn R
Skystrike), **all 3 fully literal**. So the `{{#var:}}` scanner + arithmetic evaluator that
dominated the spec's risk section buys nothing. Three hand-authored registry entries are the
proportionate fix - do NOT build the promoter.

**The count read 1, then 16, then 3, and the 16 was the dangerous one** because it clustered
into a tidy story (Hwei's subject spells, Kha'Zix's evolved forms, Riven R) that would have
justified the whole build. It was a join artifact: a slot-level fallback attributed the
PRIMARY form's leveling text to its alternate forms. A separate `Bonus[a-z ]*Damage` label
regex independently inflated 3 -> 36 by matching the "Bonus Attack Damage" STAT GRANT. Both
traps are now written into the ROADMAP row. New memory
`feedback_population_sizing_middle_answer_trap`.

**What shipped anyway (good independent of the verdict):** the extractor now captures
`leveling*_raw` via a new `_block_param` brace-depth scanner - `leveling` is the ONLY
multi-line param on a Template:Data page, so the line-anchored `_param_re` truncates it, and
a test asserts `_param_re` is genuinely insufficient so the capture test cannot go vacuous.
Plus an `apiname`+slot join key that did not previously exist. The committed sidecar is
deliberately NOT regenerated - the capture is inert until the extractor is re-run, which is
what keeps this Tier-1.

**Verification (fresh this session):** ruff clean; `tools/tests/` 346 passed (22 new);
doc-size budget 2 passed; ASCII/mojibake/u2500 hygiene 486 passed / 10 skipped; zero
non-ASCII added. DS `:8893` unchanged at 1.256.0 / 16.14.1 (correctly - Tier-1).
Also compacted `MEMORY.md` 19.8KB -> 16.8KB on a hook prompt (247 links, 0 broken, 0 entries
dropped).

---


_Older sessions archived to `docs/history_notes.md`._
