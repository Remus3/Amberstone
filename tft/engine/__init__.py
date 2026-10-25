"""tft/engine - the TFT comp / item engine (ADR-018, docs/TFT_PROGRAM.md section 5).

A separate in-process package, NOT part of Daemon Slayer: pure stdlib
functions, deterministic, no network, no LLM, no clock, no randomness. It
learns only from game data (the set extract read through tft/tft_set.py) and
the operator's own matches (final boards plus the per-round store).

The engine's display name lives in ONE place, ENGINE_NAME below; every UI
label and API payload reads it from there (engine_meta()), so a rename is a
one-line change. A guard (tests/test_tft_engine_guards.py) fails if the name
appears in any other source file. Package, module and route names stay
neutral ("engine") for the same reason.

ENGINE_SCHEMA versions the payload shapes this package returns; bump it when
a payload key changes meaning or disappears.

Modules:
  comps       set data view, board normalisation, traits, carry, comp catalogue
  milestones  per-match milestone mining from the per-round store + medians
  recommend   live recommendations and the prior-top-4 planner-picker payload
  compare     board power compare (own versus an opponent / the lobby)
"""
from __future__ import annotations

ENGINE_NAME = "Augur"
ENGINE_SCHEMA = 1


def engine_meta() -> dict:
    """The name / schema stamp every engine payload carries."""
    return {"engine": ENGINE_NAME, "schema": ENGINE_SCHEMA}
