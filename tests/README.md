# tests/ - wave and slice map

Most of `tests/` is named for the subject it pins. One family is named for
the deep-audit wave that wrote it instead, and that name says nothing to a
reader who was not there. This file maps each of those modules to what it
covers. `tests/test_tests_readme_wave_map_rm722.py` fails if a
`test_p2w<N>_*.py` module is missing from this file or this file names one
that does not exist.

## Reading the name

`test_p2w<W>_<area>_<slice>.py`:

- `p2w<W>` - phase 2 (deep audit), wave W. Waves 1, 2 and 4 wrote test
  modules (`p2w1` = audit cycles 7-10, `p2w2` = cycles 11-12, `p2w4` =
  cycles 14-15).
- `<area>` and `<slice>` - the part of the tree the slice audited and its
  letter. Each module pins the fixes that slice landed, one test per fixed
  behaviour, written failing first.
- `..._symbol_cites_s144d33` - a later guard (RM-1053) that holds the
  parent module's prose to symbols instead of line numbers. It sits beside
  its parent and has no wave of its own.

## Wave 1 (P2-W1): app, coaches, core, dashboard

- `test_p2w1_app_a.py` - app / game_reader / modes / vision_server /
  modules: JSON-boundary NaN and Infinity coercion (audit cycle 10).
- `test_p2w1_app_b.py` - lcu post-game collector and client integer and
  champ-name handling (cycle 10).
- `test_p2w1_coach_a.py` - coaches/ base coach poll tick and the
  `_maybe_coach` previous-state argument (cycle 9).
- `test_p2w1_coach_b.py` - coaches/ draft profile, adaptation hint and
  related bounds and coercions (cycle 9).
- `test_p2w1_core_a.py` - core live-data spine: TFT snapshot defensive copy,
  live-client cache auth, replay history, match-metrics flush and the Riot
  API client (cycle 7).
- `test_p2w1_core_b.py` - core coach slice: coaching timestamps and the
  non-fatal write contract (cycle 7).
- `test_p2w1_core_c.py` - core build / DS adjacency: the WPA catalog
  defaults (cycle 7).
- `test_p2w1_core_d.py` - core post-game and stats: death-pattern loader
  fail-soft behaviour (cycle 7).
- `test_p2w1_core_e.py` - core archetype / vision: pytesseract subprocess
  hardening (cycle 7).
- `test_p2w1_core_f.py` - core infra / metrics / workers: `polled_json`
  atomic write retry (cycle 7).
- `test_p2w1_dash_a.py` - dashboard spine, infra and bridge: web asset
  path-traversal hardening (cycle 8).
- `test_p2w1_dash_b.py` - the `/api/state` hot-path pipeline: the
  adaptation latch no-raise contract (cycle 8).
- `test_p2w1_dash_c.py` - champ-select and lobby routes (`routes_pickban`)
  (cycle 8).
- `test_p2w1_dash_d.py` - the Daemon Slayer dashboard routes, one test class
  per fixed behaviour (cycle 8).
- `test_p2w1_route_symbol_cites_s144d33.py` - symbol-cite guard for
  `test_p2w1_dash_d.py`.
- `test_p2w1_dash_e.py` - post-game, WPA and builders surface: the shared
  per-thread connection that `_build_last_match` closed (cycle 8).

## Wave 2 (P2-W2): Daemon Slayer engine and the Phase 3 supervisor

- `test_p2w2_ds_a.py` - missile travel time and other non-finite inputs to
  the combat-math engine (cycle 11).
- `test_p2w2_ds_a_symbol_cites_s144d33.py` - symbol-cite guard for slice A.
- `test_p2w2_ds_b.py` - `antitank` effective-magnitude and finite-float
  hardening (cycle 11).
- `test_p2w2_ds_b_symbol_cites_s144d33.py` - symbol-cite guard for slice B.
- `test_p2w2_ds_c.py` - `ability_hps` NaN and infinity boundary guard
  (cycle 11).
- `test_p2w2_ds_d.py` - effects data: the effect-application boundary in
  `_effects_types` (cycle 12).
- `test_p2w2_ds_d_symbol_cites_s144d33.py` - symbol-cite guard for slice D.
- `test_p2w2_ds_e.py` - non-finite resist propagation and canonical-id-key
  resolution (cycle 12).
- `test_p2w2_ds_e_symbol_cites_s144d33.py` - symbol-cite guard for slice E.
- `test_p2w2_ds_f.py` - the DS combat-math engine and its `:8860` HTTP
  server (cycle 11).
- `test_p2w2_ds_g.py` - `fight_report`, `mana_sim` and `data_loader`
  coercions, such as a non-finite mana pool (cycle 12).
- `test_p2w2_ds_g_symbol_cites_s144d33.py` - symbol-cite guard for slice G.
- `test_p2w2_ds_h.py` - Phase 3 supervisor set (`agents/_supervisor_*`)
  (cycle 12). Slice H is the supervisor, not the DS engine, despite the
  `ds` in the name.
- `test_p2w2_ds_h_symbol_cites_s144d33.py` - symbol-cite guard for slice H.

## Wave 4 (P2-W4): ops, scripts, tft, repo root and tools

Half-wave 2 (audit cycle 15):

- `test_p2w4_hw2_a.py` - ops runtime spine: `rc_state_validator`.
- `test_p2w4_hw2_b.py` - `ops/phase3_*` and the headless-audit loop
  controller under `ops/loop/`.
- `test_p2w4_hw2_d.py` - scripts/ data pipeline and match / rewind deep.
- `test_p2w4_hw2_e.py` - scripts/ extractors, builders, audit and
  pre-commit gates.
- `test_p2w4_hw2_f.py` - tft/ parse, aggregate and error-path helpers.
- `test_p2w4_hw2_h.py` - repo-root surface files such as
  `performance_tracker`.

Tools slices (audit cycle 14):

- `test_p2w4_tools_b.py` - the DS upstream extractors (ddragon / cdragon /
  wiki into Daemon Slayer data).
- `test_p2w4_tools_d.py` - DS tooling: the match-DB MCP server, generators,
  prefilters, build scorers and launchers (the review-mirror sync tools it
  once covered were deleted).
- `test_p2w4_tools_e.py` - the champion-loadout family of live validators
  and generators.
- `test_p2w4_tools_g.py` - packaging, install, boot, cert and gate tools.
- `test_p2w4_tools_h.py` - live-utility, cost, drift and dev tooling, such
  as the cost-health watchdog.

## Other name tags

- `_rm<NNN>` suffix - the BACKLOG row the module closes (`ROADMAP.md` /
  `BACKLOG.md` carry the row).
- `_s144<lane><NN>` suffix - the session-144 lane item that added it
  (provenance only).
