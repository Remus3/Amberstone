"""Per-file live-half digests of web/, read by tests/test_web_ascii_sweep.py.

Why path prefixes, not lane names: a digest belongs to a web/ path, and lanes
do not partition paths (the uiux and queue lanes both edit web/js/main.js:
RM-1253, RM-1222). The four most re-captured sources get an area of their
own. Each row is followed by a blank line, so two lanes that re-capture
DIFFERENT sources merge cleanly even when their rows sit next to each other;
two lanes that edit the SAME source still conflict, and the merger re-captures.

The longest prefix wins and "web/" is the catch-all, so every web/ source has
exactly one area and a new directory needs no declaration here.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.guard_data import GuardDataError, check_area_files

HERE = Path(__file__).resolve().parent
SUFFIX = ".txt"

# Area file stem -> the web/ path prefix it holds.
AREAS = {
    "css_champ_select": "web/css/panels/champ_select_view.css",
    "css_header": "web/css/panels/header.css",
    "css_other": "web/css/",
    "css_panels": "web/css/panels/",
    "js_champ_select": "web/js/panels/champ_select.js",
    "js_lib": "web/js/lib/",
    "js_main": "web/js/main.js",
    "js_other": "web/js/",
    "js_panels": "web/js/panels/",
    "mock": "web/mock/",
    "web_other": "web/",
}

_ROW = re.compile(r"([0-9a-f]{64})  (web/\S.*)")
_HEADER = ("# Live-half digests for {prefix} - one `<sha256>  <path>` row per source, a\n"
           "# blank line after each. Never hand-edit: re-capture as the note on\n"
           "# tests/test_web_ascii_sweep.py _LIVE_HALF_ROWS says.\n")


def area_for(rel: str, areas=None) -> str:
    """The area holding one repo-relative web/ path: the longest prefix."""
    table = AREAS if areas is None else areas
    best = None
    for stem, prefix in table.items():
        if rel.startswith(prefix) and (best is None or len(prefix) > len(table[best])):
            best = stem
    if best is None:
        raise GuardDataError(f"{rel}: no area holds this path")
    return best


def load(directory: Path = HERE, areas=None) -> dict[str, str]:
    """{web/ path: digest} over every declared area file."""
    table = AREAS if areas is None else areas
    check_area_files(directory, SUFFIX, table)
    rows: dict[str, str] = {}
    for stem in sorted(table):
        path = directory / (stem + SUFFIX)
        raw = path.read_bytes()
        if b"\r" in raw:
            raise GuardDataError(f"{path}: carries a CR - data files are LF only")
        try:
            text = raw.decode("ascii")
        except ValueError as exc:
            raise GuardDataError(f"{path}: not ASCII: {exc}") from exc
        count = 0
        for line in text.split("\n"):
            if not line or line.startswith("#"):
                continue
            match = _ROW.fullmatch(line)
            if match is None:
                raise GuardDataError(f"{path}: malformed row: {line!r}")
            digest, rel = match.groups()
            if rel in rows:
                raise GuardDataError(f"{path}: duplicate row for {rel}")
            if area_for(rel, table) != stem:
                raise GuardDataError(
                    f"{path}: {rel} belongs in area {area_for(rel, table)}")
            rows[rel] = digest
            count += 1
        if count == 0:
            raise GuardDataError(f"{path}: area has no rows - delete the file and "
                                 "its AREAS row if the area is really gone")
    return rows


def drift_lines(actual: dict[str, str], pinned: dict[str, str]) -> list[str]:
    """One line per source whose live half differs from its pinned row."""
    lines = [f"no row (new source): {rel}" for rel in sorted(actual.keys() - pinned.keys())]
    lines += [f"stale row (source gone): {rel}" for rel in sorted(pinned.keys() - actual.keys())]
    lines += [f"live half changed: {rel}" for rel in sorted(actual.keys() & pinned.keys())
              if actual[rel] != pinned[rel]]
    return lines


def render_area(stem: str, rows: dict[str, str], areas=None) -> bytes:
    """One area file's exact bytes: ASCII, LF, rows sorted by path."""
    table = AREAS if areas is None else areas
    body = [_HEADER.format(prefix=table[stem])]
    body += [f"{rows[rel]}  {rel}\n\n" for rel in sorted(rows)
             if area_for(rel, table) == stem]
    if len(body) == 1:
        raise GuardDataError(f"area {stem} would have no rows - delete it from AREAS")
    return "".join(body).encode("ascii")


def write_areas(rows: dict[str, str], directory: Path = HERE) -> list[str]:
    """Rewrite only the area files whose bytes changed; return their names."""
    from core.polled_json import atomic_write_bytes

    written = []
    for stem in sorted(AREAS):
        path = directory / (stem + SUFFIX)
        data = render_area(stem, rows)
        if not path.exists() or path.read_bytes() != data:
            atomic_write_bytes(path, data)
            written.append(path.name)
    return written
