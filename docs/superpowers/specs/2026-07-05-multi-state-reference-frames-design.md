# Multi-state reference frames (vision calibrator enabler)

Date: 2026-07-05
Status: approved (enabler slice); precursor to the config-keyed HUD-section-tree design (follow-on)

## Problem
The vision calibrator calibrates OCR region boxes against ONE native reference still
per game config. Some HUD elements (death_timer, enemy_deaths) only render in specific
game states (self dead, enemies dead) that the base still does not depict, so their
boxes cannot be positioned accurately. The in-process self-grab overwrites a single
native frame per config, so an operator-provided screenshot of a transient state has
no ingest path.

## Goal
Let the operator calibrate against MULTIPLE named reference stills per config
(base + arbitrary states such as self_dead, enemy_dead), ingesting operator-provided
full-screen native screenshots, without changing the flat profile schema or the
native-OCR consume path.

## Design

### Storage (core/vision_profiles.py)
- reference_path(config_key, state=None): state in {None,"","base"} -> existing
  `<safe(ck)>.jpg` (backward-compat); else `<safe(ck)>__<safe(state)>.jpg`.
- load_reference / save_reference_image / capture_reference gain an optional `state`.
- list_reference_states(config_key) -> ["base", ...ingested], by scanning REFERENCE_DIR.
- ingest_reference_from_path(src_path, state, config_key=None): read the image, require
  dims == profile base (load_profile(ck)["base"]), save via save_reference_image(force).
  Reject a dims mismatch with a clear error (prevents silent miscalibration).

### Routes (dashboard/routes_vision_calibrator.py)
- GET /api/vision-frame?source=reference&state=<state> -> load_reference(state=state).
- GET /api/vision-reference-states -> {ok, states:[{state, exists, width, height}]}.
- POST /api/vision-reference {state, path} -> ingest_reference_from_path -> 200/400.

### Calibrator (web/vision_calibrator.html)
- State switcher (buttons from /api/vision-reference-states); pick -> reload frame w/ &state.
- Ingest form: [state label] [disk path] [Ingest] -> POST /api/vision-reference; on ok
  refresh states + switch to the new state.
- Boxes overlay whichever state frame is shown; Save writes the SAME flat profile.

### Why no per-state runtime tagging
A box is position-only. Native OCR reads each box from the LIVE frame; an element's
spot is empty when its state is inactive (already _has_text_signal-gated -> no false
read) and correct when active. So a box needs accurate COORDS calibrated on a frame
where the element is visible - not a per-state runtime tag. Flat profile + consume
schema stay untouched.

## Constraints
- Ingested caps must be full-screen native (base dims, 2560x1440); server validates.
- 7-bit ASCII everywhere; atomic writes; backward-compatible (base = existing file).

## Out of scope (follow-on design)
Config-keyed HUD SECTIONS with per-section zoom, the full element list-tree incl
minimap elements, per-element interpretation strategy, and element pruning. Brainstormed
separately after this enabler ships + the operator captures the state frames.
