"""tools/ds_feed_watch.py + the ds_feed_index.body_md5 bytes extension (RM-668).

Directive L-08 (external reference L): a READ-ONLY step in the DS batch
checklist, not a poller. It fetches the upstream changelog and diffs its dates
against a tracked high-water date, HEADs each chunk URL in the manifest's
data-block list, and records a per-block body hash beside each URL.

Every test drives a FAKE HTTP layer; nothing here touches the network.
"""
import hashlib
import json
import re
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


BLOCKS_KEY = "refl" + fw.DATA_BLOCKS_SUFFIX


def _manifest(prior=None):
    src = {"ddragon_items": "https://cdn.example.test/item.json",
           BLOCKS_KEY: {"aram_modifiers": U1, "skill_orders": U2}}
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
    assert out["sources"][BLOCKS_KEY] == m["sources"][BLOCKS_KEY]
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
    # Directive hard rule 3: provenance is "external reference L". The site
    # name is derived from the pre-existing extractor key, never spelled here.
    src = (ROOT / "tools/daemon_slayer_extract.py").read_text(encoding="utf-8")
    m = re.search(r'"([a-z0-9]+)' + fw.DATA_BLOCKS_SUFFIX + '"', src)
    assert m, "extractor no longer writes a *_data_blocks key"
    site = m.group(1)
    for rel in ("tools/ds_feed_watch.py", "tools/ds_feed_watch.json",
                "tests/test_ds_feed_watch.py", "tools/ship-batch.md"):
        text = (ROOT / rel).read_text(encoding="utf-8").lower()
        assert site not in text, rel


def test_blocks_key_found_by_suffix_and_ambiguity_refused():
    assert fw.data_blocks_key({"x" + fw.DATA_BLOCKS_SUFFIX: {}, "a": 1}) == "x" + fw.DATA_BLOCKS_SUFFIX
    assert fw.data_blocks_key({"x" + fw.DATA_BLOCKS_SUFFIX: {}, "y" + fw.DATA_BLOCKS_SUFFIX: {}}) is None
    assert fw.data_blocks_key(None) is None


def test_record_keeps_prior_hash_for_unreachable_block_with_same_url(tmp_path):
    mp = tmp_path / "manifest.json"
    prior = {"skill_orders": {"url": U2, "body_md5": "22222222"},
             "gone_block": {"url": ORIGIN + "/old.js", "body_md5": "33333333"}}
    mp.write_text(json.dumps(_manifest(prior)), encoding="utf-8")
    fw.record(mp, {"aram_modifiers": {"url": U1, "body_md5": "11111111"}})
    got = json.loads(mp.read_text())["sources"][fw.HASHES_KEY]
    assert set(got) == {"aram_modifiers", "skill_orders"}
    assert got["skill_orders"]["body_md5"] == "22222222"


# -- live build discovery: files rebuilt under NEW names (RM-839) ---------------
#
# Upstream chunk names are content hashes. A rebuild publishes NEW names and
# leaves the old files on the CDN, so HEAD/GET on the recorded URLs keeps
# answering 200 with the old, unchanged bytes. Only walking the live site's
# own chunk graph can show that the recorded files are no longer served.

CHUNKS = ORIGIN + "/_next/static/chunks/"
U3 = CHUNKS + "ccc.js"
ROOT_URL = ORIGIN + "/"
ANCHORS = {"aram_modifiers": "aramDamageTaken", "skill_orders": '["Q","E","W"'}
ENTRY = "entry0000001.js"
LAZY_ARAM = "lazyaram0002.js"
NEW_SKILL = "skillnew0003.js"
UNUSED = "unused000004.js"


def _html(*names):
    return "".join(f'<script src="/_next/static/chunks/{n}"></script>'
                   for n in names).encode()


def _rebuilt_routes():
    """Old URLs still answer 200; the live root names only the NEW chunks."""
    return {
        U1: (200, b"old aramDamageTaken body"),
        U2: (200, b'old ["Q","E","W"] body'),
        U3: (200, b"old scenarios body"),
        ROOT_URL: (200, _html(ENTRY, NEW_SKILL)),
        # a lazy loader call names the ARAM chunk with a bare "<id>.js"
        CHUNKS + ENTRY: (200, b'e.l("' + LAZY_ARAM.encode() + b'")'),
        CHUNKS + LAZY_ARAM: (200, b"JSON.parse('{\"A\":{\"aramDamageTaken\":1}}')"),
        CHUNKS + NEW_SKILL: (200, b"JSON.parse('{\"A\":[\"Q\",\"E\",\"W\"]}')"),
        ORIGIN + fw.CHANGELOG_PATH: (200, b""),
    }


