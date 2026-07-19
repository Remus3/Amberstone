# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19 (the RM-92 AH session relocated `2026-07-18j` batch26-31 to `docs/history_notes.md`; newest 3 = AH-slice `2026-07-19a` + Term A `2026-07-18l` + roster-closed `2026-07-18k`). NOTE: `scripts/wakeup_prune.py` is STILL a silent NO-OP against these headers - its `SESSION_RE` requires a word boundary after the day, so a letter-suffixed header like `# 2026-07-18h` or `# 2026-07-19a` never matches and it reports "nothing to do" at any file size. Confirmed again 2026-07-19 (`--dry-run` reported "0 session(s) <= keep=3" against a 4-session file). Relocations are manual until that is fixed (filed as its own task).

---

# 2026-07-19a (RM-92 ability-haste slice SIZED -> DEFER, then its 4 tails SHIPPED 1.221.0; 2 commits, CI green)

**Verdict first, no code:** `docs/specs/SCOPE_rm92_ability_haste.md`. All 5 AH
champions route AWAY from the only scorer that prices ability haste (Twitch /
Xayah / Yunara -> `dps.py`, Udyr / Yorick -> `hybrid.py` AD branch). `dps.py` has
no ability model AT ALL - not merely no AH term. **The finding that settled it:
AH is ~1% live even where it IS wired** - the haste-shortened cooldown only feeds
the `measured <= 0` fallback (`ability_dps.py:1231`), and on the live 680-pair SR
table just 8 pairs reach it, 6 effectively. This is MODEL work already spec'd as
**RM-39 + RM-43 - do NOT open a third id.**

**Then the 4 tails, all shipped** (`5f2371ce`, ENGINE 1.221.0): `aram_ability_haste`
was assigned total AH and printed an ARAM note during SR runs (fixed, zero
production consumers); **NEW DEFAULT-OFF seam `apply_canonical_cast_rate_keys`** -
cast-rate lookups keyed the DISPLAY name against ID-keyed data so 21 champions
silently took `global_fallback` while still reporting "measured", across **4 call
sites** not 1, fixed at the `ult_rates.py` chokepoint; plus 3 stale comments and a
registry docstring citing a regen tool that has never existed. 8 ward PNGs
restored (zero code refs - removal stays a deliberate call).

**Two process errors, both self-caught.** (1) Skipped the regen step **with a
memory telling me not to** - `feedback_engine_bump_ritual_order` documents this
exact failure from the previous session. The stamp is independent of the content;
byte-identical output still needs the regen. Cost a 20-min suite. (2) Nearly
reported a stale subagent `repo_suite.txt` as my own run; caught on mtimes.

**Do NOT redo:** the RM-92 population audit (CLOSED), the AH sizing (DEFER is
final), the 4 tails (shipped + live-probed). **Open:** operator-gated default-ON
flips for BOTH seams (`team_blended`, `apply_canonical_cast_rate_keys`); three
Share gaps flagged not fixed (route tables claim "4 GET + 15 POST" vs a live 31;
`team_blended` + `kit_conversion_strength` undocumented in the authored half;
three version anchors uncovered by `_doc_anchor_rules()` - which is why README sat
72 minors stale while `--check` read green).

---

# 2026-07-18l (C1 audit resized Term A + Term A SHIPPED 1.220.0 + a self-inflicted false bug retracted; 2 commits)

**C1 first, and it changed the work.** Re-adjudicated all 21 RM-92 rows at BUILD
DEPTH (7 parallel agents, live 1.219.0, `/rank-<archetype>`, mode=SR, top=200,
depths 0-3, cross-checked vs all 3 shipped variants + `gold.purchasable`):
**21 -> 17 REAL / 2 ARTIFACT / 2 POOL-CANDIDACY.** Deflation is 19%, not the ~33%
the 6-row sample projected. **Composition was the finding, not the count** -
ABILITY-HASTE 5 / MOBILITY 4 / ALLY-FACING 3 / CC-UPTIME 2 / OTHER 3. Soraka's
"#10 of 10 dead last" canonical instance is a PROBE ARTIFACT (#3 at depth, and
the shipped order already buys it); Yuumi's "most complete instance" too. That
cut Term A's justification from an assumed 13 champions to **2 measured** ones,
so the operator swapped the "exactly 13 changed" golden-diff gate (churn) for a
correctness gate on Taric + Thresh. Re-derivation also found **14 raw `affects`
hits, not 13** - the old note dropped Nunu.

**Term A SHIPPED** `43a2e0ea` (ENGINE 1.220.0): `score_by="team_blended"` on
`ds.ehp`, DEFAULT-OFF. Taric Locket #24 -> #6, Thresh #20 -> #5, 12 gated
champions, verified live on `:8893`. Two NEW modules are both thin - the item
side is an ADAPTER over the existing curated `enchanter_items.json` (not a new
registry), the champion side is a BOOLEAN `affects` gate. ZERO new constants.
The gate is load-bearing: disabled, Locket enters the top-6 for Rammus too.

