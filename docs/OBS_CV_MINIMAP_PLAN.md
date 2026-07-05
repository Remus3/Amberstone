# OBS + Deterministic-CV + Minimap-Identity Plan

Operator-directed 2026-07-05 (R81 cycle, expansion 3). A phased roadmap to (1) hook
OBS up properly, (2) drive DETERMINISTIC coaching calls + utilizations from CV (the
Haiku/Sonnet-to-ZERO north star), and (3) upgrade the minimap from presence to
champion identity. ASCII-only, name-scrubbed (competitor techniques referenced
generically). Nothing here ships blind headless - every coach-serving flip is
live-gated (a wrong deterministic read is worse than an LLM call; do-not-flip-blind).

## 1. Current state (verified, cited) - two assumptions corrected

- **OBS is ALREADY integrated (text-push only).** `core/obs_publisher.py` is a complete
  OBS-WebSocket v5 client: Hello/Identify/Identified handshake with SHA256 auth, backoff
  reconnect, recv-queue drain (keepalive-flap fix), AppLoop-or-thread run path. Wired at
  `dashboard/server.py:259-260` (`get_publisher().start_background()`), config-gated by
  `config/coach_settings.json` -> `obs.enabled` (default false, port 4455). `websockets`
  is already in `requirements.txt` - NO new dependency for any OBS work. Its ONLY current
  capability is pushing a one-line RC-state string to a Text (GDI+) source (`_render_state`).
  It does NOT read frames, control scenes, or manage recording. So OBS work = EXTEND this
  foundation, not build from scratch.
- **Deterministic-CV primitives are ALREADY built, mostly UNWIRED.** `core/vision_tesseract.py`
  already implements `_bar_fill_pct` (green/blue/red column fill %), `_ally_ults_strip` (4-slot
  ult-ready bools), `_ult_pct` (circular cooldown-sweep 0-100), `_ocr_cooldown` (spell/summ CD
  seconds), `ally_levels`. `data/vision_regions.json` already carries calibrated regions
  (`ally_1..4_hp/mana`, `ally_ults`, `ally_levels`, `score_blue/red`). (`death_timer` +
  `enemy_deaths` OCR were PRUNED 2026-07-05 - the same respawn data is live from the API's
  `allPlayers[].respawnTimer`.) The GAP: coaches' `TIERED_FIELDS` do not request the
  deterministic ones - ARAM (`coaches/aram_coach.py`) escalates HUD-adjacent fields to Sonnet.
  The tiered router (`core/vision_routing.py`) runs Tesseract first and escalates only on a
  miss, so wiring a field to a working OCR parser drops its Sonnet calls to zero automatically.
- **Template assets already on disk.** `data/icons/champions/*.png` = 173 champion icons at
  128x128 RGB; `data/icons/spells/*.png` = summoner-spell icons. Zero network for the
  minimap-identity + summoner-spell template sets.
- **Minimap = presence only.** `core/minimap_geometry.py` (calibrated CAL_SCALE 1.62 -> 312px
  square at design px), `core/minimap_blob_detect.py` (saturation-gated team-color blob
  centroids, pure-numpy by deliberate design, NO opencv), native ~416px grab
  (`RC_ZOI_NATIVE_GRAB` default ON), `core/zoi_influence.py` (dots -> bubbles/map-control).
  Wired at `dashboard/_state_builder.py:454-480` (sr/aram gated, TTL-cached, fail-soft).
- **Runtime baseline:** DWM/GDI BitBlt + PIL ImageGrab capture (Vanguard-safe, no DXGI /
  injection). opencv is NOT installed in the Python314 runtime. pytesseract + Tesseract.exe
  are both present and live.
- **Real gaps:** (a) OBS is text-push only (no frame source, no scene/replay control); (b)
  deterministic CV parsers exist but are not wired into coach field lists (Sonnet still fires);
  (c) minimap is presence-not-identity; (d) no objective/recall icon CV.

## 2. OBS hookup plan (extend the existing publisher; no new dep)

Keep the raw `websockets` client already in `obs_publisher.py` - do NOT add `obs-websocket-py`
(RC already speaks OBS-WS v5 correctly incl the auth handshake + the non-obvious drain fix).
The current `_set_text` is fire-and-forget; frame-grab needs a request/response helper that
awaits the `op=7` response. This socket talks to OBS on `127.0.0.1:4455`, never the game -
Vanguard-irrelevant throughout.