def test_rebuild_under_new_names_is_moved_although_old_urls_answer():
    http = FakeHttp(_rebuilt_routes())
    rep = fw.watch(_manifest(), "2026-09-20", http, now_iso="t",
                   anchors=ANCHORS)
    # the old URLs still answer, so the HEAD/GET pass alone saw nothing
    assert rep["unreachable"] == []
    assert rep["moved"] == ["aram_modifiers", "skill_orders"]
    assert rep["relocated"]["aram_modifiers"]["old"] == U1
    assert rep["relocated"]["aram_modifiers"]["new"] == CHUNKS + LAZY_ARAM
    assert rep["relocated"]["skill_orders"]["new"] == CHUNKS + NEW_SKILL
    assert rep["live"]["status"] == "complete"
    out = fw.render(rep)
    assert "MOVED: aram_modifiers, skill_orders" in out
    assert LAZY_ARAM in out and NEW_SKILL in out
    assert {c[0] for c in http.calls} <= {"HEAD", "GET"}


def test_nothing_rebuilt_keeps_moved_none_and_stops_crawling_early():
    routes = {
        U1: (200, b"aramDamageTaken"), U2: (200, b'["Q","E","W"'),
        # the root names one recorded chunk directly, the other lazily
        ROOT_URL: (200, _html(ENTRY, "aaa.js", UNUSED)),
        CHUNKS + ENTRY: (200, b'e.l("static/chunks/bbb.js")'),
        CHUNKS + UNUSED: (200, b""),
        ORIGIN + fw.CHANGELOG_PATH: (200, b""),
    }
    http = FakeHttp(routes)
    rep = fw.watch(_manifest(), "2026-09-20", http, now_iso="t",
                   anchors=ANCHORS)
    assert rep["moved"] == []
    assert rep["relocated"] == {}
    assert rep["unverified"] == []
    assert rep["live"]["status"] == "ok"
    assert "MOVED: none" in fw.render(rep)
    # every recorded name was seen after the first fetch: no further crawl
    assert ("GET", CHUNKS + UNUSED) not in http.calls


def test_unreadable_live_root_is_reported_not_called_none():
    http = FakeHttp({U1: (200, b"one"), U2: (200, b"two")})
    rep = fw.watch(_manifest(), "2026-09-20", http, now_iso="t",
                   anchors=ANCHORS)
    assert rep["live"]["status"] == "failed"
    assert rep["live"]["root_status"] == 404
    assert rep["relocated"] == {}
    assert "cannot be seen" in fw.render(rep)


def test_capped_crawl_is_unverified_not_moved(monkeypatch):
    monkeypatch.setattr(fw, "LIVE_CRAWL_MAX_FETCH", 1)
    routes = dict(_rebuilt_routes())
    # the only chunk the cap lets us read names neither recorded file
    routes[ROOT_URL] = (200, _html(ENTRY, UNUSED))
    http = FakeHttp(routes)
    rep = fw.watch(_manifest(), "2026-09-20", http, now_iso="t",
                   anchors=ANCHORS)
    assert rep["live"]["status"] == "capped"
    assert rep["moved"] == []
    assert rep["unverified"] == ["aram_modifiers", "skill_orders"]
    assert "UNVERIFIED: aram_modifiers, skill_orders" in fw.render(rep)


def test_other_recorded_chunks_are_watched_too_and_labels_drop_the_prefix():
    m = _manifest()
    src = m["sources"]
    src["refl_scenarios_chunk"] = U3
    src["refl_scenarios_chunk_bytes"] = 123
    src["refl_scenario_pieces"] = {"scenarios": [U3, U2], "roles": U1}
    assert fw.watched_chunks(m) == {
        "aram_modifiers": U1, "skill_orders": U2,
        # a piece sharing a block's URL is that block; only new files count
        "scenario_pieces.scenarios[0]": U3, "scenarios_chunk": U3}
    http = FakeHttp(_rebuilt_routes())
    rep = fw.watch(m, "2026-09-20", http, now_iso="t", anchors=ANCHORS)
    assert rep["moved"] == ["aram_modifiers", "scenario_pieces.scenarios[0]",
                            "scenarios_chunk", "skill_orders"]
    assert rep["relocated"]["scenarios_chunk"] == {
        "old": U3, "new": None, "candidates": []}
    assert "not in the live build" in fw.render(rep)


def test_anchors_come_from_the_extractor_table_without_importing_it(monkeypatch):
    # Single source of truth: the extractor's _DATA_BLOCKS, read by AST (an
    # import would configure logging and open its log file).
    monkeypatch.delitem(sys.modules, "daemon_slayer_extract", raising=False)
    anchors = fw.extractor_anchors()
    assert "daemon_slayer_extract" not in sys.modules
    m = json.loads(fw.manifest_path().read_text(encoding="utf-8"))
    assert set(anchors) == set(fw.block_urls(m))
    assert all(isinstance(a, str) and a for a in anchors.values())


def test_extractor_anchors_resolve_names_and_literals(tmp_path):
    src = tmp_path / "x.py"
    src.write_text('A_ANCHOR = "alpha"\n'
                   '_DATA_BLOCKS = (("a", A_ANCHOR), ("b", "beta"),'
                   ' ("c", MISSING))\n', encoding="utf-8")
    assert fw.extractor_anchors(src) == {"a": "alpha", "b": "beta"}
    assert fw.extractor_anchors(tmp_path / "absent.py") == {}
