"""core.build_planner - overlay adaptive-build planning package (WP-C).

Package marker only. WP-C1 lands ``kit_synergy`` here: a champion-kit vs item
synergy scorer that mirrors the ``core.archetype_picks`` data-loader pattern and
NEVER imports the DS engine (split-brain guard
``test_routes_state_has_no_in_process_engine_import`` in
tests/test_ds_preview_e2e_p1l21.py).
"""
