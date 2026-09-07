# LEAP-06 - R129 engine residuals: Viego R AD-credit + bruiser/hybrid ability-DPS XOR

> P3 AMENDMENT (judge panel 2026-07-17, supersedes conflicting text below):
> 1. ENGINE VERSION: do NOT hard-pin "1.217.0". At execution start read the live
>    ENGINE_VERSION literal and bump +1 minor from CURRENT (other LEAP items may land
>    first). Update the AC-A8/AC-B9 RED-test literals to that value when writing them.
> 2. STRIKE the "re-stamp the embedded ENGINE version field in build_orders_*.json"
>    step: Family A tables are patch-keyed and carry NO engine_version field
>    (probe-confirmed). Orders stay byte-identical at default-OFF; regen is a no-op
>    here and belongs to LEAP-04/07.

Status: SPEC (Fable 5 forward-leap portfolio, 2026-07-16). No code in this file.

> CLOSURE 2026-07-25 (measured at ENGINE 1.246.0, patch 16.14.1) - read this before
> building anything below:
> - **Sub-fix A SHIPPED at ENGINE 1.245.0** as `apply_cdragon_surplus_ad`
>   (`abilities.py:947`, pinned by `agents/daemon_slayer/tests/test_cdragon_surplus_ad_a29.py`).
>   D2's APPEND prescription was corrected in flight to a field-level merge because
>   `compute_ability_dps` reads `damage_blocks[0]` only.
> - **Sub-fix B is ALREADY SHIPPED** as `apply_ad_axis_ability_damage` (RM-39/RM-43 L2,
>   ENGINE 1.223.0, DEFAULT-OFF). All three XOR sites carry the three-arm shape:
>   `hybrid.py:687-700`, `:1236-1251`, `:1336-1351`; flag appended at `:464` and `:1012`;
>   route at `server.py:922-966`; 37 pins in `test_ad_axis_ability_damage_rm39.py`.
>   **D6 / D7 are SUPERSEDED and `blend_ability_axis` must NOT be built.** Its only delta
>   over the shipped seam is crediting MAGIC damage rows and `item_proc_dps`, both measured
>   and refuted by name at RM-39 (MAGIC excluded permanently, MIXED held, and
>   `total_ability_dps` folds `item_proc_dps` which promotes Liandry's to #1 for Aatrox).
>   For B's own primary seed Riven the two formulations are numerically identical
>   (87.0619 either way). B's double-count premise is refuted too: `compute_dps`
>   auto-empower credit is `aa_empower_amp`, gated on DEFAULT-OFF `apply_ability_amps`
>   with placeholder `(0.0,)` entries (`dps.py:808-826`), roster Caitlyn W / Fiora E /
>   Jayce W / Sivir W / Nidalee Q - none of the six bruisers D7 excludes.
> - Remaining value on this seam is the RM-39 default-ON flip, which is live-gated and
>   blocked on the RM-98 cast-rate time base, not in this spec.
Owner of execution: one cold Opus 4.8 (Max20) session, effort max.
Scope discipline: this spec is self-contained. A session with ONLY CLAUDE.md +
this file has everything it needs. Do not re-derive scope from chat or memory.
Ground truth in this doc was probed live 2026-07-16 at ENGINE 1.216.0 / patch
16.14.1; re-probe before building only if the patch or ENGINE has moved.

--------------------------------------------------------------------------------
## GOAL
--------------------------------------------------------------------------------

front-load the thinking into specs; execution sessions are typing, not deciding.

Close the two R129 Daemon Slayer engine residuals that survived the R129
Fimbulwinter cycle (BACKLOG.md:11-12). Both are pure-simulation damage-model
completions surfaced by the R129 DS-sweep hunters, both were deferred as
"genuine but not blind-shippable", and both ship the same way every DS damage
seam ships: a NEW default-OFF flag + a bounded opt-in registry, byte-identical
at the default, with the default-ON flip left to a separate live-gated decision.

Sub-fix A - Viego R "Heartbreaker" 120% total-AD primary hit is uncredited: a
CDragon-vs-Meraki damage-block cardinality mismatch drops the whole R form back
to Meraki, so the 120% AD term is never scored and `compute_ability_dps` returns
0 for R at full HP.

Sub-fix B - the bruiser/hybrid scorer scores the damage term as a strict XOR
(ability DPS if AP-axis, else auto DPS), so AD-axis bruisers with real ability
damage (Riven / Jarvan) have their ability DPS zeroed instead of blended.

The one-line operator intent: an AD bruiser's cast damage should count toward its
build score, and Viego's R should not read as zero damage at full HP - without
flipping any kit-axis win-rate lever or moving a single ranking at the default.

--------------------------------------------------------------------------------
## EVIDENCE (ground truth, cited; probed 2026-07-16)
--------------------------------------------------------------------------------

Residual source-of-truth:
- The two residuals verbatim - `BACKLOG.md:11` (Viego) and `BACKLOG.md:12`
  (hybrid XOR), under "Daemon Slayer scorer calibration".
- Both deferred to BACKLOG FUTURE by the R129 Fimbulwinter cycle - `docs/LEDGER.md`
  entry 903 (ENGINE 1.213.0 -> 1.214.0, commit `86ffb9b9`): "2 genuine-but-bigger
  candidates -> BACKLOG FUTURE (Viego R ... 120% total-AD ...; bruiser/hybrid
  scorer XOR drops ability-DPS for AD-axis champs ...)".
- Current engine: `ENGINE_VERSION = "1.216.0"` - `agents/daemon_slayer/__init__.py:18`
  (single source of truth). Patch `16.14.1` - `data/daemon_slayer/current.txt`.

### Sub-fix A - Viego R (the cardinality mismatch)

The on-disk Meraki snapshot has ONE damage block for Viego R; the CDragon sidecar
has TWO. The merge falls back to Meraki whole-form and drops the surplus block.

- Snapshot `data/daemon_slayer/16.14.1/champion_abilities.json`, Viego R
  (`data.Viego.R`, one form, form_index 0): `damage_blocks` has exactly ONE
  `attribute_kind == "damage"` block - the missing-HP block
  (`target_missing_hp_pct = [12, 16, 20]`, `unparsed_modifiers` "5% per 100 bonus
  AD"). The 120% term lives ONLY in prose: `effects_descriptions[1]` = "All
  targets hit are dealt 120% : 240% (based on critical strike chance) AD physical
  damage." (verified by direct JSON read).
- Sidecar `data/daemon_slayer/16.14.1/cdragon_ability_ratios.json`,
  `champions.Viego.R`: TWO `resolution == "mechanical"` blocks -
  (1) `name="TotalDamage"`, `total_ad_pct = [120,120,120,120,120,120]`;
  (2) `name="TotalPercentHealth"`, `base = [12,16,20,24,28,32]`,
  `total_ad_pct = [5,5,5,5,5,5]` (the missing-HP block). The 120% AD block is
  present and machine-parsed in the sidecar (verified by direct JSON read).
- The merge that drops it - `agents/daemon_slayer/abilities.py`
  `_apply_cdragon_ratio_preference` (`abilities.py:532-595`). The cardinality
  guard is `abilities.py:580-581`: `if m_counts != Counter(csig) or any(v > 1 ...):
  return form  # ambiguous structure - whole-form fall back to Meraki`. For Viego
  R that is Counter(1 Meraki signature) vs Counter(2 CDragon signatures) -> not
  equal -> whole form returns unchanged (Meraki, missing-HP only). The docstring
  at `abilities.py:540-556` confirms the merge is an OVERWRITE-only re-source that
  "COUNT is never changed" - it can never APPEND a surplus CDragon block.
- The load-time flag surface - `AbilitiesSnapshot.load(...)`
  (`abilities.py:613-624`): existing opt-in seams `apply_passive_damage=False`,
  `apply_passive_heal=False`, `apply_passive_shield=False`, `apply_all_out_bonus`,
  `prefer_cdragon_ratios=True`, `apply_cdragon_resource_guard=False`. The new
  Sub-fix A flag lands here in the SAME shape (default False -> byte-identical).
- Consequence: Viego R missing-HP block is 0 at full HP (0 missing HP), and its
  only other coefficient (+5%/100AD) also scales on missing HP, so
  `compute_ability_dps("Viego")` credits 0 for R at full HP. The 120% AD term
  (roughly bonus-AD-scaling, residual estimate ~130 from AD alone) is never
  counted. This is mathematically certain from the block data above; the exact
  post-fix magnitude is captured by the RED test, not asserted from prose.

Sibling cardinality sweep (the tightest-matching-set probe, done 2026-07-16;
compares snapshot `attribute_kind=="damage"` block count vs sidecar mechanical
block count per (champ, spell)):

  SURPLUS (snapshot < sidecar; an AD-scaling mechanical block is dropped - SAME
  root cause as Viego):
    Viego  R : snap 1 / side 2  - TotalDamage total_ad_pct=120  [PRIMARY]
    Pyke   R : snap 0 / side 1  - RADDamage total_ad_pct         (execute)
    Rengar R : snap 0 / side 1  - BonusDamage total_ad_pct       (leap empower)
    Quinn  R : snap 0 / side 1  - Damage total_ad_pct            (on-cast AoE)
    Yorick R : snap 0 / side 1  - YorickBigGhoulDamage total_ad_pct (pet/Maiden)
    Jinx   Q : snap 0 / side 1  - RocketDamage total_ad_pct      (AA modifier)

  REFUTED-nearby (snapshot >= sidecar, or sidecar block is not AD damage - NOT
  the same root cause; the exclusion set):
    Yone    W : snap 3 / side 2  (snapshot already richer)
    Teemo   E : snap 3 / side 2  (snapshot already richer)
    Shyvana W : snap 2 / side 2  (match; sidecar blocks are Calc_Shield / Damage
                                  with no total_ad_pct - shield, not AD damage)

  This matches the residual's named siblings and its "REFUTED nearby: Yone W /
  Teemo E / Shyvana W (reworked-kit / on-hit / stale-CDragon)" exactly.

The mirror-pattern precedent for a hand-authored per-(champ,key) block registry -
`agents/daemon_slayer/_passive_damage_overrides.py` (header lines 1-64):
hand-authored, keyed by (champion, key, form_index), `to_damage_block(entry)`
builds a synthetic `DamageBlock(attribute_kind="damage", ...)` through the
EXISTING evaluator with ZERO new math, injected only when the opt-in flag is
passed, default byte-identical. This is the fallback mechanism (see DESIGN D2).

### Sub-fix B - bruiser/hybrid ability-DPS XOR

The scorer's damage term is a strict XOR keyed on damage axis. Three identical
sites, all in `agents/daemon_slayer/hybrid.py`:
- The axis classifier - `_damage_axis(snapshot, champion_id)` (`hybrid.py:73-79`):
  `return "ap" if magic > attack else "ad"` (DDragon `info.magic` vs
  `info.attack`).
- The ability-DPS scalar - `_ability_damage(...)` (`hybrid.py:82-108`) ->
  `compute_ability_dps(...).total_ability_dps`.
- XOR site 1 - `compute_hybrid` (`hybrid.py:462-469`):
  `if _damage_axis(...) == "ap": base_damage = _ability_damage(...) else:
  base_damage = dps_result.weighted_dps`.
- XOR site 2 - `rank_items_by_hybrid` baseline (`hybrid.py:938-946`):
  `baseline_dps = _ability_damage(...) if axis == "ap" else
  baseline_dps_result.weighted_dps`.
- XOR site 3 - `rank_items_by_hybrid` scored (`hybrid.py:1026-1034`):
  `scored_damage = _ability_damage(...) if axis == "ap" else
  dps_scored.weighted_dps`.
- The `compute_hybrid` signature is `hybrid.py:281` (existing bool
  `assume_ms_utility` at `hybrid.py:314`); `rank_items_by_hybrid` is
  `hybrid.py:737` (`assume_ms_utility` at `hybrid.py:779`). The new Sub-fix B
  flag lands beside `assume_ms_utility` in BOTH signatures.
- The per-spell sum that IS non-zero for AD bruisers -
  `ability_dps.py:1270`: `total_dps = sum(s.dps for s in per_spell)`
  (`compute_ability_dps` def `ability_dps.py:913`, returns
  `total_ability_dps=total_dps` at `ability_dps.py:1444`; the empty-form path
  returns `0.0` at `ability_dps.py:1513`).
- The AP-axis awareness was SHIPPED for AP champs at ENGINE 1.185.0
  (`BACKLOG.md:16`, "Bruiser scorer axis-awareness - SHIPPED"); the AD-axis
  ability portion was left zeroed - that residual is this Sub-fix B.

Affected AD-axis bruisers (DDragon `info` probed 2026-07-16 from
`data/daemon_slayer/16.14.1/champions.json`; all are `magic <= attack` -> the XOR
else-branch -> auto-only, ability DPS dropped):

    champ      attack magic  axis   archetype_weights [alpha,beta]  auto-empower?
    Riven         8     1    ad     [0.70, 0.30] (line 15)          no  (SEED)
    JarvanIV      6     3    ad     [0.55, 0.45] (line 8)           no  (SEED)
    Camille       8     3    ad     [0.65, 0.35] (line 11)          YES (Q) exclude
    Renekton      8     2    ad     [0.65, 0.35] (line 12)          YES (W) exclude
    Darius        9     1    ad     [0.65, 0.35] (line 9)           YES (W) exclude
    Nasus         7     6    ad     [0.50, 0.50] (line 17)          YES (Q) exclude
    Sett          8     1    ad     [0.55, 0.45] (line 13)          YES (Q) exclude
    Vi            8     3    ad     [0.55, 0.45] (line 22)          YES (E) exclude

  archetype_weights.json line numbers are from
  `agents/daemon_slayer/archetype_weights.json` (verified). NOTE the residual's
  own warning (`BACKLOG.md:12`): "a BLANKET AD-bruiser sum is REFUTED-unsafe
  (double-counts auto-empower abilities Nasus Q / Renekton W / Camille Q / Sett Q
  / Vi E that compute_dps already counts as an auto)". The pure-cast subset that
  is SAFE to blend is Riven + Jarvan (Q/W/E are independent ability strikes / the
  EQ combo, not next-auto empowers).

Ship-pattern precedent (the exact Tier-2 shape this session follows) -
`docs/LEDGER.md` entry 515 (ENGINE 1.145.0 -> 1.146.0, commit `dc2eb0c3`): NEW
`assume_<x>: bool = False` seam, byte-identical off, RED-first test, engine bump
quoted-literal-only across the DS source .py, Share re-synced SAME commit
(--check green), DS :8893 taskkill + `schtasks /Run RC-DaemonSlayer` -> /health,
dual suite, live default-ON flip appended to `docs/LIVE_GAME_GATED_SYNC.md`.
Entry 903 is the more recent same-shape precedent (115 py pins, 6 build-order
tables re-stamped orders byte-identical default-OFF).

UNVERIFIED-SKIP (1): the live NUMERIC pre-fix `total_ability_dps` for Riven /
Jarvan was NOT executed here (constructing a full DataSnapshot is out of a
read-only probe budget and DS :8893 was not reachable at probe time). The
mechanism, the axis, the weights, and the sum line (`ability_dps.py:1270`) are
all verified; the exact numbers are the RED test's job (D6 / AC-B2). Do NOT carry
a fabricated magnitude forward - let the RED test capture the real value.

--------------------------------------------------------------------------------
## SCOPE + NON-SCOPE
--------------------------------------------------------------------------------

Two sub-fixes, ONE Tier-2 session, ONE ENGINE bump (1.216.0 -> 1.217.0). The two
sub-fixes touch DISJOINT files (Sub-fix A = abilities.py + a small allowlist;
Sub-fix B = hybrid.py + a small opt-in table) and are independent - they may be
built in either order or in parallel, then shipped under one version bump.

IN SCOPE - Sub-fix A (Viego, LOAD-side):
- A NEW default-OFF load-time flag on `AbilitiesSnapshot.load` (mirror
  `apply_passive_damage`) that APPENDS the surplus clean CDragon mechanical
  block for an ALLOWLISTED (champion, spell_key) pair, using the machine-parsed
  sidecar block (`cdragon_ability_ratios.json`).
- v1 allowlist seed = `{(Viego, R)}` ONLY (the tightest matching set - a clean
  primary-hit AD term).
- The 5 SURPLUS siblings (Pyke R, Rengar R, Quinn R, Yorick R, Jinx Q) are the
  documented candidate QUEUE; each gets a SEMANTIC validation pass this session
  and is seeded in v1 ONLY if its surplus block is a clean sustained-ability-DPS
  term (see D3). Any that are execute / pet / mode-switch / auto-modifier stay in
  the queue with an explicit exclusion note + test.
- Exclusion tests pinning the REFUTED-nearby set (Yone W / Teemo E / Shyvana W)
  and any un-seeded SURPLUS sibling as byte-identical (append never fires).

DETERMINATION (the task's extractor-side contingency does NOT apply): Sub-fix A
is LOAD-side, not extractor-side. Evidence: the CDragon sidecar already carries
the 120% total-AD block machine-parsed (verified above), Meraki legitimately
structures Viego R as a single leveling block, and the drop is entirely the
overwrite-only merge at `abilities.py:580-581`. Therefore the scope is a
load-time append seam - NOT an extractor edit + snapshot regen. Do NOT edit
`tools/daemon_slayer_abilities_extract.py` or regenerate `champion_abilities.json`
for this fix (that would be a wider, unnecessary blast radius and would fight the
sidecar-preference architecture).

IN SCOPE - Sub-fix B (hybrid blend):
- A NEW `blend_ability_axis: bool = False` flag + a small per-champ opt-in table
  (membership set), threaded through `compute_hybrid` and both
  `rank_items_by_hybrid` sites (baseline + scored). When ON and the champ is in
  the table, the AD-axis damage term becomes `auto_dps + ability_dps` (SUM);
  otherwise the existing XOR is byte-identical.
- v1 opt-in table seed = the pure-cast subset that carries NO auto-empower
  double-count. Pinned seeds = Riven + JarvanIV. Each other candidate is
  validated this session and seeded ONLY if it passes the double-count exclusion
  check.
- Exclusion tests pinning the auto-empower champs (Renekton / Camille / Darius /
  Nasus / Sett / Vi) as byte-identical (never blended) and the AP-axis branch as
  unchanged.

NON-SCOPE (do NOT do in this session):
- NO default-ON flip for either flag. Both ship default-OFF (byte-identical). The
  default-ON flips are TWO separate live-gated rows in
  `docs/LIVE_GAME_GATED_SYNC.md` (need a live/replayed Viego game and a live AD
  bruiser game). "NOT blind-shippable" per both BACKLOG residuals.
- NO general APPEND seam / blanket sibling append for Sub-fix A (residual option
  b). The allowlist bounds v1; the general seam is the FUTURE widening once the
  registry proves out.
- NO blanket AD-bruiser sum for Sub-fix B (REFUTED-unsafe, double-counts
  auto-empowers). Table membership only.
- NO change to `archetype_weights.json` alpha/beta values. Those weight DPS vs
  EHP; the new blend is auto-vs-ability WITHIN the DPS term - a different axis.
  Do not conflate them.
- NO intra-damage per-champ alpha/beta weighting of auto-vs-ability in v1. v1 is
  a plain SUM. A weighted intra-damage blend is FUTURE (keep the table a simple
  set; avoid a second calibration surface).
- NO crit-scaling upper term for Viego R ("120% : 240% based on crit chance"). v1
  models the 120% base only (conservative; residual "from AD alone"). Document as
  a v1 caveat.
- NO extractor edit / snapshot regen (see DETERMINATION above).
- NO kit-axis win-flip. This is a pure-sim damage-model completion; it does NOT
  collide with the DSP11 gate (`BACKLOG.md:12`, and memory
  `project_dsp11_gate_do_not_revert`).

--------------------------------------------------------------------------------
## DESIGN DECISIONS (pre-answered - execution does not re-decide)
--------------------------------------------------------------------------------

D1 (A locus). LOAD-side append, not extractor-side. Justification in the SCOPE
DETERMINATION. The sidecar carries the block; the fix reads it.

D2 (A mechanism, RECOMMENDED). Allowlist-gated APPEND in the CDragon merge path.
Add a helper (co-locate near `_apply_cdragon_ratio_preference`) that, for a
(champ, spell_key) in the v1 allowlist, takes the sidecar mechanical block(s)
whose stat-family signature matches NONE of the Meraki damage blocks (the
"surplus" set), converts each to a fresh `DamageBlock(attribute_kind="damage",
...)`, and APPENDS it to the form's `damage_blocks`. Gate the whole thing behind a
NEW `AbilitiesSnapshot.load` flag (proposed name `apply_cdragon_surplus_ad`,
default False). OFF -> zero appended blocks -> byte-identical. This is preferred
over the hand-authored registry because the coefficient (120% `total_ad_pct`) is
already machine-parsed in the sidecar - nothing to hand-author or re-verify each
patch.
  FALLBACK (only if the sidecar-block -> DamageBlock conversion hits a shape snag
  in execution): the hand-authored per-(champ,key,form_index) registry mirroring
  `_passive_damage_overrides.py` (`to_damage_block` synthetic block), same flag,
  same default-OFF. Pick the fallback ONLY on a concrete conversion blocker;
  prefer D2's sidecar-sourced path.

D3 (A seed + sibling policy). v1 allowlist = `{(Viego, R)}`. For each of the 5
SURPLUS siblings, validate the SEMANTICS before seeding:
  - Viego R: direct primary-hit AD damage on a normal cast -> clean sustained
    ability-DPS append. SEED.
  - Pyke R (execute / threshold): a raw DPS append mis-models a health-threshold
    execute. Default EXCLUDE unless execution shows the surplus block is modeled
    as flat cast damage (it is a `RADDamage` execute term) - keep in queue,
    exclusion test.
  - Yorick R (pet / Maiden `YorickBigGhoulDamage`): pet damage is a separate
    cadence, not the caster's spell rotation. EXCLUDE, queue + test.
  - Jinx Q (rocket `RocketDamage`): an auto-attack MODIFIER / weapon-swap, at
    high double-count risk with `compute_dps` autos. EXCLUDE, queue + test.
  - Rengar R (leap empower `BonusDamage`) and Quinn R (on-cast AoE `Damage`):
    plausible clean cast terms - seed ONLY if the execution session confirms the
    block is unconditional cast damage AND not already credited elsewhere; else
    queue + test.
  Do NOT blanket-seed all 6. The v1 shipped seed is Viego plus any sibling that
  concretely passes the clean-cast check; everything else is a documented queue
  entry with a byte-identical exclusion test. This is the "tightest matching set
  FIRST + exclusion tests before widening" discipline.

D4 (A default). OFF. Byte-identical at the default (the full DS suite passes
unchanged). Default-ON flip is a separate live-gated decision;
`docs/LIVE_GAME_GATED_SYNC.md` row.

D5 (A caveat). Viego R missing-HP block is 0 at full HP; pre-fix R DPS = 0 there.
Post-fix (flag ON) the 120% total-AD term makes R DPS > 0 at full HP. Model the
120% base only; the crit-scaled 240% upper bound is a v1-documented omission.

D6 (B mechanism). NEW `blend_ability_axis: bool = False` on `compute_hybrid` and
`rank_items_by_hybrid` (beside `assume_ms_utility`) + a small opt-in table
(proposed a frozenset/JSON of champion ids). At all three XOR sites: when
`blend_ability_axis` AND `axis == "ad"` AND champ in table, the damage term =
`weighted_dps + total_ability_dps` (SUM). The AP-axis branch is UNTOUCHED (AP
still scores on ability_dps only). OFF or not-in-table -> the existing XOR is
byte-identical (a name-bind, not a float op, on the OFF path). All three sites
MUST get the identical treatment (baseline and scored, or a delta is corrupted).

D7 (B seed + exclusion). v1 table = pure-cast, no auto-empower. Pinned seeds =
`Riven`, `JarvanIV`. For each other AD-axis bruiser candidate, seed ONLY if its
`compute_ability_dps` per_spell does NOT include a spell that `compute_dps`
already credits as an auto-empowered attack. The named auto-empower kits
(Renekton W, Camille Q, Darius W, Nasus Q, Sett Q, Vi E) stay OUT -> exclusion
test asserts them byte-identical flag-ON.

D8 (B not a win-flip). No `archetype_weights.json` change; the blend is orthogonal
to the DPS-vs-EHP alpha/beta. Does not collide with the DSP11 kit-axis gate.

D9 (B default). OFF (empty-effect). Default-ON flip = separate live-gated row.

D10 (shared). ONE ENGINE bump (1.216.0 -> 1.217.0), quoted-literal-only. ONE
commit. Share mirror in the SAME commit. Both new test files RED-first before any
production edit.

--------------------------------------------------------------------------------
## TESTABLE ACCEPTANCE CRITERIA (RED-first; assert computed quantities)
--------------------------------------------------------------------------------

Write both test files FIRST and confirm each new assertion is RED (fails / errors
on the absent flag or symbol) before touching production. Assert COMPUTED
quantities (a DPS value, a sum equality, a > 0), never a cross-item ranking
comparison (memory: data-fragile cross-item asserts are banned).

Sub-fix A - `agents/daemon_slayer/tests/test_viego_r_ad_credit_r129.py`:
- AC-A1 (default guard, stays GREEN): with the flag OFF (default),
  `compute_ability_dps("Viego", level=..., full HP)` credits 0.0 for the R spell
  (the R per_spell entry dps == 0.0). Byte-identical to today.
- AC-A2 (RED before fix): with the flag ON, the Viego R per_spell dps > 0.0 at
  full HP.
- AC-A3 (RED before fix): with the flag ON, the Viego R contribution SCALES with
  bonus AD - add a bonus-AD item and assert R dps strictly rises (proves the
  appended block is the 120% total-AD term, not a constant).
- AC-A4 (RED before fix): with the flag ON, the Viego R form has exactly ONE more
  `attribute_kind=="damage"` block than with the flag OFF (cardinality 1 -> 2);
  the pre-existing missing-HP block is unchanged.
- AC-A5 (bounding guard): with the flag ON, an un-seeded SURPLUS sibling (assert
  the concrete v1 non-seed set, e.g. Yorick R / Jinx Q) is byte-identical to flag
  OFF - the allowlist gates the append.
- AC-A6 (refuted-nearby guard): with the flag ON, Yone W / Teemo E / Shyvana W
  ability DPS is byte-identical to flag OFF (never appended).
- AC-A7 (per seeded sibling, if any pass D3): RED that the seeded sibling's
  spell dps > 0 flag-ON and 0 (or byte-identical) flag-OFF.
- AC-A8: ENGINE pin == "1.217.0"; test file is 7-bit ASCII (byte scan).

Sub-fix B - `agents/daemon_slayer/tests/test_hybrid_blend_ability_axis_r129.py`:
- AC-B1 (default guard, stays GREEN): with `blend_ability_axis=False` (default),
  `compute_hybrid` and both `rank_items_by_hybrid` paths for Riven are
  byte-identical to today (the damage term == `weighted_dps`, the XOR else-branch).
- AC-B2 (RED before fix): `total_ability_dps("Riven") > 0` (captures the real
  pre-existing nonzero the residual cites - this is the UNVERIFIED-SKIP magnitude,
  pinned here by the test, not by prose).
- AC-B3 (RED before fix): with `blend_ability_axis=True` and Riven in the table,
  the `compute_hybrid` damage term == `weighted_dps + total_ability_dps` (assert
  the SUM equality on a real or stubbed snapshot), and it is strictly greater than
  the flag-OFF value.
- AC-B4 (RED before fix): BOTH `rank_items_by_hybrid` sites use the blend - assert
  the baseline damage term AND at least one scored candidate's damage term equal
  their respective `weighted_dps + total_ability_dps` when Riven is in the table
  and the flag is ON.
- AC-B5 (RED before fix): JarvanIV in the table gets the same blend (nonzero
  ability contribution, sum equality).
- AC-B6 (double-count exclusion guard): with the flag ON, each auto-empower champ
  (Renekton, Camille, Darius, Nasus, Sett, Vi) is NOT in the table and its
  hybrid score is byte-identical to flag OFF (the blanket-sum REFUTED-unsafe path
  never fires).
- AC-B7 (AP-branch guard): with the flag ON, an AP-axis champ routed through the
  bruiser scorer (e.g. Mordekaiser) still scores on ability_dps only - the blend
  does not touch the AP branch (byte-identical to flag-OFF AP behavior).
- AC-B8 (non-member guard): an AD-axis champ NOT in the table is byte-identical
  flag-ON vs flag-OFF.
- AC-B9: ENGINE pin == "1.217.0"; test file is 7-bit ASCII (byte scan).

Global byte-stability: with BOTH flags OFF (the shipped default), the entire dual
suite passes unchanged - that IS the unrelated-champ byte-stability proof. Add
one explicit assertion that a random unrelated AD carry's `compute_ability_dps`
and hybrid score are unchanged at the default.

--------------------------------------------------------------------------------
## R5 TIER = Tier-2 (schema / engine / scorer)
--------------------------------------------------------------------------------

Both sub-fixes touch the DS engine scorers -> Tier-2 full discipline (CLAUDE.md
"Execution Efficiency & Tooling Rules" R5; "Testing Discipline"; memories
`feedback_ds_bump_run_tests_dir`, `reference_ds_server_not_supervisor_watched`,
`feedback_engine_bump_quoted_literal_only`).

- ENGINE bump: quoted-literal-only byte replace `"1.216.0"` -> `"1.217.0"` across
  ALL DS source .py (the test pins + `__init__.py`; ~115 pins per the 903
  precedent). Confirm 0 stray `"1.216.0"` remain in *.py. Do NOT touch bare
  `1.216.0` in CHANGELOG / ORCHESTRATION prose (those are historical).
- Dual suite (run each ONCE, trust the exit code per R6; re-run only affected
  files if edited-since or the pipe glitched): the DS dir
  `agents/daemon_slayer/tests` AND the RC `tests/` tree. Expect the two NEW test
  files GREEN post-fix and the full suites at their baseline counts (20,190 total
  per LEDGER 904).
- Share mirror in the SAME commit (memories `feedback_ds_commit_share_test_mirror`,
  `feedback_share_mirror_tools_drift`): re-sync `Share/src/agents/daemon_slayer/`
  (abilities.py, hybrid.py, the new allowlist + table modules, __init__.py, both
  new test files) + prepend `Share/CHANGELOG.md` and
  `agents/daemon_slayer/CHANGELOG.md` dated entries; run the ds_share_sync
  `--check` to green (do NOT hand-edit the mirror).
- DS :8893 restart + /health verify: after the bump, `taskkill /F /PID <ds_pid>`
  then `schtasks /Run /TN RC-DaemonSlayer` (it is NOT supervisor-watched;
  GOTCHA per memory: confirm the port is actually free before /Run - a detached
  child can hold it). Verify `/health` reports `1.217.0`. Do NOT launch the suite
  during the Share-sync + DS-bounce window (mid-suite bounce = false
  anchor-mismatch flakes; memory `feedback_finish_ds_edits_before_full_suite`).
- Build-order precompute re-stamp: both flags default OFF -> the precomputed
  `data/daemon_slayer/16.14.1/build_orders_{sr,aram,arena}.json` ORDERS are
  byte-identical. Re-stamp ONLY the embedded ENGINE version field (regen tool if
  it re-stamps in place; else leave orders and bump the version field). If ANY
  order shifts, STOP - that is a default-not-byte-identical regression to fix
  before shipping (memory `reference_hz_precompute_patch_regen`,
  `feedback_ds_worktree_merge_regen_dist_bundle`).

--------------------------------------------------------------------------------
## FILES TOUCHED (by the execution session, not this spec)
--------------------------------------------------------------------------------

Sub-fix A:
- `agents/daemon_slayer/abilities.py` - new `apply_cdragon_surplus_ad` flag on
  `AbilitiesSnapshot.load` + the allowlist-gated append helper near
  `_apply_cdragon_ratio_preference`.
- `agents/daemon_slayer/_cdragon_surplus_ad_allowlist.py` (NEW, small) - the
  `{(champ, spell_key)}` v1 allowlist, seeded `{(Viego, R)}` plus any D3-passing
  sibling. (Or an inline frozenset in abilities.py if the reviewer prefers; a
  small module mirrors the `_passive_*_overrides.py` convention.)
- `agents/daemon_slayer/tests/test_viego_r_ad_credit_r129.py` (NEW).

Sub-fix B:
- `agents/daemon_slayer/hybrid.py` - `blend_ability_axis` flag on `compute_hybrid`
  + `rank_items_by_hybrid`; the blend at the three XOR sites (462-469 / 938-946 /
  1026-1034); the table membership check.
- `agents/daemon_slayer/_hybrid_blend_table.json` (NEW, small; mirror
  `archetype_weights.json` load pattern) OR an inline frozenset - the opt-in set
  seeded `{Riven, JarvanIV}`.
- `agents/daemon_slayer/tests/test_hybrid_blend_ability_axis_r129.py` (NEW).

Shared / ship:
- `agents/daemon_slayer/__init__.py` - `ENGINE_VERSION` 1.216.0 -> 1.217.0.
- ~115 DS source .py - ENGINE pin byte-replace (mechanical).
- `agents/daemon_slayer/CHANGELOG.md` + `Share/CHANGELOG.md` - dated entries.
- `Share/src/agents/daemon_slayer/**` - mirror (same commit, --check green).
- `data/daemon_slayer/16.14.1/build_orders_{sr,aram,arena}.json` - ENGINE
  re-stamp only (orders byte-identical).
- `docs/LIVE_GAME_GATED_SYNC.md` - TWO live default-ON flip rows.
- `docs/DAEMON_SLAYER.md` - banner ENGINE + test-count refresh.
- `docs/LEDGER.md` - append the R129-residuals completion entry (newest-first;
  NEVER CLAUDE.md).

Do NOT touch any frozen file (CLAUDE.md frozen list) and do NOT edit
`tools/daemon_slayer_abilities_extract.py` or regenerate `champion_abilities.json`
(load-side fix; see SCOPE DETERMINATION).

--------------------------------------------------------------------------------
## EST SESSIONS + MODEL
--------------------------------------------------------------------------------

EST SESSIONS: 1 (one Tier-2 session; two disjoint sub-fixes, one ENGINE bump, one
commit). The sibling SEMANTIC validation (D3) and the auto-empower exclusion
checks (D7) fit inside the session - they are grep + one-probe-per-champ, not new
research arcs.

MODEL: claude-opus-4-8, effort max. Subagent-first per CLAUDE.md: the two disjoint
sub-fixes are a natural 2-slice parallel (abilities.py vs hybrid.py, no shared
file) with a read-only verifier gate before the merge + bump; or inline if the
session prefers (both are single-module + its test, near the R9 threshold). The
ENGINE bump + Share mirror + DS bounce is the sole-merger step after both slices
land.

--------------------------------------------------------------------------------
## DONE RITUAL
--------------------------------------------------------------------------------

1. Both new test files RED-first confirmed, then GREEN post-fix.
2. Dual suite green (DS dir + tests/), counts at baseline; both flags OFF ->
   byte-identical proven.
3. ENGINE bump verified: 0 stray `"1.216.0"` in *.py; /health-to-be 1.217.0.
4. Share `--check` green (mirror in the same commit); CHANGELOGs prepended.
5. DS :8893 taskkill + `schtasks /Run RC-DaemonSlayer`; confirm /health == 1.217.0
   (port-free check first).
6. Build-order tables ENGINE re-stamp (orders byte-identical) verified.
7. Commit + push (verified-green -> no ask, memory `feedback_always_commit_push`);
   commit body via `git commit -F <ascii tmpfile>` (special-char rule).
8. Append `docs/LEDGER.md` completion entry; append the TWO
   `docs/LIVE_GAME_GATED_SYNC.md` default-ON flip rows; refresh
   `docs/DAEMON_SLAYER.md` banner.
9. Confirm CI green before declaring done.

--------------------------------------------------------------------------------
## GHOST LIST (do NOT re-do / do NOT re-open)
--------------------------------------------------------------------------------

- The R129 Fimbulwinter "Everlasting" shield EHP credit is SHIPPED (ENGINE
  1.214.0, commit `86ffb9b9`, LEDGER 903). ONLY these two residuals remain. Do
  NOT re-credit the Fimbulwinter shield or re-open the R129 shield work.
- Do NOT re-credit Navori / Kraken "Bring It Down" - already modeled default-ON
  (`BACKLOG.md:32` Kraken don't-redo anchor: PeriodicProc every_n_attacks=3,
  Arena mirror 226672, guard-tested). Not part of this spec.
- Zed / Talon / Qiyana lethality rows are LEDGER-889 REFUTED - do NOT fold them
  into either sub-fix.
- Sub-fix A is LOAD-side, DETERMINED, not extractor-side (the sidecar carries the
  120% block machine-parsed). Do NOT "fix the extractor" or regen the snapshot.
- Do NOT ship the general/blanket CDragon-surplus APPEND seam (residual option b)
  - the allowlist bounds v1; the sibling sweep is the tightest-matching-set
  (Viego seed) + exclusion tests, widened only on per-champ evidence (Engine /
  Build Conventions: grep siblings, tightest set first, exclusion tests before
  widening - done here via the cardinality probe).
- Do NOT blanket-sum AD-bruiser auto+ability for Sub-fix B - REFUTED-unsafe
  (auto-empower double-count: Nasus Q / Renekton W / Camille Q / Sett Q / Vi E).
  Table membership only; Riven + Jarvan seed.
- Do NOT flip either flag default-ON in this session (NOT blind-shippable; live
  default-ON flips are the two LIVE_GAME_GATED_SYNC rows).
- Do NOT change `archetype_weights.json` alpha/beta (DPS-vs-EHP axis; orthogonal
  to the new auto-vs-ability blend).
- Do NOT add the Viego crit upper term (240%) or an intra-damage alpha/beta in
  v1 - both are documented FUTURE.
- 7-bit ASCII only in every authored byte (no em / en dashes, no smart quotes);
  `precommit_gate.py` is the backstop.
