"""RM-1173: scripts/download_aram_icons.py runs nothing at import, names
its icons the way the dashboard requests them, and writes them atomically.

The script fills data/icons/aram_items/, which dashboard/routes_static.py
serves at /icons/items/<slug>.png, where web/legacy_index.html `itemSlug`
builds the slug from an item NAME. Three defects, fixed together:

1. The WHOLE download ran at MODULE LEVEL: importing the file created the
   output directory, fetched the DDragon version list and item data, and
   called ``sys.exit(1)`` when the network was down. No test could import
   it. Same class as scripts/probe_missing_codes.py (RM-1131) and
   scripts/team_planner_sync.py (RM-1172).
2. Its slug rule stripped ``'s?`` where the JS strips ``'s\\b``, so
   "Jak'Sho, The Protean" became jakho-the-protean.png while the legacy page
   requests jaksho-the-protean.png (a 404). Measured over the tracked
   DDragon item data: Jak'Sho (6665, 226665) was the only name the two
   rules disagreed on. The tracked icon is renamed in the same slice.
3. Each icon was written with a bare ``write_bytes`` into a directory the
   dashboard serves; it now goes through core.polled_json.atomic_write_bytes.

No test touches the network: the import is proved call-free in a CHILD
process whose ``urllib.request.urlopen`` refuses, and in this process every
test binds the script's OWN ``urllib.request.urlopen`` (``bind_urlopen``,
never the process-wide stdlib attribute, RM-801).
"""
from __future__ import annotations

import ast
import importlib
import json
import os
import pathlib
import re
import subprocess
import sys

import pytest

from tests._module_view import bind_urlopen

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_SRC = ROOT / "scripts" / "download_aram_icons.py"
_MOD = "scripts.download_aram_icons"
_ICON_DIR = ROOT / "data" / "icons" / "aram_items"
_LEGACY = ROOT / "web" / "legacy_index.html"
_DDRAGON_DIR = ROOT / "data" / "meta_build" / "ddragon"

_ALLOWED_TOP = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.Assign,
                ast.AnnAssign)


def _is_docstring(node: ast.stmt) -> bool:
    return (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str))


def _is_main_guard(node: ast.stmt) -> bool:
    """Exactly `if __name__ == "__main__":`."""
    return (isinstance(node, ast.If) and not node.orelse
            and ast.unparse(node.test) == "__name__ == '__main__'")


def _is_sys_path_guard(node: ast.stmt) -> bool:
    """`if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))` only."""
    return (isinstance(node, ast.If) and not node.orelse
            and ast.unparse(node.test) == "str(ROOT) not in sys.path"
            and [ast.unparse(b) for b in node.body]
            == ["sys.path.insert(0, str(ROOT))"])


def test_the_module_body_runs_no_download():
    """Static guard, checked BEFORE anything imports the script."""
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    bad = [ast.unparse(n).splitlines()[0] for n in tree.body
           if not (isinstance(n, _ALLOWED_TOP) or _is_docstring(n)
                   or _is_main_guard(n) or _is_sys_path_guard(n))]
    assert bad == [], f"module-level statements run at import: {bad}"
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            calls = [ast.unparse(c.func) for c in ast.walk(node)
                     if isinstance(c, ast.Call)]
            assert not any(k in c for c in calls
                           for k in ("urlopen", "fetch", "mkdir", "loads",
                                     "print", "exit", "write")), calls


_CHILD_IMPORT = (
    "import sys, urllib.request\n"
    "calls = []\n"
    "def refuse(*args, **kwargs):\n"
    "    calls.append(args)\n"
    "    raise RuntimeError('test refuses network access')\n"
    "urllib.request.urlopen = refuse\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import scripts.download_aram_icons\n"
    "print('urlopen calls at import:', len(calls))\n"
)


def test_importing_the_script_makes_no_network_call_and_does_not_exit():
    """Runtime twin of the static guard, in a child process so the refusing
    urlopen can never leak into another test (RM-801)."""
    no_window = 0x08000000 if os.name == "nt" else 0
    r = subprocess.run(
        [sys.executable, "-I", "-c", _CHILD_IMPORT, str(ROOT)],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        creationflags=no_window,
    )
    assert r.returncode == 0, (r.stdout[-1000:], r.stderr[-2000:])
    assert r.stdout.strip().splitlines() == ["urlopen calls at import: 0"], r.stdout


class _Resp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body


@pytest.fixture
def dai(monkeypatch):
    """Import the script with its own urlopen refusing by default."""
    test_the_module_body_runs_no_download()
    sys.modules.pop(_MOD, None)
    mod = importlib.import_module(_MOD)
    calls: list[str] = []

    def refuse(url, *args, **kwargs):
        calls.append(url)
        raise RuntimeError("test refuses network access")

    # Scoped to the script's own urllib.request.urlopen (RM-801).
    assert bind_urlopen(monkeypatch, mod, refuse) >= 1
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    mod._test_calls = calls
    yield mod
    sys.modules.pop(_MOD, None)


def _js_item_slug(name: str) -> str:
    """Mirror of web/legacy_index.html itemSlug (anchored below)."""
    s = re.sub(r"'s\b|'", "", str(name or "").lower())
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"^-+|-+$", "", s)


def test_the_js_rule_this_mirror_copies_is_unchanged():
    src = _LEGACY.read_text(encoding="utf-8").replace("\r\n", "\n")
    m = re.search(r"function itemSlug\(name\) \{\n  (.*?)\n\}", src, re.S)
    assert m, "itemSlug not found in web/legacy_index.html"
    assert ".replace(/'s\\b|'/g, '')" in m.group(1), m.group(1)


