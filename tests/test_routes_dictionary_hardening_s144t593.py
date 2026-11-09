"""S144-T-593 - /api/dictionary/* never serves a junk field, never loses the whole
map to one bad row and never pins a corrupt dictionary in the browser cache.

dashboard/routes_dictionary.py serves four GET routes built from files RC does
not author (the DDragon mirror under data/meta/ and the CommunityDragon-derived
cherry_augments.json snapshot). Findings pinned here (S144-T-593):

F1 an augment ``icon`` was turned into ``icon_url`` with no shape check, and
   web/js/panels/last_match.js interpolates ``icon_url`` UNESCAPED into an
   ``<img src="...">`` attribute, so a quote in the snapshot broke out of the
   attribute; a ``..`` segment walked off the CDragon plugin root; a non-str
   icon raised and lost the WHOLE augment map (500).
F2 augment ``name`` / ``rarity`` went out raw: a dict / number rendered as
   text and a NaN name put a bare NaN token in the body, which JSON.parse
   refuses (every roster icon lost).
F3 data/daemon_slayer/current.txt was joined onto the data dir unvalidated
   (a ``..`` or absolute value read any cherry_augments.json on disk) and a
   BOM survived ``strip()``.
F4 champion-tags: one entry with a non-str name, a non-numeric / NaN / inf /
   huge rating or an unhashable slug lost the WHOLE map (500, every enemy
   chip blank); a str ``tags`` was split per character; a bool rating read 1;
   a negative rating flipped AD / AP; a padded name was keyed with its padding.
F5 items / runes were served verbatim with ``immutable, max-age=86400`` even
   when the file was truncated, held a NaN token or was not a JSON container,
   so the browser pinned a broken dictionary for a day.
F6 four ``except Exception`` blocks swallowed programming errors as a 500 and
   logged the exception text; they now catch the expected I/O and decode
   errors only and log the exception type.
"""
from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dashboard import routes_dictionary as rd


class _Handler:
    def __init__(self) -> None:
        self.status = 0
        self.body = b""
        self.content_type = ""
        self.cache_control: str | None = None

    def _send(self, status, body, content_type, cache_control=None):
        self.status = status
        self.body = body
        self.content_type = content_type
        self.cache_control = cache_control

    def strict_json(self):
        def _refuse(tok):
            raise ValueError(f"non-strict JSON constant {tok}")
        return json.loads(self.body.decode("utf-8"), parse_constant=_refuse)


