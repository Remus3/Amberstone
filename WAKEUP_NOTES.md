# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) + R47 UI-audit cycle 16 (2026-06-30, full in LEDGER 702) + E11 sweep (2026-07-04, LEDGER 773-774) archived + /live-gated-drain (2026-07-04, LEDGER 780) archived 2026-07-05 + HZ-regrn+ARAM-leak-fix (2026-07-08, LEDGER 814-815) + enemy-spells CSS fix (2026-07-08, LEDGER 816) + /live-gated-drain (2026-07-08, LEDGER 820) archived 2026-07-09. Only the last 3 sessions kept here.

---

# 2026-07-10 (DS Darius E Apprehend % armor-penetration anti-tank credit - R93; ENGINE 1.189.0 -> 1.190.0, Tier-2)

Gemini-loop DIRECTOR REFILL R93. Full detail: LEDGER 834. Commit `874bf871`. DS `:8893` bounced 1.190.0.

- PREMISE CORRECTED: the directive's example shred abilities (Nasus E / Wukong Q / Trundle R / Evelynn W) are ALL
  already credited (ds_antitank_hint.py is a read-only consumer; the real registry is antitank._ANTITANK_REGISTRY).
  A MECHANIZED scan of champion_abilities.json 16.13.1 vs the SHRED/PERCENT_PEN rows found the genuine gap = kit
  % PENETRATION passives: Darius E 20-40% armor, Pantheon R + Ambessa R 10-30% armor, Annie R 15-20% magic (all
  PERCENT from raw damage_blocks, not flat lethality).
- SHIPPED ONE: Darius E (Apprehend) always-on % armor pen -> add("Darius","E","PERCENT_PEN","SUSTAINED",magnitude=0.7),
  the SUSTAINED sibling of Mordekaiser E. Darius was absent from the registry entirely (compute_antitank 0.0 -> 0.455,
  top_kind PERCENT_PEN, shreds_resist True). Annie NOT picked - item-308 pins her as a flat-damage zero-scorer.
  Additive/read-by-none (the /anti-tank route is opt-in) -> no default live surface change; Mordekaiser byte-identical.
- Tier-2: ENGINE 1.189.0 -> 1.190.0; 105 test-pin re-stamps (125 quoted-literal occ, EOL-preserving); item-308
  coverage pins 78/102/29/5 -> 79/103/30/6; CHANGELOG 1.190.0; DAEMON_SLAYER banner 1.190.0/8122; 6 HZ-B tables regen
  (build_orders STAMP-ONLY; variants Darius-ONLY content diff, softer anti-tank wall 4200->3340 SR); ds_share_sync 421
  --check green; DS :8893 bounced 1.190.0. Share/CHANGELOG.md left (periodic batch artifact, R87/R90/R92 precedent).
- GATES: DS 8122 / 0 fail; RC 11244 pass (11 transient reds - 7 test_ds_share_* raced a concurrent ds_share_sync, 1
  phase8 pre-bounce stale :8893, 2 coach-poll flake, 1 matchdb conn - ALL cleared clean re-run: cluster 83 + coach-poll
  2 in isolation), 0 R93 regressions; TDD 11 (10 RED pre-fix); verifier ALL 8 claims CONFIRMED; ruff/py_compile/ASCII clean.
