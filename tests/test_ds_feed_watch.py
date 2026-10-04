"""tools/ds_feed_watch.py + the ds_feed_index.body_md5 bytes extension (RM-668).

Directive L-08 (external reference L): a READ-ONLY step in the DS batch
checklist, not a poller. It fetches the upstream changelog and diffs its dates
against a tracked high-water date, HEADs each chunk URL in the manifest's
data-block list, and records a per-block body hash beside each URL.

Every test drives a FAKE HTTP layer; nothing here touches the network.
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import pytest

import ds_feed_index as fi
import ds_feed_watch as fw

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://upstream.example.test"
U1 = ORIGIN + "/_next/static/chunks/aaa.js"
U2 = ORIGIN + "/_next/static/chunks/bbb.js"


class FakeHttp:
    def __init__(self, routes, head_routes=None):
        self.routes = routes            # url -> (status, bytes)
        self.head_routes = head_routes or {}
        self.calls = []

    def head(self, url):
        self.calls.append(("HEAD", url))
        if url in self.head_routes:
            st = self.head_routes[url]
            if isinstance(st, Exception):
                raise st
            return st
        return self.routes.get(url, (404, b""))[0]

    def get(self, url):
        self.calls.append(("GET", url))
        return self.routes.get(url, (404, b""))


def _manifest(prior=None):
    src = {"ddragon_items": "https://cdn.example.test/item.json",
           fw.DATA_BLOCKS_KEY: {"aram_modifiers": U1, "skill_orders": U2}}
    if prior is not None:
        src[fw.HASHES_KEY] = prior
    return {"engine": "daemon_slayer", "sources": src}


def _md5(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()[:8]


# -- body_md5 extension ---------------------------------------------------------


def test_body_md5_hashes_raw_bytes_verbatim():
    assert fi.body_md5(b"chunk-body") == _md5(b"chunk-body")


def test_body_md5_json_path_unchanged():
    obj = {"a": 1, "fetched_at": "x", "b": [1, 2]}
    blob = json.dumps({"a": 1, "b": [1, 2]}, sort_keys=True,
                      separators=(",", ":"))
    assert fi.body_md5(obj) == _md5(blob.encode("utf-8"))
    # a str is still a JSON value, never mistaken for a raw body
    assert fi.body_md5("abc") == _md5(b'"abc"')


# -- manifest reading -------------------------------------------------------------


def test_block_urls_and_origin():
    m = _manifest()
    assert fw.block_urls(m) == {"aram_modifiers": U1, "skill_orders": U2}
    assert fw.origin_of(fw.block_urls(m).values()) == ORIGIN


def test_origin_refuses_mixed_hosts():
    assert fw.origin_of([U1, "https://other.example.test/x.js"]) is None


def test_live_manifest_carries_the_data_block_list():
    # Meta-guard: if the key vanished, every other test here would still pass
    # against fixtures while the real checklist step had nothing to watch.
    m = json.loads(fw.manifest_path().read_text(encoding="utf-8"))
    urls = fw.block_urls(m)
    assert len(urls) >= 1
    assert fw.origin_of(urls.values()) is not None


# -- HEAD + per-block hash ---------------------------------------------------------


def test_check_blocks_heads_then_hashes():
    http = FakeHttp({U1: (200, b"one"), U2: (200, b"two")})
    rows = fw.check_blocks(_manifest(), http, now_iso="2026-10-04T00:00:00Z")
    assert rows["aram_modifiers"] == {
        "url": U1, "status": 200, "body_md5": _md5(b"one"),
        "fetched_at": "2026-10-04T00:00:00Z"}
    assert ("HEAD", U1) in http.calls and ("GET", U1) in http.calls


def test_rotated_chunk_is_flagged_without_a_get():
    http = FakeHttp({U1: (200, b"one")}, head_routes={U2: 404})
    rows = fw.check_blocks(_manifest(), http, now_iso="t")
    assert rows["skill_orders"]["status"] == 404
    assert rows["skill_orders"]["body_md5"] is None
    assert ("GET", U2) not in http.calls


def test_transport_error_is_reported_not_raised():
    http = FakeHttp({U1: (200, b"one")}, head_routes={U2: OSError("down")})
    rows = fw.check_blocks(_manifest(), http, now_iso="t")
    assert rows["skill_orders"]["status"] is None
    assert rows["skill_orders"]["body_md5"] is None


# -- changelog high-water diff ------------------------------------------------------


def test_changelog_dates_parse_common_formats():
    text = ("<li>2026-09-18 fix</li><h3>September 25, 2026</h3>"
            "<p>3 Oct 2026 - data</p><p>Sept 30th, 2026</p><p>v16.19</p>")
    assert fw.changelog_dates(text) == [
        "2026-09-18", "2026-09-25", "2026-09-30", "2026-10-03"]


def test_new_since_is_strictly_after_high_water():
    dates = ["2026-09-18", "2026-09-20", "2026-09-25"]
    assert fw.new_since(dates, "2026-09-20") == ["2026-09-25"]


def test_watch_report_diffs_changelog_and_flags_moved_blocks():
    prior = {"aram_modifiers": {"url": U1, "body_md5": _md5(b"one")},
             "skill_orders": {"url": U2, "body_md5": "deadbeef"}}
    http = FakeHttp({
        U1: (200, b"one"), U2: (200, b"two"),
        ORIGIN + fw.CHANGELOG_PATH: (200, b"<p>2026-09-30</p><p>2026-09-01</p>"),
    })
    rep = fw.watch(_manifest(prior), "2026-09-20", http, now_iso="t")
    assert rep["changelog"]["url"] == ORIGIN + fw.CHANGELOG_PATH
    assert rep["changelog"]["new_entries"] == ["2026-09-30"]
    assert rep["moved"] == ["skill_orders"]
    assert rep["unreachable"] == []
    # read-only: only HEAD/GET were issued
    assert {c[0] for c in http.calls} <= {"HEAD", "GET"}


def test_watch_without_prior_hashes_moves_nothing():
    http = FakeHttp({U1: (200, b"one"), U2: (200, b"two"),
                     ORIGIN + fw.CHANGELOG_PATH: (200, b"")})
    rep = fw.watch(_manifest(), "2026-09-20", http, now_iso="t")
    assert rep["moved"] == []
    assert rep["changelog"]["new_entries"] == []


# -- recording beside the URLs --------------------------------------------------------


def test_record_writes_hashes_beside_urls_and_preserves_the_rest(tmp_path):
    mp = tmp_path / "manifest.json"
    m = _manifest()
    mp.write_text(json.dumps(m, indent=2), encoding="utf-8")
    rows = {"aram_modifiers": {"url": U1, "status": 200, "body_md5": "11111111",
                               "fetched_at": "t"}}
    fw.record(mp, rows)
    raw = mp.read_bytes()
    assert b"\r" not in raw
    out = json.loads(raw)
    assert out["sources"][fw.DATA_BLOCKS_KEY] == m["sources"][fw.DATA_BLOCKS_KEY]
    assert out["sources"][fw.HASHES_KEY] == rows
    assert out["sources"]["ddragon_items"] == m["sources"]["ddragon_items"]
    assert not list(tmp_path.glob("*.tmp"))


def test_record_refuses_a_url_that_is_not_in_the_block_list(tmp_path):
    mp = tmp_path / "manifest.json"
    mp.write_text(json.dumps(_manifest()), encoding="utf-8")
    before = mp.read_bytes()
    with pytest.raises(ValueError):
        fw.record(mp, {"aram_modifiers": {"url": U2, "body_md5": "x"}})
    assert mp.read_bytes() == before


def test_cli_default_is_report_only(tmp_path, capsys):
    mp = tmp_path / "manifest.json"
    mp.write_text(json.dumps(_manifest()), encoding="utf-8")
    wp = tmp_path / "watch.json"
    wp.write_text(json.dumps({"changelog_high_water": "2026-09-20"}),
                  encoding="utf-8")
    before = (mp.read_bytes(), wp.read_bytes())
    http = FakeHttp({U1: (200, b"one"), U2: (200, b"two"),
                     ORIGIN + fw.CHANGELOG_PATH: (200, b"2026-09-30")})
    rc = fw.run([], http=http, manifest=mp, watch_file=wp)
    assert rc == 0
    assert (mp.read_bytes(), wp.read_bytes()) == before
    assert "2026-09-30" in capsys.readouterr().out


def test_cli_ack_advances_high_water_only(tmp_path):
    mp = tmp_path / "manifest.json"
    mp.write_text(json.dumps(_manifest()), encoding="utf-8")
    wp = tmp_path / "watch.json"
    wp.write_text(json.dumps({"changelog_high_water": "2026-09-20"}),
                  encoding="utf-8")
    m_before = mp.read_bytes()
    http = FakeHttp({})
    assert fw.run(["--ack", "2026-09-30"], http=http, manifest=mp,
                  watch_file=wp) == 0
    assert json.loads(wp.read_text())["changelog_high_water"] == "2026-09-30"
    assert mp.read_bytes() == m_before
    assert http.calls == []
    with pytest.raises(SystemExit):
        fw.run(["--ack", "not-a-date"], http=http, manifest=mp, watch_file=wp)


def test_new_tracked_files_never_spell_the_site_name():
    # Directive hard rule 3: provenance is "external reference L"; the only
    # allowed spelling is the pre-existing manifest key itself.
    key = fw.DATA_BLOCKS_KEY
    site = key.split("_", 1)[0]
    for rel in ("tools/ds_feed_watch.py", "tools/ds_feed_watch.json",
                "tests/test_ds_feed_watch.py", "tools/ship-batch.md"):
        text = (ROOT / rel).read_text(encoding="utf-8").lower()
        assert text.count(site) == text.count(key), rel


def test_record_keeps_prior_hash_for_unreachable_block_with_same_url(tmp_path):
    mp = tmp_path / "manifest.json"
    prior = {"skill_orders": {"url": U2, "body_md5": "22222222"},
             "gone_block": {"url": ORIGIN + "/old.js", "body_md5": "33333333"}}
    mp.write_text(json.dumps(_manifest(prior)), encoding="utf-8")
    fw.record(mp, {"aram_modifiers": {"url": U1, "body_md5": "11111111"}})
    got = json.loads(mp.read_text())["sources"][fw.HASHES_KEY]
    assert set(got) == {"aram_modifiers", "skill_orders"}
    assert got["skill_orders"]["body_md5"] == "22222222"
