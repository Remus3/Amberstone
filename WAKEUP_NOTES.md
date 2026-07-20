# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

---

# 2026-07-20f - R140 RM-100 consolidation: CLEAN / REFUTED-PREMISE

**Head `60ee6289`. ENGINE-IMPACT NONE** - docs-only Tier-0, no ENGINE_VERSION bump (stays 1.228.0 /
patch 16.14.1), no Share resync, no `:8893` bounce owed. Doc-hygiene guards 13/13 green.

Gemini-loop cycle 2, directive R140: fan out worktree agents to consolidate 5 near-identical local
`_run_coro` / `_run_poll_loop` copies into `tests/_asyncio_isolation.py`. **Nothing was built, because
the work had already shipped one cycle earlier in this same loop run** (R137, `114977ee`).

Refuted on ground truth before any dispatch: `tests/_asyncio_isolation.py` on disk since 03:23
(`run_coro` + `run_coro_capturing_thread`); grep for `def _run_coro` / `def _run_poll_loop` /
`def run_coro` returns ZERO local definitions under `tests/` or `agents/`; all 5 named files already
import the shared runner; `tests/test_asyncio_isolation_guard.py` already blocks a sixth copy and
pins zero bare `asyncio.run(` under `tests/`. Fresh this run: **73 passed in 3.71s**.

**The real defect was the stale prose that manufactured the directive.** `ROADMAP.md:20` still read
"(5 near-identical copies; consolidating them is the open follow-up)" - R137 shipped the code but
never cleared the text, and the director builds its refill digest from ROADMAP prose, so a follow-up
closed in code but open in prose re-picks every cycle. That line now states CLOSED, names the shared
module and both runners, names the 5 migrated files, and cites `114977ee`.

The RM-100 **LATENT half is deliberately left standing**: `tests/snapshot_panels` still leaks
asyncio's per-thread running-loop marker via its `scope="session"` `pw_browser` fixture, so a new
test calling bare `asyncio.run()` on the main thread still fails. Closing consolidation is NOT
closing the leak - do not conflate them.

No subagents / worktrees (R9 inline - the build slice was cancelled by ground truth). PART C durable
steer in `ops/loop/control/gemini_ask.txt`: this loop has now produced several refuted-premise cycles
(R114, R115, R137, R140) from the same lag, so the director is asked to ground "X is still open"
premises in a grep checked THIS cycle rather than digest prose.
