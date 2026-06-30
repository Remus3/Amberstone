# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) archived. Only the last 3 sessions kept here.

---

# 2026-06-30 (R47 headless cycle 16 - 5-phase UI audit of the 4 PGR child panels; 2 sub-floor fixes + a floor guard; Tier-1 CSS-only)

Gemini-directed headless loop cycle 16 (from directive.md; operator-triggered). UI audit, ENGINE-IMPACT NONE. Full detail in LEDGER 702 + ORCHESTRATION_PLAN R47.

- **Scope.** C3 (item 332) audited the parent last_match.js/css but left the 4 PGR child panels (`web/{js,css}/panels/pgr_build_wpa`, `pgr_lane_compare`, `pgr_loadout`, `pgr_winprob`) un-audited. R47 is that 5-phase fixture audit (STRUCTURE/TYPOGRAPHY/HIT-TARGETS/ASCII/HIERARCHY vs `docs/UI_SCALE_SPEC_V2.md`).
- **Method.** 4 parallel read-only audit subagents (one per panel) + an orchestrator ground-truth grep cross-check (non-ASCII + font-size + pointer/hit-min). One subagent FLAKED (hallucinated the game-monitor skill's live-state gate instead of auditing) -> re-audited that panel inline per never-trust-a-flaked-subagent.
- **Findings.** 3 panels 0 MUST-FIX (fully tokenized, pure-display, 0 non-ASCII). 2 sub-floor hardcodes, both resolved in-slice: `pgr_loadout.css:133` `.pld-aug-name` 13px inside `@media(max-width:900px)` -> REMOVED (base `var(--fs-xs,16px)` applies; the column stack, not a font shrink, is the anti-clip; operator monitor fixed 1920x1080 so it never rendered); `pgr_winprob.css:86` `.pwp-ylab/.pwp-xlab` 11px inline-SVG chart-axis labels -> KEPT + inline operator-exception rationale (chart-density; 16px would crowd the 180px curve; R40/item-184).
- **Deliverable + verify.** New `tests/test_pgr_child_panel_floor_guard.py` (8 tests, RED-first - flagged both offenders -> GREEN). Read-only verifier CONFIRM 4/4. Full RC suite `tests/ --ignore=tests/daemon_slayer` 10136 passed / 0 failed (+8). CSS-only asset-hash reload (ADR-008); no RC restart, no ENGINE/DS/Share.
- **NEXT.** PGR dashboard pixel capture OWED (Chrome surface retired 2026-06-27 overlay-only + PGR not in overlay + no live game; baseline render byte-identical). Commits `c5f0cf3d` (slice) + `7f800a4d` (docs). Resume the headless loop.

---

# 2026-06-30 (R46 headless cycle 15 - DS schema lift: STACKING permanent max-HP passives (Sion W / Cho'Gath R / Swain P); ENGINE 1.159.0 -> 1.160.0)

Gemini-directed headless loop cycle 15 (from directive.md; operator-triggered). DS schema lift. Full detail in LEDGER 700 + ORCHESTRATION_PLAN R46.

- **A NEW survivability axis + the SECOND EHP-NUMERATOR term** (after the revive multiplier): champion passives granting PERMANENT bonus max health PER STACK, not in the resolved stat block so neither EHP scorer saw them. Premise was correct + not-yet-on-disk (the named module did not exist); no premise correction needed.
- **Ground truth (vs `data/daemon_slayer/16.13.1/champion_abilities.json`):** Sion W Soul Furnace "+4 bonus health per kill (+15 large/champ)"; Cho'Gath R Feast per-stack health = parsed "Bonus Health Per Stack" damage_block `[80,120,160]` by rank; Swain P "+15 bonus health permanently per Soul Fragment".
- **Module + seam (`2b3f8d38` feat).** New pure `agents/daemon_slayer/_passive_health_overrides.py` (`passive_health_stack_hp` + 3 seeds). `compute_ehp` gains END-appended `assume_passive_health_stacks=False`; True adds the per-champ bonus max-HP RAW to every per-type numerator (phys/mag/true) like `ext_flat_hp`/`flat_mit_*`. Per-stack HP EXACT Meraki; the assumed STACK COUNT by level is a CONSERVATIVE midpoint (LOW 18-entry curves; Sion +15-upside omitted) - never over-states.
- **DEFAULT-OFF byte-identical** (flag False -> 0.0 -> identical to 1.159.0; no live consumer passes it; unregistered champ 0 even ON).
- **Tier-2.** TDD RED-first `test_passive_health_overrides_r46.py` (RED import-fail -> GREEN 18). Read-only verifier CONFIRM 7/7 (fresh DS 7658; OFF byte-identical Sion L11; ON strictly > OFF all 3 axes; Garen ON==OFF; Meraki `[80,120,160]`; ruff/0-stray clean). ENGINE 1.159.0 -> 1.160.0 (93 files / 106 pins, 0 stray) + DS `:8893` bounce (PID 6972 -> live 1.160.0) + Share `--check` green (385 files) + banner 7640 -> 7658 SAME feat commit. DS 7658 pass / RC 10128 pass (9 mid-bump Share/doc/live drift failures cleared post-sync+bounce, re-run 43/43).
- **NEXT:** live default-ON flip EXCLUDED (no live per-champ stack feed; scorer reads a conservative assumed curve) -> `docs/LIVE_GAME_GATED_SYNC.md`. Resume the headless loop.

---

# 2026-06-30 (R45 headless cycle 14 - DS schema lift: percent-of-resist LOW-HP DOUBLED tier (Poppy W); ENGINE 1.158.0 -> 1.159.0)

Gemini-directed headless loop cycle 14 (from directive.md; operator-triggered single cycle). DS schema lift. Full detail in LEDGER 699 + ORCHESTRATION_PLAN R45.

- **Premise correction (spec subagent + my independent re-verify of every cite).** The item-268 percent-of-resist mode already credited Poppy W +12% of TOTAL armor/MR + Rell W +15% of BONUS; the directive's "Poppy 10%/20%, Rell 10%" numbers were WRONG vs Meraki 16.13.1. The ONE genuine gap = Poppy "doubled to 24% below 40% max HP" (omitted at `_passive_resist_overrides.py:407`). Rell was already correct - untouched.
- **Seam (`22dca695` feat).** `PassiveResistEntry` gains 3 END-appended fields (`low_hp_pct_armor` / `low_hp_pct_mr` / `low_hp_threshold`, default 0.0 dormant); `resist_grants` gains keyword-only `caster_current_hp_pct=1.0` (END) + an INCREMENTAL low-HP branch inside the percent block (base 12% + incremental 12% = 24% when caster HP < threshold); `compute_ehp` + `compute_hybrid` thread it (forward-only). Poppy seeded 12/12/0.40.
- **DEFAULT-OFF byte-identical on two axes:** `apply_passive_resist=False` short-circuits; `apply_passive_resist=True` at the default full-HP 1.0 leaves the low-HP branch dormant (1.0 not < 0.40) = identical to 1.158.0. No live consumer passes the kwarg.
- **Tier-2.** TDD RED-first `test_passive_resist_low_hp_tier_r45.py` (RED 15-fail -> GREEN). Build agent (main tree) + read-only verifier CONFIRM 6/6 (independent `resist_grants` math 0.24*200=48.0; Rell + unseeded byte-identical; scope clean). ENGINE 1.158.0 -> 1.159.0 (92 files / 105 pins, 0 stray) + DS `:8893` taskkill (PID 11308) / relaunch (live 1.159.0) + Share `--check` green (383 files) + DAEMON_SLAYER.md banner 7621 -> 7640 SAME feat commit. DS 7640 pass / RC 10128 pass.
- **NEXT:** live default-ON flip EXCLUDED (the EHP scorer never reads caster HP) -> `docs/LIVE_GAME_GATED_SYNC.md`. Resume the headless loop.
