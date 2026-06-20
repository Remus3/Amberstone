"""RC2 P5.1 - core.laning_cv_overrides pure-decision tests.

Pins the spec-1.2 layer-1/2/3 CV override pipeline (enemy dead > enemy missing
> my low-HP-vs-aggressive), the fog-model enemy lookup by canonical id, the
confidence bands, and the fail-soft None on every missing/malformed input.
Pure - operates on synthetic in-memory vision_state dicts (no file, no network).
"""
from __future__ import annotations

from core import laning_cv_overrides as cvo


# --------------------------------------------------------------------------- #
# Synthetic vision_state (matches core.vision_tracker output shape)
# --------------------------------------------------------------------------- #
def _vs(enemies: dict) -> dict:
    return {"game_mode": "CLASSIC", "enemies": enemies, "summary": {}}


def _enemy(champ, *, is_dead=False, respawn=None, visible=True, missing=None,
           zone="lane"):
    return {
        "champion": champ, "is_dead": is_dead, "respawn_in_s": respawn,
        "visible": visible, "missing_for_s": missing, "last_seen_zone": zone,
    }


# --------------------------------------------------------------------------- #
# enemy_cv_status - canonical-id lookup
# --------------------------------------------------------------------------- #
def test_status_matches_display_name():
    vs = _vs({"Caitlyn": _enemy("Caitlyn", missing=8.0, visible=False)})
    st = cvo.enemy_cv_status(vs, "Caitlyn")
    assert st["visible"] is False
    assert st["missing_for_s"] == 8.0


def test_status_matches_canonical_spacing():
    # display "Tahm Kench" must match a fog key canonicalizing to TahmKench.
    vs = _vs({"TahmKench": _enemy("TahmKench", is_dead=True, respawn=20.0)})
    st = cvo.enemy_cv_status(vs, "Tahm Kench")
    assert st["is_dead"] is True


def test_status_absent_enemy_empty():
    vs = _vs({"Annie": _enemy("Annie")})
    assert cvo.enemy_cv_status(vs, "Zed") == {}


def test_status_malformed_empty():
    assert cvo.enemy_cv_status({}, "Zed") == {}
    assert cvo.enemy_cv_status(None, "Zed") == {}
    assert cvo.enemy_cv_status({"enemies": "x"}, "Zed") == {}


# --------------------------------------------------------------------------- #
# cv_override - layer 1: enemy dead -> shove
# --------------------------------------------------------------------------- #
def test_dead_enemy_shoves_high():
    st = _enemy("Zed", is_dead=True, respawn=18.0, visible=False)
    ov = cvo.cv_override(st, 0.9, "back_off")
    assert ov is not None
    assert ov["verdict"] == "shove"
    assert ov["confidence"] == "high"
    assert ov["kind"] == "enemy_dead"
    assert "18s" in ov["reason"]


def test_dead_enemy_unknown_respawn_still_shoves():
    st = _enemy("Zed", is_dead=True, respawn=None, visible=False)
    ov = cvo.cv_override(st, 0.9, "trade")
    assert ov is not None and ov["verdict"] == "shove"


def test_dead_outranks_missing_and_low_hp():
    # is_dead wins even when I am low HP and the static verdict is aggressive.
    st = _enemy("Zed", is_dead=True, respawn=10.0, visible=False, missing=30.0)
    ov = cvo.cv_override(st, 0.10, "all_in")
    assert ov["kind"] == "enemy_dead"


# --------------------------------------------------------------------------- #
# cv_override - layer 2: enemy missing -> back off
# --------------------------------------------------------------------------- #
def test_missing_enemy_backs_off_mid():
    st = _enemy("Zed", visible=False, missing=5.0)
    ov = cvo.cv_override(st, 0.9, "trade")
    assert ov is not None
    assert ov["verdict"] == "back_off"
    assert ov["confidence"] == "mid"
    assert ov["kind"] == "enemy_missing"


def test_missing_under_threshold_no_override():
    st = _enemy("Zed", visible=False, missing=1.0)
    assert cvo.cv_override(st, 0.9, "trade") is None


def test_visible_enemy_not_missing():
    st = _enemy("Zed", visible=True, missing=None)
    assert cvo.cv_override(st, 0.9, "trade") is None


# --------------------------------------------------------------------------- #
# cv_override - layer 3: my low HP vs an aggressive verdict -> disengage
# --------------------------------------------------------------------------- #
def test_low_hp_disengages_aggressive():
    st = _enemy("Zed", visible=True)
    ov = cvo.cv_override(st, 0.20, "all_in")
    assert ov is not None
    assert ov["verdict"] == "disengage"
    assert ov["confidence"] == "high"
    assert ov["kind"] == "low_hp"


def test_low_hp_ignored_when_verdict_passive():
    st = _enemy("Zed", visible=True)
    # hold / even / back_off are already safe - low HP adds nothing.
    assert cvo.cv_override(st, 0.20, "hold") is None
    assert cvo.cv_override(st, 0.20, "back_off") is None


def test_low_hp_fires_even_without_enemy_status():
    # my HP is my own state; an empty fog status must not block the disengage.
    ov = cvo.cv_override({}, 0.10, "trade")
    assert ov is not None and ov["kind"] == "low_hp"


def test_healthy_hp_no_override():
    st = _enemy("Zed", visible=True)
    assert cvo.cv_override(st, 0.95, "all_in") is None


def test_none_hp_no_low_hp_override():
    st = _enemy("Zed", visible=True)
    assert cvo.cv_override(st, None, "all_in") is None


def test_empty_status_no_enemy_layers():
    assert cvo.cv_override({}, 0.9, "trade") is None


# --------------------------------------------------------------------------- #
# resolve_cv_override - glue (preloaded dict + fail-soft loader)
# --------------------------------------------------------------------------- #
def test_resolve_with_preloaded_vision_state():
    vs = _vs({"Caitlyn": _enemy("Caitlyn", is_dead=True, respawn=12.0)})
    ov = cvo.resolve_cv_override("Caitlyn", 0.9, "back_off", vision_state=vs)
    assert ov["kind"] == "enemy_dead"


def test_resolve_missing_file_returns_none(tmp_path):
    ov = cvo.resolve_cv_override(
        "Caitlyn", 0.9, "trade", path=tmp_path / "nope.json")
    assert ov is None


def test_resolve_never_raises_on_garbage():
    assert cvo.resolve_cv_override(None, "x", None, vision_state="garbage") is None


def test_load_vision_state_missing_file(tmp_path):
    assert cvo.load_vision_state(tmp_path / "absent.json") == {}
