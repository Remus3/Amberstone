"""RM-1255 repo guard: no dashboard route module builds an f-string from a
repr of a value (``{x!r}``, ``{repr(x)}`` or ``{_clip(x)}``).

In ``dashboard/routes_*.py`` that shape was the RM-1233 / RM-1255 echo: a
400 (or 404) text that quoted the caller's own query value back. Every
route now names the parameter and the expected shape instead, so the
guard is scoped to the whole module, not only to error bodies: a log line
that wants a repr uses lazy ``%r`` logging, which this guard does not
match. A hit here is a new echo until proven otherwise.

Known open sites are allow-listed BY COUNT, so a fix there turns this guard
red until the entry is removed. None is open: the last one,
``routes_loadout.py`` ``_resolve_user_build``, was closed by RM-1374 (fixed
404 texts; the route no longer forwards the resolver's dict).

An empty enumeration would pass vacuously, so the walk is anchored: it
must see at least 40 route modules, and the detector is shown to fire on
a synthetic source holding each of the three shapes.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "dashboard"

# file name -> number of repr-shaped f-string fields still allowed there.
_KNOWN_OPEN: dict[str, int] = {}

_REPR_CALLS = frozenset({"repr", "_clip"})


def _repr_fields(source: str) -> list[int]:
    """Line numbers of every f-string field that is a repr of a value."""
    hits: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.JoinedStr):
            continue
        for part in node.values:
            if not isinstance(part, ast.FormattedValue):
                continue
            if part.conversion == ord("r"):
                hits.append(part.lineno)
                continue
            value = part.value
            if (isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id in _REPR_CALLS):
                hits.append(part.lineno)
    return sorted(hits)


def _route_modules() -> list[Path]:
    return sorted(ROUTES.glob("routes_*.py"))


def test_walk_is_not_empty():
    assert len(_route_modules()) >= 40, _route_modules()


def test_detector_fires_on_each_shape():
    src = (
        'a = f"bad id {tok!r}"\n'
        'b = f"bad id {repr(tok)}"\n'
        'c = f"bad id {_clip(tok)}"\n'
        'd = f"fine {count} {name:>4}"\n'
        'e = "%r" % (tok,)\n'
    )
    assert _repr_fields(src) == [1, 2, 3]


def test_no_route_module_formats_a_repr_into_an_fstring():
    found: dict[str, list[int]] = {}
    for path in _route_modules():
        lines = _repr_fields(path.read_text(encoding="utf-8"))
        if lines:
            found[path.name] = lines
    unexpected = {
        name: lines for name, lines in found.items()
        if len(lines) != _KNOWN_OPEN.get(name, 0)
    }
    stale = sorted(set(_KNOWN_OPEN) - set(found))
    assert not unexpected, (
        "repr-shaped f-string field in a dashboard route (the RM-1255 echo; "
        "name the parameter and the expected shape instead), or a known-open "
        f"count changed - update _KNOWN_OPEN only when fixing it: {unexpected}")
    assert not stale, (
        f"known-open site fixed, drop it from _KNOWN_OPEN: {stale}")
