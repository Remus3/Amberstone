# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) + R47 UI-audit cycle 16 (2026-06-30, full in LEDGER 702) + E11 sweep (2026-07-04, LEDGER 773-774) archived + /live-gated-drain (2026-07-04, LEDGER 780) archived 2026-07-05 + HZ-regrn+ARAM-leak-fix (2026-07-08, LEDGER 814-815) + enemy-spells CSS fix (2026-07-08, LEDGER 816) + /live-gated-drain (2026-07-08, LEDGER 820) archived 2026-07-09. Only the last 3 sessions kept here.

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

---

# 2026-07-10 (R95 vision CV consumes core.hud_settings COLOR layer - colorblind + gamma; NO ENGINE bump, Tier-1)

Gemini-loop DIRECTOR REFILL R95. Full detail: LEDGER 836. Commit `87c3a990`. No restart/bounce (neutral-safe, RC picks up on next restart).

- The net-new item the R94 escalation asked for (consume the hud_settings COLOR layer - genuinely unwired). PREMISE
  CONFIRMED: core/hud_settings.py:106 read_hud_settings() already returns colorblind/color_correction_needed/color{...},
  but vision_tesseract consumed it only transitively (profile-key selection), never the color settings.
- SHIPPED (3 files): vision_tesseract.py new _HUD_COLOR + configure_hud_color() (mirrors _DROP_FIELDS); _bar_fill_pct
  relaxes green/blue/red match when colorblind (ColorPalette!=0) so a hue-shifted bar registers; _preprocess adds a
  fail-soft inverse gamma/brightness/contrast (_apply_color_correction) when color_correction_needed. vision_profiles.
  active_config_key() installs the live layer via configure_hud_color(read_hud_settings()) each call. DEFAULT-NEUTRAL
  byte-identical (default palette + 0.5 sliders -> both fns unchanged; live OCR path untouched until colorblind/gamma active).
- ENGINE-IMPACT NONE (client-side CV, no DS math/bump/Share). TDD 7 tests (INV1-INV4 + configure install/clear) +
  read-only verifier CONFIRM (targeted 29/0, R95 7/7, exactly 3 files). Full RC 11264 passed; the only 2 fails =
  the LEDGER-828 coach-poll asyncio isolation flake, PROVEN not R95 (passes 2/2 isolated; vision has 0 asyncio refs).
- Don't-redo: hud_settings COLOR layer is now consumed (do NOT re-pitch); generic OCR crop/native wiring stays DONE
  (793/832/835, do NOT re-pitch a 5th time); NEXT NO-LLM vision frontier = Lane E CV template-match atlas (BACKLOG:280/283).

---

# 2026-07-10 (R94 public-API native-crop regression guard - vision OCR; NO ENGINE bump, Tier-1)

Gemini-loop DIRECTOR REFILL R94. Full detail: LEDGER 835. Commit `9a5fac79`. No restart/bounce (test-only).

- PREMISE REFUTED (the 3rd re-pitch): "wire native OCR crops + color-correction into vision_tesseract.py" ALREADY
  shipped LEDGER 793 (_color_correct :183 / _preprocess :198 / _scale_bbox :128 / the vision_profiles hot-path in
  _regions() :86) + the R91 derive_scaled_regions primitive (LEDGER 832). Fresh grep: NO stubs, NO 1280/frame-halving
  (the only "halve" token is a comment naming the failure prevented); verifier CONFIRMED vision_tesseract.py UNMODIFIED.
- SHIPPED the one in-scope residual (WIRING-ONLY): tests/test_vision_tesseract_native_crop_r94.py (4 CI-safe tests,
  PIL-only, tesseract seams stubbed). The PUBLIC crop path (crop_png_b64 + the read_fast_fields work-list) had ZERO
  native-profile coverage - the existing wiring test exercises only _regions/_scale_bbox/_color_correct/_preprocess in
  isolation. Proves a native 2560x1440 frame crops at native coords with no 1920->native downscale drift.
- GATES: new 4 + vision surface 71 pass / 0 fail; tests/ collection clean (11281); the full RC suite 0-fail through 81%
  at the 10-min cap (R6 full re-run skipped, test-only); ruff/py_compile/ASCII clean; verifier CONFIRM 4/4. ENGINE-IMPACT NONE.
- ESCALATED (gemini_ask.txt): the director re-pitched vision-OCR wiring 3x - STOP. Next NO-LLM vision target = Lane E CV
  template-match atlas OR consume the core.hud_settings COLOR layer (settings-driven inverse-correction + colorblind bar
  adaptation, genuinely unwired) as a NEW scoped item; else rotate to a DS different-mechanic refute pass.
- Don't-redo: native-crop + generic color-correction wiring is DONE + now public-API-guarded (do NOT re-pitch a 4th
  time); the 23-box recalibration is a live-gated operator task, not a loop slice.
