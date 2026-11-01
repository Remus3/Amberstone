"""Guard: the docs/DAEMON_SLAYER.md server.py row GROUPS its routes honestly.

RM-1285. ``tests/test_docs_daemon_slayer_drift.py`` pins the route SET on
the ``server.py`` module-map row in both directions, but nothing read the
labels and counts the row puts on those routes. Measured at local main
6cd6779fafc1 (ENGINE 1.290.0):

  * "the 7 archetype rankers" headed TEN routes: the six ``/rank-*``
    archetype rankers plus the four evaluators ``/hybrid``, ``/ability-dps``,
    ``/burst`` and ``/hps``, whose handlers compute a score for one build
    and rank nothing (``server.py`` ``_route_hybrid`` / ``_route_ability_dps``
    / ``_route_burst`` / ``_route_hps`` docstrings);
  * ``/modifier-summary`` sat among "the additive scored-axis routes", but it
    is a GET-only diagnostic (``do_GET`` serves it directly; it is not in
    ``_POST_ROUTES``) that scores nothing;
  * the "34 routes" headline was unguarded prose.

The row is split on ``;`` into clauses. A clause whose label carries a number
must list exactly that many backticked routes; the headline count must equal
the registered surface; the archetype-ranker clause may hold only ``/rank-*``
routes and must hold all of them but the carry ``/rank``; every GET-only path
sits in the core clause and no GET-only path sits in the scored-axis clause.
The route parsers are imported from the drift guard so the two guards read one
surface. ASCII only.
"""
from __future__ import annotations

import ast
import re

from tests.test_docs_daemon_slayer_drift import (
    _SERVER,
    _doc_route_row,
    _get_only_routes,
    _post_routes,
    _server_routes,
)

_ROUTE = re.compile(r"`(/[^`]+)`")
_COUNT = re.compile(r"\b(\d+)\b")


def _tree() -> ast.Module:
    return ast.parse(_SERVER.read_text(encoding="utf-8"))


def _clauses() -> list[tuple[str, list[str]]]:
    """(label, routes) per ``;`` clause of the row's route list.

    The label is the clause text before its first backticked route, with any
    markdown table pipes dropped. The ``<N> routes - `` headline is cut first
    so its count is not read as the core clause's own count.
    """
    row = _doc_route_row()
    body = row.split("ThreadingHTTPServer`", 1)[1]
    body = re.sub(r"\d+ routes - ", "", body, count=1)
    out = []
    for part in body.split(";"):
        routes = _ROUTE.findall(part)
        if not routes:
            continue
        label = part.split("`", 1)[0].replace("|", " ").strip()
        out.append((label, routes))
    return out


def _clause(word: str) -> tuple[str, list[str]]:
    hits = [c for c in _clauses() if word in c[0]]
    assert len(hits) == 1, f"expected one clause labelled {word!r}, got {hits}"
    return hits[0]


def test_row_parses_into_labelled_clauses():
    """Anchor: an empty parse must not pass every check below vacuously."""
    clauses = _clauses()
    assert len(clauses) >= 6, clauses
    seen = [r for _, rs in clauses for r in rs]
    assert len(seen) == len(set(seen)), "a route is listed in two clauses"
    assert set(seen) == _server_routes()


def test_headline_route_count_matches_server():
    row = _doc_route_row()
    m = re.search(r"(\d+) routes - ", row)
    assert m, "the row lost its '<N> routes - ' headline"
    assert int(m.group(1)) == len(_server_routes()), (
        f"row says {m.group(1)} routes, server registers "
        f"{len(_server_routes())}"
    )


def test_every_numbered_clause_lists_that_many_routes():
    numbered = [(lbl, rs) for lbl, rs in _clauses() if _COUNT.search(lbl)]
    assert numbered, "no clause carries a count - parser drift?"
    for label, routes in numbered:
        n = int(_COUNT.search(label).group(1))
        assert n == len(routes), (
            f"clause {label!r} says {n} but lists {len(routes)}: {routes}"
        )


def test_archetype_ranker_clause_holds_exactly_the_rank_dash_routes():
    label, routes = _clause("archetype rankers")
    want = sorted(r for r in _post_routes(_tree()) if r.startswith("/rank-"))
    assert len(want) >= 6, want
    assert sorted(routes) == want, (
        f"clause {label!r} lists {sorted(routes)}; the /rank-* archetype "
        f"rankers are {want} (evaluators belong in their own clause)"
    )


def test_get_only_routes_sit_in_the_core_clause_not_the_scored_axes():
    get_only = _get_only_routes(_tree())
    assert {"/health", "/snapshot", "/modifier-summary"} <= get_only
    _, core = _clauses()[0]
    assert get_only <= set(core), (
        f"GET-only routes {sorted(get_only - set(core))} are outside the "
        "core clause"
    )
    _, axes = _clause("scored-axis")
    assert not (get_only & set(axes)), (
        f"GET-only {sorted(get_only & set(axes))} listed as a scored axis"
    )
