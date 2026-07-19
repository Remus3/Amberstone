# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-19l (three lanes shipped; every filing was wrong somewhere load-bearing, and I broke Share/src and fixed it)

**A ROADMAP number, a spec's prescribed fix, and a stated defect premise are all
just claims. Three of three were wrong this session in ways that would have
shipped defects, and all three were caught by reading files instead of prose.**

Shipped: `556662a7` RM-107 + the `begin/end` HTTP 400 sibling; `b9ac8de9`
CHANGELOG 1.224.0/1.225.0 backfill + prepend guard; `8bf21a77` Share/src
recovery; `ba676157` atomic Share sync; `a60d32e6` Lane 1 feed index + RM-108;
`37db1414` ENGINE 1.227.0 (RM-101/102/103/105). CI green. Ledger 965-967.

**THE INCIDENT, because it will recur otherwise.** Commit `6464532e` (mine)
emptied `Share/src` on main - 501 deletions, 596,900 lines, ZERO additions.
`ds_share_sync._write` was `rmtree` THEN rebuild, so the mirror spent the entire
~483-file rebuild deleted, and I committed while background agents were live.
Recovered within minutes; root-fixed in `ba676157` as stage-then-swap. **Do NOT
restore the rmtree shape.** Two rules earned: never commit while agents are
live, and verify a commit's CONTENTS, not its message.

**A SECOND silent trap in the same family:** `pathlib.write_text` on Windows
translates `\n` to `\r\n`, so my patcher scripts CRLF-ified 134 working-tree
files whose index form is LF. Only the Share byte-compare caught it. Any future
agent patching files with `write_text` reintroduces it - **use `write_bytes`.**

**Three filings corrected, do not re-inherit them.** (1) RM-107's prescribed
"narrow the except" is mechanically impossible - `_lcu_get` swallows the error
itself. (2) RM-101's ~154 HP is an UN-AMORTIZED upper bound, not a coefficient;
shipped at 0.25 = 38.38, and the "reorders a ranking" conclusion was then
MEASURED true anyway (+81.56 EHP, 9 of 138 positions, top-6 swap). (3) RM-108's
"a naive parser reads 0.0" is false - all 56,896 tokens land in display-prose
keys with zero runtime readers, so the detector serves registry AUTHORS.

**Two guards earned their keep.** The changelog guard I wrote this session
caught my OWN bump. The R134 signature guard rejected my OWN wiring (flags
inserted mid-signature). Both fired correctly on their author.

**NEXT: RM-104** (Kaenic mirror 222504) plus the three always-on lifeline
mirrors `226673` / `223053` / `223156` the verifier found carrying the identical
`shield=None` defect. Then the ~28 silent-no-op bare excepts the sweep sized but
did not fix - that population has now produced four silent failures in two
sessions.

---

# 2026-07-19k (R137 - RM-99 Heartsteel shipped, and the number the spec told us to use was wrong because the FEED was frozen)

**A vendored feed sitting in a `16.14.1/` directory is not 16.14.1 data. Nothing
in this repo checks that, and one frozen feed put a wrong coefficient into a spec
that then propagated into ROADMAP prose as fact. The cross-patch hash was the only
thing that could see it.**

Shipped (ENGINE 1.225.0 -> 1.226.0, commit `843f83a3`): `_item_health_stack.py`
crediting Heartsteel 3084 + Arena mirror 223084's permanent-max-HP half behind
DEFAULT-OFF `assume_item_health_stacks`, folded into the three main per-type EHP
numerators next to `passive_health_hp` / `rune_perm_hp`, route-surfaced on `/ehp`,
`/rank-tank`, `/hybrid`, `/rank-bruiser`. Built inline, not with worktree agents -
every edit landed in shared seams (`ehp.py` / `hybrid.py` / `server.py` /
`__init__.py`), so a split would have been all-collision with no parallelism to win.

**THREE spec errors, each caught by reading files instead of prose.** (1) RM-99
says the coefficient is 8 percent. It is 10. `items_meraki.json` is FROZEN, not
lagging: strip `fetched_at` and its body is byte-identical across all five
vendored patch dirs (md5 `5f2ab2ca072637d9`, 16.10.1 .. 16.14.1) despite five
separate fetches - pinned at content patch 25.15, the item-side twin of the RM-81
defect. DDragon `items.json` IN THE SAME DIRECTORY, CommunityDragon 16.14 and the
wiki all read 10, and the wiki's dated `V26.11` note ("increased to 10% from 8%")
predicts the exact 8 -> 10 flip visible between our OWN vendored 16.10.1 and
16.11.1 dirs. (2) "Folded next to `item_bonus_hp_amp_hp`" is under-specified -
there are TWO numerator regions and this term belongs to the permanent-HP family,
which the `_blend_with_heal` mirror does not carry. (3) "Copy R46" is right for
the math and wrong for the plumbing: `assume_passive_health_stacks` never reaches
`rank_items_by_ehp`, `hybrid.py` or `server.py`, so mirroring it ships a lane the
scorer cannot reach. That unreachable population is BIGGER than ROADMAP claims -
`assume_kaenic_shield`, `assume_hsp_amp`, `assume_eclipse_shield` and
`assume_chainlaced_shield` are all compute_ehp-only too.