**I filed a false bug and retracted it** `7b116d50`. Claimed the Arena table
ships map-30-illegal items; it does not - all 9 tables audit clean, ARAM too. I
read item NAMES then resolved them to BASE ids; base and mirror share a name
(Moonstone = 6617 map30=False AND 226617 map30=True) and the table stores the
mirror. Shipped `tests/test_build_order_map_legality.py` so it cannot recur -
this also closes RM-04's "correct by luck not construction" gotcha.

**Do NOT redo:** the RM-92 population audit (done, LEDGER 950). Term A (shipped;
live default-ON flip is the only open tail). The Arena map-30 "bug" (does not
exist - run the guard test, 1 second). The 2 `coach_poll_offload` failures are a
load flake that passes standalone.

**Next:** the ABILITY-HASTE class is the largest measured RM-92 residual (5
champions) but only `ability_dps.py` prices AH - `dps`/`hybrid`/`ehp`/`burst`/
`hps` carry ZERO, and carry/bruiser have no cooldown model to compress, so it is
RM-86-sized. Size it before committing.

---

# 2026-07-18k (ROSTER CLOSED 173/173 + 3 bugs landed + repo-wide .md prune; 6 commits)

**DS_SWEEP is DONE. 173/173 - GAP 135, REFUTE 35, FENCED 3, Remaining 0.** Batch32
closed it: Ziggs [REFUTE], Zilean [GAP RM-96 NEW], Zoe [GAP RM-40], Zyra [GAP RM-97
NEW]. RM-96 = ds.hps prices heal/shield-CONDITIONAL passives at full value on a
champion who cannot trigger them (Zilean pool inverted at #4/#5). RM-97 = persistent
pet damage has no schema slot (Zyra plants 55-65 pct of her damage, scored zero;
generalizes to Heimerdinger / Ivern / Yorick). Both SPEC-ONLY. Next free spec = RM-98.
**Do NOT re-open the roster.**

THREE BUGS LANDED, and in all three the briefed fix was WRONG - check the measurement
before implementing anything handed down:
- **RM-93** as briefed was a REGRESSION. Admitting Zaz'Zak's/Bloodsong ranks Bloodsong
  #2 Vel'Koz / #3 Jinx. Real defect was the inverse: the SR deny held 2 of 5 Bounty of
  Worlds upgrades. Landed sibling-complete (+3 ids), SR pool 144 -> 141, no ENGINE bump
  (precedent 415c1795). Live-verified on restarted :8893.
- **RM-81** prescribed fix would have CRASHED the tool (Aurelion Sol Q IndexError kills
  the sweep) plus 12 bad truncations. Real tell is an INTERNAL DROP, not end-to-end
  decrease. Mordekaiser Q 388.9 pct -> 4.81 pct, SHAPE_SUSPECT marker added.
- **Unpaired enemy-share** silently returned NO recommendation (reproduced: Thresh 141
  rows -> None). 50.1 pct of real comps hit it. `_resolve_enemy_shares` derives the
  partner. Hard prerequisite for the archetype program.

DOCS: BACKLOG 285 -> 141 lines (15 teardowns relocated VERBATIM to
`docs/research/COMPETITOR_LIFT_INDEX.md` - the prune plan named that destination and
never created it). ROADMAP 85125 -> 41690 bytes, `test_doc_size_budget` was RED at HEAD
and is now green. 213 machine-generated reports archived. New `docs/adr/README.md` (adr/
was cited 29x with ZERO links). ADR-001 retired. RC_WORK_TRACKER resynced.

**LEDGER CITATION DEFECT (annotated, not repaired):** 387 of 1148 cited SHAs dead. NOT a
history rewrite - I claimed that first and it was WRONG (inferred from file position, which
maps to item number not date). Real shape: steady ~50 pct Apr-Jun, **0 of 537 in July** -
a worktree-slice citation convention that already self-corrected. Work landed; citations
were wrong. Preamble added to the 3 ledger docs.

**GATED SYNTHETIC TRIAGE: 6 of 124 closed, not "a lot".** 14 agents (7 triage + 7
adversarial refuters). CONFIRMED 15 / PARTIAL 24 / REFUTED 31. Dominant kill =
SUBSTITUTION. Two agents produced evidence that failed audit (fabricated build numbers;
3-of-880 sample published as a bound). **Do NOT re-pitch the synthetic drain** - header
carries the note. Real yield = 24 PARTIAL rewrites (live half is now a glance). 118 open.

NEXT: **Term A** archetype objective - `score_by="team_blended"` on ehp.py, DEFAULT-OFF,
gated on the ally-facing `affects` signal; moves 13 of a 28-champion cohort that currently
shares ONE byte-identical build order (Taric and Rammus get the same six items). Needs new
`_item_ally_grant.py`, ENGINE 1.220.0. **Do C1 FIRST:** re-adjudicate RM-92 at build depth -
Soraka/Yuumi "#10 of 10" are `item_ids=[]` ARTIFACTS (Moonstone is #2 at depth and the
shipped build order already buys it); 2 of 6 re-probed rows dissolved, so the 21-champion
figure is unaudited. Verification metric is CONTEXT LIFT (permutation test); pre-fix
baseline measures the engine as context-BLIND (MRR +0.0018, 42 pct placebo-identical).