def _write(path: Path, text: str, *, bom: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    path.write_bytes(data)
    return path


class _TmpCase(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)

    def tearDown(self) -> None:
        self._td.cleanup()


# ---------------------------------------------------------------- augments

_GOOD_ICON = "/lol-game-data/assets/ASSETS/UX/Cherry/Augments/Icons/ADAPt_small.png"


class AugmentsHardeningTests(_TmpCase):
    def _serve(self, augments_doc, patch: str = "16.21.1"):
        ds = self.root / "ds"
        _write(ds / "current.txt", patch + "\n")
        _write(ds / patch / "cherry_augments.json", json.dumps(augments_doc))
        h = _Handler()
        with mock.patch.object(rd, "_DS_DATA_DIR", ds):
            rd._serve_augments(h)
        return h

    def test_quote_in_icon_never_reaches_icon_url(self):
        evil = '/lol-game-data/x.png" onerror="alert(1)'
        h = self._serve({"augments": {"1": {"name": "A", "rarity": "kGold", "icon": evil}}})
        self.assertEqual(h.status, 200)
        self.assertEqual(h.strict_json()["augments"]["1"]["icon_url"], "")

    def test_dotdot_segment_never_reaches_icon_url(self):
        for icon in ("/lol-game-data/../../evil.png", "/lol-game-data/a/./b.png",
                     "/lol-game-data/a//b.png", "/lol-game-data/a b.png",
                     "/lol-game-data/a.png?x=1", "/lol-game-data/a.png#f",
                     "/lol-game-data/a\\b.png", "/lol-game-data/\u00e9.png"):
            with self.subTest(icon=icon):
                self.assertEqual(rd._cdragon_icon_url(icon), "")

    def test_non_str_icon_is_blank_and_map_survives(self):
        doc = {"augments": {
            "1": {"name": "A", "rarity": "kGold", "icon": {"x": 1}},
            "2": {"name": "B", "rarity": "kSilver", "icon": 5},
            "3": {"name": "C", "rarity": "kSilver", "icon": _GOOD_ICON},
        }}
        h = self._serve(doc)
        self.assertEqual(h.status, 200)
        augs = h.strict_json()["augments"]
        self.assertEqual(augs["1"]["icon_url"], "")
        self.assertEqual(augs["2"]["icon_url"], "")
        self.assertTrue(augs["3"]["icon_url"].startswith(rd._CDRAGON_GAMEDATA_BASE))

    def test_cdragon_icon_url_refuses_non_str(self):
        for junk in (5, 1.5, True, ["a"], {"a": 1}, b"/lol-game-data/a.png"):
            with self.subTest(junk=junk):
                self.assertEqual(rd._cdragon_icon_url(junk), "")

    def test_non_str_name_and_rarity_read_blank(self):
        doc = {"augments": {
            "1": {"name": {"x": 1}, "rarity": 3, "icon": _GOOD_ICON},
            "2": {"name": 7, "rarity": ["kGold"], "icon": _GOOD_ICON},
            "3": {"name": True, "rarity": None, "icon": _GOOD_ICON},
        }}
        h = self._serve(doc)
        augs = h.strict_json()["augments"]
        for aid in ("1", "2", "3"):
            self.assertEqual(augs[aid]["name"], "")
            self.assertEqual(augs[aid]["rarity"], "")

    def test_nan_name_never_emits_a_bare_nan_token(self):
        ds = self.root / "ds"
        _write(ds / "current.txt", "16.21.1")
        _write(ds / "16.21.1" / "cherry_augments.json",
               '{"augments": {"1": {"name": NaN, "rarity": Infinity, "icon": "'
               + _GOOD_ICON + '"}}}')
        h = _Handler()
        with mock.patch.object(rd, "_DS_DATA_DIR", ds):
            rd._serve_augments(h)
        self.assertEqual(h.status, 200)
        row = h.strict_json()["augments"]["1"]
        self.assertEqual((row["name"], row["rarity"]), ("", ""))

    def test_non_dict_root_or_augments_is_500_not_raise(self):
        for doc in ([1, 2], "x", {"augments": [1, 2]}, {"augments": "abc"}):
            with self.subTest(doc=doc):
                h = self._serve(doc)
                self.assertEqual(h.status, 500)
                self.assertIsNone(h.cache_control)

    def test_missing_augments_key_is_empty_200(self):
        h = self._serve({"other": 1})
        self.assertEqual(h.status, 200)
        self.assertEqual(h.strict_json()["augments"], {})

    def test_bom_snapshot_still_served(self):
        ds = self.root / "ds"
        _write(ds / "current.txt", "16.21.1")
        _write(ds / "16.21.1" / "cherry_augments.json",
               json.dumps({"augments": {"1": {"name": "A", "rarity": "kGold",
                                              "icon": _GOOD_ICON}}}), bom=True)
        h = _Handler()
        with mock.patch.object(rd, "_DS_DATA_DIR", ds):
            rd._serve_augments(h)
        self.assertEqual(h.status, 200)
        self.assertEqual(h.strict_json()["augments"]["1"]["name"], "A")


class CurrentPatchTests(_TmpCase):
    def _patch_of(self, text: str, *, bom: bool = False) -> str:
        ds = self.root / "ds"
        _write(ds / "current.txt", text, bom=bom)
        with mock.patch.object(rd, "_DS_DATA_DIR", ds):
            return rd._current_ds_patch()

    def test_valid_patch_reads_through(self):
        self.assertEqual(self._patch_of("16.21.1\n"), "16.21.1")
        self.assertEqual(self._patch_of("  16.21.1  "), "16.21.1")

    def test_bom_is_dropped(self):
        self.assertEqual(self._patch_of("16.21.1\n", bom=True), "16.21.1")

    def test_traversal_or_junk_patch_reads_empty(self):
        for junk in ("..", "../16.21.1", "16.21.1/../..", "/etc", "C:\\x",
                     "16.21.1\nother", "16.21", "abc", "", "16.21.1.5",
                     "1" * 20 + ".1.1"):
            with self.subTest(junk=junk):
                self.assertEqual(self._patch_of(junk), "")

    def test_absent_or_undecodable_reads_empty(self):
        ds = self.root / "ds"
        with mock.patch.object(rd, "_DS_DATA_DIR", ds):
            self.assertEqual(rd._current_ds_patch(), "")
        ds.mkdir(parents=True)
        (ds / "current.txt").write_bytes(b"\xff\xfe16")
        with mock.patch.object(rd, "_DS_DATA_DIR", ds):
            self.assertEqual(rd._current_ds_patch(), "")

    def test_junk_patch_is_a_404_not_a_read_elsewhere(self):
        ds = self.root / "ds"
        _write(ds / "current.txt", "..")
        # a cherry_augments.json one level up must never be served
        _write(self.root / "cherry_augments.json", json.dumps({"augments": {"9": {}}}))
        h = _Handler()
        with mock.patch.object(rd, "_DS_DATA_DIR", ds):
            rd._serve_augments(h)
        self.assertEqual(h.status, 404)


# ------------------------------------------------------------ champion tags

def _champ(name, *, cid=None, tags=("Mage",), attack=2, magic=8, defense=3):
    return {"id": cid if cid is not None else name, "name": name,
            "tags": list(tags) if isinstance(tags, tuple) else tags,
            "info": {"attack": attack, "magic": magic, "defense": defense}}


class ChampionTagsHardeningTests(_TmpCase):
    def _serve_text(self, text: str, *, bom: bool = False):
        path = _write(self.root / "champs.json", text, bom=bom)
        h = _Handler()
        with mock.patch.object(rd, "_CHAMPS_PATH", path):
            rd._serve_champion_tags(h)
        return h

    def _serve(self, data):
        return self._serve_text(json.dumps({"data": data}))

    def test_non_str_name_skips_that_entry_only(self):
        h = self._serve({"A": _champ(5), "B": _champ(["x"]), "C": _champ("Annie2")})
        self.assertEqual(h.status, 200)
        out = h.strict_json()
        self.assertIn("Annie2", out)
        self.assertNotIn("5", out)

    def test_blank_or_padded_name(self):
        h = self._serve({"A": _champ("   ", cid="Blank"), "B": _champ("  Ahri  ", cid="Ahri")})
        out = h.strict_json()
        self.assertNotIn("   ", out)
        self.assertNotIn("Blank", out)
        self.assertIn("Ahri", out)
        self.assertNotIn("  Ahri  ", out)

    def test_junk_ratings_never_500(self):
        rows = {
            "s": _champ("Sx", attack="abc", magic=8),
            "n": _champ("Nx", attack=2, magic=float("nan")),
            "i": _champ("Ix", attack=float("inf"), magic=1),
            "b": _champ("Bx", attack=10 ** 400, magic=1),
            "t": _champ("Tx", attack=True, magic=False),
            "g": _champ("Gx", attack=-3, magic=-9),
            "l": _champ("Lx", attack=[1], magic={"a": 1}),
        }
        h = self._serve(rows)
        self.assertEqual(h.status, 200)
        out = h.strict_json()
        self.assertEqual(out["Sx"]["attack"], 0)
        self.assertEqual(out["Nx"]["magic"], 0)
        self.assertEqual(out["Ix"]["attack"], 0)
        self.assertEqual(out["Bx"]["attack"], 10)
        self.assertEqual((out["Tx"]["attack"], out["Tx"]["magic"]), (0, 0))
        self.assertEqual((out["Gx"]["attack"], out["Gx"]["magic"]), (0, 0))
        self.assertEqual((out["Lx"]["attack"], out["Lx"]["magic"]), (0, 0))
        for name in ("Sx", "Nx", "Ix", "Bx", "Tx", "Gx", "Lx"):
            for k in ("attack", "magic", "defense"):
                v = out[name][k]
                self.assertIs(type(v), int)
                self.assertTrue(0 <= v <= 10)

    def test_negative_rating_cannot_flip_polarity(self):
        # attack=-3 used to lose to magic=0 (AP) for a Marksman; clamped to 0/0
        # it takes the documented zero-info fallback (Marksman -> AD).
        h = self._serve({"m": _champ("Mx", tags=("Marksman",), attack=-3, magic=0)})
        self.assertEqual(h.strict_json()["Mx"]["tags"][0], "AD")

    def test_float_rating_truncates_like_int(self):
        h = self._serve({"f": _champ("Fx", attack=7.9, magic=3.0)})
        out = h.strict_json()
        self.assertEqual((out["Fx"]["attack"], out["Fx"]["magic"]), (7, 3))

    def test_str_tags_never_split_per_character(self):
        h = self._serve({"t": _champ("Tg", tags="Tank")})
        row = h.strict_json()["Tg"]
        self.assertEqual(row["tags"][1], "FLEX")
        self.assertEqual(row["primary"], "")

    def test_non_str_tag_elements_dropped(self):
        h = self._serve({"t": _champ("Tg", tags=[5, {"a": 1}, "Mage"])})
        row = h.strict_json()["Tg"]
        self.assertEqual(row["tags"][1], "MAGE")
        self.assertEqual(row["primary"], "Mage")

    def test_unhashable_or_non_str_slug_skipped_entry_kept(self):
        h = self._serve({"a": _champ("Ax", cid={"x": 1}), "b": _champ("Bx", cid=17)})
        self.assertEqual(h.status, 200)
        out = h.strict_json()
        self.assertIn("Ax", out)
        self.assertIn("Bx", out)
        self.assertNotIn("17", out)

    def test_non_dict_info_reads_zero(self):
        row = _champ("Ix")
        row["info"] = [1, 2]
        h = self._serve({"i": row})
        out = h.strict_json()["Ix"]
        self.assertEqual((out["attack"], out["magic"], out["defense"]), (0, 0, 0))

    def test_non_dict_root_or_data_is_500(self):
        for text in ("[1, 2]", "5", '{"data": [1, 2]}', '{"data": "x"}'):
            with self.subTest(text=text):
                h = self._serve_text(text)
                self.assertEqual(h.status, 500)
                self.assertIsNone(h.cache_control)

    def test_bom_file_served(self):
        h = self._serve_text(json.dumps({"data": {"a": _champ("Ax")}}), bom=True)
        self.assertEqual(h.status, 200)
        self.assertIn("Ax", h.strict_json())

    def test_unexpected_error_is_not_swallowed(self):
        path = _write(self.root / "champs.json", json.dumps({"data": {"a": _champ("Ax")}}))
        h = _Handler()
        with mock.patch.object(rd, "_CHAMPS_PATH", path), \
                mock.patch.object(rd._cio, "merged_info", side_effect=RuntimeError("bug")), \
                self.assertRaises(RuntimeError):
            rd._serve_champion_tags(h)

    def test_unexpected_read_error_is_not_swallowed(self):
        # Only I/O and decode errors are a 500; a programming error inside the
        # read propagates to the dispatcher (which answers its own fixed 500)
        # instead of being logged away as a "read failed".
        path = _write(self.root / "champs.json", "{}")
        ds = self.root / "ds"
        _write(ds / "current.txt", "16.21.1")
        _write(ds / "16.21.1" / "cherry_augments.json", "{}")
        with mock.patch.object(rd, "_read_json", side_effect=RuntimeError("bug")):
            with mock.patch.object(rd, "_CHAMPS_PATH", path), \
                    self.assertRaises(RuntimeError):
                rd._serve_champion_tags(_Handler())
            with mock.patch.object(rd, "_DS_DATA_DIR", ds), \
                    self.assertRaises(RuntimeError):
                rd._serve_augments(_Handler())
        with mock.patch.object(Path, "read_bytes", side_effect=RuntimeError("bug")), \
                self.assertRaises(RuntimeError):
            rd._serve_file(_Handler(), path)

    def test_damage_profile_tag_tolerates_junk(self):
        self.assertEqual(rd._damage_profile_tag(None, ["Mage"], 2, 8), "AP")
        self.assertEqual(rd._damage_profile_tag("Zz", "Marksman", 0, 0), "AP")
        self.assertEqual(rd._damage_profile_tag("Zz", ["Marksman"], None, float("nan")), "AD")
        self.assertEqual(rd._damage_profile_tag("Zz", None, "9", 1), "AP")

    def test_log_line_names_type_not_text(self):
        path = _write(self.root / "secret-dir-name" / "champs.json", "{not json")
        h = _Handler()
        with mock.patch.object(rd, "_CHAMPS_PATH", path), \
                self.assertLogs(rd.log, level="WARNING") as cap:
            rd._serve_champion_tags(h)
        self.assertEqual(h.status, 500)
        joined = "\n".join(cap.output)
        self.assertIn("JSONDecodeError", joined)
        self.assertNotIn("Expecting", joined)


# ------------------------------------------------------------ items / runes

class ServeFileHardeningTests(_TmpCase):
    def _serve(self, raw: bytes):
        path = self.root / "dict.json"
        path.write_bytes(raw)
        h = _Handler()
        rd._serve_file(h, path)
        return h

    def test_truncated_file_is_500_never_cached(self):
        h = self._serve(b'{"data": {"1001": {"name": "Bo')
        self.assertEqual(h.status, 500)
        self.assertIsNone(h.cache_control)

    def test_nan_token_is_500(self):
        for raw in (b'{"a": NaN}', b'[Infinity]', b'{"a": -Infinity}'):
            with self.subTest(raw=raw):
                self.assertEqual(self._serve(raw).status, 500)

    def test_scalar_root_is_500(self):
        for raw in (b"5", b'"x"', b"null", b"true", b""):
            with self.subTest(raw=raw):
                self.assertEqual(self._serve(raw).status, 500)

    def test_non_utf8_is_500(self):
        self.assertEqual(self._serve(b'{"a": "\xff"}').status, 500)

    def test_valid_container_served_verbatim(self):
        for raw in (b'{"a": 1}', b"[1, 2]", b'\xef\xbb\xbf{"a": 1}'):
            with self.subTest(raw=raw):
                h = self._serve(raw)
                self.assertEqual(h.status, 200)
                self.assertEqual(h.body, raw)
                self.assertEqual(h.cache_control, rd._DICT_CACHE_CONTROL)

    def test_missing_is_404(self):
        h = _Handler()
        rd._serve_file(h, self.root / "absent.json")
        self.assertEqual(h.status, 404)

    def test_read_error_is_500_and_logs_type(self):
        path = self.root / "dict.json"
        path.write_bytes(b"{}")
        h = _Handler()
        with mock.patch.object(Path, "read_bytes", side_effect=PermissionError("C:/secret")), \
                self.assertLogs(rd.log, level="WARNING") as cap:
            rd._serve_file(h, path)
        self.assertEqual(h.status, 500)
        joined = "\n".join(cap.output)
        self.assertIn("PermissionError", joined)
        self.assertNotIn("C:/secret", joined)


# -------------------------------------------------- real data, unchanged

class RealDataUnchangedTests(unittest.TestCase):
    """The hardening must not move a single valid byte."""

    def test_real_items_and_runes_served_verbatim(self):
        for path in (rd._ITEMS_PATH, rd._RUNES_PATH):
            # Tracked in git: a missing mirror must FAIL (skip-hygiene guard).
            self.assertTrue(path.is_file(), f"{path.name} is missing from the checkout")
            h = _Handler()
            rd._serve_file(h, path)
            self.assertEqual(h.status, 200, path.name)
            self.assertEqual(h.body, path.read_bytes())

    def test_real_augment_icons_all_pass_the_shape_check(self):
        h = _Handler()
        rd._serve_augments(h)
        # cherry_augments.json is tracked: a 404 here must FAIL (skip-hygiene guard).
        self.assertNotEqual(h.status, 404, "cherry_augments.json is missing")
        self.assertEqual(h.status, 200)
        patch = rd._current_ds_patch()
        raw = json.loads((rd._DS_DATA_DIR / patch / "cherry_augments.json")
                         .read_text(encoding="utf-8"))["augments"]
        out = h.strict_json()["augments"]
        self.assertEqual(set(out), {str(k) for k in raw})
        for aid, row in raw.items():
            icon = row.get("icon") or ""
            want = ""
            if icon:
                low = icon.lstrip("/").lower().removeprefix("lol-game-data/")
                want = rd._CDRAGON_GAMEDATA_BASE + low
            self.assertEqual(out[str(aid)]["icon_url"], want, aid)
            self.assertEqual(out[str(aid)]["name"], row.get("name") or "")
            self.assertEqual(out[str(aid)]["rarity"], row.get("rarity") or "")

    def test_real_champion_ratings_in_range(self):
        # Tracked in git: a missing mirror must FAIL (skip-hygiene guard).
        self.assertTrue(rd._CHAMPS_PATH.is_file(), "ddragon_champions.json is missing")
        h = _Handler()
        rd._serve_champion_tags(h)
        self.assertEqual(h.status, 200)
        out = h.strict_json()
        self.assertGreater(len(out), 170)
        for row in out.values():
            for k in ("attack", "magic", "defense"):
                self.assertFalse(isinstance(row[k], float) and math.isnan(row[k]))


if __name__ == "__main__":
    unittest.main()
