"""GET /api/duo-synergy trust-boundary hardening (S144-T-601, lane 8).

dashboard/routes_duo_synergy.py is a GET route on :8888, so a LAN peer reaches
it with any query. Measured on the module before this change:

* the four champion parameters (ally_bot_lock / ally_bot_hover /
  ally_sup_lock / ally_sup_hover) were echoed into the 200 body verbatim and
  unbounded - markup, CR / LF, bidi controls and a 20000-character value all
  came back as a cell's "champ" / "pair_with" (the RM-1255 echo class), and each
  distinct value was a new cache key holding that copy;
* top_n went through int(), so "1_1" and Arabic-Indic digits read as numbers
  and any junk silently read the default;
* a non-finite rate from the seed was served under 200 as a bare NaN token,
  which the browser's JSON.parse rejects (the panel goes to its error state);
* the 5 s cache TTL ran on the wall clock, so a clock stepped back served a
  stale grid for as long as the step;
* the laning tip lookup keyed on the CALLER's spelling, so a resolved pair
  sent in lower case got the default tip instead of its own;
* a non-string "default" in the tips file was rendered with str().

Every test here names the defect it pins.
"""
from __future__ import annotations

import dataclasses
import json
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from core import smoothed_rates_101qq as S101  # noqa: E402
from dashboard import routes_duo_synergy as RDS  # noqa: E402

CHAMP_PARAMS = ("ally_bot_lock", "ally_bot_hover", "ally_sup_lock",
                "ally_sup_hover")


class _Handler:
    def __init__(self, path: str) -> None:
        self.path = path
        self.status: int | None = None
        self.body: bytes = b""
        self.calls = 0

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.calls += 1
        self.status = status
        self.body = body
        assert content_type == "application/json"

    def strict(self) -> dict:
        def _no_constant(token: str):
            raise ValueError(f"non-standard JSON token {token}")
        return json.loads(self.body.decode("utf-8"),
                          parse_constant=_no_constant)


def _do(query: str) -> _Handler:
    h = _Handler("/api/duo-synergy?" + query)
    RDS._serve_duo_synergy(h)
    return h


@pytest.fixture(autouse=True)
def _static_seed(monkeypatch):
    # Pin the live Tencent fetch OFF: the committed static seed is the data.
    monkeypatch.setenv("RC_DUO_SYNERGY_LIVE", "0")
    S101._reset_cache()
    RDS._reset_caches()
    yield
    RDS._reset_caches()
    S101._reset_cache()


# --------------------------------------------------------------------------
# Champion parameters: shape-checked, never echoed when refused
# --------------------------------------------------------------------------

_BAD_NAMES = [
    "<script>alert(1)</script>",
    "x\r\nSet-Cookie: a",
    "\u202eJinx",                 # bidi override
    "\uff2ainx",                  # fullwidth J
    "Jinx\u3000",                 # ideographic space (old strip() ate it)
    "A" * 33,                     # one past the cap
    "A" * 20000,
    "Jinx\"}",
    "../../etc",
    "Jinx;Senna",
    "'Jinx",                      # must start with a letter / digit
]


@pytest.mark.parametrize("param", CHAMP_PARAMS)
@pytest.mark.parametrize("bad", _BAD_NAMES)
def test_bad_champion_value_is_a_fixed_400_and_never_echoed(param, bad):
    from urllib.parse import quote
    with mock.patch.object(RDS, "_build_payload",
                           side_effect=AssertionError("built")) as built:
        h = _do(f"{param}={quote(bad)}")
    assert h.status == 400
    body = h.strict()
    assert body == {"ok": False, "error": f"{param}_invalid"}
    assert built.call_count == 0
    raw = h.body.decode("utf-8")
    assert bad not in raw
    assert len(h.body) < 100
    # A refused query never takes a cache slot.
    assert RDS._CACHE == {}


@pytest.mark.parametrize("good", [
    "Jinx", "Kaisa", "TahmKench", "Kai'Sa", "Dr. Mundo", "Nunu & Willump",
    "A" * 32, "  Jinx  ", "jinx", "X1",
])
def test_well_shaped_champion_names_are_still_served(good):
    from urllib.parse import quote
    h = _do("ally_bot_lock=" + quote(good))
    assert h.status == 200
    body = h.strict()
    assert body["mode"] == "bot_locked"
    assert body["top_row"][0]["champ"] == good.strip()


def test_blank_champion_value_still_reads_as_absent():
    h = _do("ally_bot_lock=%20%20&my_role=sup")
    assert h.status == 200
    assert h.strict()["mode"] == "none"


