"""RC2 P5.1 - core.laning_cv_overrides pure-decision tests.

Pins the spec-1.2 layer-1/2/3 CV override pipeline (enemy dead > enemy missing
> my low-HP-vs-aggressive), the fog-model enemy lookup by canonical id, the
confidence bands, and the fail-soft None on every missing/malformed input.
Pure - operates on synthetic in-memory vision_state dicts (no file, no network).
"""
from __future__ import annotations

from core import laning_cv_overrides as cvo
from core.coach_choices import CoachChoice


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


# --------------------------------------------------------------------------- #
# RC2 P5.2 - cv_choice_pair + apply_cv_to_choices (the served-chip integration)
# --------------------------------------------------------------------------- #
def _base_choices(a_label="Trade now", *, with_c=False):
    base = [
        CoachChoice(key="A", label=a_label, source_tag="ds-matchup"),
        CoachChoice(key="B", label="Farm safe", source_tag="ds-matchup"),
    ]
    if with_c:
        base.append(CoachChoice(key="C", label="Buy Kraken Slayer",
                                source_tag="ds-build"))
    return base


def test_cv_choice_pair_none_or_unknown_empty():
    assert cvo.cv_choice_pair(None) == []
    assert cvo.cv_choice_pair({"verdict": "bogus"}) == []
    assert cvo.cv_choice_pair("garbage") == []


def test_cv_choice_pair_shove():
    ov = {"verdict": "shove", "confidence": "high",
          "reason": "Enemy dead 15s - shove + take plates/prio",
          "kind": "enemy_dead"}
    pair = cvo.cv_choice_pair(ov)
    assert [c.key for c in pair] == ["A", "B"]
    assert pair[0].label == "Shove + take plates/prio"
    assert pair[0].confidence == "high"
    assert pair[0].source_tag == "cv-laning"
    assert "15s" in pair[0].expected_outcome
    assert pair[1].label == "Hold"
    assert all(c.source_tag == "cv-laning" for c in pair)


def test_apply_cv_no_override_returns_base_unchanged():
    vs = _vs({"Zed": _enemy("Zed", visible=True)})
    base = _base_choices()
    out = cvo.apply_cv_to_choices(base, "Zed", 0.9, base_verdict="even",
                                  vision_state=vs)
    assert out is base  # identity - no copy, no mutation


def test_apply_cv_enemy_dead_drives_shove_preserves_c():
    vs = _vs({"Zed": _enemy("Zed", is_dead=True, respawn=15.0, visible=False)})
    base = _base_choices(with_c=True)
    out = cvo.apply_cv_to_choices(base, "Zed", 0.9, base_verdict="back_off",
                                  vision_state=vs)
    assert [c.key for c in out] == ["A", "B", "C"]
    assert out[0].label == "Shove + take plates/prio"
    assert out[0].confidence == "high"
    assert out[0].source_tag == "cv-laning"
    assert "15s" in out[0].expected_outcome
    # the build 'C' choice is preserved from the base set.
    assert out[2].label == "Buy Kraken Slayer"
    assert out[2].source_tag == "ds-build"


def test_apply_cv_enemy_missing_drives_back_off():
    vs = _vs({"Zed": _enemy("Zed", visible=False, missing=6.0)})
    out = cvo.apply_cv_to_choices(_base_choices(), "Zed", 0.9,
                                  base_verdict="trade", vision_state=vs)
    assert out[0].label == "Back off + ward"
    assert out[0].confidence == "mid"
    assert out[0].source_tag == "cv-laning"


def test_apply_cv_low_hp_drives_disengage():
    vs = _vs({"Zed": _enemy("Zed", visible=True)})
    out = cvo.apply_cv_to_choices(_base_choices(), "Zed", 0.20,
                                  base_verdict="all_in", vision_state=vs)
    assert out[0].label == "Disengage"
    assert out[0].confidence == "high"
    assert out[0].source_tag == "cv-laning"


def test_apply_cv_low_hp_ignored_when_verdict_passive():
    vs = _vs({"Zed": _enemy("Zed", visible=True)})
    base = _base_choices()
    out = cvo.apply_cv_to_choices(base, "Zed", 0.20, base_verdict="even",
                                  vision_state=vs)
    assert out is base


def test_apply_cv_empty_base_still_emits_pair():
    vs = _vs({"Zed": _enemy("Zed", is_dead=True, respawn=10.0)})
    out = cvo.apply_cv_to_choices([], "Zed", 0.9, base_verdict="back_off",
                                  vision_state=vs)
    assert [c.key for c in out] == ["A", "B"]
    assert out[0].source_tag == "cv-laning"


def test_apply_cv_failsoft_on_garbage_returns_base():
    base = _base_choices()
    out = cvo.apply_cv_to_choices(base, None, "x", base_verdict=None,
                                  vision_state="garbage")
    assert out is base
