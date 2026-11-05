"""s144 true-audit cycle 134 - core/coach_output.py hardening.

The `choices` decode is the one seam all four live coaches (ARAM / Arena /
Brawl via `CoachOutput.from_fields`, SR via `coach_integration/_coach.py`)
route the model's native-emit choices array through before it is written into
data/*_coaching_data.json by `json.dumps` with the default allow_nan=True.

Findings pinned here:
  F1  a NaN / Infinity / -Infinity token or an overflowing literal (1e400)
      decoded to a non-finite float and reached the artifact as a bare NaN /
      Infinity token - not valid JSON for any strict reader.
  F2  an already-decoded list passed through unvalidated: a set, bytes, an
      object, a non-str dict key, a self-referencing list or a non-finite
      float made the artifact's json.dumps raise, so the coach's whole tick
      write failed (safe_write returns False and the panel goes stale).
  F3  from_fields raised TypeError on a non-mapping or a non-str key instead
      of degrading to no choices.
  F4  the decode's blind `except Exception` is narrowed to the two errors
      json.loads raises on a str (ValueError, RecursionError).
"""
from __future__ import annotations

import json
import math

import pytest

from core import coach_output
from core.coach_output import CoachOutput, decode_choices


def _strict(obj) -> str:
    """Serialise the way a strict JSON reader would demand."""
    return json.dumps(obj, allow_nan=False, indent=2)


# ---------------------------------------------------------------- F1


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity", "1e400", "-1e400"])
def test_non_finite_number_in_string_decodes_to_none(token):
    raw = '[{"key":"A","label":"hold","confidence":' + token + "}]"
    out = decode_choices(raw)
    assert out == [{"key": "A", "label": "hold", "confidence": None}]
    _strict(out)


def test_non_finite_nested_and_top_level_entries_keep_the_rest():
    raw = '[NaN, {"key":"B","label":"push","x":[1, Infinity, {"y": -Infinity}]}]'
    out = decode_choices(raw)
    assert out == [None, {"key": "B", "label": "push", "x": [1, None, {"y": None}]}]
    _strict(out)


def test_sr_json_object_fallback_shape_is_strict_after_decode():
    # coach_integration/_coach.py re-dumps a non-str choices value with
    # json.dumps (allow_nan default), so a model NaN arrives as "NaN" text.
    redumped = json.dumps([{"key": "A", "label": "x", "w": float("nan")}])
    assert "NaN" in redumped
    out = CoachOutput.from_fields({"choices": redumped}).choices
    assert out == [{"key": "A", "label": "x", "w": None}]
    _strict({"choices": out})


def test_finite_numbers_unchanged():
    out = decode_choices('[{"key":"A","label":"x","n":3,"f":0.25,"b":true,"z":null}]')
    assert out == [{"key": "A", "label": "x", "n": 3, "f": 0.25, "b": True, "z": None}]
    assert out[0]["b"] is True


# ---------------------------------------------------------------- F2


class _Obj:
    pass


@pytest.mark.parametrize("junk", [{1, 2}, b"bytes", _Obj(), frozenset({1}), 1 + 2j])
def test_list_passthrough_non_json_leaf_is_none(junk):
    out = decode_choices([{"key": "A", "label": "x", "v": junk}])
    assert out == [{"key": "A", "label": "x", "v": None}]
    _strict(out)


def test_list_passthrough_non_finite_float_is_none():
    out = decode_choices([float("nan"), {"k": float("inf")}, -float("inf"), 1.5])
    assert out == [None, {"k": None}, None, 1.5]
    _strict(out)


def test_list_passthrough_non_str_dict_key_dropped():
    out = decode_choices([{"key": "A", (1, 2): "tuple-key", 7: "int-key", "label": "x"}])
    assert out == [{"key": "A", "label": "x"}]
    _strict(out)


