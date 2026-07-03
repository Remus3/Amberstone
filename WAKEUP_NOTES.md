# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) + R47 UI-audit cycle 16 (2026-06-30, full in LEDGER 702) archived. Only the last 3 sessions kept here.

---

# 2026-07-03 (R68 LOOP - Thornmail/Bramble item Thorns reflect; ENGINE 1.175.0; R49 seam gains an item path)

Loop cycle 6. Director picked residual #2 from the R66 list (Thornmail item-reflect); directive's "ENGINE_VERSION in server.py" corrected to `agents/daemon_slayer/__init__.py:18`. Premise verified vs vendored Meraki 16.13.1: 3075 = 20 + 10% BONUS armor magic per incoming AA + GW; 3076 = 10 flat. Shipped the small schema lift: item-keyed registry in `_passive_reflect_overrides.py` (3075/223075/323075 + 3076; 223076/323076 absent from pool, guarded), END-appended `caster_bonus_armor_pct` field + kwarg, dps+burst fold strongest owned Thorns item (dedup one credit) under the existing default-OFF `assume_passive_reflect`. Champion path (Rammus) byte-identical. TDD RED-first 31 tests; slice `404f855b`, merge `59cd622e`; verifier CONFIRM 9/9; HZ-B regen first-try stamp-only (default-OFF seam - orders byte-identical); DS :8893 live 1.175.0; dual suite DS 7874 + RC 10467, 0 real failures; Share 403 --check green (ingest bundle rebuilt on main). No live flip - seam row extended.

**Process notes:** (1) 3rd worktree-index corruption ROOT-CAUSED: the post-commit gist hook inherits GIT_DIR and its `git add -A` hits the committing worktree's index - spawn-task chip filed for the hook fix (commit/disk unaffected; `git reset --mixed` repairs). (2) Controller cycle deadline 5400s < Tier-2 wall-clock - breached once mid-suite, stall-recovery /diagnose injected, diagnosed not-a-hang, recovered in-cycle; consider raising cycle_deadline_sec for ds-sweep Tier-2 directives. (3) RC suite teardown ERROR = RF5 hermeticity guard catching the LIVE controller.log append mid-suite (external writer, not a test) - expected while the loop runs suites concurrently with the controller.

---

# 2026-07-03 (R67 LOOP - Terminus Juxtaposition 3-stack Dark pen; ENGINE 1.174.0; residual-list pick worked)

Loop cycle 5. Director picked FROM the R66 residual list as instructed (no re-scan, no stale-digest premise) - the loop-health fix from R66 held. Premise verified vs vendored Meraki 16.13.1: Juxtaposition Dark = 10% armor+magic pen per stack x3 = 30%/30%; registry pinned 1 stack while citing the BC full-stack convention. Shipped SR 3302 + Arena 223302 pen 0.10 -> 0.30 ungated (plain data correction). Light-side caster resists (6-8 armor+MR x3) = schema lift (no item-keyed resist-grant path) -> BACKLOG tail, not built blind. TDD RED-first 14 tests (`test_terminus_juxtaposition_r67.py`); slice `5331c62f`, merge `34255183`; HZ-B regen both generators full-roster OQ19 recipe FIRST TRY (no shrink); DS :8893 live 1.174.0; dual suite DS 7843 + RC 10467, 0 failed; Share 402 files --check green.

**Process note (2nd occurrence):** the worktree build agent's INDEX corrupted again (4133 staged deletions, disk==HEAD blobs) - verifier caught it; merged the commit sha directly, never the worktree state. If a 3rd worktree index corruption appears, root-cause the worktree tooling (same-worktree races memory `feedback_cc_session_perf`).

---

# 2026-07-03 (R66 LOOP - Guinsoo Seething Strike cond-AS; ENGINE 1.173.0; saturation-claim REFUTED by adversarial workflow)

Loop cycle 4. Directive named 3 "unmodeled" passives (Kraken/Statikk/Hydra) - ALL already modeled (stale-digest family R63/R64). Instead of a 4th CLEAN no-op: scan agent claimed the damage registry SATURATED; a 3-lens adversarial refute workflow (absent/partial/drift) DISPROVED that with 8 cited findings. Shipped #1: Guinsoo 3124 + Arena 223124 `bonus_as_conditional=0.32` (Seething Strike 8%x4, Meraki 16.13.1) on the existing R42 ungated lane - PART C sync gemini ruled NO new seam (Yun Tal no-flag precedent + sec-12); no live-flip row, B44 spot-check appended to LIVE_GAME_GATED_SYNC instead. ENGINE 1.172.0->1.173.0, 95 pin files, Share 401 files --check green, DS :8893 live at 1.173.0. TDD RED-first 9 tests; verifier CONFIRM 10/10; merge `d79ebcb6`.