@pytest.mark.parametrize(("name", "slug"), [
    ("Jak'Sho, The Protean", "jaksho-the-protean"),
    ("Death's Dance", "death-dance"),
    ("Liandry's Anguish", "liandry-anguish"),
    ("Rabadon's Deathcap", "rabadon-deathcap"),
    ("Blade of The Ruined King", "blade-of-the-ruined-king"),
])
def test_slugify_matches_the_dashboard_item_slug(dai, name, slug):
    assert dai.slugify(name) == slug == _js_item_slug(name)


def test_slugify_agrees_with_the_js_rule_on_every_tracked_item_name(dai):
    files = sorted(_DDRAGON_DIR.glob("*/item.json"))
    assert files, f"no tracked DDragon item data under {_DDRAGON_DIR}"
    names = set()
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        names.update(v.get("name", "") for v in data.get("data", {}).values())
    assert len(names) > 100, len(names)
    assert "Jak'Sho, The Protean" in names
    differ = sorted(n for n in names if dai.slugify(n) != _js_item_slug(n))
    assert differ == []


def test_the_tracked_jaksho_icon_has_the_name_the_dashboard_requests():
    assert (_ICON_DIR / "jaksho-the-protean.png").is_file()
    assert not (_ICON_DIR / "jakho-the-protean.png").exists()


def _item(name, *, maps=None, purchasable=True, depth=3, image="1.png",
          frm=None):
    row = {"name": name, "maps": {"12": True} if maps is None else maps,
           "gold": {"purchasable": purchasable}, "depth": depth,
           "image": {"full": image}}
    if frm is not None:
        row["from"] = frm
    return row


def test_aram_items_from_keeps_purchasable_final_aram_items_only(dai):
    raw = {"data": {
        "1": _item("Final", depth=3),
        "2": _item("Component", depth=2, frm=["9"]),
        "3": _item("No recipe basic", depth=1),
        "4": _item("Rift only", maps={"11": True}),
        "5": _item("Not for sale", purchasable=False),
        "6": _item("", depth=3),
        "7": _item("No image", image=""),
    }}
    assert dai.aram_items_from(raw) == {
        "1": {"name": "Final", "img": "1.png"},
        "3": {"name": "No recipe basic", "img": "1.png"},
    }


def test_download_icons_writes_atomically_skips_cached_and_counts_failures(
        dai, tmp_path, monkeypatch):
    out = tmp_path / "icons"
    out.mkdir()
    (out / "cached-item.png").write_bytes(b"old")
    urls: list[str] = []

    def fake(url, *args, **kwargs):
        urls.append(url)
        if url.endswith("/bad.png"):
            raise OSError("synthetic failure")
        return _Resp(b"PNG:" + url.rsplit("/", 1)[-1].encode("ascii"))

    bind_urlopen(monkeypatch, dai, fake)
    written: list[pathlib.Path] = []
    real = dai.atomic_write_bytes

    def spy(path, data):
        written.append(pathlib.Path(path))
        real(path, data)

    monkeypatch.setattr(dai, "atomic_write_bytes", spy)
    items = {
        "1": {"name": "Jak'Sho, The Protean", "img": "6665.png"},
        "2": {"name": "Cached Item", "img": "2.png"},
        "3": {"name": "Broken", "img": "bad.png"},
    }
    assert dai.download_icons(items, "16.13.1", out) == (1, 1, 1)
    assert (out / "jaksho-the-protean.png").read_bytes() == b"PNG:6665.png"
    assert (out / "cached-item.png").read_bytes() == b"old"
    assert written == [out / "jaksho-the-protean.png"]
    assert urls == [
        "https://ddragon.leagueoflegends.com/cdn/16.13.1/img/item/6665.png",
        "https://ddragon.leagueoflegends.com/cdn/16.13.1/img/item/bad.png",
    ]
    assert not (out / "broken.png").exists()


def test_the_script_has_no_bare_write_bytes():
    src = _SRC.read_text(encoding="utf-8")
    assert ".write_bytes(" not in src and ".write_text(" not in src
    assert "from core.polled_json import atomic_write_bytes" in src


def test_main_returns_1_when_the_version_list_cannot_be_fetched(
        dai, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(dai, "OUT_DIR", tmp_path / "icons")
    assert dai.main() == 1
    out = capsys.readouterr().out
    assert "ERROR fetching versions:" in out
    assert dai._test_calls == [
        "https://ddragon.leagueoflegends.com/api/versions.json"]


def test_main_runs_the_whole_download_on_fake_ddragon(
        dai, tmp_path, monkeypatch, capsys):
    out_dir = tmp_path / "icons"
    monkeypatch.setattr(dai, "OUT_DIR", out_dir)
    items = {"data": {"6665": _item("Jak'Sho, The Protean", image="6665.png")}}

    def fake(url, *args, **kwargs):
        if url.endswith("/api/versions.json"):
            return _Resp(json.dumps(["16.13.1", "16.12.1"]).encode("ascii"))
        if url.endswith("/16.13.1/data/en_US/item.json"):
            return _Resp(json.dumps(items).encode("ascii"))
        if url.endswith("/16.13.1/img/item/6665.png"):
            return _Resp(b"PNG")
        raise AssertionError(f"unexpected url {url}")

    bind_urlopen(monkeypatch, dai, fake)
    assert dai.main() == 0
    assert (out_dir / "jaksho-the-protean.png").read_bytes() == b"PNG"
    text = capsys.readouterr().out
    assert "Using version: 16.13.1" in text
    assert "Found 1 ARAM-available items" in text
    assert "New downloads:  1" in text
    text.encode("ascii")