def test_refusal_names_the_first_bad_parameter_only():
    h = _do("ally_bot_lock=Jinx&ally_sup_hover=%3Cb%3E")
    assert h.status == 400
    assert h.strict()["error"] == "ally_sup_hover_invalid"


# --------------------------------------------------------------------------
# top_n: ASCII digits only, then the existing clamp
# --------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "1_1", "\u0662", "\uff12", "abc", "-1", "1.0", "+2", "0x2", "1234567",
    "2 2",
])
def test_bad_top_n_is_a_fixed_400(bad):
    from urllib.parse import quote
    h = _do("top_n=" + quote(bad))
    assert h.status == 400
    assert h.strict() == {"ok": False, "error": "top_n_invalid"}
    assert RDS._CACHE == {}


@pytest.mark.parametrize("val,expect", [("0", 1), ("1", 1), ("3", 3),
                                        ("4", 4), ("99", 4), ("000002", 2),
                                        (" 2 ", 2)])
def test_numeric_top_n_keeps_the_clamp(val, expect):
    from urllib.parse import quote
    h = _do("my_role=bot&top_n=" + quote(val))
    assert h.status == 200
    body = h.strict()
    assert len(body["top_row"]) == expect
    assert len(body["bottom_row"]) == expect


# --------------------------------------------------------------------------
# Non-finite numbers: never a bare NaN / Infinity token in a 200
# --------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_solo_fields_serve_null_not_a_bare_token(bad):
    orig = S101.top_solo_picks

    def _patched(role, top_n=4):
        return [dataclasses.replace(r, itemp=bad, iwinrate=bad,
                                    smoothed_rate=bad, rank=bad)
                for r in orig(role, top_n)]

    with mock.patch.object(S101, "top_solo_picks", _patched):
        h = _do("my_role=bot")
    assert h.status == 200
    body = h.strict()
    cell = body["top_row"][0]
    assert cell["itemp"] is None
    assert cell["iwinrate"] is None
    assert cell["smoothed_rate"] is None
    assert cell["rank"] == 0
    assert isinstance(cell["champ"], str) and cell["champ"]


def test_non_finite_duo_fields_serve_null_not_a_bare_token():
    orig = S101.top_duos_for_bot

    def _patched(bot, top_n=4):
        return [dataclasses.replace(d, doublewinrate=float("nan"),
                                    iwinrate_sup=float("inf"),
                                    itemp_bot=float("nan"),
                                    smoothed_rate=float("-inf"))
                for d in orig(bot, top_n)]

    with mock.patch.object(S101, "top_duos_for_bot", _patched):
        h = _do("ally_bot_lock=Jinx")
    assert h.status == 200
    body = h.strict()
    cell = body["bottom_row"][0]
    assert cell["doublewinrate"] is None
    assert cell["iwinrate"] is None
    assert cell["itemp"] is None
    assert cell["smoothed_rate"] is None
    assert cell["champ"]


def test_a_non_finite_value_anywhere_else_is_a_fixed_500_not_a_bad_200():
    with mock.patch.object(RDS, "_build_payload",
                           return_value={"ok": True, "x": float("nan")}):
        h = _do("my_role=bot")
    assert h.status == 500
    assert h.strict() == {"ok": False, "error": "internal error - see logs"}
    # A body that could not be served is not cached either.
    assert RDS._CACHE == {}


def test_a_non_json_safe_health_block_degrades_without_killing_the_grid():
    with mock.patch.object(S101, "health",
                           return_value={"stale_for_s": float("nan")}):
        h = _do("my_role=bot")
    assert h.status == 200
    body = h.strict()
    assert body["health"]["available"] is False
    assert len(body["top_row"]) == 4


@pytest.mark.parametrize("value,expect", [
    (0.123456, 0.1235), (0, 0), (3, 3), (-0.5, -0.5),
    (True, None), (False, None), (None, None), ("0.5", None),
    (float("nan"), None), (float("inf"), None),
])
def test_cell_rate_helper(value, expect):
    got = RDS._r4(value)
    assert got == expect and type(got) is type(expect)


@pytest.mark.parametrize("value,expect", [
    (3.4, 3), (118.0, 118), (7, 7), (True, 0), (None, 0), ("4", 0),
    (float("nan"), 0), (float("-inf"), 0),
])
def test_solo_rank_helper(value, expect):
    got = RDS._rank(value)
    assert got == expect and type(got) is int


