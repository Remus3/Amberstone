# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

---

# 2026-07-19g (gemini-loop cycle 2 - DS modelled runes as offense only; defensive resist half now exists)

**The transferable lesson is about how a good agent report can still be wrong.**

The R132 sweep agent that found the rune hole did excellent work: every `file:line`
it cited survived an independent grep, its REFUTEs were all correct, and the
structural gap it identified was real. `ehp.py` grep for `rune|perk|keystone`
returns ZERO matches, `rank.py` returns ZERO, seven live Resolve rune ids return
0 hits across the entire package, and Aftershock 8439 is registered for damage
only with its own formula string admitting "(resist-bonus side not modeled)".

It still got the central formula wrong. It reported Aftershock as
`45 + 75% of Bonus Resists` and dropped the trailing longDesc clause:
"Resistance bonus from Aftershock capped at: 80-150 (based on level)". Building
on the paraphrase would have shipped math that over-credits precisely the
high-resist tanks the feature exists to serve - at level 18 with 150 bonus armor
the uncapped value is 157.5 against a cap of 150. What caught it was re-reading
the raw `runesReforged.json` longDesc instead of the agent's summary of it.

**Rule to carry: when a finding hands you a FORMULA, reproduce the formula from
source before building on it - checking the cited file:line is not the same
check.** Same failure family as the existing DS probe-trap memories, new surface
(paraphrase drift rather than probe-parameter drift).

Second lesson, smaller but sharp: **a test suite can PROTECT the defect it ought
to catch.** R133 found `test_arena_mirrors_credit_same_as_base` asserting
`base == mirror` - which is exactly the "base nominal" seeding bug expressed as
an invariant. The wrong Arena magnitudes were not merely uncaught, they were
pinned. Before assuming a red test means a new break, check what the existing
tests assert about the values you are correcting.

**Shipped:** R132 `e6a84734` (ENGINE 1.223.0 -> 1.224.0) new
`_rune_resist_grants.py` for Aftershock / Conditioning / Unflinching, folded into
`eff_armor` / `eff_mr` behind DEFAULT-OFF `apply_rune_resist_grants`. R133
`ad16ba65` (executor-opened, no bump) corrected three of four Arena / prismatic
mirror magnitudes - 226665 is 40% not 30%, 224401 is 50 MR not 70, 663059 is 10%
not 20% - each re-verified against the raw item index before editing.

**Deliberately not built, spec'd read-only:** RM-99 Heartsteel's permanent-HP
half is pinned at ZERO stacks forever (~43 EHP per proc; ~16.5 procs takes #1 off
Randuin's on Sion) - RM-101 the defensive-rune remainder - RM-102 Warmog's Arena
mirror credited a Vitality passive it does not have - RM-103 Unending Despair's
250% SELF heal uncredited and mislabelled "ally ... utility-only" - RM-104 Kaenic
Arena mirror double-gated out of its own shield. Font of Life is DATA-BLOCKED:
its base heal is an unresolved `@BaseHeal@` template var in live DDragon 16.14.1.
Do not invent a number for it.

---

# 2026-07-19f (gemini-loop cycle 1 - two silent failures closed: the nightly critic and the nightly suite)

**Both failures were invisible to the surfaces we actually watch. That is the
transferable lesson, not the individual fixes.**

**RC-GeminiAudit produced nothing for 28 nights while reading Enabled/Ready.**
`ops/runtime/gemini_last_audit.txt` pinned a worktree-slice sha that never
survived cherry-pick, so `git log <dangling>..HEAD` came back empty and
`tools/gemini_audit.ps1` took its own "nothing to audit" branch and exited 0 -
no review, no log line, `logs/gemini_audit.log` did not exist at all. The
session-start anomaly probe only ever surfaced the unrelated `0xC000013A`.
**Exit 0 is not success and Ready is not health.** Now self-heals to `HEAD~10`
with a loud WARN and logs `START pid=...` unconditionally as its first write.

**The 0xC000013A is a SEPARATE fault, still unproven, deliberately left open.**
Six hypotheses refuted, including my own leading one - InteractiveToken session
teardown died to a same-night control (5 sibling InteractiveToken tasks ran
3:00 through 4:17, all result 0, one of them one second earlier). The task was
NOT re-registered: changing a working ops surface on refuted evidence is churn.
**If it recurs on a later nightly, the marker fix is not the cause - read the
log. START then silence = killed mid-run; no START = died before line 20.**
The task still DISPLAYS `Last Result -1073741510` until the 7/20 run clears it;
that is historical, not live.

**The nightly full-suite had been red for 12 consecutive days** (runs
28935372989 .. 29682372934) and nobody saw it, because the push `check` job is
green BY CONSTRUCTION - it never runs `tests/` as one process, so it cannot
reproduce the pollution. Only the nightly can. **Two unrelated bugs, not one
ordering bug**, which is exactly why both files passed in isolation: Playwright's
session-scoped ProactorEventLoop leaves asyncio's per-thread running-loop marker
set on the main thread (that marker is LIVE - clearing it in conftest makes
snapshot_panels time out, tried and reverted), and the Jhin test depended on a
live `:8893` CI can never spawn (`creationflags=0x08000000` raises on Linux).
Test-side fixes only. **Main is green: 20544 passed, 82 skipped, 2357 subtests,
0 failed** (run 29688982602, dispatched manually since only that job reproduces).

**LATENT, carry forward:** `tests/snapshot_panels` still leaks the loop marker.
Any NEW test calling bare `asyncio.run()` on the main thread and sorting after
it fails identically - use the `_run_coro`/`_run_poll_loop` pattern. Four
near-identical local copies now exist; consolidating them is the open follow-up.

**Process note worth keeping:** both slice agents REFUTED an orchestrator
hypothesis on evidence, and both were right to. They were briefed to verify
premises rather than accept them. Keep briefing them that way.
