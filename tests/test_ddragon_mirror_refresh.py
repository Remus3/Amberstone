"""Unit tests for tools/ddragon_mirror_refresh.py.

Pure-stdlib tests (no network). Live network paths are covered by the
operator-run --dry-run and the manual first-flight refresh; tests here
lock the in-process logic: safe-path filters, asset enumeration shape,
manifest round-trip, and the fetch_one decision tree under mocked HTTP.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from tools import ddragon_mirror_refresh as ddr


# ---------------------------------------------------------------------------
# safe-path filters

@pytest.mark.parametrize("name,expected", [
    ("Aatrox.png", "Aatrox.png"),
    ("1001.png", "1001.png"),
    ("Summoner4.png", "Summoner4.png"),
    ("", None),
    (None, None),
    ("../etc/passwd.png", None),
    ("..\\Windows\\System32\\evil.png", None),
    (".hidden.png", None),
    (".", None),
    ("..", None),
    ("a/b.png", None),
    ("a\\b.png", None),
    ("C:foo.png", None),
    ("name\x00.png", None),
])
def test_safe_basename(name, expected):
    assert ddr._safe_basename(name) == expected


@pytest.mark.parametrize("rel,expected", [
    ("perk-images/Styles/Domination/Electrocute/Electrocute.png",
     "perk-images/Styles/Domination/Electrocute/Electrocute.png"),
    ("perk-images/Styles/7200_Domination.png", "perk-images/Styles/7200_Domination.png"),
    ("", None),
    (None, None),
    ("/abs/path.png", None),
    ("perk-images\\Styles\\x.png", None),
    ("perk-images/../etc/passwd.png", None),
    ("perk-images/./x.png", None),
])
def test_safe_relpath(rel, expected):
    assert ddr._safe_relpath(rel) == expected


# ---------------------------------------------------------------------------
# enumerate_assets walks every bundle class

def _stub_bundles():
    return {
        "champion": {
            "data": {
                "Aatrox": {
                    "image": {"full": "Aatrox.png"},
                    "passive": {"image": {"full": "Aatrox_Passive.png"}},
                    "spells": [
                        {"image": {"full": "AatroxQ.png"}},
                        {"image": {"full": "AatroxW.png"}},
                    ],
                },
                "Ahri": {
                    "image": {"full": "Ahri.png"},
                    "passive": {"image": {"full": "Ahri_Passive.png"}},
                    "spells": [{"image": {"full": "AhriQ.png"}}],
                },
            },
        },
        "item": {"data": {
            "1001": {"image": {"full": "1001.png"}},
            "3074": {"image": {"full": "3074.png"}},
        }},
        "summoner": {"data": {
            "SummonerFlash": {"image": {"full": "SummonerFlash.png"}},
            "SummonerHeal": {"image": {"full": "SummonerHeal.png"}},
        }},
        "profileicon": {"data": {
            "1": {"image": {"full": "1.png"}},
            "2": {"image": {"full": "2.png"}},
        }},
        "runesReforged": [
            {
                "icon": "perk-images/Styles/7200_Domination.png",
                "slots": [
                    {"runes": [
                        {"icon": "perk-images/Styles/Domination/Electrocute/Electrocute.png"},
                        {"icon": "perk-images/Styles/Domination/DarkHarvest/DarkHarvest.png"},
                    ]},
                    {"runes": [
                        {"icon": "perk-images/Styles/Domination/CheapShot/CheapShot.png"},
                    ]},
                ],
            },
        ],
    }


def test_enumerate_assets_covers_every_class():
    assets = ddr.enumerate_assets("16.10.1", _stub_bundles())
    by_cls: dict[str, list] = {}
    for a in assets:
        by_cls.setdefault(a.cls, []).append(a)
    # Expected: 2 champion, 2 passive, 3 spell (2x ability for Aatrox + 1 Ahri)
    # + 2 summoner spells (de-duped into spell class), 2 item, 2 profileicon,
    # 3 map (11/12/30), 4 rune (1 tree + 3 runes)
    assert {a.rel_dest for a in by_cls["champion"]} == {
        "img/champion/Aatrox.png", "img/champion/Ahri.png"}
    assert {a.rel_dest for a in by_cls["passive"]} == {
        "img/passive/Aatrox_Passive.png", "img/passive/Ahri_Passive.png"}
    spell_dests = {a.rel_dest for a in by_cls["spell"]}
    assert "img/spell/AatroxQ.png" in spell_dests
    assert "img/spell/AhriQ.png" in spell_dests
    assert "img/spell/SummonerFlash.png" in spell_dests
    assert "img/spell/SummonerHeal.png" in spell_dests
    assert {a.rel_dest for a in by_cls["item"]} == {
        "img/item/1001.png", "img/item/3074.png"}
    assert {a.rel_dest for a in by_cls["profileicon"]} == {
        "img/profileicon/1.png", "img/profileicon/2.png"}
    assert {a.rel_dest for a in by_cls["map"]} == {
        "img/map/map11.png", "img/map/map12.png", "img/map/map30.png"}
    rune_dests = {a.rel_dest for a in by_cls["rune"]}
    assert "img/perk-images/Styles/7200_Domination.png" in rune_dests
    assert "img/perk-images/Styles/Domination/Electrocute/Electrocute.png" in rune_dests


def test_enumerate_assets_url_versioning():
    assets = ddr.enumerate_assets("16.10.1", _stub_bundles())
    for a in assets:
        if a.cls == "rune":
            # Rune assets are version-LESS under /cdn/img/.
            assert a.url.startswith("https://ddragon.leagueoflegends.com/cdn/img/")
        else:
            assert a.url.startswith(
                "https://ddragon.leagueoflegends.com/cdn/16.10.1/img/")


def test_enumerate_assets_rejects_traversal():
    bundles = _stub_bundles()
    bundles["item"]["data"]["evil"] = {"image": {"full": "../../etc/passwd"}}
    bundles["champion"]["data"]["Bad"] = {
        "image": {"full": "../Aatrox.png"},
        "passive": {"image": {"full": "ok_passive.png"}},
        "spells": [],
    }
    assets = ddr.enumerate_assets("16.10.1", bundles)
    rel_dests = {a.rel_dest for a in assets}
    assert "img/item/passwd" not in rel_dests
    assert "img/champion/../Aatrox.png" not in rel_dests
    # passives from the same bad champion still pass because they used a clean
    # basename - per-field rejection, not all-or-nothing per champion.
    assert "img/passive/ok_passive.png" in rel_dests


def test_enumerate_assets_dedupes_overlapping_spell_paths():
    bundles = _stub_bundles()
    # Same image.full appearing on both summoner and champion ability sides
    # must produce ONE asset entry (idempotent destination).
    bundles["summoner"]["data"]["DupeWithChampionSpell"] = {
        "image": {"full": "AatroxQ.png"},
    }
    assets = ddr.enumerate_assets("16.10.1", bundles)
    count = sum(1 for a in assets if a.rel_dest == "img/spell/AatroxQ.png")
    assert count == 1


# ---------------------------------------------------------------------------
# manifest round-trip

def test_manifest_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(ddr, "META_DIR", tmp_path)
    m = ddr.read_manifest("16.10.1")
    assert m["version"] == "16.10.1"
    assert m["assets"] == {}
    m["assets"]["img/item/1001.png"] = {
        "size": 4537,
        "sha256": "fc8248d1681f492d324bea66a61bce4a" * 2,
        "etag": '"fc8248d1681f492d324bea66a61bce4a"',
    }
    ddr.write_manifest("16.10.1", m)
    written = json.loads((tmp_path / "16.10.1" / "_assets_manifest.json").read_text("utf-8"))
    assert written["version"] == "16.10.1"
    assert "fetched_at" in written
    assert written["assets"]["img/item/1001.png"]["size"] == 4537


def test_manifest_corrupt_recovers(tmp_path, monkeypatch):
    monkeypatch.setattr(ddr, "META_DIR", tmp_path)
    (tmp_path / "16.10.1").mkdir(parents=True)
    (tmp_path / "16.10.1" / "_assets_manifest.json").write_text(
        "{not valid json", encoding="utf-8")
    m = ddr.read_manifest("16.10.1")
    assert m == {"version": "16.10.1", "assets": {}}


# ---------------------------------------------------------------------------
# fetch_one decision tree

def _mk_asset():
    return ddr.Asset(
        cls="item",
        url="https://ddragon.leagueoflegends.com/cdn/16.10.1/img/item/1001.png",
        rel_dest="img/item/1001.png",
    )


def test_fetch_one_skip_when_present_default(tmp_path):
    a = _mk_asset()
    dest = tmp_path / "out.png"
    dest.write_bytes(b"existing")
    with mock.patch.object(ddr, "http_get") as mh:
        status, entry = ddr.fetch_one(a, dest, manifest_entry={"size": 8},
                                      check_changed=False, force=False)
    assert status == "skip_present"
    assert entry is None
    mh.assert_not_called()


def test_fetch_one_new_when_missing(tmp_path):
    a = _mk_asset()
    dest = tmp_path / "deep" / "out.png"
    body = b"\x89PNG\r\n" + b"x" * 100
    fake = ddr.HttpResult(200, {"etag": '"abc"', "last-modified": "now"}, body)
    with mock.patch.object(ddr, "http_get", return_value=fake) as mh:
        status, entry = ddr.fetch_one(a, dest, manifest_entry=None,
                                      check_changed=False, force=False)
    assert status == "new"
    assert dest.exists() and dest.read_bytes() == body
    assert entry["size"] == len(body)
    assert entry["etag"] == '"abc"'
    assert entry["last_modified"] == "now"
    assert len(entry["sha256"]) == 64
    mh.assert_called_once()


def test_fetch_one_check_changed_skips_on_etag_match(tmp_path):
    a = _mk_asset()
    dest = tmp_path / "out.png"
    dest.write_bytes(b"old")
    head = ddr.HttpResult(200, {"etag": '"abc"', "content-length": "3"}, b"")
    with mock.patch.object(ddr, "http_head", return_value=head) as mhead, \
         mock.patch.object(ddr, "http_get") as mget:
        status, entry = ddr.fetch_one(
            a, dest, manifest_entry={"etag": '"abc"', "size": 3},
            check_changed=True, force=False,
        )
    assert status == "skip_present"
    assert entry is None
    mhead.assert_called_once()
    mget.assert_not_called()


def test_fetch_one_check_changed_refetches_on_etag_diff(tmp_path):
    a = _mk_asset()
    dest = tmp_path / "out.png"
    dest.write_bytes(b"old")
    head = ddr.HttpResult(200, {"etag": '"new"', "content-length": "10"}, b"")
    body = b"newbody___"
    full = ddr.HttpResult(200, {"etag": '"new"', "last-modified": "later"}, body)
    with mock.patch.object(ddr, "http_head", return_value=head), \
         mock.patch.object(ddr, "http_get", return_value=full):
        status, entry = ddr.fetch_one(
            a, dest, manifest_entry={"etag": '"old"', "size": 3},
            check_changed=True, force=False,
        )
    assert status == "changed"
    assert dest.read_bytes() == body
    assert entry["etag"] == '"new"'


def test_fetch_one_check_changed_handles_304(tmp_path):
    a = _mk_asset()
    dest = tmp_path / "out.png"
    dest.write_bytes(b"old")
    # HEAD says different etag -> trigger conditional GET; GET returns 304.
    head = ddr.HttpResult(200, {"etag": '"otheretag"', "content-length": "3"}, b"")
    nm = ddr.HttpResult(304, {}, b"")
    with mock.patch.object(ddr, "http_head", return_value=head), \
         mock.patch.object(ddr, "http_get", return_value=nm):
        status, entry = ddr.fetch_one(
            a, dest, manifest_entry={"etag": '"old"', "size": 3},
            check_changed=True, force=False,
        )
    assert status == "skip_present"
    assert entry is None


def test_fetch_one_404_marked_failed(tmp_path):
    a = _mk_asset()
    dest = tmp_path / "out.png"
    fake = ddr.HttpResult(404, {}, b"")
    with mock.patch.object(ddr, "http_get", return_value=fake):
        status, entry = ddr.fetch_one(a, dest, manifest_entry=None,
                                      check_changed=False, force=False)
    assert status == "fail_404"
    assert entry is None
    assert not dest.exists()


def test_fetch_one_404_retries_once_then_succeeds(tmp_path):
    # CDN edge 404s under load can be transient; one retry must recover.
    a = _mk_asset()
    dest = tmp_path / "deep" / "out.png"
    body = b"\x89PNG\r\nrecovered"
    miss = ddr.HttpResult(404, {}, b"")
    hit = ddr.HttpResult(200, {"etag": '"r"'}, body)
    with mock.patch.object(ddr, "http_get", side_effect=[miss, hit]) as mh:
        status, entry = ddr.fetch_one(a, dest, manifest_entry=None,
                                      check_changed=False, force=False)
    assert status == "new"
    assert dest.exists() and dest.read_bytes() == body
    assert entry["etag"] == '"r"'
    assert mh.call_count == 2


def test_fetch_one_404_retries_once_then_gives_up(tmp_path):
    a = _mk_asset()
    dest = tmp_path / "out.png"
    miss = ddr.HttpResult(404, {}, b"")
    with mock.patch.object(ddr, "http_get", side_effect=[miss, miss]) as mh:
        status, entry = ddr.fetch_one(a, dest, manifest_entry=None,
                                      check_changed=False, force=False)
    assert status == "fail_404"
    assert entry is None
    assert not dest.exists()
    assert mh.call_count == 2


def test_fetch_one_force_refetches_when_present(tmp_path):
    a = _mk_asset()
    dest = tmp_path / "out.png"
    dest.write_bytes(b"old")
    body = b"forced-new"
    full = ddr.HttpResult(200, {"etag": '"f"'}, body)
    with mock.patch.object(ddr, "http_get", return_value=full):
        status, entry = ddr.fetch_one(
            a, dest, manifest_entry={"etag": '"old"', "size": 3},
            check_changed=False, force=True,
        )
    # force + manifest_entry present = "changed"
    assert status == "changed"
    assert dest.read_bytes() == body
    assert entry["etag"] == '"f"'


# ---------------------------------------------------------------------------
# index helpers

def test_index_roundtrip(tmp_path, monkeypatch):
    idx_path = tmp_path / "_index.json"
    monkeypatch.setattr(ddr, "INDEX_PATH", idx_path)
    assert ddr.read_index() == {}
    ddr.write_index("16.10.1", ["champion", "item"])
    parsed = json.loads(idx_path.read_text("utf-8"))
    assert parsed["latest_pulled"] == "16.10.1"
    assert parsed["bundles"] == ["champion", "item"]
    assert parsed["locale"] == "en_US"


def test_check_only_exit_codes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ddr, "WEB_DIR", tmp_path / "web")
    # latest != cached -> flip pending (exit 1)
    rc = ddr.cmd_check_only("16.11.1", "16.10.1")
    assert rc == 1
    assert "flip_pending" in capsys.readouterr().out
    # latest == cached + no mirror dir -> still exit 1
    rc = ddr.cmd_check_only("16.10.1", "16.10.1")
    assert rc == 1
    assert "no_mirror_dir" in capsys.readouterr().out
    # mirror dir present -> up-to-date
    (tmp_path / "web" / "16.10.1").mkdir(parents=True)
    rc = ddr.cmd_check_only("16.10.1", "16.10.1")
    assert rc == 0
    assert "up_to_date" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# stats rendering is human-readable

def test_render_stats_table_lists_each_class():
    s = ddr.PlanStats(total=10, skipped_present=7, fetched_new=2, fetched_changed=1, failed=0)
    s.by_class = {
        "champion": [3, 1, 0, 0],
        "item": [5, 1, 1, 0],
        "spell": [2, 0, 0, 0],
    }
    out = ddr.render_stats_table(s)
    assert "champion" in out
    assert "item" in out
    assert "TOTAL" in out
    assert "new=2 chg=1 skip=7" in out


# ---------------------------------------------------------------------------
# exit-code tolerance: a handful of transient single-asset flakes across
# thousands of CDN probes must not trip the nightly cron's last_result canary
# (item 376 - benign result=2 from one 404 among ~6800 assets).

def _stats(total, failed):
    s = ddr.PlanStats(total=total)
    s.failed = failed
    return s


def test_exit_code_zero_when_clean():
    assert ddr._exit_code_for(_stats(6792, 0)) == 0


def test_exit_code_tolerates_small_transient_ratio():
    # 3 / 6792 = 0.044% <= 0.5% -> tolerated, exit 0.
    assert ddr._exit_code_for(_stats(6792, 3)) == 0


def test_exit_code_two_on_mass_failure():
    # 10 / 100 = 10% -> genuine partial outage, exit 2.
    assert ddr._exit_code_for(_stats(100, 10)) == 2


def test_exit_code_threshold_boundary_inclusive():
    # exactly 0.5% (1/200) is tolerated (<=); 1/199 just over is not.
    assert ddr._exit_code_for(_stats(200, 1)) == 0
    assert ddr._exit_code_for(_stats(199, 1)) == 2


def test_exit_code_zero_total_no_crash():
    assert ddr._exit_code_for(_stats(0, 0)) == 0


def test_failures_within_tolerance_boundary():
    assert ddr._failures_within_tolerance(_stats(6792, 3)) is True
    assert ddr._failures_within_tolerance(_stats(200, 1)) is True
    assert ddr._failures_within_tolerance(_stats(199, 1)) is False
    assert ddr._failures_within_tolerance(_stats(10, 0)) is True


# ---------------------------------------------------------------------------
# main() index-write gating shares the tolerance: a version flip must complete
# same-night despite a tolerable transient flake (item 376 follow-up B).

def _wire_main(monkeypatch, *, latest, cached, stats):
    monkeypatch.setattr(ddr, "resolve_latest_version", lambda: latest)
    monkeypatch.setattr(ddr, "read_index", lambda: {"latest_pulled": cached})
    monkeypatch.setattr(ddr, "run", lambda *a, **k: stats)
    spy = mock.Mock()
    monkeypatch.setattr(ddr, "write_index", spy)
    return spy


def test_main_advances_index_on_flip_despite_tolerable_failure(monkeypatch, capsys):
    s = _stats(6792, 3)
    s.fetched_new = 10
    spy = _wire_main(monkeypatch, latest="16.12.1", cached="16.11.1", stats=s)
    rc = ddr.main(["--check-changed"])
    assert rc == 0
    spy.assert_called_once()
    assert spy.call_args.args[0] == "16.12.1"


def test_main_keeps_index_on_flip_with_mass_failure(monkeypatch, capsys):
    s = _stats(100, 10)
    spy = _wire_main(monkeypatch, latest="16.12.1", cached="16.11.1", stats=s)
    rc = ddr.main(["--check-changed"])
    assert rc == 2
    spy.assert_not_called()


# ---------------------------------------------------------------------------
# _http retry-with-backoff (transient errors should not flake the cron)

def test_http_retries_on_url_error_then_succeeds(monkeypatch):
    import urllib.error as ue
    from io import BytesIO

    class _FakeResp:
        status = 200
        headers = {"etag": '"ok"'}
        def read(self): return b"BODY"
        def __enter__(self): return self
        def __exit__(self, *a): return False

    calls = []
    def fake_open(req, timeout):
        calls.append(req.full_url)
        if len(calls) == 1:
            raise ue.URLError("timed out")
        return _FakeResp()

    sleeps = []
    monkeypatch.setattr(ddr.urllib_request, "urlopen", fake_open)
    monkeypatch.setattr(ddr.time, "sleep", lambda s: sleeps.append(s))

    res = ddr._http("GET", "https://example/asset.png")
    assert res.status == 200
    assert res.body == b"BODY"
    assert len(calls) == 2
    assert sleeps == [ddr.RETRY_BACKOFFS[0]]


def test_http_gives_up_after_max_retries(monkeypatch):
    import urllib.error as ue

    calls = []
    def always_fail(req, timeout):
        calls.append(req.full_url)
        raise ue.URLError("timed out")

    monkeypatch.setattr(ddr.urllib_request, "urlopen", always_fail)
    monkeypatch.setattr(ddr.time, "sleep", lambda s: None)

    with pytest.raises(ue.URLError):
        ddr._http("GET", "https://example/dead.png")
    assert len(calls) == len(ddr.RETRY_BACKOFFS) + 1


def test_http_retries_on_5xx_then_succeeds(monkeypatch):
    import urllib.error as ue

    class _FakeResp:
        status = 200
        headers = {}
        def read(self): return b"OK"
        def __enter__(self): return self
        def __exit__(self, *a): return False

    calls = []
    def flaky(req, timeout):
        calls.append(req.full_url)
        if len(calls) == 1:
            raise ue.HTTPError(req.full_url, 503, "down", {}, None)
        return _FakeResp()

    sleeps = []
    monkeypatch.setattr(ddr.urllib_request, "urlopen", flaky)
    monkeypatch.setattr(ddr.time, "sleep", lambda s: sleeps.append(s))

    res = ddr._http("GET", "https://example/asset.png")
    assert res.status == 200
    assert res.body == b"OK"
    assert len(calls) == 2
    assert sleeps == [ddr.RETRY_BACKOFFS[0]]


def test_http_does_not_retry_on_404(monkeypatch):
    import urllib.error as ue

    calls = []
    def four_oh_four(req, timeout):
        calls.append(req.full_url)
        raise ue.HTTPError(req.full_url, 404, "gone", {}, None)

    monkeypatch.setattr(ddr.urllib_request, "urlopen", four_oh_four)
    sleeps = []
    monkeypatch.setattr(ddr.time, "sleep", lambda s: sleeps.append(s))

    res = ddr._http("GET", "https://example/missing.png")
    assert res.status == 404
    assert len(calls) == 1
    assert sleeps == []