def test_finite_values_keep_their_exact_type_and_rounding():
    h = _do("my_role=sup&top_n=4")
    body = h.strict()
    recs = S101.top_solo_picks("bot", top_n=4)
    for rec, cell in zip(recs, body["top_row"]):
        assert cell["iwinrate"] == round(rec.iwinrate, 4)
        assert cell["itemp"] == round(rec.itemp, 4)
        assert cell["smoothed_rate"] == round(rec.smoothed_rate, 4)
        assert cell["rank"] == int(round(rec.rank))


# --------------------------------------------------------------------------
# Cache TTL: monotonic, not the wall clock
# --------------------------------------------------------------------------

def test_wall_clock_stepping_back_does_not_extend_the_cache_ttl():
    first = _do("my_role=sup")
    assert first.strict()["cached"] is False
    real_wall = time.time
    real_mono = time.monotonic
    with mock.patch.object(RDS.time, "time", lambda: real_wall() - 3600), \
            mock.patch.object(RDS.time, "monotonic",
                              lambda: real_mono() + RDS._CACHE_TTL_S + 1):
        second = _do("my_role=sup")
    body = second.strict()
    assert body["cached"] is False
    assert body["elapsed_ms"] >= 0


def test_elapsed_ms_ignores_a_wall_clock_running_backwards():
    # Every wall-clock read is 10 s earlier than the last; elapsed_ms is
    # measured on perf_counter, so it stays a small non-negative number.
    state = {"t": time.time()}

    def _backwards() -> float:
        state["t"] -= 10.0
        return state["t"]

    with mock.patch.object(RDS.time, "time", _backwards):
        body = _do("my_role=bot").strict()
    assert 0 <= body["elapsed_ms"] < 60_000


def test_wall_clock_jumping_forward_does_not_expire_a_fresh_entry():
    # The TTL is elapsed time: a wall-clock jump alone neither extends nor
    # cuts it.
    _do("my_role=sup")
    real_wall = time.time
    with mock.patch.object(RDS.time, "time", lambda: real_wall() + 3600):
        again = _do("my_role=sup")
    assert again.strict()["cached"] is True


def test_an_entry_stamped_in_the_future_is_not_served():
    # A stamp from another clock (a caller passing time.time() to
    # _cache_put) reads as a miss, never as fresh forever.
    key = ("sup", "", "", "", "", 4)
    RDS._cache_put(key, time.monotonic() + 10_000.0,
                   {"ok": True, "mode": "stale"})
    h = _do("my_role=sup")
    body = h.strict()
    assert body["cached"] is False
    assert body["mode"] == "none"


def test_cache_still_hits_inside_the_ttl():
    _do("my_role=sup")
    again = _do("my_role=sup")
    assert again.strict()["cached"] is True


# --------------------------------------------------------------------------
# Laning tips: canonical names, string-only default
# --------------------------------------------------------------------------

def test_lower_case_locked_pair_gets_its_own_tip():
    exact = _do("ally_bot_lock=Jinx&ally_sup_lock=Senna").strict()
    RDS._reset_caches()
    lower = _do("ally_bot_lock=jinx&ally_sup_lock=senna").strict()
    tips = RDS._load_tips()
    assert exact["laning_tips"] == tips["pairs"]["Jinx:Senna"]
    assert lower["laning_tips"] == exact["laning_tips"]


def test_non_string_tips_default_reads_as_no_default(tmp_path, monkeypatch):
    p = tmp_path / "laning_tips_duo.json"
    p.write_text(json.dumps({"default": ["x", 1], "pairs": {"A:B": 5,
                                                            "C:D": "tip"}}),
                 encoding="utf-8")
    monkeypatch.setattr(RDS, "_TIPS_PATH", p)
    RDS._reset_caches()
    tips = RDS._load_tips()
    assert tips["default"] == ""
    assert tips["pairs"] == {"C:D": "tip"}
    assert RDS._laning_tips_for("X", "Y") is None


# --------------------------------------------------------------------------
# Last-resort arm: fixed body, scrubbed cause with its type name
# --------------------------------------------------------------------------

def test_last_resort_arm_logs_type_and_scrubbed_cause(caplog):
    with mock.patch.object(RDS, "_build_payload",
                           side_effect=KeyError("evil\r\nline")):
        with caplog.at_level("WARNING", logger="rc.web_dashboard"):
            h = _do("my_role=bot")
    assert h.status == 500
    assert h.strict() == {"ok": False, "error": "internal error - see logs"}
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "KeyError" in text
    assert "\r\n" not in text
