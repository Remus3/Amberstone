# WAKEUP_NOTES - RC hand-off ledger

> Older sessions live in `docs/history_notes.md` (append-only archive); per-item ledger in `docs/LEDGER.md`. Newest 3 sessions kept here verbatim. Last relocation: 2026-07-19, automatic via `scripts/wakeup_prune.py` (relocated RM-39 L1 build `2026-07-19c`; newest 3 = gemini-loop cycle 1 silent-failure repair `2026-07-19f` + RM-98 adjudication `2026-07-19e` + RM-39 L2 widen `2026-07-19d`). NOTE: `scripts/wakeup_prune.py` **is FIXED as of 2026-07-19** (`2f35163d`) - its `SESSION_RE` no longer requires a word boundary after the day, so letter-suffixed headers like `# 2026-07-19a` match and the prune works at `--keep 3`. Relocations are automatic again; the prior standing "manual until fixed" instruction is retired.

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

---

# 2026-07-26e - weekly hygiene (unattended)

**Relocated:** none. WAKEUP already at exactly 3 sessions; CLAUDE.md 27KB (under 60KB); no stray ledger entries.

**Memory update (autonomous):** `project_codebase_audit_clean_baseline.md` - removed stale "Game-PC MCP :8892 required for web/ fixture audit" clause (Game-PC retired ADR-011; correct path is Legion :8888 + headless audit via [[feedback_phase3_fixture_ritual]]).

**Anomaly triage:** all 19 RC-* tasks in expected states. RC alive, DS :8893 alive patch=16.14.1, LCU Offline (no game in progress). No actionable anomalies.

**Flags for operator (judgment calls - no action taken):**

1. `_next_session_snapshot_card_build.md` in memory dir: player-snapshot card SHIPPED (PR #6, LEDGER 782). Handoff memo is consumed. Safe to delete.
2. `_handoff_competitor_deep_research.md` in memory dir: main research EXECUTED 2026-07-05. Lolmath SELECTIVE-SAVE DS-knob coverage check marked "still queued" at bottom but is NOT in ROADMAP. Clarify: still wanted, or abandon?
3. `feedback_gamepc_league_fullscreen_lockup.md` in memory dir: Game-PC RETIRED. Advice names dead infra (Parsec + Duet adapters on Game-PC). Delete or retarget to Legion virtual-display guidance?
4. `project_out_of_game_spatial_brand.md` in memory dir: parked worktree files (pseudo_screen_overlay.py, rofl_stats_backfill.py) are merged to main. Theme work (Hextech-Unified + Deep Terminal, palette pick) status unclear - resolved or still pending?
5. CLAUDE.md "TDD First" section: stale suite counts (DS 9546 / RC 13061, dated 2026-07-25). Current from 2026-07-26d: DS 9783 / RC 13115. Approve CLAUDE.md touch to update?

---

# 2026-07-26d - the directive asked for a sweep that was already closed (R193, gemini loop cycle 3)

ENGINE **1.254.0 -> 1.255.0**, patch 16.14.1. HEAD `9fde56bb`. Three worktree
slices on disjoint file sets, Claude sole merger, read-only verifier gate before
every merge. Suites fresh AFTER the last edit: DS **9783 passed / 1 skipped /
4653 subtests**, RC `tests/` **13115 passed / 106 skipped / 460 subtests**.

**The first deliverable was refusing the stated scope.** R193 asked for base
lifesteal magnitudes + Arena/ARAM mirror parity on the six headline vamp items -
R181 verbatim, which measured ZERO DRIFT and left a 15-test guard on disk, with
Bloodthirster's Ichorshield, Shieldbow's Lifeline and Riftmaker's omnivamp all
already modelled. Re-running it would have produced a confident CLEAN and no
value. Three read-only recon agents were aimed at what R181 did NOT cover - the
vamp math model, the wider sustain family's magnitudes, and route reachability -
and every one came back with a real defect.

What landed:

- **hydra_cleave had desynced and the suite was defending the bug.** Ravenous
  Hydra 3074 / 223074 modelled Cleave at 0.35 total AD; Meraki 16.14.1 reads
  40%; the two siblings with byte-identical Meraki text were already at 0.40.
  Two tests asserted Ravenous scores BELOW its own siblings - a stale
  coefficient frozen as a feature. Sibling sweep then caught Tiamat 3077 at
  0.50, likewise pinned. Fixing only 3074 would have repeated the
  narrow-first-fix pattern of items 208/213.
- **Neither fix moves a shipped build table, and that was measured** - all four
  families regenerated full-roster across BOTH keyspaces, every diff is the two
  stamp lines. Cleave only fires at `targets_in_rotation > 1`; the tables are
  single-target.
- **DEFAULT-OFF `assume_crit_weighted_vamp`** - the vamp heal pool priced
  lifesteal off an auto-attack that never crits. OFF byte-identical (verifier
  re-measured against main, full result-dict md5 match), ARMED x1.7875 on Jinx
  L16, exact no-op at zero crit. It moves `blended_ehp`, so the flip is
  operator-gated.
- **`assume_max_stacks_omnivamp` was stranded** - zero occurrences in
  `server.py`. Now on `/ehp` + client keyword. **Both reachability guards were
  green the whole time and structurally cannot see this class**: they enumerate
  keys `server.py` already parses, so a never-parsed kwarg never enters the set.
  A green seam guard is evidence about parsed keys, not about capability.

**The verifier gate paid for itself again.** It BLOCKED slice B on a real
regression (`test_rune_resist_signature_convention_r134.py`) that neither of
that slice's own test scopes collected, so the slice's green claim was true and
insufficient. It also found corrupted git indexes in two worktrees (phantom
staged deletions, files intact) and proved every committed blob matched disk.

Three RC-side failures at the end were mine and are fixed, not waived: the
Share README release-history is a SEPARATE site from the auto-restamped header,
and the new route test imports the host-only client by design so it needed
registering in `ds_share_sync._HOST_DEPENDENT_TESTS`.

Next session: RM-116 (a) ranker-lane forwarding of the omnivamp flag, (b)
Sundered Sky 6610 overheal-to-bonus-health, (c) lifesteal credit on Ravenous
Cleave/Crescent. Do NOT re-commission a vamp base-magnitude sweep - closed
twice now.