**Two things deliberately NOT done, both filed instead.** RM-99's secondary clause
wanted `every_n_seconds=3.5` on the damage half fixed "with the same proxy number";
that is a DEFAULT-ON change to shipped scoring that moves live build orders, so it
is RM-99b now. Consequence stated rather than hidden: the two halves of the
Heartsteel model currently disagree about firing rate (~8.57x single-target), and
matching a known-wrong cadence for self-consistency would have made the new lane
wrong on purpose. And RM-105, found by probe while waiting on a regen:
`effective_ehp_with_sustain` understates whenever ANY permanent-HP seam is armed,
because `_blend_with_heal` omits the whole family - measured -618.33 EHP with
`apply_rune_health_grants` ON, -301.42 with R46, -373.24 with this lane, 0.0000 at
defaults. Pre-existing, unguarded (the sustain contract test only asserts equality
at default flags), and it fires exactly when the queued default-ON flips happen.

**Process notes for next time.** The `tests/` background run reported "exit code
0" in its notification - that was `tail`'s code through the pipe, and pytest had
actually failed one doc-drift test. Read the output, never the piped status.
`agents/daemon_slayer/CHANGELOG.md` is missing entries for 1.224.0 AND 1.225.0
despite `__init__.py` mandating the prepend; not reconstructed, because building
them from ROADMAP prose would be inventing history. ENGINE anchors are ~141 hard
assertions across 120 test files - bump them mechanically but filter to
assertion-shaped lines, since 3 occurrences are historical docstring references
that must NOT move.

**Verified this run, nothing carried forward:** DS 8787 passed / 1 skipped / 2461
subtests; `tests/` 11987 passed / 23 skipped / 359 subtests; all 9 regenerated
build-order tables stamp-only (zero non-stamp changed lines); Share 1.226.0
`--check` clean; DS `:8893` live at 1.226.0.

**SECOND HALF - a research thread that found more than the research was for.**
Operator supplied external links and authorized the ToS risk; the SGP route was
probed live and WORKS (RM-106): the LCU mints a session JWT, and the NA host
returns Match-V5-shaped rows for KIWI / queue-2400, 14 of the last 20 games, with
`perks` and `playerAugment1/2` on 153-field participants. But the better find came
from a triage agent, not the links: **`GET /lol-match-history/v1/game-timelines/{gameId}`
on the LOCAL LCU returns 200 with 21 frames and 10 participantFrames for a KIWI
match** (RM-106a) - so the event-mode timeline question is answered YES with no SGP
at all. Caveat priced in: only CHAMPION_KILL + BUILDING_KILL events, NO
ITEM_PURCHASED / SKILL_LEVEL_UP, so it unlocks gold/xp curves and kill maps but not
item or skill order. **And it exposed a live defect (RM-107):** RC's post-game
collector calls a DIFFERENT path that measured 404, inside a bare `except` logging
at DEBUG - invisible for its whole life. That is the THIRD silent-no-op this
session after the RM-100 nightly critic and a `tail`-masked pytest exit code; a
bare `except` at DEBUG is functionally no error handling and this repo has a
pattern of them.

**Two of my own assertions were wrong and caught by verifying:** I claimed ChampR's
in-client item-set writing might be an uncovered gap - RC already does it
(`tools/lcu_agent.py:1040`); and I framed a client-debugger tool as promising when
its own README tells you to stop the Vanguard services. Same failure mode as the
RM-99 coefficient: reasoning from plausibility instead of reading. Three times in
one session.

**THE PROVENANCE SPEC IS RESEARCH, NOT A READY PLAN - do not implement it as
written.** Two workflow passes (38 agents, ~6.2M subagent tokens). Revision 1: 911
lines, 43 audit gaps. Revision 2: 2019 lines, 32 gaps, 3 of 3 lenses NEEDS_WORK.
Findings improved a lot (measured, with resolutions attached - the run-scope
BLOCKER is a real design error caught by replaying commit `544d6362`), but the
DOCUMENT DOUBLED while converging. The operator asked for a guard plus an index
over five dirs, "hours, no network"; what exists is a 7-rule classification ladder
plus run semantics plus a citation-baseline generator plus per-value provenance.
Partly my fault - I specified 9 required sections and ran a 4-way architecture
competition, which selects for elaboration. **Next session should OPEN BY CUTTING
to the real Phase 1**, keeping only the resolutions in
`docs/specs/SPEC_data_provenance_AUDIT_rev2.md` that survive the cut. Do not start
by implementing 2019 lines.

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
