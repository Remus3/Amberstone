"""
coaches/__init__.py
Coach package. Coaches are imported by module path: the game-start router
(app/_game_lifecycle.py) builds each mode's coach from
core/coach_registry.py MODE_COACH_MAP.

RM-292 (b): the dynamic loader that used to live here (load_coach,
unload_all, a mode table and a config toggle routing TFT to a PBE
coach) had no caller since the initial commit and was retired with the
PBE coach subsystem; tests/test_rm292b_pbe_coach_retired.py pins that.
"""
