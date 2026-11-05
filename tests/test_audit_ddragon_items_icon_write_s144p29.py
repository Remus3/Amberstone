"""RM-1180: audit_ddragon_items.download_icon writes atomically and only images.

download_icon wrote each fetched icon with `dest.write_bytes(data)` straight
into web/data/ddragon/<ver>/img/item/, the tree the :8888 dashboard serves: no
scratch file, no fsync, no rename, so a reader could see a half-written PNG.
Its only payload check was `len(data) < 64`, so a 200 error page or an
interstitial of 64+ bytes landed as `<id>.png`. The sibling icon writer
(lib/icons/downloader.py, RM-373) already requires PNG/JPEG magic before the
write, and scripts/cache_ddragon_assets.py (RM-1130) already routes through
core.polled_json.atomic_write_bytes. This pins both on download_icon.

The opener (open_consented since RM-1441) is stubbed: no test here touches
the network.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _ROOT / "scripts" / "audit_ddragon_items.py"
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 120
_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 120
_HTML = b"<!DOCTYPE html><html><body>Service Unavailable</body></html>" + b" " * 64


def _load():
    spec = importlib.util.spec_from_file_location("audit_ddragon_items_s144p29", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Resp:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _stub_urlopen(mod, monkeypatch, bodies: dict[str, bytes]) -> list[str]:
    """bodies maps a source host fragment ('ddragon' / 'communitydragon') to
    the 200 body that source serves."""
    seen: list[str] = []

    def fake(req, timeout=None, context=None):
        url = req.full_url
        seen.append(url)
        for key, body in bodies.items():
            if key in url:
                return _Resp(body)
        raise mod.URLError("no stub")

    # RM-1441: the icon GET opens through the module's own open_consented
    # name (setattr raises if it is gone, so this fake cannot go inert).
    monkeypatch.setattr(mod, "open_consented", fake)
    return seen


def test_non_image_body_from_both_sources_writes_nothing(tmp_path, monkeypatch):
    mod = _load()
    _stub_urlopen(mod, monkeypatch, {"ddragon.leagueoflegends": _HTML,
                                     "communitydragon": _HTML})
    dest = tmp_path / "img" / "item" / "3089.png"
    assert mod.download_icon("16.14.1", "3089", dest) is None
    assert not dest.exists()
    assert not any(p.is_file() for p in tmp_path.rglob("*"))


def test_non_image_ddragon_body_falls_through_to_cdragon(tmp_path, monkeypatch):
    mod = _load()
    seen = _stub_urlopen(mod, monkeypatch, {"ddragon.leagueoflegends": _HTML,
                                            "communitydragon": _PNG})
    dest = tmp_path / "3089.png"
    assert mod.download_icon("16.14.1", "3089", dest) == "cdragon"
    assert dest.read_bytes() == _PNG
    assert len(seen) == 2


def test_non_image_body_never_overwrites_an_existing_icon(tmp_path, monkeypatch):
    mod = _load()
    _stub_urlopen(mod, monkeypatch, {"ddragon.leagueoflegends": _HTML,
                                     "communitydragon": _HTML})
    dest = tmp_path / "3089.png"
    dest.write_bytes(_PNG)
    assert mod.download_icon("16.14.1", "3089", dest) is None
    assert dest.read_bytes() == _PNG


@pytest.mark.parametrize("body", [_PNG, _JPEG], ids=["png", "jpeg"])
def test_valid_image_lands_byte_identical(tmp_path, monkeypatch, body):
    mod = _load()
    _stub_urlopen(mod, monkeypatch, {"ddragon.leagueoflegends": body})
    dest = tmp_path / "web" / "img" / "item" / "3157.png"
    assert mod.download_icon("16.14.1", "3157", dest) == "ddragon"
    assert dest.read_bytes() == body
    # no scratch file left beside it
    assert sorted(p.name for p in dest.parent.iterdir()) == ["3157.png"]


def test_write_goes_through_the_shared_atomic_writer(tmp_path, monkeypatch):
    mod = _load()
    _stub_urlopen(mod, monkeypatch, {"ddragon.leagueoflegends": _PNG})
    calls: list[tuple[Path, bytes]] = []
    real = mod.atomic_write_bytes

    def spy(path, data):
        calls.append((Path(path), data))
        real(path, data)

    monkeypatch.setattr(mod, "atomic_write_bytes", spy)
    dest = tmp_path / "3157.png"
    assert mod.download_icon("16.14.1", "3157", dest) == "ddragon"
    assert calls == [(dest, _PNG)]


def test_magic_set_agrees_with_the_rm373_icon_downloader():
    mod = _load()
    from lib.icons import downloader
    assert tuple(mod._IMAGE_MAGIC) == tuple(downloader._IMAGE_MAGIC)


def test_no_in_place_write_bytes_left_in_download_icon():
    import ast
    tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "download_icon")
    attrs = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
    assert "write_bytes" not in attrs
