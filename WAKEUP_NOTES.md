# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) + R47 UI-audit cycle 16 (2026-06-30, full in LEDGER 702) + E11 sweep (2026-07-04, LEDGER 773-774) archived + /live-gated-drain (2026-07-04, LEDGER 780) archived 2026-07-05 + HZ-regrn+ARAM-leak-fix (2026-07-08, LEDGER 814-815) + enemy-spells CSS fix (2026-07-08, LEDGER 816) + /live-gated-drain (2026-07-08, LEDGER 820) archived 2026-07-09. Only the last 3 sessions kept here.

---

# 2026-07-10 (R98 Vision-OCR premise re-refuted (4th re-pitch) + native-2560-vs-1280-halved-frame OCR crop guard - vision; ENGINE-IMPACT NONE)

Gemini-loop DIRECTOR REFILL R98 re-issued the ROADMAP Vision-OCR NEXT ("recalibrate 23 boxes at 2560x1440 + wire native OCR crops/color-correction into core/vision_tesseract"). Full detail: LEDGER 839. Commit `1fddb516`.

- BOTH slices REFUTED (verify-before-declare; 4th re-pitch - R94 refuted the wiring half + escalated, R95/R96 advanced past it):
  - SLICE 1 DONE: data/vision_profiles/2560x1440_...1.6200.json is a real native CUSTOM-HUD calib (34 regions, ally panels at
    x=2173-2546 RIGHT = ShowTeamFramesOnLeft=0, NOT a naive left-derive), scalar OCR boxes backfilled (test_vision_profile_2560_ocr_boxes.py).
  - SLICE 2 DONE: vision_tesseract._regions():86 prefers the active native profile + base; _color_correct/_preprocess/
    _apply_color_correction(R95)/configure_hud_color all wired (profile_wiring + native_crop_r94 + hud_color_r95 guards).
- GENUINE UNCOVERED SEAM shipped (R94-style residual): the live OCR read path consumes the 1280-HALVED /latest-frame
  (vision_server/_frame.py _SELF_GRAB_MAX_WIDTH=1280), so a native-2560 profile is scaled DOWN 0.5x at crop time - a production
  condition no test drove. NEW tests/test_vision_tesseract_halved_frame_r98.py (5 CI-safe PIL-only): native-base install, 0.5x
  half-scale map, anti-1920-drift sentinel, all boxes inside 1280x720, non-degenerate crop. The failing-first draft REVEALED
  Legion genuinely re-loads a real 2560 profile post-teardown (native profile IS the live active calib, not a fixture).
- Tier-1 test-only, ENGINE-IMPACT NONE. R98 5/5 + full vision surface 153/0. ROADMAP Vision-OCR NEXT corrected to DONE + names
  the only open seam. ESCALATED (gemini_ask.txt): director MUST retire the Vision-OCR NEXT; only tail = wire
  core/screen_grab.grab_native() into the OCR crop path = LIVE-GATED Lane E, not a blind flip. Next headless lane: Lane A
  scenario precompute OR a ds-sweep rotation.
- Don't-redo: 2560x1440 recalibration + native-crop/color-correction wiring are SHIPPED + guarded (4th refutation; do NOT re-pitch).

---

# 2026-07-10 (R97 Eclipse (6692/226692) Ever Rising Moon self-shield EHP credit - ds-engine; ENGINE 1.190.0 -> 1.191.0)

Gemini-loop DIRECTOR REFILL R97 (ds-sweep). Full detail: LEDGER 838. Commits `b80547ab` (merge) + `7b24a779` (sync). DS :8893 bounced 1.191.0.

- FRESH adversarial Meraki(16.13.1)-vs-registry refute pass. PICK #1 Alistar R (55/65/75% all-damage DR) REFUTED live
  (verify-before-build): spell_damage_reduction_pct("Alistar","R")==(55,65,75) is ALREADY folded into EHP by the R19/R35
  snapshot fold in mitigation_multipliers (ehp.compute_ehp:1292 passes the snapshot); Gragas W + Warwick E fold identically;
  the _passive_mitigation_overrides.py:70-74 exclusion docstring is STALE (that whole modifier-block DR class is covered).
