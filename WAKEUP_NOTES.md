# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

---

# 2026-07-20i - R143 HSP registry: mirror id-space coverage + Moonstone semantic split

**ENGINE 1.229.0 -> 1.230.0 (patch 16.14.1). Tier-2** - Share mirror resynced in the SAME
commit, DS `:8893` bounced onto 1.230.0, build-order precompute regenerated, dual suite green.

Gemini-loop cycle 1. Directive asked for an HSP magnitude + mirror sweep of 7 enchanter items.

**The directive's own axis came back CLEAN.** All 12 committed bare-id magnitudes in
`enchanter_items.json` re-derived from DDragon 16.14.1 - every one already correct. The
`[UNVERIFIED]` "lack correct magnitudes" premise is REFUTED. Two real defects found off-axis.

**Defect 1 - mirror ids returned a silent 0.0.** `_hsp_amp.sum_wielder_hsp_pct` keys on BARE
ids; `core/daemon_slayer_resolver.name_to_id` returns `32xxxx` (mode="sr") and `22xxxx`
(mode="arena") MIRRORS. `_hsp_amp.py:51` missed -> silent 0.0, no raise/log/fallback (R135
fallthrough class). Live-reachable: `coach_integration/_coach.py:300` -> `item_ids` at :318.
Measured 0.22 under mode="sr" vs a 0.88 bare-id control.

**The one-line fix would have been WRONG.** Prefix-strip / normalize is the natural fix and it
ships wrong numbers: mirrors diverge in BOTH directions. Mikael 3222 .12 SR / .15 at `323222`;
Dawncore 6621 .16 SR / .20 at `326621` / .12 at Arena `226621`. Arena also lifts Redemption
.10->.12, Ardent .10->.12, Staff .10->.14. 22 mirror records enumerated explicitly instead.

**Defect 2 - Moonstone 6617: right value, wrong consumer.** Its 0.30 is NOT an HSP stat (catalog
grants none) - it is the Starlit Grace CHAIN-TO-ALLY ratio, which the text says excludes
yourself. `_hsp_amp` (documented as WIELDER self-amp) read it anyway, over-crediting own shield
(`ehp.py:1647`) + own regen (`sustain.py:382`) by +30%. **NOT zeroed** - the same field is
load-bearing for ally throughput at `hps.py:605`. Split via a new `ally_chain_only` bool
appended at the END of `EnchanterItemFormula` (no-mid-class-insert), True for 6617 alone.

**Flagged side effect:** `hps.py:575` gates on `has_item`, so mirror records now resolve there
too and compound into `amp_factor`. Closer to correct (was: no amp no heal; now: amp no heal)
but a real `ds.hps` behavior change riding this bump.

**Bump bookkeeping caught the rest.** RC went 14 red / 7 unique guards, all stamp propagation:
`test_build_order_engine_stamp_sync` x6 (HZ-B precompute is patch-keyed static data a DS bump
leaves stale - regen per the guard's own docstring, 3 modes x 173 champs) +
`test_docs_daemon_slayer_drift` x1 (doc anchor). All 9 green after.

Both defects were latent behind DEFAULT-OFF `assume_hsp_amp` (zero production callers pass
True) - a pre-flip fix, not an incident.

**Don't-redo:** the 12 bare-id magnitudes are SWEPT and CORRECT. Do NOT "simplify" the mirror
enumeration into a prefix-strip helper - magnitudes genuinely differ per id space. Moonstone
6617's 0.30 is CORRECT for `hps.py` - do NOT zero or delete it; it is gated off the wielder
path by `ally_chain_only`, not by its value.

---

# 2026-07-20h - R142 RM-101 residual runes SHIPPED: Second Wind 8444 + Guardian 8465

**ENGINE 1.228.0 -> 1.229.0 (patch 16.14.1). Tier-2** - Share mirror resynced in the SAME
commit, DS `:8893` bounced onto 1.229.0, dual suite green.

Gemini-loop cycle 3. Closes the rune arc R132 opened (resist grants, DENOMINATOR) and R136
continued (health + Heal/Shield-Power, NUMERATOR). RM-101 now has no buildable rune left.

**Premises checked BEFORE dispatch.** All three longDescs re-read from
`data/meta_build/ddragon/16.14.1/runesReforged.json`: 8444 and 8465 buildable as described,
8463 carrying the literal unresolved `@BaseHeal@` - DATA-BLOCKED confirmed, not assumed.

**Shipped, both DEFAULT-OFF, both on the existing `rune_ids` transport:**
- `_rune_self_heal.py` / `apply_rune_self_heal` - Second Wind 8444, 4% of missing health,
  reusing the scorer's own `_MISSING_HP_SHARE_FOR_HEALS` rather than inventing a second
  reading. Discounted 0.6 = `_FIGHT_WINDOW_S / 10s`, derived from two named constants.
- `_rune_shield_grants.py` / `apply_rune_shield_grants` - Guardian 8465, level-lerped 40-150
  plus 6% bonus health, amortized 0.2.

**Neither midpoint inherited the sibling 0.3, and each deviation is argued.** Second Wind
triggers on taking champion damage, which IS the EHP frame's premise - a firing discount
would price in uncertainty the model does not have, so it takes a DURATION ratio instead.
Guardian's 75-40s cooldown is 2x-3.75x Aftershock's, so it fires at most once per fight; 0.2
is the engine's existing value for a reactively popped 1.5s spell shield, which Guardian's
shield literally is.

**Guardian is AP-OMITTED on purpose - a measured ceiling.** `ehp.py` carries ZERO wielder
ability power (all 38 `ap` tokens are `enemy_ap_share`, an incoming damage-type share). The
"+20% AP" term is unrepresentable; omitting it UNDERCOUNTS, which is the safe direction. A
mutation-tested regression class fails RED if a future edit fabricates an AP value. Ally half
omitted for the same frame reason.

**Verifiers mutation-tested the guards rather than reading them**, which is the only reason
the gate meant anything: S1's mutated the `ehp.py` constants and confirmed the convention pin
went RED (proving it is a real cross-module guard, not a literal asserted against itself);
S2's injected an `ap_pct` field and confirmed all 4 AP-omission tests went RED, and opened
`_champion_spell_shield_overrides.py:111` to confirm the cited 0.2 actually exists there.
S1's verifier also caught two miscited docstring pointers (`ehp.py:341` -> `:342`, `:1477` ->
`:791`), both fixed at merge. A cited `file:line` is not proof.

