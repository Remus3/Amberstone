# No-LLM Precompute Plan - Client-Side Vision + Scenario DB

Status: VISION / planning. Authored 2026-06-27 from an operator directive during
the live-flip validation session. This is the next-session pickup doc; it bundles
this session's pending work at the bottom.

## North star (operator framing, 2026-06-27, faithful capture)

Bring the WHOLE project to NO live LLM. Build a fast, accurate, rapid-firing
CLIENT-SIDE vision tier whose output is saved into a premade, expansive, robust
database covering future plans and scenario mutations. "Pay it once maybe twice" -
run the expensive AI a bounded number of times to BUILD the database, then never
again at runtime. This removes the API-key requirement for live AI usage. The
"dictionary" needs occasional updating (like a patch to RC), but overall is
streamlined. The result: hyper-fast iterative live feedback loops that need far
less computation, and a fine-tuned, on-the-fly built-in coach that contextualizes
findings and leans toward an output even on PARTIAL reading of the screen,
regardless of how the operator has their screen set up. Analogy: how ray tracing
renders - progressive, best-effort from whatever rays (fragments) are available.

## Budget reality - why now (operator photos 2026-06-27)

- Plan: Max (20x). Current session 11% used, weekly all-models 17% used, Sonnet
  0% used (untouched).
- Usage credits: $418.34 balance, $0.00 spent this cycle, untouched ~2 months,
  resets Jul 1, auto-reload on.

Implication: there is a large, idle BUILD-TIME budget. The clean split:

- BUILD-TIME (abundant, effectively free): Claude Code / Claude chat sessions under
  the Max 20x plan do the design + code + scenario-table generation. This is where
  "iterate with Claude chats" lands - it does NOT touch the RC runtime API key.
- RUNTIME (the thing to drive to ZERO): the RC coaches + vision escalation call the
  Anthropic API via API-Key-Claude.txt (Haiku live). This is the live spend the
  no-LLM effort eliminates.
- The bounded "pay once/twice" vision-labeling passes (Sonnet vision to bootstrap
  templates) can be funded from the $418 API credits - a one-time, capped cost.

So: spend idle build-time capacity to precompute everything; runtime becomes
deterministic and API-key-free.

## What "no-LLM" actually requires (technical grounding)

Two distinct live-LLM consumer classes remain (see live_input_seam_findings_2026-06-27.md):

1. Per-tick coaching text: ARAM (4 Haiku calls), Arena (6), Brawl (2) coaches. SR
   coach already shows ZERO Haiku calls - it is the template for "done" (precomputed
   DS + deterministic A/B). Port the other 3 onto SR's pattern.
2. Vision OCR escalation: the vision server escalates OCR misses to Haiku/Sonnet.
   This is the target of the client-side vision tier below.