- GAP CONFIRMED + SHIPPED (pick #2): Eclipse (6692 SR + 226692 Arena) "Ever Rising Moon" self-shield - the damage half
  (6% target maxHP PeriodicProc) was modeled but the SHIELD half was uncredited (ITEM_EFFECTS[6692].shield is None;
  _collect_shields skips it). Meraki "160|80 (+40%|20% bonus AD) 2s". FIX = shield=ItemShield(ANY, flat=160,
  bonus_ad_scaling=0.40, ranged_modifier=0.5, default_off=True) on both ids + NEW default-OFF assume_eclipse_shield seam
  (ehp._collect_shields/compute_ehp, 4-spot parallel of assume_kaenic_shield) with a SHIELD-SPECIFIC gate so arming eclipse
  never cross-credits Kaenic 2504. ItemShield needed no schema lift (bonus_ad_scaling/ranged_modifier/default_off exist R92).
- Orchestrator + 1 worktree build subagent (TDD RED-first 20 tests, 16 RED) + read-only verifier CONFIRM 8/8 (OFF
  byte-identical {} 0-credit / ON melee any=200 / ranged=100 / cross-contam ZERO) BEFORE the no-ff merge. Share --check green
  422; HZ-B stamp-only re-stamp (0 content lines); banner 1.191.0/8142. DS 8142 pass/1skip; RC 11271 pass / 3 fail ALL
  pre-existing-flake-or-stale (2 = LEDGER-828 coach-poll 2/2 isolated; 1 = doc-drift STALE - suite launched pre-banner-bump,
  3/3 fresh) / 0 R97 regressions.
- Also backfilled Share/CHANGELOG 1.186->1.190 (R88/R90/R92/R93; operator chip, commit `a28c0678`) - the entries omitted
  since --check does not gate CHANGELOG completeness. Live default-ON flip -> LIVE_GATED.
- Don't-redo: Alistar/Gragas/Warwick + the whole modifier-block DR class is folded via R19/R35 (do NOT re-pitch a percent-DR
  seam for them); Eclipse Ever Rising Moon shield SHIPPED (do NOT re-pick 6692/226692); the damage half stays modeled + untouched.

---

# 2026-07-10 (R96 Lane E client-side CV template-match atlas FOUNDATION - vision; NO ENGINE bump, Tier-1)

Gemini-loop DIRECTOR REFILL R96. Full detail: LEDGER 837. Commit `406ac0e3`. No restart/bounce (pure new unused core module).

- The genuine NEXT NO-LLM vision frontier the R94/R95 escalations queued (Lane E CV template-match atlas), NOT another
  vision-OCR wiring re-pitch. Ground-truth correction: cv2 5.0.0 + numpy 2.5.0 ARE installed (OBS_CV_MINIMAP_PLAN L40
  "opencv NOT installed" is STALE - refuted live).
- SHIPPED new core/vision_template_match.py: generic match_icon(crop, category, roster=None, threshold=None) -> (id, conf)
  over a lazy in-memory OpenCV atlas of the local DDragon icons (champions 173 / items 36 / spells 18). Two-stage match
  mirrors minimap_identity._match_score (TM_CCORR_NORMED offset -> masked Pearson conf, threshold 0.6); roster restriction
  via _name_keys; helpers list_ids/available_categories. HAVE-distinct from minimap_identity (that = minimap-DOT +
  10-roster identify_dots; R96 = generic single-crop -> full-category inverse, the OBS_CV_MINIMAP_PLAN #8 objective /
  #10 item substrate).
- DEFAULT-OFF, NO live wiring (verifier: only the test imports it). ENGINE-IMPACT NONE. Orchestrator + 1 worktree build
  subagent + read-only verifier CONFIRM (8 tests, ruff/py_compile/ASCII clean, contract sane 173/36) BEFORE the ff-only
  merge (b54e38eb..406ac0e3). Full RC 11272 passed; the only 2 fails = the LEDGER-828 coach-poll asyncio flake, PROVEN
  not R96 (2/2 isolated; R96 has 0 asyncio refs). Live template-match quality on real frames = live-gated (do-not-flip-blind).
- Don't-redo: the Lane E CV template-match FOUNDATION is SHIPPED (do NOT re-pitch match_icon/atlas); vision-OCR wiring stays
  DONE (793/832/835/836); NEXT = live crop-producer wiring + per-champ/objective/item consumers + Live-Client/CV fusion.