**The R134 signature guard caught a real miss, not just bookkeeping.** Widening it -7 -> -9
surfaced that `hybrid.py` needed the seams threaded too - an ehp-only wiring would have passed
every new test while leaving both hybrid entry points unable to reach either lane.

Green fresh: DS **8944 passed / 1 skipped / 2543 subtests**; R142 trio **78 passed / 25
subtests**; ruff clean; 0 non-ASCII introduced; Share `--check` green at 1.229.0 / 493 files.

Don't-redo: RM-101 is CLOSED for every buildable rune. Font of Life 8463 stays DATA-BLOCKED -
do NOT invent a number. Guardian's AP term stays omitted until `ehp.py` actually carries
wielder AP; the tripwire enforces it.

---

# 2026-07-20g - R141 RM-100 CLOSED: asyncio leak accepted as a priced tradeoff

**Head `bacc559f` (`ba23bae0` is the content commit). ENGINE-IMPACT NONE** - Tier-0 docs +
guard-verify, no ENGINE_VERSION bump (stays 1.228.0 / patch 16.14.1), no Share resync, no `:8893`
bounce owed, no route change.

Gemini-loop cycle 4. This cycle answered the PART-C escalation R140 wrote: R140 closed the
consolidation half of RM-100 and deliberately left the LEAK half standing, so something had to
decide fix-or-accept. **Decision: option (B), leave it LATENT - and the reason is a priced trade.**

The fix has a known shape and a known price: narrow `pw_browser` off `scope="session"`
(`tests/snapshot_panels/conftest.py:246`) and pay a browser launch across ~387 snapshot_panels
tests, permanently. What that buys is bounding a leak that is **already bounded** by
`PlaywrightContextManager.__exit__` (measured py3.14 + playwright 1.59.0, recorded in R137) and that
has **zero live trigger** - no bare `asyncio.run(` calls exist under `tests/` at all. Bad trade.

Accepting a latent bug is only defensible if a test fails the moment it stops being latent. It does,
and it was re-run THIS cycle rather than inherited from the escalation text:
`tests/test_asyncio_isolation_guard.py` = **7 passed in 2.57s**, pinning both invariants (no bare
`asyncio.run(` under `tests/`; no sixth local runner copy).

`ROADMAP.md:20` is now a CLOSED bullet that states the tradeoff, its price, and the guard, with an
explicit do-not-re-pitch. That sentence is the deliverable - it is the same stale-prose failure mode
R140 root-caused, one level up: an open-reading bullet with no verdict re-picks every director cycle.

**One deliberate deviation, logged not silent.** The directive said mark RM-100 fully CLOSED. The
RC-GeminiAudit `0xC000013A` last-run result is still genuinely UNPROVEN (six hypotheses refuted), so
it rides inside the closed bullet as a labelled watch-item. Writing "closed" over an unproven fault
in a living doc is a false claim, and living docs are where false claims compound.

No subagents / worktrees (R9 inline - one ROADMAP bullet, one plan row, one guard run). Fresh
verification: **RC 12290 passed / 23 skipped / 359 subtests in 1325s** (exit 0), ruff clean, zero
non-ASCII bytes on any added line. LEDGER 979.
