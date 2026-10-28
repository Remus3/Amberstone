"""Guard: the on-hit DPS test cites server.py by symbol, not line (RM-1053).

Measured 2026-10-28 at ENGINE 1.290.0. The Slice B comments in
``agents/daemon_slayer/tests/test_onhit_dps.py`` cited ``server.py:2018`` for
``_POST_ROUTES``, ``server.py:181-185`` for ``_SnapshotCache.get``,
``server.py:1160`` for ``_route_rank_onhit``'s ``snap = _CACHE.get()`` and
``server.py:1154-1158`` for that route's docstring. At HEAD :2018 sits inside
``_route_rank_onhit``'s body, :181-185 is the ``/stats`` HTML help text and
:1154-1160 is a ``/rank-tank`` health-coupling comment; the real symbols live
hundreds of lines away. ``test_hybrid_enemy_champions.py:55`` and
``test_cost_aware_top_f2.py:60-62`` still resolved, but a line cite into a
file other commits edit only stays right by luck.

The tests below pin the cites and the claims they carried by symbol instead.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

from agents.daemon_slayer import server

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "agents" / "daemon_slayer" / "tests"
TARGET = TESTS / "test_onhit_dps.py"
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d")


def _target() -> str:
    return TARGET.read_text(encoding="utf-8")


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "(confirmed at server.py:2018)",
        "(server.py:181-185 _SnapshotCache.get raises",
        "``test_hybrid_enemy_champions.py:55``",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "``server._POST_ROUTES``",
        "``test_hybrid_enemy_champions._SNAPSHOT``",
        "test_rank_route_seam_passthrough.py:",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left_in_the_onhit_test():
    hits = [
        f"{TARGET.name}:{n}: {line.strip()}"
        for n, line in enumerate(_target().splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_onhit_test_names_the_symbols():
    text = _target()
    for symbol in (
        "``server._POST_ROUTES``",
        "``server._SnapshotCache.get``",
        "``server._route_rank_onhit``",
        "``test_hybrid_enemy_champions._SNAPSHOT``",
        "``test_cost_aware_top_f2.TestCostCeilingFilter"
        ".test_default_off_byte_identical``",
    ):
        assert symbol in text, symbol


def test_post_routes_dispatches_rank_onhit():
    assert server._POST_ROUTES["/rank-onhit"] is server._route_rank_onhit


def test_unseeded_snapshot_cache_raises():
    try:
        server._SnapshotCache().get()
    except RuntimeError:
        return
    raise AssertionError("_SnapshotCache.get did not raise when unseeded")


def test_rank_onhit_reads_the_cache_and_skips_mage_only_keys():
    src = inspect.getsource(server._route_rank_onhit)
    assert "snap = _CACHE.get()" in src
    doc = server._route_rank_onhit.__doc__ or ""
    assert "``max_priority``" in doc and "``block_strategy``" in doc
    assert "not parsed here" in doc


def test_hybrid_module_singleton_is_the_cited_idiom():
    text = (TESTS / "test_hybrid_enemy_champions.py").read_text(encoding="utf-8")
    assert "\n_SNAPSHOT = DataSnapshot.load()\n" in text


def test_cost_aware_default_off_test_still_compares_absent_to_none():
    text = (TESTS / "test_cost_aware_top_f2.py").read_text(encoding="utf-8")
    head, _, body = text.partition("    def test_default_off_byte_identical(self):")
    assert body, "test_default_off_byte_identical is gone"
    assert "class TestCostCeilingFilter(" in head
    assert "class " not in head.rsplit("class TestCostCeilingFilter(", 1)[1]
    assert "self._ids(cost_ceiling=None)" in body.split("    def ", 1)[0]