- **O1 - POC: request/response + `GetSourceScreenshot` (1 session).** Add `_request(ws, type,
  data)` awaiting the matching `requestId` in `op=7`. Call `GetSourceScreenshot` (imageFormat
  jpg, width 1280) on the League Game-Capture source -> base64 JPEG. Prove a frame round-trips.
- **O2 - frame-source swap into `:8889` (1-2 sessions).** OBS Game Capture is OCCLUSION-PROOF
  (captures the game surface even when the RC overlay sits on top) - RC gets the per-window
  Windows.Graphics.Capture technique for free via OBS instead of vendoring a GPL capture tool.
  Add an alternate frame provider in `vision_server/_frame.py` / `_relay.py` that pulls
  `GetSourceScreenshot` when `obs.frame_source=true`, so `modes/shared_vision._capture_screen`
  (`:8889/latest-frame`) transparently gets OBS frames. Reuses the token-gated `:8889` cache,
  one config flag, no extra process. Today's `screen_agent.py` GDI grab is full-desktop BitBlt
  (grabs whatever is on screen incl the overlay); the OBS path is source-scoped + occlusion-proof.
  Keep the GDI grab as fallback.
- **O3 - scene/source + replay control (1 session, optional).** Wrap `SetCurrentProgramScene`,
  `StartRecord`/`StopRecord`, `SaveReplayBuffer`. Concrete uses: auto-save an OBS replay-buffer
  clip on a detected death/teamfight (feed from `core/decision_detector.py`); auto-switch scene
  on champ-select -> in-game (from `core/game_snapshot` transitions); post-game `StopRecord`
  returns the file path for the Post-Game-Review reframe. Fire-and-forget, fail-soft, config-gated.

## 3. Deterministic-CV-for-calls plan (Haiku/Sonnet-to-ZERO)

"Replaces Sonnet" = removing a field from a coach's `TIERED_FIELDS` Sonnet escalation because a
working OCR/CV parser already validates it. Region = `data/vision_regions.json` key (existing
unless NEW). Ranked by value x determinism x low-risk.

| # | Call / utilization | CV technique | Region | RC integration point | Replaces Sonnet |
|---|---|---|---|---|---|
| 1 | Self HP / mana | OCR + `_bar_fill_pct` (built) | hp, mana (exist) | base coach state + low-HP fight guard | Partial |
| 2 | Timer / gold / level / CS / KDA | OCR (built) | exist | extend to all coaches' TIERED_FIELDS | Yes |
| 3 | Ally HP bars (party frames) | `_bar_fill_pct` green (built) | ally_1..4_hp (exist) | ZOI ally-strength + peel/dive cues (unconsumed today) | Yes |
| 4 | Summoner-spell up/down | `_ocr_cooldown` + text-signal gate (built) | NEW summ1_cd, summ2_cd | `core/summoner_cooldowns.py` consumer exists; drives "enemy Flash down -> all-in" | Yes (no current source; :2999 has no CDs) |
| 5 | Ult ready (self + ally) | `_ult_pct` / `_ally_ults_strip` (built) | ally_ults (exists) + NEW self_ult | spike / all-in cue | Yes |
| 6 | Death timer / enemy deaths | API `respawnTimer` (OCR PRUNED 2026-07-05) | - | `allPlayers[].respawnTimer` + `isDead` -> `vision_state.json` (live; consumed by active_match.js + SR prompt) | N/A - API covers it |
| 7 | Ability cooldown-sweep = CAST / utilization proxy | `_ult_pct` sweep transition full->0 frame-to-frame | NEW q/w/e_cd | new stateful tracker; :2999 has no cast data so this is the ONLY cast signal | Net-new |
| 8 | Objective icon + timer (drake/baron/elder) | template-match icons OR OCR the on-screen timer | NEW region | complements `core/event_callouts.py` static schedule with live-spawned truth | Partial |
| 9 | Recall channel | `_bar_fill_pct` on the cast-bar OR template-match the glyph | NEW recall_bar | tempo cue ("enemy recalling") | Net-new |
| 10 | Item completion (shop/inventory) | template-match vs `data/icons/items` | NEW inventory region | build-order tracker (hardest; per-item templates) | Partial |

