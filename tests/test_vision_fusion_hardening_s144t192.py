"""core.vision_fusion hardening (s144 true-audit cycle 192).

Each test pins one measured defect of the fail-soft fusion layer that sits on
the live vision tick (modes/shared_vision._log_fusion_shadow). CV values come
from OCR or a Sonnet JSON reply, and json.loads accepts NaN, Infinity and
unbounded integers, so every hostile value below is reachable from a reply.
"""
from __future__ import annotations

import math
import types

from core import vision_fusion as vf
from core.vision_fusion import fuse_reads, is_plausible_cv

NAN = float("nan")
INF = float("inf")


# -- is_plausible_cv: non-finite and overflowing reads ------------------------

def test_nan_cv_read_is_implausible_for_ranged_and_unranged_fields():
    assert is_plausible_cv("cs", NAN, 40) is False
    assert is_plausible_cv("gold", NAN, 8703) is False
    assert is_plausible_cv("hp", NAN) is False
    assert is_plausible_cv("level", NAN, None) is False


def test_nan_cv_never_beats_a_stale_liveclient_value():
    for field, lc in (("cs", 40), ("gold", 8703), ("level", 6)):
        res = fuse_reads({field: lc}, {field: NAN}, live_stale=True)
        assert res[field]["source"] == "liveclient", field
        assert res[field]["value"] == lc
        assert "cv_implausible:" + field in res["_notes"]


def test_infinite_cv_read_is_implausible_even_without_an_anchor():
    assert is_plausible_cv("hp", INF) is False
    assert is_plausible_cv("hp", -INF, None) is False


def test_int_beyond_float_range_is_implausible_not_fail_open():
    huge = 10 ** 400
    assert is_plausible_cv("cs", huge, 40) is False
    assert is_plausible_cv("hp", -huge) is False
    res = fuse_reads({"cs": 40}, {"cs": huge}, live_stale=True)
    assert res["cs"]["source"] == "liveclient"
    assert res["cs"]["value"] == 40


def test_non_finite_or_overflowing_anchor_is_no_anchor():
    # A junk Live Client anchor must not reject a sane CV read, and must not
    # make an out-of-range one plausible either: only the range rule applies.
    assert is_plausible_cv("cs", 40, INF) is True
    assert is_plausible_cv("cs", 40, NAN) is True
    assert is_plausible_cv("cs", 40, 10 ** 400) is True
    assert is_plausible_cv("cs", 5000, NAN) is False


def test_numeric_subclass_cannot_redirect_the_gate():
    class Liar(int):
        def __float__(self):
            raise RuntimeError("boom")

        def __lt__(self, other):
            return False

        def __gt__(self, other):
            return False

    # Value 5000 is outside the cs range whatever the subclass claims.
    assert is_plausible_cv("cs", Liar(5000), 40) is False
    assert is_plausible_cv("cs", Liar(45), 40) is True


def test_existing_open_defaults_still_hold():
    assert is_plausible_cv("unknown_field", object(), object()) is True
    assert is_plausible_cv("gold", None, None) is True
    assert is_plausible_cv("kda", "5/2/9", "4/2/9") is True
    assert is_plausible_cv("gold", 100, None) is True
    assert is_plausible_cv(["unhashable"], 1, 2) is True


# -- _cv_conf: measured confidence map ----------------------------------------

def test_nan_confidence_degrades_to_default_not_nan():
    res = fuse_reads({}, {"hp": 5}, cv_confidence={"hp": NAN})
    conf = res["hp"]["confidence"]
    assert math.isfinite(conf)
    assert conf == vf.CV_DEFAULT_CONF
    res = fuse_reads({}, {"hp": 5}, cv_confidence={"hp": "nan"})
    assert res["hp"]["confidence"] == vf.CV_DEFAULT_CONF


def test_overflowing_confidence_does_not_drop_the_whole_fusion():
    res = fuse_reads({"gold": 5}, {"hp": 5}, cv_confidence={"hp": 10 ** 400})
    assert res["gold"]["value"] == 5
    assert res["hp"]["confidence"] == 1.0
    res = fuse_reads({"gold": 5}, {"hp": 5}, cv_confidence={"hp": -(10 ** 400)})
    assert res["hp"]["confidence"] == 0.0


def test_bool_confidence_is_not_a_score():
    res = fuse_reads({}, {"hp": 5}, cv_confidence={"hp": True})
    assert res["hp"]["confidence"] == vf.CV_DEFAULT_CONF


def test_numeric_string_confidence_still_accepted():
    res = fuse_reads({}, {"hp": 5}, cv_confidence={"hp": "0.9"})
    assert res["hp"]["confidence"] == 0.9


def test_non_mapping_confidence_is_ignored_not_fatal():
    for junk in (5, 1.5, object(), ["hp"], "hp"):
        res = fuse_reads({"gold": 5}, {"hp": 5}, cv_confidence=junk)
        assert res["gold"]["value"] == 5, junk
        assert res["hp"]["confidence"] == vf.CV_DEFAULT_CONF, junk


def test_duck_typed_non_mapping_confidence_is_not_honored():
    class Duck:
        def __contains__(self, key):
            return True

        def __getitem__(self, key):
            return 0.95

    res = fuse_reads({}, {"hp": 5}, cv_confidence=Duck())
    assert res["hp"]["confidence"] == vf.CV_DEFAULT_CONF