- LESSON: launched the bg RC suite BEFORE the Share sync + DS bounce settled -> 11 false reds (the CLAUDE.md "wait to
  settle" warning). Next cycle: Share-sync + bounce THEN the full suite.
- Don't-redo: anti-tank SHRED registry comprehensive + Darius %pen SHIPPED; Pantheon/Ambessa/Annie %pen are lower-pri
  FUTURE (ult-tied, smaller %); live default-ON flip -> LIVE_GATED B4. Next DS refill needs a FRESH different-mechanic pass.

---

# 2026-07-10 (DS Kaenic Rookern 2504 Magebane magic-shield EHP credit - R92; ENGINE 1.188.0 -> 1.189.0, Tier-2)

Gemini-loop DIRECTOR REFILL R92. Full detail: LEDGER 833. Commit `6882735c`. DS `:8893` bounced 1.189.0.

- PREMISE CORRECTED: directive target "tank_items.json/fighter_items.json" does NOT exist; tank/fighter item
  credits live in the Python ehp/_effects_data ItemShield pool + _passive_*_overrides seams. Refute retargeted there.
- GAP: Kaenic Rookern (2504, 80-MR MR-tank) had NO shield=ItemShield in ITEM_EFFECTS, so its Magebane magic shield
  (15% of MAX health) was ZERO magical EHP - unlike lifeline siblings Sterak/Maw/Shieldbow (always-on ItemShield).
- FIX (NEW default-OFF assume_kaenic_shield seam): additive ItemShield fields max_hp_scaling (15%-of-max exact) +
  default_off (opt-in gate); ehp._collect_shields/compute_ehp thread max_hp + the flag; 2504 gets
  shield=ItemShield(MAGICAL, max_hp_scaling=0.15, default_off=True). Routed opt-in (not the always-on pool) because
  Magebane's no-magic-15s uptime is anti-correlated with magic fights. OFF byte-identical; armed = 15%-max-HP magical EHP.
- Tier-2: 105 test-pin re-stamps; CHANGELOG 1.189.0; DAEMON_SLAYER banner 1.189.0/8111; 6 HZ-B tables STAMP-ONLY
  re-stamp; ds_share_sync 420 files --check green; DS :8893 bounced 1.189.0.
- GATES: DS 8111 / 0 fail; RC 11253 pass (2 pre-existing coach-poll flake, GREEN 2/2 in isolation, LEDGER-828), 0 R92
  regressions; TDD 13 (12 RED pre-fix); ruff clean; pre-commit gate passed.
- Don't-redo: tank/fighter item-keyed byte-identical seams SATURATED (tenacity/reflect/AH/HSP zero room); Kaenic
  SHIPPED; live default-ON flip -> LIVE_GATED R92. Next DS refill needs a FRESH different-mechanic refute pass.

---

# 2026-07-10 (reusable OCR-region resolution-scaling primitive - R91 Vision-OCR Hardening; Tier-1, NO ENGINE bump)

Gemini-loop DIRECTOR REFILL R91 (cycle 6). Full detail: LEDGER 832. Commit `67f4c35a`. No DS bounce (ENGINE-IMPACT NONE).

- PREMISE-CHECK reconciled a partially-stale digest: the "wire color-correction + native crops / replace stubs
  into vision_tesseract.py" half ALREADY shipped LEDGER 793 (_color_correct/_preprocess/_scale_bbox + the profile
  hot-path in _regions() - grep found NO stubs), and the 2560x1440 profiles already exist as gitignored per-machine
  JSON (data/vision_profiles/2560x1440_*.json, guarded by a Legion-local test that SKIPS on CI). vision_tesseract.py
  left UNTOUCHED.
- GENUINE net-new: derive_scaled_regions() + derive_profile() + _load_legacy_regions() appended to
  core/vision_profiles.py (L320/L330/L350) - a pure primitive scaling the hand-calibrated 1920x1080 boxes
  (data/vision_regions.json) to any native base by per-axis int(coord*dst/src), BYTE-EXACT with
  vision_tesseract._scale_bbox (verified over all 21 fields), so a derived native-base profile crops the identical
  rectangle with no downscale drift. Closes the CI gap where the 1.3333x math was only Legion-guarded; seeds future
  resolutions (3440x1440).
- VERIFY: TDD RED-first (test_vision_profile_derive.py, 8 tests); read-only verifier CONFIRM all 5 claims (files
  L320/L330/L350, git additive-only, ruff clean, 21 passed fresh, byte-exact OK 21 fields).
- GATES: Tier-1 relevant suite 83 passed / 0 fail across the 9 vision_profiles/vision_tesseract consumers; ruff +
  py_compile + ASCII-clean; CI green 67f4c35a. Additive to vision_profiles.py only.
- Don't-redo: color-correction + native-crop wiring is DONE (LEDGER 793); the primitive is SHIPPED + CI-tested; the
  actual per-HUD 2560 box tuning stays LIVE-GATED (needs a live 2560 frame; the *1.3333 seed is not a substitute).
