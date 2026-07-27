"""R121 TDD RED-first: core.vision_atlas_precompute dhash atlas + manifest.

Characterizes the deterministic difference-hash (dhash) icon atlas precompute
that lets a downstream consumer name an icon by nearest-Hamming lookup against a
prebuilt manifest - the Haiku/Sonnet-to-ZERO Lane E CV atlas foundation - with
NO vision-model call and NO cv2 dependency at query time.

Two tiers:
  - PURE (no cv2): the numeric core - dhash / hamming / hex64 / nearest and the
    manifest write/load round-trip. These run in CI always.
  - CV2-GATED: real on-disk icon decode + full build_manifest. Each starts with
    `cv2 = pytest.importorskip("cv2")` so it self-skips when opencv is absent.

Non-fragile per CLAUDE.md testing discipline: no hardcoded icon counts and no
patch string literal - the patch is compared against vap._patch() and counts
against len(vtm.list_ids(...)) / computed sums.

ASCII only (repo hard rule). No em-dashes.
"""
import numpy as np
import pytest

import core.vision_atlas_precompute as vap
import core.vision_template_match as vtm


def _sample_manifest():
    """A fresh, minimal, valid manifest literal (schema_version 1)."""
    return {
        "schema_version": 1,
        "generator": "core.vision_atlas_precompute",
        "hash_algo": "dhash",
        "hash_bits": 64,
        "patch": "16.13.1",
        "categories": {"items": {"count": 1, "icons": {"foo": "00ff00ff00ff00ff"}}},
        "total_icons": 1,
    }


# --------------------------------------------------------------------------- #
# PURE (no cv2) - the numeric core + manifest IO.
# --------------------------------------------------------------------------- #
def test_dhash_deterministic():
    arr = np.tile(np.arange(16.0), (16, 1))
    result = vap.dhash(arr)
    assert vap.dhash(arr) == result
    assert isinstance(result, int)


def test_dhash_increasing_is_zero_decreasing_is_full():
    inc = np.tile(np.arange(16.0), (16, 1))
    dec = np.tile(np.arange(16.0)[::-1], (16, 1))
    assert vap.dhash(inc) == 0
    assert vap.dhash(dec) == (2 ** 64 - 1)
    assert vap.hamming(vap.dhash(inc), vap.dhash(dec)) == 64


def test_dhash_uniform_is_zero():
    uniform = np.full((16, 16), 7.0)
    assert vap.dhash(uniform) == 0


def test_dhash_bad_input_none():
    assert vap.dhash(None) is None
    assert vap.dhash(np.arange(5.0)) is None  # 1D, not 2D


def test_hamming_symmetry_bounds():
    assert vap.hamming(0xABCD, 0xABCD) == 0
    assert vap.hamming(0, 2 ** 64 - 1) == 64
    a, b = 0x0F0F, 0x00FF
    assert vap.hamming(a, b) == vap.hamming(b, a)
    assert 0 <= vap.hamming(a, b) <= 64
    assert vap.hamming("ff", 0x0F) == vap.hamming(255, 15)


def test_hamming_bad_input_none():
    assert vap.hamming("zzz", 1) is None


def test_hex64_format():
    s = vap.hex64(0xABCDEF)
    assert len(s) == 16
    assert all(c in "0123456789abcdef" for c in s)
    assert int(s, 16) == 0xABCDEF
    assert vap.hex64(2 ** 64) == "0" * 16  # masks to 64 bits


def test_nearest_ranks_by_distance():
    icons = {"a": vap.hex64(0), "b": vap.hex64(0xF), "c": vap.hex64(0xFFFF)}
    res = vap.nearest(0, icons, top_k=2)
    assert res[0][0] == "a"
    assert res[0][1] == 0
    assert len(res) == 2
    dists = [d for _, d in res]
    assert dists == sorted(dists)


def test_nearest_accepts_subdict_and_bad_input():
    sub = {"icons": {"x": vap.hex64(0), "y": vap.hex64(0xFF)}}
    assert vap.nearest(0, sub, top_k=1)[0][0] == "x"
    assert vap.nearest(0, {}) == []
    assert vap.nearest(0, None) == []


def test_write_load_roundtrip(tmp_path):
    m = _sample_manifest()
    p = tmp_path / "m.json"
    assert vap.write_manifest(m, p) == p
    assert p.exists()
    assert vap.load_manifest(p) == m
    assert not list(tmp_path.glob("*.tmp"))  # no partial left behind


def test_manifest_json_is_ascii(tmp_path):
    m = _sample_manifest()
    p = tmp_path / "a.json"
    vap.write_manifest(m, p)
    raw = p.read_bytes()
    assert all(b < 128 for b in raw)


def test_load_missing_is_empty(tmp_path):
    assert vap.load_manifest(tmp_path / "nope.json") == {}


# --------------------------------------------------------------------------- #
# CV2-GATED - real icon decode + full manifest build (self-skip without cv2).
# --------------------------------------------------------------------------- #
def test_icon_hash_real():
    cv2 = pytest.importorskip("cv2")
    ids = vtm.list_ids("items")
    # data/icons/items/ is TRACKED (36 committed icons), so an empty list means
    # list_ids() or the committed icon set broke. cv2 above is the only real
    # capability gate here.
    assert ids, "no item icons found under the tracked data/icons/items/ dir"
    d = vtm._CATEGORY_DIRS["items"]
    h = vap.icon_hash(d / (ids[0] + ".png"))
    assert isinstance(h, int)


def test_build_manifest_schema():
    cv2 = pytest.importorskip("cv2")
    m = vap.build_manifest(["items"])
    assert m["schema_version"] == 1
    assert m["hash_algo"] == "dhash"
    assert m["hash_bits"] == 64
    assert m["patch"] == vap._patch()
    cat = m["categories"]["items"]
    assert cat["count"] == len(cat["icons"])
    assert cat["count"] > 0
    assert m["total_icons"] == sum(c["count"] for c in m["categories"].values())
    assert all(
        len(hx) == 16 and all(ch in "0123456789abcdef" for ch in hx)
        for hx in cat["icons"].values()
    )
    assert set(cat["icons"].keys()) <= set(vtm.list_ids("items"))


def test_build_manifest_nearest_selfmatch():
    cv2 = pytest.importorskip("cv2")
    m = vap.build_manifest(["items"])
    icons = m["categories"]["items"]["icons"]
    stem, hx = next(iter(sorted(icons.items())))
    res = vap.nearest(hx, icons, top_k=1)
    assert res
    assert res[0][0] == stem
    assert res[0][1] == 0  # an icon's own stored hash self-matches at distance 0