def test_list_passthrough_tuple_becomes_list():
    out = decode_choices([{"key": "A", "pair": (1, 2)}])
    assert out == [{"key": "A", "pair": [1, 2]}]


def test_self_referencing_list_is_bounded_not_circular():
    loop: list = [{"key": "A", "label": "x"}]
    loop.append(loop)
    out = decode_choices(loop)
    _strict(out)  # a circular reference would raise ValueError here
    assert out[0] == {"key": "A", "label": "x"}


def test_depth_beyond_cap_is_none_and_never_raises():
    cap = coach_output._MAX_DEPTH
    deep: object = "leaf"
    for _ in range(cap + 5):
        deep = [deep]
    out = decode_choices([deep])
    _strict(out)
    node = out
    depth = 0
    while isinstance(node, list) and node:
        node = node[0]
        depth += 1
    assert node is None
    assert depth <= cap + 1


def test_oversized_int_is_none():
    out = decode_choices([{"key": "A", "big": 10 ** 5000, "ok": 2 ** 63}])
    assert out == [{"key": "A", "big": None, "ok": 2 ** 63}]
    _strict(out)


def test_wide_int_literal_in_string_is_none():
    out = decode_choices("[" + "9" * 30 + "]")
    assert out == [None]
    _strict(out)


def test_valid_list_passthrough_equal_and_not_aliased():
    v = [{"key": "A", "label": "x", "confidence": "high"}]
    out = decode_choices(v)
    assert out == v
    assert out is not v
    out[0]["label"] = "mutated"
    assert v[0]["label"] == "x"


def test_safe_write_shape_round_trips_after_hardening():
    # The coach writes the decoded list via json.dumps(data, indent=2); that
    # must not raise for any passthrough the model can no longer poison.
    out = CoachOutput.from_fields(
        {"choices": [{"key": "A", "v": {1, 2}, "w": float("nan")}]}
    ).choices
    json.dumps({"choices": out}, indent=2)


# ---------------------------------------------------------------- F3


@pytest.mark.parametrize("fields", [[("choices", "[1]")], "choices", 5, ("a", "b")])
def test_from_fields_non_mapping_is_no_choices(fields):
    assert CoachOutput.from_fields(fields).choices == []


def test_from_fields_non_str_key_dropped_rest_kept():
    model = CoachOutput.from_fields({1: "x", "action": "PUSH", "choices": '[{"key":"A"}]'})
    assert model.choices == [{"key": "A"}]
    art = model.to_artifact()
    assert art["action"] == "PUSH"
    assert 1 not in art


def test_from_fields_none_still_empty():
    assert CoachOutput.from_fields(None).to_artifact() == {"choices": []}


# ---------------------------------------------------------------- F4


def test_deeply_nested_string_is_empty_not_raised():
    raw = "[" * 100000 + "]" * 100000
    assert decode_choices(raw) == []


def test_decode_does_not_swallow_unexpected_errors(monkeypatch):
    def boom(*_a, **_k):
        raise KeyError("not a json error")

    monkeypatch.setattr(coach_output.json, "loads", boom)
    with pytest.raises(KeyError):
        decode_choices('[{"key":"A"}]')


@pytest.mark.parametrize("raw", ["", "   ", "not json", '{"a":1}', '"s"', "42", '[{"key":"A"'])
def test_malformed_or_non_list_still_empty(raw):
    assert decode_choices(raw) == []


def test_every_output_is_strict_json_for_mixed_junk():
    raws = [
        '[NaN]', '[1e999]', '[{"a":[Infinity]}]', '[[[[-Infinity]]]]',
        [float("nan")], [{"s": {1}}], [b"x"], [[[[[[[[[[[[[[[[[[["x"]]]]]]]]]]]]]]]]]]],
    ]
    for raw in raws:
        out = decode_choices(raw)
        _strict(out)
        for leaf in json.loads(json.dumps(out)):
            if isinstance(leaf, float):
                assert math.isfinite(leaf)
