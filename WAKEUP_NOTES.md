# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) + R47 UI-audit cycle 16 (2026-06-30, full in LEDGER 702) archived. Only the last 3 sessions kept here.

---

# 2026-07-02 (OQ18 LOOP - live-input wiring across the DS HTTP boundary; ENGINE 1.168.0 -> 1.169.0)

Loop directive OQ18 executed by this session (head 3d7ce104; commit `3a96c0e3`, LEDGER 740). Wire the producer-only-orphan live inputs across the :8893 HTTP routes so each live-gated eyeball is a pure HTTP flag flip (item-638 pattern). **NO engine-math file changed - server.py only + version stamp** (both `compute_antitank(level=)` + `compute_antitank_live` already accepted the args; OQ18 is pure transport - the directive's "changes live math" framing = the NEW capability, not a math edit).

- **Ground-truth first (grep-before-scaffold):** ramp-seeded anti-tank champs (Aatrox/Brand/KSante/Mordekaiser/Ornn/Renata/Skarner/Urgot/Zed/Zeri) are DISJOINT from the P3.2 seeded champs (Gwen/Vayne) -> the level-ramp seam never perturbs existing P3.2 tests; Heal 7 / Ignite 14 / PtA 8005 / Janna granter all verified against source before the test was written.
- **Scope call:** kept the two anti-tank seams ORTHOGONAL at the route (`item_ids` -> compute_antitank_live P3.2 AP/AD; `level` -> compute_antitank ramp) - NOT coupled inside compute_antitank_live, which would break its "naked build byte-identical to static" contract for ramp champs.
- **Wired (server.py):** /anti-tank +level (R17/R39 ramp, B12) +item_ids/augments (P3.2 live build, B4); 3 NEW additive routes /summoner-fight-adj (DSP5/B31) + /enemy-rune-threat (DSP6/B32) + /ally-protected-ehp (DSP7/B33). Every input DEFAULT-OFF/empty -> byte-identical (test-pinned).
- **TDD** test_oq18_route_seam_transport.py RED 9/11 -> GREEN 11/11. **Verifier CONFIRM 7/7 + byte-identical TRUE.** ENGINE 1.169.0 (pins 108/95, 0 stray) + Share --check green 395 files + DS :8893 bounce (pid 6332 -> 1.169.0). Dual suite DS 7774 / RC 10434, 0 real fail (the RC "1 failed" = live-integration engine_version anchor, GREEN post-bounce - identical to OQ17). Drift guard test_docs_daemon_slayer_drift CAUGHT the missing routes + stale banner mid-run.
- **Handoff:** client-helper emit (core/daemon_slayer_client.py typed helpers for the new routes); the default-ON consumer half (a survivability/draft scorer that CALLS these producers with the live set). Live plumbs stay gated -> LIVE_GAME_GATED_SYNC B31-B33 / B4 / B12 (headless-prep-done).
- Frozen files untouched. CI green baseline held.

---

# 2026-07-02 (OQ17 LOOP - /rank* HTTP-boundary seam transport; ENGINE 1.167.0 -> 1.168.0)

Loop directive OQ17 executed by this session (head da6489c1; commit `e73799f3`, LEDGER 739). Thread the ENGINE-ONLY default-OFF seams across the /rank* HTTP boundary so each live-gated eyeball is a pure HTTP flag flip (item-638 pattern). NO math change - server.py only + version stamp.

- **Plan-agent spec caught 2 premise drifts** (verify-the-premise): R50 apply_all_out_bonus is a load-time AbilitiesSnapshot flag NOT a per-call compute param -> EXCLUDED (not a pure flag-flip, FUTURE); Phase-D "4 non-every-AA on_hit" is not a distinct seam (3 un-routed categories of apply_passive_damage, already /dps).
- **Scope call (R30 precedent):** rune-gate seams DSP4/R51/R53 route to /burst not the ranker - a flat keystone amp washes out of the candidate-baseline delta. This DROPPED the planned burst.py ranker slice; OQ17 = single-file server.py change, main-thread + verifier gate.
- **Wired:** /burst +runes +assume_takedown/assume_ability_amp/score_completion_runes/gate_target_hp_amp/gate_caster_hp_amp/caster_current_hp_pct; /rank-assassin +assume_takedown/assume_squishy_target/assume_ability_amp/target_preset (ranker already forwards); /dps +apply_melee_aa_gate. All DEFAULT-OFF -> byte-identical.
- **TDD** test_oq17_route_seam_transport.py RED 8/12 divergence -> GREEN 12/12. **Verifier CONFIRM 6/6.** ENGINE 1.168.0 (pins 107/94, 0 stray) + Share --check green 394 files + DS :8893 bounce (pid 22732 -> 1.168.0). Dual suite DS 7763 / RC 10435, 0 real fail (the RC "1 failed" = live-integration engine_version anchor, GREEN post-bounce).
- **Handoff:** R50 route wiring (needs per-request AbilitiesSnapshot construction); client-helper emit (core/daemon_slayer_client.py). Live flips stay gated -> LIVE_GAME_GATED_SYNC B2/B3/B6/B7/B18/B19/B34.
- Frozen files untouched. CI green baseline held. Worktree note: C:/RC-CIWatchdog belongs to that scheduled task, untouched.

---

# 2026-07-02 (R58 LOOP - assume_ms_utility seam: MS utility valuation for bruiser/juggernaut; ENGINE 1.166.0 -> 1.167.0)

Loop directive R58 executed by this session (head e7e95653; merge `304c88dd`, slice `9b42acd8`, LEDGER 738). Premise verified FIRST: item MS resolves into stats["ms"] (engine.py:200) but the bruiser/juggernaut scorer consumed it at ZERO (only consumer ability_dps.py:285); DDragon 16.13.1 DMP 3742 + FoN 4401 both 4 pct MS.

- **Seam (hybrid.py ONLY):** DEFAULT-OFF END-appended `assume_ms_utility` on compute_hybrid + rank_items_by_hybrid (spec caught the routing fact: the ranker does NOT call compute_hybrid - both entry points need the flag). `_ms_utility_multiplier` = 1 + min(0.15 cap, bonus_ms_frac * 0.5) - melee attack-uptime model; DPS term only; shared multiplier cancels in the normalized pct; raw dps/delta_dps stay RAW (no Shipwrecker double-count). Worked pin: Darius + DMP + FoN -> 367.2 -> x1.04; zero-DPS FoN gains exactly +0.013 hybrid_delta_pct.
- **Orchestrated:** Plan spec agent (cites re-verified) -> 1 worktree build agent (TDD RED 16F/2P observed -> GREEN 18 tests) -> verifier CONFIRM 7/7 -> sole merger.
- **Ship:** ENGINE 1.167.0 (pins 107/94, 0 stray) + DS bounce (live 1.167.0) + Share --check green 393 files SAME commit; Share/CHANGELOG 1.167.0 prepend + backfilled the MISSING 1.165.0->1.166.0 OQ11 entry; DAEMON_SLAYER banner 1.167.0/7751. Fresh dual suite: DS 7751 / RC 10435, 0 failed.
- **Handoff:** stack-ramp conditional-MS registry (Shipwrecker +20 flat at 100 momentum / Steadfast +6 pct at max stacks) feeds the same seam later. Live default-ON flip -> LIVE_GAME_GATED_SYNC B41 (PRACTICE-SR) + flip-ledger entry.
- Frozen files untouched. CI green baseline held. Worktree note: C:/RC-CIWatchdog belongs to that scheduled task, untouched.
