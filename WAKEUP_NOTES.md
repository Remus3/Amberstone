# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-06-02 - item 266 (/headless-upgrade RUN 2): Haiku-elim WAVE 3 wired+validated+rendered + GATE FINDING (no ENGINE bump, no restart)

HEAD `cb46386` (7 commits incl 3 merges). ENGINE 1.94.0 UNCHANGED, DS :8893 + RC pid 324 NOT restarted (new dashboard module loads on next /api/state; ADR-008 auto-serves web/*). CI green run 26822121720. RESUME of item-265 wave 3 (rate-limited at 0 tokens last run).

GATE FINDING (the run's headline - the matchup engine is the LLM-trade-judgment substitute, so its predictive validity gates flipping a coach off Haiku):
- gold-at-10min agreement 48.8% L6+L9 (Wilson [46.9,54.0], n~2773) = COIN-FLIP.
- solo-kill duel 51.3% L6 / 52.0% L9 (Wilson STILL brackets 0.50, n~1278) = faint, NOT significant.
- any-kill ~50%.
VERDICT: the Lane A matchup engine carries no statistically significant signal vs real outcomes. Per section 4b "do not flip blind" -> NO coach flipped off Haiku. The matchup-derived A/B chips stay a SECONDARY surface; the correct-by-construction CALLOUTS (objective/spike timers) + LEAD (CS/gold/level/kda deltas) are the VALID Haiku-elim wins and are now wired+rendered.

SHIPPED (6 slices, all disjoint; 3 parallel worktree agents wave 1, then de-bias+trade inline + 1 bg agent wave 2 after a transient server-side rate-limit at 0 tokens):
- W3A `85be547` (merge): NEW `dashboard/_deterministic_coaching.py` (`compute_deterministic` maps coach+`lc.enemy_team`->game_state, orchestrates laning_choices/next_callouts/project_lead, TTL-cached 3s monotonic evict>64 so matchup() to :8893 stays OFF the 500ms poll, fail-soft) + `dashboard/_state_builder.py` choices deterministic-FIRST (resolve_choices: laning -> native -> synth) + 2 NEW /api/state keys `callouts`+`lead_projection`. Chips render via the EXISTING `#rn-choices` UI unchanged. +23t.
- W3B `603fb5c` (merge): NEW `tools/replay_matchup_validate.py` (rewind_history.db 614 SR replays, pairs same-team_position, compute_matchup in-process vs lane-gold-at-10min). +15t.
- W3C `caeaa80` (merge) + de-bias `a0d3276`: NEW `tools/daemon_slayer_pickban_targets_generate.py` + `data/daemon_slayer/16.11.1/pickban_targets.json` (172 champs, 29k in-process matchup calls) + `core/pickban_targets.py`. RAW net_swing collapsed every champ's counters onto the same global bullies (Renekton/Fiddlesticks everywhere) -> DE-BIASED by candidate global dominance colmean(B): counters sort `swing(B,A)-colmean(B)`, good_against `swing(A,B)+colmean(B)`, de-bias in the SORT not a hard cut. Lists now per-champ-specific (Yasuo<-grapplers, Garen<-mages, Caitlyn<-dive; 0/5 Lux-vs-Garen overlap). +23t.
- W3B-trade `bd8e5e1`: harness `--ground-truth {gold,trade,both}` adds the solo-kill duel differential from timeline_events CHAMPION_KILL (the DIRECT 1v1 test the chip claims vs the noisy gold proxy). +6t.
- W3E `187f330` (merge): NEW `web/js/panels/callouts.js` (renderLead+renderCallouts, idempotent sig-dedup, fail-soft, ETA Mm:Ss/NOW) + `web/css/panels/callouts.css` (@import, v2.1 tokens) + `#rn-lead`+`#rn-callouts` mounts in index.html + main.js applyState wire. +21 panel-DOM t.
- Share mirror synced `cb46386` (pickban_targets.json into Share/src; --check drift guard turned CI green).

Cost/latency 7-lever sweep CLEAN (L1 16 cache_control / L2 24 _CACHE / L3 tightest 500ms no sub-500 NET; the W3A matchup() is local :8893 free + TTL-3s gated to live games, NOT a regression / L4 10 suppress 0 trailing-space / L5 haiku floor + sonnet/opus = telemetry+charter only / L6 17 RC-* / L7 CSS parity 4/4).

Don't-redo: (a) matchup engine = NO-signal vs real outcomes - do NOT re-pitch flipping the prose coach onto it; a fidelity lift (item-aware + real-level) is operator-gated + LIKELY A MODELING CEILING (a 1v1 burst+ehp model cannot capture lane macro/ganks/skill). (b) the CALLOUTS + LEAD are correct-by-construction Haiku-elim wins, now wired+rendered - lean on these, NOT the matchup chips. (c) the `compute_deterministic` TTL cache keeps matchup() off the 500ms poll - do NOT remove it. (d) build coaching is ALREADY Haiku-free (curated loadouts + Lane B build_orders); champ_select pickban-DB flip needs a counter-quality validation first - do NOT flip blind. (e) pickban de-bias is in the SORT (sign-filter on real beat, colmean-adjusted rel); entries carry both raw net_swing + rel; `--check` drift guard green; the Share/ mirror MUST be re-synced when a data/daemon_slayer/<patch>/ file changes (ds_share_sync --check is a CI gate - this run's base wave was red until the mirror landed). (f) `ops/runtime/matchup_validation*.json` gate artifacts are gitignored runtime (NOT committed).

OWED (live/operator-gated): W3E callouts+lead VISUAL capture - Game-PC MCP :8892 is DOWN post-1PC, code-side 5-phase UI-audit + 92 tests stand. NEXT (operator-gated): matchup-engine fidelity lift (uncertain payoff) OR pivot Haiku-elim to the non-prediction surfaces (callouts/lead/build-orders already shipped) ; overlay Lane D (Electron Phase 2, needs Game-PC visual) ; champ_select pickban-DB flip after a counter-quality validation. Synopsis: Desktop/RC_HEADLESS_SYNOPSIS_2026-06-02.md.

---

# 2026-06-02 - item 265 (/headless-upgrade): Haiku-elimination FOUNDATIONS (ENGINE 1.94.0)

HEAD `f977c0d` (5 merges + 2 fixes this run). ENGINE 1.93.0 -> 1.94.0, DS :8893 restarted 1.94.0, DS 6045 -> 6056, RC +118 new tests, CI green (run 26804451116), Share re-synced 1.94.0. RC NOT restarted (new core/ modules load on next coach tick).

SHIPPED (PRIMARY north star = zero live Haiku via precomputed DS lookups):
- Lane A `agents/daemon_slayer/matchup.py` `compute_matchup` -> verdict {all_in,trade,back_off,even} + net_swing; NEW `/v2/matchup`. The deterministic trade-judgment substitute. +13 DS tests.
- Lane B `tools/daemon_slayer_build_orders_generate.py` -> `data/daemon_slayer/16.11.1/build_orders_{sr,aram,arena}.json` (516/516 cells). FIX: generator must pass BOTH enemy_ad_share + enemy_ap_share (engine rejects sum>1.0; ad_heavy 0.7 was returning empty for 74 champs).
- Lane C `core/laning_verdicts.py` (matchup->CoachChoice) + Lane E `core/event_callouts.py` + Lane P `core/lead_projection.py`. Pure, fail-soft, NOT wired into coaches yet.

DON'T-REDO: compute_matchup is the trade engine (do not reimplement); build_orders generator passes both shares; the 3 generators are not yet wired live.

NEXT (wave 3 - hit server-side rate-limiting at 0 tokens mid-dispatch, /done fired; REDO next session): W3A wire deterministic choices+callouts+lead into `dashboard/_state_builder.py` (TTL-cached, fail-soft, deterministic-FIRST choices, byte-identical out-of-game) ; W3B replay-validation harness (rewind_history -> matchup verdict agreement = the GATE for flipping a coach off Haiku) ; W3C Pick&Ban targets DB. Then validate-via-replay BEFORE flipping any coach choices off its live Haiku call (section 4b: do NOT flip blind); frontend slice (visual proof + UI-audit) for callouts/lead; overlay Lane D. Synopsis: Desktop/RC_HEADLESS_SYNOPSIS_2026-06-02.md.

---

# 2026-06-02 - item 264: DS GAP-2 effects-text RESIST-STAT grant registry + 6 seeded (ENGINE 1.93.0, DS restarted + live-verified, RC NOT restarted)

Operator "start the next DS schema lift and exhaust it then /done". Pre-flight: clean tree, main, item 263 last shipped, DS 1.92.0. Item 262 declared the survivability TRIAD (heal/shield/DR) scorer-COMPLETE; gap-plan named items + item-257 "LAST named clean headless DS item" all done. Found the genuinely-next clean lift by reading item 261's OWN exclusion list: "RESIST-STAT grant (bonus armor/MR, a DIFFERENT axis than a damage multiplier)" was a documented NEGATIVE = the FOURTH survivability axis, unmodeled.

SHIPPED `c3ee4a0` (ENGINE 1.92.0 -> 1.93.0): NEW `_passive_resist_overrides.py` (sibling of `_passive_mitigation_overrides.py`) - `PassiveResistEntry` (armor+mr flat-or-per-level + conditional_probability + level_scaled) + `resist_grants(champ, level, apply) -> (bonus_armor, bonus_mr)`. `compute_ehp(apply_passive_resist=False)` adds grants to armor/mr BEFORE `_armor_factor` (NOT a DR multiplier - the resist add RAISES the denominator directly; the two compose). +2 EhpResult fields (reported armor/mr stay the resolved stat; grant surfaced separately) + to_dict + note. Threaded through BOTH EHP-bearing scorers in ONE item: rank_items_by_ehp + /ehp + /rank-tank + compute_hybrid + rank_items_by_hybrid + /hybrid + /rank-bruiser.

SEEDED 6 (4 permanent + 2 active, exact 16.11.1): Garen W 30/30 cap, Wukong P 6:10 armor-only level_scaled, Shyvana P 5/5, Sejuani P 10/10 in-combat (prob 1.0); Gwen W 22/22, Pantheon E 5:30 level_scaled (active, amortized `_ACTIVE_RESIST_PROB=0.3`). EXCLUDED documented NEGATIVES: value-not-in-text (Olaf R/Rammus W/Kennen R/Nasus R/Hecarim W/Malphite W/Singed R/Taric W/Graves E), percent-of-resist (Poppy W/Rell W), form-gated gate-dependent (Jayce R Hammer), resurrection (Anivia P), per-stack unbounded (Thresh P), ball-attached (Orianna E).

KEY FINDING (honest, DIFFERS from item 261 DR): a flat resist add goes through the NON-LINEAR `_armor_factor`, so unlike DR (uniform multiplicative scale, rank-INVARIANT) a resist grant is NOT uniform -> the item-rankers CAN re-rank flag-on (armor item worth marginally less to a champ with innate armor). Correct, not a bug.

Verified: DS suite 6013 -> 6043 (+30 = new file, 0 failed); ruff clean; 0 non-ASCII added; +30 tests `test_passive_resist_overrides_item264.py`; Share re-sync 267 files --check clean + authored 04/05/CHANGELOG semantic updates (gist auto-pushed 276 files); DS restarted PowerShell taskkill + schtasks -> /health 1.93.0/16.11.1/172/705; live /ehp Garen off 2483.46 / on 2948.44 (+30 armor/MR, reported armor 74.855, resist_armor 30.0), Caitlyn (no entry) flag-on byte-identical, default OFF byte-identical; CI green run 26800841051. Operator was MID-GAME (ranked SR InProgress) during wrap - RC never restarted (DS engine + tests + Share + docs only).

Don't-redo: resist grant raises the armor/MR denominator DIRECTLY (do NOT route through the DR registry); it DOES re-rank flag-on (correct, non-linear curve); reported EhpResult.armor/.mr stay the resolved build stat; default apply_passive_resist=False byte-identical (do NOT flip default-on without live validation = Phase D); the EXCLUDED classes need NEW schema seams (value-not-in-text = "read the parsed block" lift; Poppy/Rell = percent-of-resist mode). The FOUR survivability axes (heal/shield/DR/resist-grant) are now COMPLETE across both EHP scorers - clean headless effects-text survivability lane EXHAUSTED.
