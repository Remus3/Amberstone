# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-19j (gemini-loop cycle 5 - R136 shipped RM-101's numerator half, and two blockers in our OWN ROADMAP turned out to be conventions that already shipped)

**A claim written in our own ROADMAP ages exactly like an external source, and
inherits no more trust. Verify a BLOCKER before honouring it, not just a formula
before building on it.**

Shipped (ENGINE 1.224.0 -> 1.225.0, commit `18aca9e3`): `_rune_health_grants.py`
(Overgrowth 8451 permanent max-HP + Grasp 8437 self-side heal / permanent-HP)
behind DEFAULT-OFF `apply_rune_health_grants`, and `_rune_hsp_amp.py`
(Revitalize 8453's flat 5% Heal/Shield Power) behind DEFAULT-OFF
`apply_rune_hsp_amp`. Both reuse R132's existing `rune_ids` transport, so no
entry point gained a new ids parameter. Three agents on disjoint file sets with
the orchestrator holding EVERY shared seam, so the slices structurally could not
collide - both build agents returned exactly two untracked files and zero seam
edits, verifier-confirmed.

**The directive was wrong and was not followed.** It ordered all seven RM-101
runes including Font of Life 8463. Our own spec records 8463 as DATA-BLOCKED on
an unresolved `@BaseHeal@` DDragon template var; the directive's premise line was
tagged `[from-digest]` and the digest had dropped the qualifier. Re-confirmed
from raw source: `@BaseHeal@` appears verbatim in ALL FOUR vendored snapshots, is
one of only 3 unresolved tokens in the whole rune file, and no independent
vendored source exists (the aggregator B scrapes re-serve the same DDragon payload; no
CommunityDragon `perks.json` is vendored). The number was not invented. Two tests
pin 8463 + 8465 at zero credit so a later pass cannot seed a guess.

**Two ROADMAP claims REFUTED, both re-grepped rather than taken on the agent's
word.** "Second Wind needs a missing-health convention the scorer lacks" - it is
a local variable at the exact call site (`ehp.py:355
_MISSING_HP_SHARE_FOR_HEALS = 0.5`). "Bone Plating needs a hit-count convention
that does not exist" - `_passive_flat_mitigation_overrides.py:92
_ASSUMED_FLAT_DR_INSTANCES = 6.0` with discrete instance math at `:270` shipped
in R9 a MONTH before the claim was written. Both blockers were authored by a
careful agent that read the rune correctly and simply never checked whether the
sibling registry it needed already existed. This is the third cycle running in
the same family (R132's Aftershock cap, R134's audit, now this).

**NEXT: Bone Plating 8473.** Its instance count of 3 is stated in the rune text,
so it REPLACES that registry's largest assumption instead of adding one, and at
~154 prevented HP (L13) it is the only buildable remainder big enough to reorder
a ranking. Shape: rune-keyed `_rune_flat_mitigation.py`, `level_scaled` copied
from the percent sibling, `_lerp_per_level(30.0, 60.0)`, folded next to
`flat_mit_*`. The one judgement call is `conditional_probability` - "from
**them**" scopes the block to a single attacker, so seed it conservatively.
Then Second Wind (buildable, small at ~50 numerator HP), then Guardian self-only
(AP-omitted, under the shipped Irelia-W / Fizz-P omission precedent).

Two hazards worth carrying. (1) The rune-HSP seam is only OBSERVABLE on a build
owning a self-shield - HSP scales the shield pool, so on a shieldless tank build
arming the flag is correctly a no-op. This cost one red test before it was
understood; `test_hsp_amp_needs_a_shield_to_amplify` now pins it so nobody
"fixes" a working seam. (2) After an ENGINE bump the first RC suite run WILL show
~15 failures that are pure regen debt - build-order engine stamps, the
`docs/DAEMON_SLAYER.md` banner, and one live-integration test that cannot pass
until `:8893` is bounced. The regen commands are quoted in
`tests/test_build_order_engine_stamp_sync.py`'s own docstring.

---

# 2026-07-19i (gemini-loop cycle 4 - the sweep's thesis was refuted by measurement; the shippable bug was found on the way past it)

**A missing guard is not a bug until something can reach it. Measure reachability
before pricing the fix.**

The directive ordered a League movespeed soft-cap seam (caps above 415 / 490,
floor below 220) and pre-declared ENGINE-IMPACT BUMP. The piecewise is real and
correctly stated, and nothing in the repo applies it - so the gap looks obvious.
It is unreachable at every site. `core/champion_movespeed.est_ms` is uncapped but
the roster's base MS spans only 315 (Rell) to 355 (Master Yi) across all 173
champs, and its sole consumer `core/mia_reachability.py:165` passes NO items, so
no breakpoint can bind. The DS path that CAN exceed 415 (`hybrid.py:272`, measured
426.6 on Darius + Swifties + DMP + FoN) is double-gated: `assume_ms_utility` is
DEFAULT-OFF with no production caller, AND `_MS_UTILITY_DPS_CAP = 0.15` saturates
at 1.30x base, bounding the whole error to 0.794 percentage points inside a
27-unit window and exactly zero above 442. A third site the directive never named,
`ability_dps.py:293`, is default-ON but populated by exactly one block roster-wide
(Janna W: 1.09 magic damage, only on an off-class Phantom Dancer build).

Taking the BUMP at face value would have shipped a DEFAULT-OFF seam, an
ENGINE_VERSION bump, a Share re-sync and a `:8893` bounce to correct a quantity
that is provably zero on every live path. The `ENGINE-IMPACT` header is a
PREDICTION, not a fact - and the precommit gate checks it for free ("no mirrored
DS source staged - skipping Share sync").

**The second lesson is sharper: the existing test passed because it sampled the
one case outside the failing class.**

The other sweep lane came back CLEAN on mirrors and magnitudes (0 missing, 0 drift
across 99 MS-bearing items) but found a genuine wrong answer in passing.
`_item_index()` hit `continue` on zero-MS entries BEFORE the name `setdefault`, so
a canonical 4-digit id granting no movespeed never claimed its own display name and
the next mode mirror answered for it: `item_ms("Warmog's Armor")` returned 4% from
Arena `443083` while canonical `3083` grants none; Gargoyle Stoneplate 10%
(`443193`); Rite of Ruin 4% (ARAM `123430`). All three reproduced against raw
DDragon before any code was written.

`tests/test_champion_movespeed.py` pinned exactly one name lookup - "Boots of
Swiftness" - and Boots of Swiftness is precisely the shape that cannot exhibit the
bug, a canonical id that HAS movespeed and therefore already claims its own name
key. A green suite over a sampled-wrong fixture is indistinguishable from a green
suite over correct code. When a lane reports CLEAN, check what the tests actually
sample before believing the code is exercised. Same family as R133's
`test_arena_mirrors_credit_same_as_base`, one rung down: R133 asserted the wrong
thing, R135 asserted the right thing about the wrong row.

Shipped `e4ab8144` (fix, no ENGINE bump - `core/`, no DS import) + `e2b186ff`
(docs). Suite 20673 passed / 24 skipped / 0 failed. Zephyr and Gambler's Blade
deliberately untouched: no 4-digit canonical exists for either, and `3172` is
Gunmetal Greaves NOT Zephyr, so `"22" + base_id` is a FALSE mirror-pairing rule.
Also worth keeping: `items_meraki.json` has NO `stats` key on any of its 320
entries, so DDragon is the SOLE movespeed magnitude source - the habitual
cross-check-against-Meraki silently cannot run on this axis.

---

# 2026-07-19h (gemini-loop cycle 3 - the REGRESS audit was 2/3 right, and the wrong third was the dangerous one)

**An audit verdict is not privileged evidence. Premise-check it like any other claim.**

The directive arrived as a REGRESS fix-first: three named regressions in R132, an
ENGINE bump, two worktree slices. One of the three was wrong, and it was the only
one that touched math. It read the call `_rune_resist_fn(..., total_armor=armor)`
in `ehp.py`, saw a nearby local named `bonus_armor`, and concluded item armor was
missing - prescribing `total_armor=armor+bonus_armor+ext_armor+item_resist_armor`.

Every added term is misidentified. `armor` is `stats["armor"]`, the RESOLVED build
armor, and already contains item armor - measured, Malphite L13 reads 94.2 bare and
219.2 with 3068+3075. `bonus_armor` at `ehp.py:1668` is the return value of the
CHAMPION `resist_grants(...)` registry - a peer conditional-grant lane, not a stat.
`item_resist_armor` is the ITEM registry output, itself derived from
`total_armor=armor` one call above. `ext_armor` is an ALLY-conferred resist.

Applying it feeds three peer grant lanes into the fourth, so Aftershock takes 75
percent of OTHER grants, and the value starts depending on the SOURCE ORDER of four
peer registries. Measured: Aftershock L1 goes (14.625, 15.3) -> (24.0, 24.0). The
ground truth was already written down twice - the callee's docstring at
`_rune_resist_grants.py:227-230` states the contract verbatim, and `ehp.py:1663-1664`
carries the invariant in code: "total_* exclude the passive grants (not in
base/items) so there is no self-feedback".

**This is the exact inverse of cycle 2's lesson, same failure family.** Cycle 2's
agent paraphrased a formula it had cited correctly. Cycle 3's auditor inferred a
callee's semantics from an argument NAME at the call site without opening the
callee. Both are "cited the right line, got the claim wrong".

Second lesson: **reclassify before you remediate.** Findings 2 and 3 (mid-signature
kwarg inserts) were real but were latent convention drift, not breakage - an AST
scan found a maximum of 4 positional args against functions taking 36-50, so no
caller could break. That collapsed a directed 2-worktree ENGINE-bump slice into a
6-line reorder with no bump.

Third, the durable part: `compute_ehp` carried the convention as an inline COMMENT
and three siblings violated it anyway. A convention that lives only in a comment is
not a convention. `test_rune_resist_signature_convention_r134.py` now enforces both
the trailing-kwarg rule and the `total_armor` same-values contract, so the refuted
change turns a test RED rather than silently over-crediting tanks.

Commit `534ab3ef`, ENGINE stays 1.224.0. DS 8686 / RC 11979 green, verifier CONFIRM
on all four claims. Refutation escalated to the director via `gemini_ask.txt` so
cycle 4 does not re-issue it or read the absent bump as unfinished work.