def test_raising_confidence_mapping_is_ignored():
    class Bad(dict):
        def __contains__(self, key):
            raise RuntimeError("nope")

    res = fuse_reads({"gold": 5}, {"hp": 5}, cv_confidence=Bad(hp=0.9))
    assert res["gold"]["value"] == 5
    assert res["hp"]["confidence"] == vf.CV_DEFAULT_CONF


# -- fuse_reads: input shapes -------------------------------------------------

def test_non_container_gap_fields_do_not_drop_the_whole_fusion():
    for junk in (7, 1.5, True, object()):
        res = fuse_reads({"gold": 5}, {"hp": 5}, api_gap_fields=junk)
        assert res["gold"]["value"] == 5, junk
        assert res["hp"]["source"] == "cv", junk
        assert "api_gap_fields_ignored" in res["_notes"], junk


def test_string_gap_fields_is_one_field_not_a_substring_set():
    res = fuse_reads({"a": 5}, {"a": 6}, api_gap_fields="augment_choices")
    assert res["a"]["source"] == "liveclient"
    res = fuse_reads(
        {"augment_choices": 1}, {"augment_choices": 2},
        api_gap_fields="augment_choices",
    )
    assert res["augment_choices"]["source"] == "cv"


def test_gap_fields_list_with_unhashable_member_keeps_the_rest():
    res = fuse_reads(
        {"augment_choices": 1}, {"augment_choices": 2},
        api_gap_fields=[["x"], "augment_choices"],
    )
    assert res["augment_choices"]["source"] == "cv"


def test_unbounded_gap_iterator_returns():
    import itertools

    res = fuse_reads({"gold": 5}, {}, api_gap_fields=itertools.count())
    assert res["gold"]["source"] == "liveclient"
    assert "api_gap_fields_ignored" in res["_notes"]


def test_gap_fields_generator_and_list_still_work():
    gen = (f for f in ["augment_choices"])
    res = fuse_reads({}, {"augment_choices": 2}, api_gap_fields=gen)
    assert "cv_gap:augment_choices" in res["_notes"]
    res = fuse_reads({}, {"augment_choices": 2}, api_gap_fields=["augment_choices"])
    assert "cv_gap:augment_choices" in res["_notes"]


def test_string_false_live_stale_is_not_stale():
    for flag in ("false", "0", "no", "", "off", "False", 0, 0.0, NAN, None):
        res = fuse_reads({"gold": 500}, {"gold": 520}, live_stale=flag)
        assert res["gold"]["source"] == "liveclient", repr(flag)
        assert res["gold"]["confidence"] == vf.LIVECLIENT_CONF, repr(flag)


def test_true_spellings_of_live_stale_still_stale():
    for flag in (True, "true", "1", "yes", " TRUE ", 1, 2.0):
        res = fuse_reads({"gold": 500}, {"gold": 520}, live_stale=flag)
        assert res["gold"]["source"] == "cv", repr(flag)


def test_raising_live_stale_reads_fresh():
    class Bad:
        def __bool__(self):
            raise RuntimeError("nope")

    res = fuse_reads({"gold": 500}, {"gold": 520}, live_stale=Bad())
    assert res["gold"]["source"] == "liveclient"


def test_field_named_notes_cannot_clobber_provenance():
    res = fuse_reads({"_notes": 3, "gold": 1}, {"_notes": "x"})
    assert isinstance(res["_notes"], list)
    assert all(isinstance(n, str) for n in res["_notes"])
    assert "lc_exact:_notes" not in res["_notes"]
    assert "reserved_field:_notes" in res["_notes"]
    assert res["gold"]["value"] == 1


def test_non_dict_mapping_inputs_are_read():
    lc = types.MappingProxyType({"gold": 5})
    cv = types.MappingProxyType({"hp": 7})
    res = fuse_reads(lc, cv)
    assert res["gold"]["value"] == 5
    assert res["hp"]["value"] == 7


def test_non_mapping_inputs_are_noted_not_silent():
    res = fuse_reads([("gold", 5)], "gold")
    assert "live_client_ignored" in res["_notes"]
    assert "cv_reads_ignored" in res["_notes"]
    res = fuse_reads(None, None)
    assert res["_notes"] == []


def test_one_bad_key_drops_only_that_field():
    class K:
        def __hash__(self):
            return 1

        def __eq__(self, other):
            return self is other

        def __str__(self):
            raise RuntimeError("x")

        def __repr__(self):
            raise RuntimeError("x")

    res = fuse_reads({"gold": 5, K(): 1}, {"hp": 2})
    assert res["gold"]["value"] == 5
    assert res["hp"]["value"] == 2
    assert "field_error" in res["_notes"]


def test_str_subclass_key_label_ignores_overridden_str():
    class S(str):
        def __str__(self):
            raise RuntimeError("x")

    res = fuse_reads({S("gold"): 5}, {})
    assert "lc_exact:gold" in res["_notes"]


def test_inputs_are_snapshotted_not_aliased():
    lc = {"gold": 5}
    cv = {"hp": 7}
    fuse_reads(lc, cv, live_stale=True)
    assert lc == {"gold": 5}
    assert cv == {"hp": 7}


def test_output_is_strict_json_for_hostile_numerics():
    import json

    res = fuse_reads(
        {"gold": 500}, {"gold": NAN, "hp": 4},
        live_stale=True, cv_confidence={"hp": NAN, "gold": INF},
    )
    # Confidences are always finite; the stale LC value wins over the NaN.
    for key, entry in res.items():
        if key == "_notes":
            continue
        assert math.isfinite(entry["confidence"])
    json.dumps({k: v for k, v in res.items() if k != "_notes" and k != "hp"},
               allow_nan=False)
