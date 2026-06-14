# arch: P2 deep-audit cycle 10 W1 slice A regression pins | section=tests | frozen=no
"""Deep-audit cycle 10 (P2-W1 slice A) regression tests.

Pins the FIX-NOW classes found in the app / game_reader / modes /
vision_server / modules slice:

1. NaN/Infinity coercion at the Live Client JSON boundary
   (game_reader.snapshot_normalizer._process_game). json.loads accepts the
   NaN / Infinity / -Infinity literals (a CPython extension), so a poisoned
   gameTime or championStats value reaches `int(game_time // 60)` /
   `int(currentHealth)` and raises ValueError / OverflowError. The primary
   relay read path (game_reader.poller.read_game) does NOT wrap _process_game
   in try/except, so that exception crashes the poll tick. _coerce_num()
   sanitizes every Riot float before int().

2. Subprocess hardening (charter standing class): every pytesseract
   image_to_string call in vision_server._inference.handle_ocr must pass a
   positive timeout= (pytesseract default timeout=0 waits unbounded; a hung
   tesseract.exe blocks the HTTP handler thread forever). Sibling of the
   cycle-7 core.vision_tesseract fix, which this slice missed.

3. CWD-relative path: vision_server._config logged to a bare relative
   "moon_vision_server.log", so a spawn from a non-repo-root CWD scatters the
   log. Anchored to the repo root (module grandparent dir).

4. Mode-string guard: ARAM Mayhem reports gameMode "KIWI"; mode_router must
   map it to the ARAM family (no "MAYHEM" substring check).

Importing game_reader / vision_server resolves the vision bearer token at
module load (core.vision_token raises RuntimeError when unconfigured), so the
token env var is set before any in-function import to keep the suite green on
a clean checkout (config/vision_token.txt is gitignored).
"""

import base64
import json
import math
import sys
import types
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_INFERENCE_SRC = (_REPO_ROOT / "vision_server" / "_inference.py").read_text(encoding="utf-8")
_CONFIG_SRC = (_REPO_ROOT / "vision_server" / "_config.py").read_text(encoding="utf-8")


def _set_token(monkeypatch):
    """Make the vision-token resolver succeed without the gitignored file."""
    monkeypatch.setenv("RC_VISION_TOKEN", "p2w1-app-a-test-token")


# -- 1. NaN / Infinity coercion at the Live Client boundary ------------------


def _build_reader(monkeypatch):
    _set_token(monkeypatch)
    from game_reader import GameReader
    r = GameReader()
    # Stub the network-touching enrichment reads so _process_game stays offline.
    r._try_lcu_game_id = lambda: ""
    r._read_my_runes = lambda: ""
    r._read_enemy_runes = lambda enemies: {}
    r._read_my_abilities = lambda: {}
    return r


def test_coerce_num_rejects_non_finite_and_garbage(monkeypatch):
    _set_token(monkeypatch)
    from game_reader.snapshot_normalizer import _coerce_num
    assert _coerce_num(float("nan")) == 0.0
    assert _coerce_num(float("inf")) == 0.0
    assert _coerce_num(float("-inf"), 7) == 7.0
    assert _coerce_num(None) == 0.0
    assert _coerce_num("not-a-number") == 0.0
    assert _coerce_num("12") == 12.0
    assert _coerce_num(3.5) == 3.5
    assert _coerce_num(0) == 0.0


def test_process_game_survives_nan_gametime(monkeypatch):
    """A NaN gameTime previously crashed at int(game_time // 60)."""
    r = _build_reader(monkeypatch)
    raw = {
        "gameData": {"gameTime": float("nan"), "gameMode": "CLASSIC"},
        "activePlayer": {
            "championName": "Ahri",
            "level": 5,
            "currentGold": 500,
            "championStats": {
                "currentHealth": 800.0, "maxHealth": 1000.0,
                "resourceValue": 200.0, "resourceMax": 400.0,
            },
        },
        "allPlayers": [],
        "events": {"Events": []},
    }
    out = r._process_game(raw)
    assert isinstance(out, dict)
    assert math.isfinite(out["game_seconds"])
    assert out["game_seconds"] == 0.0
    assert out["game_time"] == "0:00"