Wiring pattern (cheap, repeatable): for #1-6 the parser + region already exist - the change is
per-coach (add the field to `TIERED_FIELDS` + a validator, verify its bbox). The router
auto-serves OCR and escalates only misses. #7-10 need new small modules (a stateful sweep
tracker for casts; template-match for objective/recall/item). Per-champ templates are needed
only for minimap identity (section 4) and item-completion (#10); everything else is generic
bar-fill/OCR, resolution-scaled + champ-agnostic. Top 3 to ship first: #2 (numerics, pure
wiring), #3 (ally HP, built + unconsumed), #4 (summoner CDs, highest tactical value, no current
source).

## 4. Minimap identity plan (presence -> champion identity)

- **Technique:** OpenCV `cv2.matchTemplate` with `TM_CCOEFF_NORMED`. For each blob centroid from
  `minimap_blob_detect.detect_team_dots`, crop a window in the native ~416px grab and match
  against the champion templates, argmax above a confidence floor (~0.6). Restrict the candidate
  set to the ~10 champions actually in the game (from `:2999` team lists) -> ~10 templates per
  frame, fast + far fewer false matches.
- **Template set:** `data/icons/champions/*.png` (already on disk). Precompute once per game:
  downscale each in-game champ's icon to the calibrated minimap champ-icon px (~18-24px at the
  416px crop), apply the circular mask League uses, cache the scaled templates.
- **Calibration:** reuse `core/minimap_geometry.py` rect + the `_scaled_size_bounds` logic in
  `minimap_blob_detect.py` (design px <-> crop px).
- **Feeds:** attach `champion` + `team` to each dot -> `core/zoi_influence.compute_zoi` gets true
  per-champion identity -> enables the "predicted roam route from last_seen_zone" macro lift
  (track per-champ last_seen_zone + timestamp; gank/roam prediction when a laner disappears).
  New `/api/state` zoi fields; overlay renders champ portraits.
- **Caveats:** occlusion in fights (matcher picks the top icon; acceptable for macro), ping /
  summoner-icon overlays distort the portrait, recall/dead champs vanish (last-seen decay).
  Good for isolated icons + roam/gank macro; not frame-perfect tracking.
- **New dep:** `opencv-python` (~40MB wheel, pure userland, Vanguard-irrelevant - operates on
  captured pixels). The only genuinely new heavy dependency in the whole plan.

## 5. Dependency + Vanguard-safety + effort/risk

| Capability | New dep | Vanguard | Effort | Risk |
|---|---|---|---|---|
| O1 OBS req/resp + screenshot | none (websockets present) | N/A (talks to OBS) | 1 sess | Low |
| O2 OBS frame -> :8889 | none | Safe (OBS Game Capture, runs today) | 1-2 sess | Low-Med |
| O3 OBS scene/replay ctrl | none | N/A | 1 sess | Low |
| CV wiring #1-6 (built parsers) | none (pytesseract present) | Safe (captured pixels) | 1-2 sess | Low |
| CV new modules #7-10 | none (numpy/PIL) or opencv for template ones | Safe | 2-3 sess | Med (calibration) |
| Minimap identity | opencv-python | Safe (pixels only) | 2-3 sess | Med (occlusion accuracy) |

Phased roadmap: O1 (POC) -> CV#2 numerics wiring (cheapest win) -> CV#3/#4 (ally HP + summoner
CDs) -> O2 (occlusion-proof frames) -> minimap identity (opencv) -> CV#7-10 + O3.

## 6. The NOW-next cheap slice (start here; still live-gated)

The single genuinely safe, zero-new-dep, self-contained starting slice = **wire the already-built,
already-calibrated OCR fields (`ally_1..4_hp` via `_bar_fill_pct` + the numerics) into the
ARAM/Arena coach `TIERED_FIELDS` + validators.** Parsers + regions already exist and are tested;
it strictly reduces Sonnet escalations (direct Haiku-to-ZERO credit), fail-soft, no capture/dep
change. BUT it changes what the LIVE coach serves, so ship it SHADOW-FIRST (compute + shadow-log
the OCR value alongside the current Sonnet read, do NOT flip the served field) and require a
real-game eyeball of OCR-vs-Sonnet agreement before the flip - the same do-not-flip-blind /
HZ-shadow discipline used across RC's deterministic-coach lanes. That validation is live-gated
(add the flip row to `docs/LIVE_GAME_GATED_SYNC.md`).

Everything else (OBS frame-source, scene/replay control, the new cast/recall/objective/item CV
modules, minimap identity + opencv) is multi-session, new-dep, or needs live calibration ->
BACKLOG/FUTURE, operator-picked, nothing built blind.