Key grounding fact that REDUCES the vision scope: the Live Client API (:2999, read
in-process) already gives the player's own HP / gold / items / CS / KDA / level /
game_time DETERMINISTICALLY, no vision, no LLM (this is the `liveclient` block in
/api/state). Vision's real job is only the GAPS the API does not expose:
- Enemy item builds mid-game (partial via API, often needs the scoreboard read)
- Fog / minimap dot state (already derived from position freshness - vision_tracker)
- Arena augment choices (OCR - the proven path; no API)
- Ability cooldowns / visual combat cues not in the API
RC already runs an OCR-first tier and mirrors all DDragon item/champion icons
locally (the dashboard fetches /data/ddragon/.../img/item/*.png today). So a large
fraction of the "vision" surface is already deterministic or template-matchable.

## Architecture sketch (proposed - validate next session)

PRECOMPUTED ATLAS (the "expansive database"):
- Template set: DDragon item + champion icons (already local) as match templates;
  HUD glyph templates; augment-card templates.
- OCR region maps: per resolution / screen-setup, the pixel rects for HP / gold /
  CS / KDA / timers / scoreboard rows (extends data/vision_regions.json).
- Feature hashes: perceptual hashes / feature vectors for fast nearest-match.
- Keys: patch x screen-setup x scenario-mutation. Scenario mutations = shop open,
  scoreboard (Tab) open, dead-ally panel hidden, different aspect ratios, HUD scale.

CLIENT-SIDE CV TIER (replaces the Haiku/Sonnet escalation):
- Deterministic template-match + OCR against the atlas. No network, no LLM.
- Confidence per read.

CONFIDENCE-WEIGHTED FUSION (the "ray tracing" / partial-read layer):
- Fuse Live Client API (high trust) + CV reads (confidence-weighted) into a single
  best-effort game-state estimate.
- Always emit SOMETHING from whatever fragments fired - graceful degradation,
  screen-setup-agnostic. Never block on a full read.

DETERMINISTIC COACH (already exists for SR):
- Consumes the fused state + the precomputed DS scenario tables (laning trade /
  all-in / spike) + prebuilt metric-backed build orders + A/B deterministic choice.
- This is the SR coach pattern generalized to all modes.

PATCH UPGRADE PATH:
- On a patch, regenerate the atlas (DDragon assets auto-mirror; RC already has a
  patch-refresh SWARM workflow). The bounded vision-labeling pass re-runs only for
  genuinely new visual elements. This is the "dictionary update like a patch to RC".

## Pay-once/twice build pipeline (proposed)

1. Bootstrap templates from DDragon (free, already local) + a bounded Sonnet-vision
   pass to label anything not derivable from assets (augment cards, novel HUD).
2. Calibrate OCR region maps across the operator's actual screen-setups (one-time).
3. Freeze the atlas, versioned by patch. Commit (assets gitignored per existing
   rules; the maps + hashes are small and committable).
4. Wire the CV tier + fusion; cut the vision-Haiku escalation.
5. Port ARAM/Arena/Brawl coaches onto the SR precompute pattern.
6. Validate live; then the API key is no longer required at runtime.

## Pending from the 2026-06-27 session (bundle - operator asked to include)

Full detail: ops/audit/ds_perm_swarm/report/live_input_seam_findings_2026-06-27.md

1. Live-flip DS seams (R5 / DSP2 / DSP11, and by inference R12 / R30 / RF1 / RF3)
   are UNWIRED across the DS /rank HTTP boundary. The seam flags live only in the
   in-process scorers + offline live_flip_eyeball.py; dispatch_for_coach -> client
   -> server /rank passes none of them. The live build-chooser runs every scorer at
   DEFAULT-OFF. Proven: Briar at 7% HP gave byte-identical picks to 100% HP. Flipping
   these default-ON is multi-file engine wiring (+ self-HP input for R5) + ENGINE
   bump + Tier-2, NOT a toggle.
2. R12 (Evenshroud target-vuln) is SR-untestable on 16.13.1 - Evenshroud is map-30
   (Arena) only. Needs an Arena game for a live eyeball.
3. No in-game build-chooser overlay widget. The rc-shell overlay shows the CALL
   panel only; daemon_slayer_picks render on the (retired) :8888 dashboard only.
   The overlay needs a build widget.
4. Overlay hotkey Ctrl+Shift+A "not working" in-game: NOT a focus/keydown bug. The
   combo is registered via Electron globalShortcut (main.js:1063; overlay_state.js:44
   tagged "operator's expected combo 2026-06-27") and the shell is running (5
   electron.exe). Most likely cause: a global-accelerator collision among multiple
   electron instances - register() failure is swallowed (main.js:1081). FIX next
   session (diagnostic-first): log the register() booleans + reset to a single
   electron instance; do NOT add a Python RegisterHotKey listener (would double-
   register). Full spec authored this session.
5. Long coach tick when base under attack - operator-reported, untraced. Needs a
   coach-loop timing trace correlated to inhib/turret/nexus events.
6. Haiku-to-zero remaining: ARAM/Arena/Brawl coaches + vision escalation (above).

## Open questions for next session

- CV stack choice for the client-side tier (OpenCV template-match + a perceptual
  hash lib? tesseract for OCR is already in play). Keep it dependency-light.
- How many screen-setups must the atlas cover (operator's setups today)? Drives the
  region-map calibration cost.
- Confidence thresholds for the fusion layer (when to trust CV over a stale API read).
- Sequencing vs the seam-wiring work (item 1) - the no-LLM coach and the DS seam
  flips both feed the build-chooser; decide whether to wire seams first or build the
  precompute DB first.
