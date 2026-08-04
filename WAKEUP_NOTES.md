# WAKEUP_NOTES - RC hand-off ledger



> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-30, automatic via `scripts/wakeup_prune.py --keep 3` (relocated the RM-118 EHP-ranker session `2026-07-29f`; newest 3 = headless run 2026-07-30-01 `2026-07-30a` + headless run 2026-07-29-01 `2026-07-29h` + RM-118 hybrid-ranker `2026-07-29g`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

---

# 2026-08-04f - RM-38 SHIPPED, RM-36 blocked-with-a-measured-reason (ENGINE 1.272.0)

LEDGER 1192. Picked from the RM-35..RM-48 GAP set as the prior note directed. The
set is much smaller than "14 UNBUILT" reads: RM-37 / RM-44 / RM-46 / RM-48 are
CLOSED, RM-39 / RM-41 / RM-43 SHIPPED, RM-35's two clauses split shipped +
blocked, RM-40 / RM-45 / RM-47 blocked on mage champion-sensitivity. Genuinely
open and headless-actionable: RM-36 + RM-38 (batched) and RM-42.

**Shipped.** `apply_ad_axis_ability_damage` now reaches `rank.rank_items`,
`POST /rank` and `core.daemon_slayer_client.rank_for` - the same term the bruiser
scorer has used since 1.222.0, RELOCATED to `agents/daemon_slayer/_ad_axis_ability.py`
so there is one definition and not two (`hybrid` imports `rank`, so `rank` could
not import `hybrid`; `hybrid` re-binds). DEFAULT-OFF, byte-identical omitted, all
six build-order tables stamp-only, live-verified on `:8860`.

**The finding that decided the session, and it is worth more than the code.**
Ezreal's only PHYSICAL per-spell row is Q Mystic Shot with `ap_pct_sum` 200.0, so
the term's AP-scaling exclusion drops it and his credited sum is EXACTLY 0.0. The
seam is a provable no-op for him. RM-36 therefore is NOT closed by porting the
term - it needs a SPLIT credit for the AD portion of a dual-scaling row, which is
a new design and NOT a widen of that gate. Corki does reorder, so RM-38 is served.
Memory `reference_ad_axis_term_cannot_price_a_dual_scaling_spell`.

**Two stale filings corrected rather than inherited.** The pool half of RM-36 /
RM-38 was already shipped - `exempt_offclass_by_win` and `widen_carry_pool` are
DISJOINT, neither alone admits both Trinity Force and Spear of Shojin, and they
COMPOSE (Ezreal both flags = pool 113, Trinity #4, Shojin #42). And the ROADMAP
row's "all UNBUILT" header was wrong for most of its own table.

**A relocation hazard worth remembering.** Two existing suites stubbed
`hybrid.compute_ability_dps`; after the move that stub no longer bound the live
call target. It failed loudly here, but the same move with a tolerant stub would
have left every row-level assertion passing vacuously.

**Not claimed:** the live eyeball is filed as `G2-46` in
`docs/LIVE_GAME_GATED_SYNC.md`. A default-ON flip stays blocked on RM-98 (whole-game
cast rate summed onto a combat-window auto rate), same as for the bruiser scorer.

Suites at final state, repo root: DS 10378 passed / 6520 subtests; RC `tests/`
18225 passed / 108 skipped. Ruff clean, ASCII clean, drift guard clean.

---

# 2026-08-04e - RM-118 stranded-seam ledger DRAINED to its declined floor (ENGINE 1.271.0)

LEDGER 1191. Picked the top open row in ROADMAP NOW, exactly as the prior note said.

The ledger held 14. Ten are DECLINED BY DESIGN and stay - the 5 target/caster-state
seams (arc operator-CLOSED s232) and the 5 per-item shield opt-ins (operator-gated
live flip pending). The 4 that were real debt now reach their routes AND
`core/daemon_slayer_client.py` in the same slice: `apply_crit_chance_overrides` ->
`/dps`, `apply_ability_hsp_amp` -> `/hps`, `apply_cast_rate_propensity_prior` +
`assume_ms_utility` -> `/hybrid` and `/rank-bruiser`.

**The row was easier than it looked, and the reason is the durable finding.** Three
of the four carried a decline reason that read as a blocker - "needs a measurement
first", "engine-only by design", "an unmeasured second live flip on the same
auto-attack term". All three were about a DEFAULT FLIP. This slice ships route
EXPOSURE, default-off and byte-identical. The counts were right; the reasons were
answering a question nobody asked. Filed as memory
`feedback_decline_reason_goes_stale_before_the_count`: a row's count gets
re-measured every session, its reason never does.

Both prior durables held and both were exercised. Route ownership came from
`inspect.signature` over the whole package, never from a sibling docstring. The
TRANSPORT question was asked separately from the flag - and here the answer was
"none needed", all four being pure booleans over inputs the owning routes already
parse. That is the opposite of the rune and vamp lanes; the CHECK is what
distinguishes them, not the outcome.

Asymmetries are asserted, not assumed: `/rank-enchanter` must never carry the HSP
ability flag, `/rank` must never carry the crit overrides, `/dps` must never carry
either hybrid seam. Emitting any of those manufactures reachability with no reader.

DEFAULT-OFF proven three ways, the third being the useful one: a full regen of all
six committed build-order tables (3 modes x 2 families, 173 champions) whose only
diff is the version stamp. **Note the trap that cost 151 seconds:** the tracked
tables come from `core/build_order_precompute.py` + `core/build_order_variants.py`
(`--mode all --champions all --static`), NOT from
`tools/daemon_slayer_build_orders_generate.py`, which writes a gitignored path and
leaves `git status` clean while printing success. Memory
`reference_build_order_regen_wrong_generator`.

Ledger drains: `STRANDED_TODAY` 14 -> 10; `_UNREACHABLE_OK` 65 pairs / 16 routes ->
59 / 15, the `/rank-bruiser` row emptying entirely. New
`test_stranded_lane_route_seams_rm118.py`, 25 tests / 56 subtests, with a negative
control per seam. Suites fresh from the REPO ROOT: DS 10366 passed / 6520 subtests,
RC 18225 passed / 108 skipped / 0 failed. Ruff clean. Share mirror re-synced at 520
files with its own outward-voice CHANGELOG + README entry. Live on `:8860` after
`taskkill /F /PID` then `schtasks /Run /TN RC-DaemonSlayer`: `/health` 1.271.0 and
all six (route, seam) pairs answer over HTTP with every ON path moving.