def test_process_game_survives_inf_stats(monkeypatch):
    """Infinity championStats / currentGold previously crashed at int()."""
    r = _build_reader(monkeypatch)
    raw = {
        "gameData": {"gameTime": float("inf"), "gameMode": "CLASSIC"},
        "activePlayer": {
            "championName": "Garen",
            "level": 9,
            "currentGold": float("nan"),
            "championStats": {
                "currentHealth": float("inf"), "maxHealth": float("nan"),
                "resourceValue": float("-inf"), "resourceMax": float("inf"),
            },
        },
        "allPlayers": [],
        "events": {"Events": []},
    }
    out = r._process_game(raw)
    assert isinstance(out, dict)
    # All numeric coercions must land on finite ints, never raise.
    assert isinstance(out["hp_abs"], int)
    assert isinstance(out["hp_max"], int)
    assert isinstance(out["mp_abs"], int)
    assert isinstance(out["gold"], int)
    assert out["gold"] == 0          # NaN gold -> default 0
    assert out["hp_max"] >= 1        # inf maxHealth -> default 1
    assert math.isfinite(out["game_seconds"])


# -- 2. OCR subprocess timeout hardening -------------------------------------


def test_handle_ocr_every_call_passes_timeout():
    """Source guard: no image_to_string call site in _inference may omit
    timeout=_OCR_TIMEOUT_S."""
    sites = _INFERENCE_SRC.count("image_to_string(")
    timed = _INFERENCE_SRC.count("timeout=_OCR_TIMEOUT_S")
    assert sites == 3, f"expected 3 OCR call sites, found {sites}"
    assert timed == sites, (
        f"{sites - timed} image_to_string call(s) missing timeout=_OCR_TIMEOUT_S"
    )


def test_ocr_timeout_constant_positive(monkeypatch):
    _set_token(monkeypatch)
    import vision_server._inference as inf
    assert hasattr(inf, "_OCR_TIMEOUT_S")
    assert inf._OCR_TIMEOUT_S > 0


def _install_ocr_fakes(monkeypatch, calls, return_text="123"):
    pil = types.ModuleType("PIL")

    class _Img:
        size = (10, 10)

        def convert(self, _mode):
            return self

        def resize(self, _size, _resample=None):
            return self

    class _Enh:
        def __init__(self, img):
            self._img = img

        def enhance(self, _factor):
            return self._img

    pil.Image = types.SimpleNamespace(open=lambda *_a, **_k: _Img(), LANCZOS=1)
    pil.ImageEnhance = types.SimpleNamespace(Contrast=_Enh)
    monkeypatch.setitem(sys.modules, "PIL", pil)

    pt = types.ModuleType("pytesseract")

    def image_to_string(img, lang=None, config="", nice=0,
                        output_type="string", timeout=0):
        calls.append({"config": config, "timeout": timeout})
        return return_text

    pt.image_to_string = image_to_string
    pt.pytesseract = types.SimpleNamespace(tesseract_cmd="tesseract")
    monkeypatch.setitem(sys.modules, "pytesseract", pt)


def test_handle_ocr_runtime_passes_timeout_value(monkeypatch):
    _set_token(monkeypatch)
    import vision_server._inference as inf
    calls: list = []
    _install_ocr_fakes(monkeypatch, calls, return_text="123")
    b64 = base64.b64encode(b"x").decode("ascii")
    body = json.dumps({"crops": {"gold": b64}}).encode()
    out = inf.handle_ocr(body)
    assert out.get("ok") is True
    assert out["result"].get("gold") == 123
    assert calls, "fake pytesseract was never invoked"
    assert calls[0]["timeout"] == inf._OCR_TIMEOUT_S
    assert calls[0]["timeout"] > 0


# -- 3. CWD-relative log path anchored ---------------------------------------


def test_config_log_path_anchored_not_cwd_relative():
    """Source guard: the FileHandler must not use a bare relative filename."""
    assert 'FileHandler("moon_vision_server.log"' not in _CONFIG_SRC, (
        "bare CWD-relative FileHandler path is banned"
    )
    assert "_LOG_PATH" in _CONFIG_SRC
    assert "Path(__file__).resolve().parent.parent" in _CONFIG_SRC


def test_config_log_path_is_absolute(monkeypatch):
    _set_token(monkeypatch)
    import vision_server._config as cfg
    assert cfg._LOG_PATH.is_absolute()
    assert cfg._LOG_PATH.name == "moon_vision_server.log"
    assert cfg._LOG_PATH.parent == _REPO_ROOT


# -- 4. KIWI (ARAM Mayhem) mode-string guard ---------------------------------


def test_mode_router_kiwi_maps_to_aram(monkeypatch):
    _set_token(monkeypatch)
    from game_reader.mode_router import is_aram_mode, is_tft_mode, tower_count_for
    assert is_aram_mode("KIWI") is True
    assert is_aram_mode("ARAM") is True
    assert is_aram_mode("CLASSIC") is False
    assert is_tft_mode("KIWI") is False
    # ARAM family is 3 turrets per team; SR is 11.
    assert tower_count_for("KIWI") == 3
    assert tower_count_for("CLASSIC") == 11
