# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

# 2026-07-26g - R195 HEXCORE anchor drift made machine-enforced (gemini loop cycle 5, operator halt)

**Shipped:** `a27e5e6b` + `07360f10` (sha fill), pushed. Tier-0/1 - no ENGINE bump, no DS
bounce, no RC restart, no Share sync.

**The result worth carrying forward: the directive's DUST half was already done, and
measuring that before editing was the deliverable.** The directive asked for DUST leaves for
every net-new non-test `.py` since `d584e02e` - but that is R164's baseline and three refills
have landed on top of it (R188 `bb847bd0`, R191 `b4df6494`, which literally says "9 net-new
DUST leaves, dust 341 -> 350"). Parsing the shipped `var DUST=` literal against the 54
net-new basenames gives **0 missing**. Zero DUST edits was the correct output. A
`git log -1 -- <cited file>` age check caught it before any code.

**The real defect was anchor drift, and the fix is a guard rather than a seventh hand
refill.** Six passes (R146, R151, R157, R164, R188, R191) re-typed the same numbers by hand
because nothing tied them to the repo, so the HUD sat three ENGINE bumps stale. Re-anchored
ENGINE 1.254.0 -> 1.256.0, 9746 -> 9849 DS tests (both cite sites), commits 3972 -> 4007,
last `686a4b48` -> `cc6c241f`, LEDGER 1054 -> 1058. Then added 4 guards to
`tests/test_hexcore_offline_dust.py` (11 -> 15) that read `ENGINE_VERSION` out of
`agents/daemon_slayer/__init__.py` + the patch out of `data/daemon_slayer/current.txt`, so the
NEXT bump that forgets this file goes RED at the bump. The DS test count is pinned for
INTERNAL AGREEMENT across cite sites, not to a literal - the live number moves every batch, so
a literal guard is either wrong or forces an edit per batch, while agreement still catches the
half-refill. The LEDGER high-water anchor is deliberately unguarded (advances every session).

**Carry-forward / OWED:** the full RC `tests/` run was still in flight when the operator
called halt - it is NOT measured this cycle and NOT carried forward from R194. DS is measured:
9849 passed / 1 skipped / 4661 subtests. Targeted gate (hexcore guard + the three
ASCII/mojibake/u2500 hygiene modules) 28 passed, ruff clean, `node --check` clean on the
extracted 147956-char script block, 0 non-ASCII bytes. CI was in_progress at halt on
`07360f10` - confirm green next session.

**Don't-redo:** the `d584e02e` DUST baseline is exhausted. Do NOT re-issue "sync HEXCORE
against net-new files since d584e02e". A future refill computes its baseline from
`git log -1 -- docs/HEXCORE_offline.html`, never from a directive's remembered sha.

**Loop:** operator sent "halt when done" mid-cycle. In-flight slice finished, committed,
pushed; `ops/loop/control/STOP` dropped so the controller + AHK bridge exit. No new phase
started.

---

# 2026-07-26f - R194 DS vamp/sustain follow-ons (gemini loop cycle 4, unattended)

**Shipped:** ENGINE 1.255.0 -> 1.256.0 (`223362e3`), ROADMAP **RM-116 CLOSED**. Three
worktree slices, Claude sole merger, verifier gate before every merge: `928c750b` (B),
`3ad5b46f` (A), `86006150` (C). DS `:8893` bounced, `/health` reads 1.256.0.

**The result worth carrying forward: one of the three filed rows was WRONG, and each slice
was explicitly told a REFUTE was an allowed deliverable.** That instruction is the only
reason it did not ship.

- **(b) Sundered Sky 6610 overheal-to-bonus-health is REFUTED, not built.** The Meraki
  clause is genuinely there, which is exactly why the row was persuasive. But
  `heal_total` and `shield_any_amped` share the SAME EHP numerator and `_collect_heals`
  credits the heal in FULL with no missing-HP clamp - the engine already assumes zero
  healing is wasted, which is precisely what the overheal conversion guarantees. Naive
  injection: Aatrox L11 EHP 3991.0 -> 4348.2, all double count. And the honest clamped
  term is 0.0 for all 173 champions at L1 and L18 (worst heal-to-missing ratio 0.2205,
  Kled L1). Pinned by a 12-test guard so it cannot be re-filed.
- **(c) The sibling sweep NARROWED the set** - the opposite of the items 208/213 pattern
  and the more dangerous direction. Tiamat 3077 / Titanic 3748 / Profane 6698 /
  Stridebreaker 6631 ship byte-identical Cleave shapes with NO lifesteal clause, so a
  name or family-key fold would have over-credited four items. Eligible set is exactly
  3074 + 223074 by ID SUFFIX. **A naive substring grep for lifesteal false-positives on
  all five** via the zero-valued `lifesteal` STAT key - the clause lives in the `effects`
  prose field, and that is where the check has to look.
- **(a) The omnivamp seam was stranded one lane short of the surface that matters.** It
  reached `/ehp` in R193 but could never influence a RANKING. Now on `rank_items_by_ehp`
  behind `score_by=sustain`. It provably reorders (Amumu L13 SR, Riftmaker 4633 blended
  43 -> sustain 35) because the vamp pool enters as an ADDEND, not a uniform multiplier -
  that arithmetic distinction is what separates it from RM-115's provably-inert seams.

**New process hazards recorded:**
1. **Two tails, one round, one name.** Slices A and C both defined `_R194_TAIL` in the
   R134 signature guard on DIFFERENT entry points. Merged verbatim, the second definition
   shadows the first and BOTH case rows collapse to one tuple. Fix is a RENAME
   (`_R194A_TAIL` / `_R194C_TAIL`), never a blind concatenation.
2. **Cite function boundaries, not round line numbers.** Splitting one file by line region
   (A below 2500, C above) auto-merged cleanly, but C's diff landed a hunk 25 lines past
   the stated boundary - inside `compute_ehp`'s own return, ~370 lines clear of the ranker.
   Intent held; my number was wrong for the function it protected.
3. **The two post-bump failures were the known pair, not new breakage** - the phase8
   live-engine pin needs the DS bounce, and `test_ds_share_changelog_freshness` needs the
   Share README release-history site, which is SEPARATE from the auto-restamped header.
   R193 recorded this same trap at its item (7).

**Suites (fresh, after the last edit):** DS 9849 passed / 1 skipped / 4661 subtests; RC
`tests/` 13116 passed / 106 skipped / 460 subtests. ruff clean; ASCII/mojibake/u2500
hygiene green; `ds_share_sync --check` in sync at 498 files.

**Don't-redo:** the vamp base-magnitude / mirror-parity lane is now closed THREE times
over (R181 + R193 + R194). The Sundered Sky overheal shield is REFUTED with a guard.
