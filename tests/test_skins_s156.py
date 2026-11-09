"""s156 S4: core/skins.py + dashboard/routes_skins.py, synthetic fixtures only."""
from __future__ import annotations

import json

from core import skins
from dashboard import routes_skins
from tests._module_view import bind_urlopen


def _detail(tmp_path, slug="Foo", skins_raw=None):
    d = tmp_path / "champion_detail"
    d.mkdir()
    raw = skins_raw if skins_raw is not None else [
        {"id": "1000", "num": 0, "name": "default", "chromas": False},
        {"id": "1001", "num": 1, "name": "Alpha Foo", "chromas": True},
        {"id": "1002", "num": 2, "name": "Beta Foo", "chromas": False},
    ]
    (d / f"{slug}.json").write_text(
        json.dumps({"data": {slug: {"skins": raw}}}), encoding="utf-8")
    return d


def test_skins_for_and_count(tmp_path):
    d = _detail(tmp_path)
    lst = skins.skins_for("Foo", detail_dir=d)
    assert [s["id"] for s in lst] == [1000, 1001, 1002]
    assert lst[1]["has_chromas"] is True and lst[2]["has_chromas"] is False
    assert skins.skin_count("Foo", detail_dir=d) == 2
    assert skins.skin_name("1001", "Foo", detail_dir=d) == "Alpha Foo"
    assert skins.skin_name(9, "Foo", detail_dir=d) is None


def test_skins_for_degrades(tmp_path):
    d = _detail(tmp_path)
    assert skins.skins_for("Nope", detail_dir=d) == []
    assert skins.skins_for("../Foo", detail_dir=d) == []
    assert skins.skins_for(None, detail_dir=d) == []
    (d / "Bad.json").write_text("{not json", encoding="utf-8")
    assert skins.skins_for("Bad", detail_dir=d) == []
    sub = tmp_path / "sub"
    sub.mkdir()
    assert skins.skins_for("Foo", detail_dir=_detail(sub, skins_raw=[])) == []


def test_skins_for_skips_junk_rows(tmp_path):
    d = _detail(tmp_path, skins_raw=[
        "x", {"id": True}, {"id": "-5"}, {"id": "7", "num": "z", "name": ""}])
    lst = skins.skins_for("Foo", detail_dir=d)
    assert lst == [{"id": 7, "num": 0, "name": "7", "has_chromas": False}]


def test_chromas_for(tmp_path):
    c = tmp_path / "c.json"
    c.write_text(json.dumps({"1001": {"name": "A", "chromas": [
        {"id": 1010, "name": "Ruby"}, {"id": "bad"}, {"id": 1011}]}}),
        encoding="utf-8")
    assert skins.chromas_for("1001", cache=c) == [
        {"id": 1010, "name": "Ruby"}, {"id": 1011, "name": "1011"}]
    assert skins.chromas_for(1002, cache=c) == []
    assert skins.chromas_for("x", cache=c) == []
    assert skins.chromas_for(1001, cache=tmp_path / "missing.json") == []


def test_selected_skin_from_lcu():
    sess = {"localPlayerCellId": 2, "myTeam": [
        {"cellId": 1, "selectedSkinId": 11},
        {"cellId": 2, "selectedSkinId": 1001}]}
    assert skins.selected_skin_from_lcu(sess) == 1001
    assert skins.selected_skin_from_lcu(sess, cell_id=1) == 11
    assert skins.selected_skin_from_lcu({"myTeam": []}) is None
    assert skins.selected_skin_from_lcu(
        [{"id": 5}, {"id": 1002, "selected": True}]) == 1002
    assert skins.selected_skin_from_lcu([{"id": 5}]) is None
    assert skins.selected_skin_from_lcu(None) is None
    assert skins.selected_skin_from_lcu(
        {"localPlayerCellId": 0, "myTeam": [{"cellId": 0, "selectedSkinId": 0}]}) is None


def test_refresh_rejects_non_https_and_degrades(tmp_path):
    assert skins.refresh_cdragon_cache(url="http://x", cache=tmp_path / "c.json") is False
    assert skins.refresh_cdragon_cache(
        url="https://127.0.0.1:1/x", cache=tmp_path / "c.json", timeout=0.5) is False
    assert not (tmp_path / "c.json").exists()


def test_refresh_writes_slim_cache(tmp_path, monkeypatch):
    import io
    body = json.dumps({"1001": {"id": 1001, "name": "A", "splashPath": "/art.jpg",
                                "chromas": [{"id": 1010, "name": "R", "chromaPath": "/p"}]},
                       "bad": 3}).encode()

    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    bind_urlopen(monkeypatch, skins, lambda *a, **k: R(body))
    c = tmp_path / "sub" / "c.json"
    assert skins.refresh_cdragon_cache(cache=c) is True
    doc = json.loads(c.read_text(encoding="utf-8"))
    assert doc == {"1001": {"name": "A", "chromas": [{"id": 1010, "name": "R"}]}}
    assert not c.with_suffix(".tmp").exists()


def test_refresh_routes_the_write_through_polled_json(tmp_path, monkeypatch):
    """s156 C9: the cache write goes through core.polled_json (per-writer
    scratch name, fsync, retry, scratch never left behind), not a hand-rolled
    destination-derived tmp + rename (RM-258 / RM-261 atomic-write guard)."""
    import io

    from core import polled_json

    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    body = json.dumps({"1001": {"id": 1001, "name": "A", "chromas": []}}).encode()
    bind_urlopen(monkeypatch, skins, lambda *a, **k: R(body))
    calls = []
    real = polled_json.atomic_write_bytes
    monkeypatch.setattr(polled_json, "atomic_write_bytes",
                        lambda p, d: (calls.append((p, d)), real(p, d))[1])
    c = tmp_path / "c.json"
    assert skins.refresh_cdragon_cache(cache=c) is True
    assert [p for p, _ in calls] == [c]
    assert c.read_bytes() == b'{"1001":{"name":"A","chromas":[]}}'


def test_route_payload_and_serve(tmp_path):
    d = _detail(tmp_path)
    c = tmp_path / "c.json"
    c.write_text(json.dumps({"1001": {"chromas": [{"id": 1010, "name": "R"}]}}),
                 encoding="utf-8")
    out = routes_skins.build_payload({"champion": ["Foo"], "skin": ["1001"]},
                                     detail_dir=d, cache=c)
    assert out["count"] == 2 and out["chromas"] == [{"id": 1010, "name": "R"}]
    assert routes_skins.build_payload({}, detail_dir=d, cache=c)["skins"] == []

    class H:
        path = "/api/skins?champion=Zzz"
        sent = None

        def _send(self, s, b, t):
            self.sent = (s, json.loads(b), t)

    h = H()
    routes_skins._serve_skins(h)
    assert h.sent[0] == 200 and h.sent[1]["skins"] == []
    match = routes_skins.GET_ROUTES[0][0]
    assert match("/api/skins") and match("/api/skins?x=1") and not match("/api/skinsX")