**Gotcha re-learned (now also in ORCHESTRATION findings):** HZ-B regen after a bump MUST pass the full 173-canonical roster to BOTH generators (`core.build_order_precompute` + `core.build_order_variants`, `--static --mode all --champions <csv>`); the build agent's first regen used the 10-champ SEED default -> 18 axis-parity tests failed on EMPTY orders. OQ19 (221922c5) is the recipe commit.

**Residuals for future ds-sweep cycles:** BACKLOG "DS registry residuals - R66" (Terminus 3-stack under-count top; Thornmail item-reflect; Rocketbelt/Everfrost DSV6 fits; Zeke's/Hollow Radiance/shield-lerp LOW). Director should pick FROM that list, not re-scan.

---

# 2026-07-02 (LIVE-GATED DRAIN - practice SR + ARAM Mayhem; prep-audit + a real ranged-only build bug found live)

Operator-played drain of `docs/LIVE_GAME_GATED_SYNC.md`. Probed no game -> ran the headless PREP phase first: an orchestrated 4-slice read-only audit found the headless prep surface FULLY EXHAUSTED (all 7 OQ17/OQ18 DS routes LIVE-VERIFIED WIRED-OK @1.171.0 via differential POST probes; doc rows current; Phase-D B2 = defer-needs-game). Committed the prep-audit doc sync (`28edea2a`) + cleaned 2 stale worktree-wf branches (content proven-superseded in main).

Then the operator played 2 games:
- **Practice SR (Kai'Sa champ-select -> Irelia in-game):** A1 PASS (RuneWriter lockfile-rotation reconnect after a mid-session League restart, 27f99a95 proven live), A7 PASS (PRACTICETOOL mode-correct rune push), B21 PASS (drake events Fire@403s/Earth@722s), B22 PASS (inhib@702s), B8/R7 eyeball (Irelia +23% at full stacks = sane).
- **ARAM Mayhem q2400 KIWI (Viego):** A7/E12-L2 PASS (KIWI mode-correct + re-detect on bench-swap), A6 (fast bench-swap re-push), C13 (enemy_spells captured vs a real comp).

**FINDING 1 (real bug, fix built + code-gated, DS-batch DEFERRED to game-end):** DS /rank recommends the RANGED-ONLY Runaan's Hurricane (3085) for MELEE champs - reproduced live on Irelia (#5 SR) + Viego (#8 ARAM). rank.py had no purchasability gate (B1 apply_melee_aa_gate only zeroes bolt DPS, default-OFF). Root-cause fix built in worktree `worktree-agent-abebb195a5e02b357`: `RANGED_ONLY_ITEM_IDS={"3085","223085"}` gated at the shared `_filter_candidates` chokepoint across all 7 ranker lanes; melee=attackrange<=250 (fails CLOSED); 15 RED->GREEN tests; ruff clean; no frozen files; RFC 3094 / Statikk 3087 verified NOT restricted (kept). Backfill correctly none (ephemeral compute). NEXT-SESSION / GAME-END: merge -> ENGINE 1.171.0->1.172.0 -> HZ-B regen -> Share sync -> DS :8893 restart -> full dual suite -> live-verify Viego /rank excludes 3085. Deferred mid-game to avoid a coach blip + CPU contention with the live ARAM game.

**FINDING 2 (needs settled-state confirm):** `cs_archetype_pick` looked STALE in ARAM champ-select (stuck on "Kalista" while the champ cycled Veigar->Viego->Swain; locked=234 Viego). Re-probe on a settled champ-select before root-causing.

Full drain record + still-open rows (A2 spell-push, A8 panels, B1 build-chooser, B23/B24 overlay, E1/E2 physical, C2 comp_verdict) in `docs/LIVE_GAME_GATED_SYNC.md` live-flip ledger (2026-07-02 DRAIN SESSION entry). Verifier subagent was running the fix's dual suite at wrap; fold its verdict in at game-end before the merge.
