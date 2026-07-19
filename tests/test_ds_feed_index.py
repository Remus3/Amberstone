"""Guard: the DS feed provenance index (tools/ds_feed_index.json) stays honest.

Five tests, each guarding a distinct failure mode of the index itself. T1 is
the META-GUARD: without it, an index that walked nothing would leave T2/T3
iterating an empty set and CI would stay green with the capability gone.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ds_feed_index as fi  # noqa: E402

from test_ds_fixture_policy import RETIRED_FIXTURES  # noqa: E402

_DATA = _ROOT / "data" / "daemon_slayer"
_INDEX = json.loads((_ROOT / "tools" / "ds_feed_index.json").read_text(encoding="utf-8"))

# 16.14.1 is the live dir and is deliberately NOT hash-frozen here (see T2).
FROZEN_DIRS = ("16.10.1", "16.11.1", "16.12.1", "16.13.1")


def _live_patch() -> str:
    return (_DATA / "current.txt").read_text(encoding="utf-8").strip()


def test_index_covers_every_semver_dir_and_feed():
    """META-GUARD: the index must describe the whole on-disk feed surface."""
    on_disk = {
        p.name
        for p in _DATA.iterdir()
        if p.is_dir() and fi.SEMVER_DIR.match(p.name)
    } - set(RETIRED_FIXTURES)
    assert set(_INDEX["dirs"]) == on_disk

    rows = 0
    for patch, feeds in _INDEX["dirs"].items():
        assert set(feeds) == {p.name for p in (_DATA / patch).glob("*.json")}
        rows += len(feeds)
    assert rows > 0


def test_frozen_body_hashes_recompute():
    """Frozen dirs ONLY - deliberate.

    A hash lock on the live dir would red on ordinary work: commit 544d6362
    moves 5 canonical bodies in the live dir alone. That trains the rubber
    stamp, so the lock covers only dirs that must never move again.
    """
    for patch in FROZEN_DIRS:
        for feed, row in _INDEX["dirs"][patch].items():
            got = fi.body_md5(json.loads((_DATA / patch / feed).read_text(encoding="utf-8")))
            assert got == row["body_md5"], f"{patch}/{feed} body moved"


def test_live_dir_stamps_match_their_directory():
    live = _live_patch()
    lag = set(_INDEX["known_stamp_lag"])
    for feed, row in _INDEX["dirs"][live].items():
        if row["stamp_field"] is None or feed in lag:
            continue
        assert row["declared_patch"] == live, f"{feed} declares {row['declared_patch']}"


def test_known_stamp_lag_entries_are_still_lagging():
    """A fixed feed must not sit in the exception list forever."""
    live = _live_patch()
    assert _INDEX["known_stamp_lag"], "exception list vanished"
    for feed in _INDEX["known_stamp_lag"]:
        row = _INDEX["dirs"][live][feed]
        assert row["stamp_field"] is not None, f"{feed} lost its stamp"
        assert row["declared_patch"] != live, (
            f"{feed} now declares {live} - it is fixed; drop it from known_stamp_lag"
        )


def test_walk_is_not_recursive():
    """Key-shape invariant: iterdir(), never rglob().

    No byte-ratio assertion - the semver dirs contain ZERO subdirectories, so
    any rglob-vs-iterdir ratio is 1.0 and would prove nothing.
    """
    for patch, feeds in _INDEX["dirs"].items():
        assert "/" not in patch and "\\" not in patch
        for feed in feeds:
            assert "/" not in feed and "\\" not in feed
    # NOTE (spec contradiction, disk wins): the spec said the literal string
    # "build_orders" must appear NOWHERE in the index. It cannot - the semver
    # dirs legitimately contain build_orders_sr/aram/arena.json feeds. The real
    # invariant is that the non-semver sibling DIRS are absent as keys, which
    # is what a stray rglob would have dragged in.
    excluded = {"build_orders", "laning_scenarios"}
    assert not (set(_INDEX["dirs"]) & excluded)
    for patch, feeds in _INDEX["dirs"].items():
        assert not (set(feeds) & excluded)
        for feed in feeds:
            assert not any(feed.startswith(x + ".") for x in excluded)
