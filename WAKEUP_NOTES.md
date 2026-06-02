# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-06-02 - item 265 (/headless-upgrade, IN PROGRESS): Haiku-elimination FOUNDATIONS (ENGINE 1.94.0)

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

---

# 2026-06-02 - item 263: Kai'Sa ARAM rebuild + Ashe SR ADC paths (data-only, RC pid 324 live-verified, no restart)

Operator "start the next open item" -> the LW DEFERRED carry (data-only loadout fix). Pre-flight: clean tree, main, item 262 last shipped, DS clean-headless lane EXHAUSTED (mitigation triad scorer-COMPLETE), remaining DS NEXT is all Phase D (live/operator-gated). So the next headless-buildable open item = the LW deferred loadout rebuild.

SHIPPED `32ed831` (data/champion_loadouts.json + 2 new files; ADR-008 auto-served, no restart): (1) Kai'Sa `aram-collapsed` - replaced 2 item-167 coverage-gap junk paths: `ap-hybrid` (4 AD items mislabeled "AP Hybrid", 0 AP) -> `ap-burst` "AP" (Hubris/Nashor/Rabadon's/Void/Shadowflame = REAL AP); `bruiser-trinity` (label "Trinity", NO Trinity Force) -> `adc-crit` "Crit". The legit `on-hit` path (BorK/Berserker/Wit's End/Guinsoo's/Terminus/Sterak's) KEPT as primary. summs [4,32]. (2) Ashe `sr-collapsed` thin 2-path (one was `sr-enchanter` = Echoes/Ardent/Staff-of-Flowing/Redemption/Moonstone = full enchanter build on a ranged ADC) -> 3 ADC paths: `utility-adc` (kept primary) + `adc-crit` + `adc-on-hit`, mirroring Caitlyn/Jinx. summs [4,21].

All builds mirror item-213-proven clean sets (0 unique-family clash). +8 tests `test_loadout_fix_kaisa_aram_ashe_sr_item263.py` (TDD RED 5-fail -> GREEN) via NEW `tools/hotfix_kaisa_aram_ashe_sr_item263.py` (atomic + idempotent, sibling of `tools/hotfix_sr_adc_loadouts_item167.py`). Verified: 62 pass (8 new + no-unique-clash + item-213 pollution + collapse + name-fallback drift guards), 71 pass (autogen + meta-conformance + dedup + user-builds), ruff clean, ASCII clean, live `/api/loadout/list` (RC pid 324) serves corrected Kai'Sa ARAM on-hit/ap-burst/adc-crit.

ROOT (verified, [[feedback_verify_before_declare_broken]]): the LW-cited `core/build_order.py::_score_item_for_archetype` is a PHANTOM ref - `grep -rln _score_item_for_archetype` returns NOTHING (item-208 named a non-existent fn; item-213 already established this). The real auto-seed/ranker root is `rank.py` (`OFFCLASS_MARKSMAN_ITEM_NAMES` + `_is_ranged_marksman` at :79/:139/:584) + the item-167 align tool routing a ranged ADC through an enchanter archetype - both UNCHANGED. This was the data-side hand-curate (Kai'Sa ARAM is deduped-in-place by item-167 policy, NOT regenerated, so re-running align would not fix it).

Don't-redo: do NOT re-investigate Kai'Sa ARAM / Ashe SR; do NOT re-pitch a `_score_item_for_archetype` fix (the fn does not exist). The `.bak-item263-*` backup is gitignored (not committed).

SIBLING POLLUTION CARRY (operator-gated, NOT this scope): the same item-167 coverage-gap auto-seed left other mislabels surfaced in this session's scan but NOT fixed (operator named only Kai'Sa ARAM + Ashe SR): Corki SR+ARAM `ap-hybrid` (0 AP), Jhin + Smolder `sr-mage` (AD items labeled "Mage"), Gwen/Elise/Gragas AP-archetype paths with 0 AP items, + a thin 4-item ARAM "Carry" template (Stormrazor/Berserker/Yun Tal/IE) across ~12 ADCs (Caitlyn/Draven/Kalista/MissFortune/Quinn/Twitch/Xayah/Varus/Zeri etc - these 4-item ARAM cores may be acceptable per the item-167 "keep role standard for ARAM" policy). Senna's enchanter items are INTENTIONAL (support-marksman, NOT pollution). A future item can sweep the genuine mislabels via the same hotfix-tool pattern.
