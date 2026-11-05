"""True-audit s144 cycle 118: coaches/sr_draft_profile.py hardening.

One test (or small group) per finding RM-1481..RM-1494. Every engine call is
faked through the module's OWN urlopen (tests/_module_view.bind_urlopen) or
by replacing `_call_beam`, so nothing here reaches a real :8860.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import types
import urllib.error
from io import BytesIO

import pytest

import coaches.sr_draft_profile as sdp
from tests._module_view import bind_urlopen

_GOOD_TOP = {
    "item_ids": ["3031", "3036", "3085", "3033", "6672", "3032"],
    "item_names": ["A", "B", "C", "D", "E", "F"],
    "total_gold": 18550,
    "final_dps": 814.86,
    "baseline_dps": 37.01,
    "delta_dps": 777.85,
    "dps_per_1k_gold": 41.93,
}
_GOOD_BEAM = {"engine_version": "0.9.3", "ranked": [_GOOD_TOP]}
# The real presets loader, captured before the autouse fixture swaps it.
_REAL_LOAD = sdp._load_presets


class _Resp:
    def __init__(self, payload: bytes):
        self._buf = BytesIO(payload)

    def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(payload, sink=None):
    if isinstance(payload, (bytes, bytearray)):
        raw = bytes(payload)
    else:
        raw = json.dumps(payload).encode("utf-8")

    def _open(req, **kw):
        if sink is not None:
            sink.append(req)
        return _Resp(raw)
    return _open


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    sdp.clear_cache()
    # Presets: always the in-module fallback unless a test says otherwise.
    monkeypatch.setattr(sdp, "_load_presets", lambda: sdp._FALLBACK_PRESETS)
    yield
    sdp.clear_cache()


# -- RM-1481: queue gate ------------------------------------------------


@pytest.mark.parametrize("qid", [float("inf"), float("-inf"), 1e400, 10 ** 400])
def test_t161_queue_gate_survives_overflow(qid):
    assert sdp.is_sr_draft_queue(qid) is False


@pytest.mark.parametrize("qid", [420.5, True, False, float("nan"), "420.0", b"420", {}])
def test_t161_queue_gate_rejects_non_integral(qid):
    assert sdp.is_sr_draft_queue(qid) is False


@pytest.mark.parametrize("qid", [420, 420.0, "420", " 440 "])
def test_t161_queue_gate_keeps_integral_forms(qid):
    assert sdp.is_sr_draft_queue(qid) is True


def test_t161_envelope_queue_id_is_normalized(monkeypatch):
    monkeypatch.setattr(sdp, "_call_beam", lambda c, p: ({}, "engine unreachable"))
    assert sdp.build_profile("Ahri", queue_id="420")["queue_id"] == 420
    sdp.clear_cache()
    assert sdp.build_profile("Ahri", queue_id=float("inf"))["queue_id"] is None


# -- RM-1482: team signature --------------------------------------------


def test_t162_team_sig_survives_overflow_and_rejects_non_ids():
    sig = sdp._team_sig([
        {"championId": float("inf")},
        {"championId": True},
        {"championId": 12.5},
        {"championId": -7},
        {"championId": 22},
        {"championId": "18"},
    ])
    assert sig == (18, 22)


# -- RM-1483: champion validation ---------------------------------------


@pytest.mark.parametrize("champ", [None, {"a": 1}, ["Ahri"], "", "   ", 42, "x" * 500],
                         ids=["none", "dict", "list", "empty", "blank", "int", "long"])
def test_t163_bad_champion_never_calls_engine_or_raises(monkeypatch, champ):
    calls = []
    monkeypatch.setattr(sdp, "_call_beam", lambda c, p: calls.append(c) or ({}, "x"))
    env = sdp.build_profile(champ, role="MIDDLE", queue_id=420)
    assert calls == []
    assert env["profiles"] == []
    assert env["champion"] is None
    assert env["notes"] and all(isinstance(n, str) for n in env["notes"])
    assert sdp._PROFILE_CACHE == {}


def test_t163_champion_is_stripped(monkeypatch):
    seen = []
    monkeypatch.setattr(sdp, "_call_beam", lambda c, p: seen.append(c) or ({}, "x"))
    env = sdp.build_profile("  Ahri ", queue_id=420)
    assert env["champion"] == "Ahri"
    assert set(seen) == {"Ahri"}


# -- RM-1484: preset numeric coercion -----------------------------------


def _capture_body(monkeypatch, preset):
    reqs: list = []
    bind_urlopen(monkeypatch, sdp, _opener(_GOOD_BEAM, reqs))
    resp, err = sdp._call_beam("Ahri", preset)
    assert reqs, "engine fake never reached"
    return json.loads(reqs[0].data.decode("utf-8")), resp, err


@pytest.mark.parametrize("bad", ["eleven", None, float("nan"), float("inf"), True, [], 1e400, -3, 99])
def test_t164_junk_level_falls_back(monkeypatch, bad):
    body, _resp, err = _capture_body(monkeypatch, {"level": bad})
    assert err is None
    assert body["level"] == 11


@pytest.mark.parametrize("bad", ["x", float("nan"), float("inf"), -5.0, True, None])
def test_t164_junk_armor_never_ships_nan(monkeypatch, bad):
    body, _resp, _err = _capture_body(monkeypatch, {"target_armor": bad, "target_mr": bad})
    assert body["target_armor"] == 80.0
    assert body["target_mr"] == 50.0
    for v in body.values():
        if isinstance(v, float):
            assert math.isfinite(v)


def test_t164_good_values_pass_through(monkeypatch):
    body, _resp, _err = _capture_body(monkeypatch, {
        "level": 14, "target_armor": 150, "target_mr": "60", "slots": 5,
        "beam_width": 20, "top": 2, "phase": "late"})
    assert body["level"] == 14 and body["target_armor"] == 150.0
    assert body["target_mr"] == 60.0 and body["slots"] == 5
    assert body["beam_width"] == 20 and body["top"] == 2 and body["phase"] == "late"


@pytest.mark.parametrize("bad", ["LATE ", "midgame", 3, {"x": 1}])
def test_t164_bad_phase_is_omitted(monkeypatch, bad):
    body, _resp, _err = _capture_body(monkeypatch, {"phase": bad})
    assert "phase" not in body


def test_t164_build_profile_survives_junk_preset(monkeypatch):
    presets = dict(sdp._FALLBACK_PRESETS)
    presets["engine_query"] = {
        "primary": {"level": "eleven", "target_armor": float("nan"), "slots": "six"},
        "alt": {"level": float("inf")},
        "experimental": {"beam_width": None},
    }
    monkeypatch.setattr(sdp, "_load_presets", lambda: presets)
    bind_urlopen(monkeypatch, sdp, _opener(_GOOD_BEAM))
    env = sdp.build_profile("Ahri", role="MIDDLE", queue_id=420)
    assert len(env["profiles"]) == 3
    assert env["profiles"][0]["engine"]["level"] == 11
    json.dumps(env, allow_nan=False)


# -- RM-1485: raw engine errors never reach notes -----------------------


def test_t165_http_error_body_not_in_notes(monkeypatch, caplog):
    secret = "Traceback internal-detail-XYZ"
    err = urllib.error.HTTPError(
        "http://x", 500, "boom", {}, BytesIO(secret.encode()))  # type: ignore[arg-type]

    def _raise(req, **kw):
        raise err
    bind_urlopen(monkeypatch, sdp, _raise)
    with caplog.at_level(logging.WARNING, logger="rc.sr_draft"):
        env = sdp.build_profile("Sett", role="TOP", queue_id=420)
    assert env["profiles"] == []
    assert env["notes"] == [f"{k}: engine HTTP 500"
                            for k in ("primary", "alt", "experimental")]
    assert not any("internal-detail" in n for n in env["notes"])
    assert "internal-detail" in caplog.text


def test_t165_exception_text_not_in_notes(monkeypatch, caplog):
    def _raise(req, **kw):
        raise OSError("socket detail-ABC")
    bind_urlopen(monkeypatch, sdp, _raise)
    with caplog.at_level(logging.WARNING, logger="rc.sr_draft"):
        env = sdp.build_profile("Sett", role="TOP", queue_id=420)
    assert len(env["notes"]) == 3
    assert not any("detail-ABC" in n for n in env["notes"])
    assert "detail-ABC" in caplog.text


def test_t165_url_error_reason_not_in_notes(monkeypatch):
    def _raise(req, **kw):
        raise urllib.error.URLError("refused by host-detail-QQ")
    bind_urlopen(monkeypatch, sdp, _raise)
    env = sdp.build_profile("Sett", role="TOP", queue_id=420)
    assert all("unreachable" in n for n in env["notes"])
    assert not any("host-detail" in n for n in env["notes"])


def test_t165_unexpected_exception_surfaces(monkeypatch):
    def _raise(req, **kw):
        raise RuntimeError("a real bug")
    bind_urlopen(monkeypatch, sdp, _raise)
    with pytest.raises(RuntimeError):
        sdp._call_beam("Sett", {})


# -- RM-1486: non-dict engine body --------------------------------------


@pytest.mark.parametrize("payload", [[1, 2], None, "str", 7, b"not json", b"\xff\xfe"])
def test_t166_non_dict_body_is_an_error(monkeypatch, payload):
    bind_urlopen(monkeypatch, sdp, _opener(payload))
    env = sdp.build_profile("Ahri", queue_id=420)
    assert env["profiles"] == []
    assert len(env["notes"]) == 3
    assert env["engine_version"] is None


# -- RM-1487: bounded reads ---------------------------------------------


def test_t167_oversize_body_is_refused(monkeypatch):
    monkeypatch.setattr(sdp, "_MAX_RESPONSE_BYTES", 64)
    # Its first 65 bytes are VALID JSON, so only the size check refuses it.
    big = b"{}" + b" " * 500
    bind_urlopen(monkeypatch, sdp, _opener(big))
    resp, err = sdp._call_beam("Ahri", {})
    assert resp == {} and err and "malformed" in err


def test_t167_error_body_read_is_bounded():
    reads = []

    class _Body(BytesIO):
        def read(self, n=-1):
            reads.append(n)
            return super().read(n)
    exc = urllib.error.HTTPError(
        "http://x", 500, "boom", {}, _Body(b"y" * 100000))  # type: ignore[arg-type]
    text = sdp._read_error_body(exc)
    assert reads and all(0 < n <= sdp._MAX_ERROR_BODY_BYTES for n in reads)
    assert len(text) <= sdp._MAX_ERROR_BODY_BYTES


# -- RM-1488: engine_version shape --------------------------------------


@pytest.mark.parametrize("ver", [7, {"v": 1}, ["0.9"], "", "   ", "v" * 500],
                         ids=["int", "dict", "list", "empty", "blank", "long"])
def test_t168_non_str_engine_version_not_published(monkeypatch, ver):
    beam = {"engine_version": ver, "ranked": [_GOOD_TOP]}
    bind_urlopen(monkeypatch, sdp, _opener(beam))
    env = sdp.build_profile("Ahri", queue_id=420)
    # The /health fallback reads the same junk body, so nothing publishes.
    assert env["engine_version"] is None
    assert len(env["profiles"]) == 3


@pytest.mark.parametrize("payload", [[1], None, {"engine_version": 3}])
def test_t168_health_junk_returns_none(monkeypatch, payload):
    bind_urlopen(monkeypatch, sdp, _opener(payload))
    assert sdp._engine_version() is None


def test_t168_health_good_is_cached(monkeypatch):
    hits = []
    bind_urlopen(monkeypatch, sdp, _opener({"engine_version": " 1.2.3 "}, hits))
    assert sdp._engine_version() == "1.2.3"
    assert sdp._engine_version() == "1.2.3"
    assert len(hits) == 1


# -- RM-1486 (verifier round 1): a too-deeply-nested body ----------------


def test_t166_deeply_nested_body_is_malformed_not_recursion(monkeypatch):
    bind_urlopen(monkeypatch, sdp, _opener(b"[" * 200000))
    env = sdp.build_profile("Zed", queue_id=420)
    assert env["profiles"] == []
    assert env["notes"] == [f"{k}: engine returned a malformed response"
                            for k in ("primary", "alt", "experimental")]
    assert sdp._engine_version() is None


# -- wire types of echoed numbers are unchanged -----------------------------


def test_echoed_int_numbers_keep_int_type(monkeypatch):
    bind_urlopen(monkeypatch, sdp, _opener(_GOOD_BEAM))
    env = sdp.build_profile("Ahri", role="MIDDLE", queue_id=420)
    eng = env["profiles"][0]["engine"]
    assert eng["total_gold"] == 18550 and type(eng["total_gold"]) is int
    assert eng["target_armor"] == 80 and type(eng["target_armor"]) is int
    assert eng["level"] == 11 and type(eng["level"]) is int


# -- RM-1489: monotonic TTLs --------------------------------------------


def test_t169_profile_ttl_ignores_wall_clock_step(monkeypatch):
    clock = {"m": 1000.0}
    fake_time = types.SimpleNamespace(
        time=lambda: 0.0,  # wall clock frozen far in the past
        monotonic=lambda: clock["m"],
        sleep=lambda s: None,
    )
    monkeypatch.setattr(sdp, "time", fake_time)
    calls = []
    monkeypatch.setattr(sdp, "_call_beam", lambda c, p: calls.append(c) or ({}, "x"))
    sdp.build_profile("Ahri", queue_id=420)
    first = len(calls)
    clock["m"] += sdp._PROFILE_TTL_S + 1
    sdp.build_profile("Ahri", queue_id=420)
    assert len(calls) == 2 * first


def test_t169_engine_version_ttl_is_monotonic(monkeypatch):
    clock = {"m": 1000.0}
    monkeypatch.setattr(sdp, "time", types.SimpleNamespace(
        time=lambda: 0.0, monotonic=lambda: clock["m"], sleep=lambda s: None))
    hits = []

    def _open(req, **kw):
        hits.append(1)
        return _Resp(json.dumps({"engine_version": "1.0"}).encode())
    bind_urlopen(monkeypatch, sdp, _open)
    assert sdp._engine_version() == "1.0"
    clock["m"] += sdp._ENGINE_VERSION_TTL_S + 1
    assert sdp._engine_version() == "1.0"
    assert len(hits) == 2


# -- RM-1490: beam row shape ---------------------------------------------


def _profile(top, monkeypatch=None):
    return sdp._profile_from_beam(
        champion="Ahri", role="MIDDLE", kind="primary", preset={},
        beam_resp={"ranked": [top]}, presets=sdp._FALLBACK_PRESETS)


def test_t170_string_item_names_not_split_into_chars():
    out = _profile({**_GOOD_TOP, "item_names": "Kraken Slayer"})
    assert out is None


def test_t170_non_list_ids_do_not_crash():
    out = _profile({**_GOOD_TOP, "item_ids": 3031})
    assert out is not None
    assert out["item_ids"] == []


def test_t170_non_str_names_dropped():
    out = _profile({**_GOOD_TOP, "item_names": ["A", None, 7, "", "B"],
                    "item_ids": ["1", "2"]})
    assert out["build_path"] == ["A", "B"]


def test_t170_non_finite_dps_nulled():
    out = _profile({**_GOOD_TOP, "final_dps": float("nan"), "delta_dps": float("inf"),
                    "baseline_dps": True, "total_gold": "lots"})
    eng = out["engine"]
    assert eng["final_dps"] is None and eng["delta_dps"] is None
    assert eng["baseline_dps"] is None and eng["total_gold"] is None
    assert eng["dps_per_1k_gold"] == 41.93
    json.dumps(out, allow_nan=False)


def test_t170_ids_with_junk_entries():
    out = _profile({**_GOOD_TOP, "item_ids": ["3031", None, {"x": 1}, 3036]})
    assert out["item_ids"] == ["3031", "", "", "3036"]


# -- RM-1491: skeleton cuts ----------------------------------------------


def test_t171_non_dict_split_falls_back():
    out = sdp._split_skeleton(list("ABCDEF"), list("123456"), {"skeleton_split": [0, 2]})
    assert [x["name"] for x in out["core"]] == ["C", "D"]


def test_t171_negative_and_reversed_cuts_clamp():
    presets = {"skeleton_split": {"start": [-2, 6], "core": [4, 2], "final": [True, 99]}}
    out = sdp._split_skeleton(list("ABCDEF"), list("123456"), presets)
    assert [x["name"] for x in out["start"]] == ["A", "B"]
    assert [x["name"] for x in out["core"]] == ["C", "D"]
    assert [x["name"] for x in out["final"]] == ["E", "F"]


# -- RM-1492: rune / spell / engine_query sections -----------------------


@pytest.mark.parametrize("section", ["engine_query", "rune_defaults_by_role",
                                     "tree_by_keystone", "spells_by_role",
                                     "skeleton_split"])
@pytest.mark.parametrize("junk", [[1, 2], "str", 5, None])
def test_t172_junk_sections_do_not_crash(monkeypatch, section, junk):
    presets = json.loads(json.dumps(sdp._FALLBACK_PRESETS))
    presets[section] = junk
    monkeypatch.setattr(sdp, "_load_presets", lambda: presets)
    bind_urlopen(monkeypatch, sdp, _opener(_GOOD_BEAM))
    env = sdp.build_profile("Ahri", role="MIDDLE", queue_id=420)
    assert isinstance(env["profiles"], list)
    for p in env["profiles"]:
        assert isinstance(p["keystone"], str)
        assert all(isinstance(s, int) for s in p["summoner_spells"])


def test_t172_spell_pair_string_not_split():
    assert sdp._spells_for("TOP", {"spells_by_role": {"TOP": "47"}}) == [4, 14]


def test_t172_spell_pair_bool_rejected():
    assert sdp._spells_for("TOP", {"spells_by_role": {"TOP": [True, 12]}}) == [4, 14]


def test_t172_non_str_keystone_and_trees():
    presets = {"rune_defaults_by_role": {"TOP": {"primary": 8005, "alt": None}},
               "tree_by_keystone": {"Press the Attack": "Precision"}}
    ks, runes = sdp._runes_for("TOP", "primary", presets)
    assert ks == "Press the Attack"
    assert runes == {"keystone": "Press the Attack", "primary": "Precision",
                     "secondary": "Domination"}


def test_t172_non_dict_engine_query_entries_noted(monkeypatch):
    presets = json.loads(json.dumps(sdp._FALLBACK_PRESETS))
    presets["engine_query"] = {"primary": "nope"}
    monkeypatch.setattr(sdp, "_load_presets", lambda: presets)
    calls = []
    monkeypatch.setattr(sdp, "_call_beam", lambda c, p: calls.append(p) or ({}, "x"))
    env = sdp.build_profile("Ahri", queue_id=420)
    assert calls == []
    assert len(env["notes"]) == 3


# -- RM-1493: presets loader ---------------------------------------------


def _real_loader(monkeypatch, tmp_path, raw: bytes):
    path = tmp_path / "sr_draft_presets.json"
    path.write_bytes(raw)
    monkeypatch.setattr(sdp, "_PRESETS_PATH", path)
    monkeypatch.setattr(sdp, "_PRESETS_CACHE", None)
    monkeypatch.setattr(sdp, "_PRESETS_MTIME", None)
    monkeypatch.setattr(sdp, "_PRESETS_BAD_MTIME", None, raising=False)
    return path


def test_t173_bad_file_parsed_and_logged_once(monkeypatch, tmp_path, caplog):
    path = _real_loader(monkeypatch, tmp_path, b"{not json")
    reads = []
    real_read = type(path).read_bytes
    monkeypatch.setattr(type(path), "read_bytes",
                        lambda self: reads.append(1) or real_read(self))
    with caplog.at_level(logging.WARNING, logger="rc.sr_draft"):
        for _ in range(5):
            assert _REAL_LOAD() is sdp._FALLBACK_PRESETS
    assert len(reads) == 1
    assert caplog.text.count("presets") == 1


@pytest.mark.parametrize("raw", [b"[" * 200000, b'{"a":' * 200000],
                         ids=["array", "object"])
def test_t173_deeply_nested_file_falls_back(monkeypatch, tmp_path, raw):
    _real_loader(monkeypatch, tmp_path, raw)
    assert _REAL_LOAD() is sdp._FALLBACK_PRESETS


def test_t173_bom_file_loads(monkeypatch, tmp_path):
    want = {"engine_query": {}, "x": 1}
    _real_loader(monkeypatch, tmp_path, b"\xef\xbb\xbf" + json.dumps(want).encode())
    assert _REAL_LOAD() == want


def test_t173_fixed_file_recovers(monkeypatch, tmp_path):
    import os
    path = _real_loader(monkeypatch, tmp_path, b"[1, 2]")
    assert _REAL_LOAD() is sdp._FALLBACK_PRESETS
    path.write_bytes(b'{"ok": 1}')
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    assert _REAL_LOAD() == {"ok": 1}


# -- RM-1494: cache isolation and locking --------------------------------


def test_t174_returned_envelope_is_isolated(monkeypatch):
    bind_urlopen(monkeypatch, sdp, _opener(_GOOD_BEAM))
    env = sdp.build_profile("Ahri", queue_id=420)
    env["profiles"].clear()
    env["notes"].append("caller scribble")
    again = sdp.build_profile("Ahri", queue_id=420)
    assert len(again["profiles"]) == 3
    assert "caller scribble" not in again["notes"]


def test_t174_cache_has_a_lock():
    assert isinstance(sdp._PROFILE_LOCK, type(threading.Lock()))


def test_t174_concurrent_builds_respect_cap(monkeypatch):
    monkeypatch.setattr(sdp, "_call_beam", lambda c, p: ({}, "x"))
    errors = []

    def _work(k):
        try:
            for i in range(80):
                sdp.build_profile(f"C{k}_{i}", queue_id=420)
        except Exception as exc:  # noqa: BLE001 - the assertion target
            errors.append(exc)
    threads = [threading.Thread(target=_work, args=(k,), name=f"t174-{k}") for k in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert errors == []
    assert len(sdp._PROFILE_CACHE) <= sdp._PROFILE_CACHE_MAX
