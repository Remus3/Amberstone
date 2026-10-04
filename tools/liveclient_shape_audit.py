"""Live Client shape audit (RM-601, directive X-01).

Provenance: idea from external reference E (re-implemented from the behaviour
description only; no code taken).

Re-parses one or more locally CAPTURED ``/liveclientdata/allgamedata`` JSON
payloads and prints three lists:

1. EVENT NAMES WITH NO RC CONSUMER - every ``EventName`` value seen in the
   captures that no RC source file consumes.
2. MODELLED FIELDS WITH THE WRONG JSON TYPE - fields RC models (``SCHEMA``
   below) whose observed JSON type differs from the expected one, e.g.
   ``Stolen`` arriving as the string "True" instead of a bool.
3. KEYS NOTHING READS - payload key names that appear nowhere in RC source.

Captures name other players. Keep them in a GITIGNORED path (for example
``ops/runtime/liveclient_captures/``) and never commit one; committed test
fixtures are synthetic and name-scrubbed.

How "consumed" is derived (a static, deliberately loose heuristic)
------------------------------------------------------------------
The scan walks the RC source directories in ``SOURCE_DIRS`` plus the ``.py``
files at the repo root, skipping ``tests/`` and ``tools/`` (so test fixtures,
allowlists and this tool's own schema never count as a consumer).

* An EventName counts as CONSUMED when it appears as a quoted string literal
  (single or double quotes, exact match) in any scanned ``.py`` / ``.js`` file
  that also contains the token ``EventName``. That is how every RC consumer
  is written today (``ev.get("EventName") == "DragonKill"``, or a name map
  next to such a read). It over-approximates (a literal in such a file need
  not be compared against EventName), so a name reported UNCONSUMED really
  has no literal anywhere near an EventName read.
* A payload KEY counts as READ when its name appears as a quoted literal in
  any scanned file, or (``.js`` only) as a ``.name`` property access. Also an
  over-approximation, so "unread" is a strong claim.

Usage::

    python tools/liveclient_shape_audit.py <capture.json | dir-of-captures>

A capture may be the raw allgamedata object or a ``{"data": {...}}`` wrapper
(the relay cache shape). Exit code is 0; this is a report, not a gate (the
gate over the SYNTHETIC fixture is tests/test_liveclient_shape_audit_rm601.py).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SOURCE_DIRS = ("app", "coaches", "core", "dashboard", "game_reader", "lcu",
               "modes", "modules", "coach_integration", "web/js")
_SKIP_PARTS = {"__pycache__", "node_modules", "_archive", "tests", "tools"}

_QUOTED = re.compile(r"""["']([A-Za-z_][A-Za-z0-9_]*)["']""")
_JS_PROP = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)")
_INT_KEY = re.compile(r"-?[0-9]+")

_NUM = "number"
# Modelled field path -> expected JSON type. "[]" marks a list element.
# Expected types are the documented wire types; "number" = int or float.
SCHEMA: dict[str, str] = {
    "activePlayer": "object",
    "activePlayer.level": "int",
    "activePlayer.currentGold": _NUM,
    "activePlayer.summonerName": "str",
    "allPlayers": "list",
    "allPlayers[].championName": "str",
    "allPlayers[].team": "str",
    "allPlayers[].level": "int",
    "allPlayers[].isDead": "bool",
    "allPlayers[].respawnTimer": _NUM,
    "allPlayers[].items": "list",
    "allPlayers[].items[].itemID": "int",
    "allPlayers[].scores": "object",
    "allPlayers[].scores.kills": "int",
    "allPlayers[].scores.deaths": "int",
    "allPlayers[].scores.assists": "int",
    "allPlayers[].scores.creepScore": "int",
    "allPlayers[].scores.wardScore": _NUM,
    "events": "object",
    "events.Events": "list",
    "events.Events[].EventID": "int",
    "events.Events[].EventName": "str",
    "events.Events[].EventTime": _NUM,
    "events.Events[].KillerName": "str",
    "events.Events[].VictimName": "str",
    "events.Events[].Assisters": "list",
    "events.Events[].DragonType": "str",
    "events.Events[].Stolen": "bool",
    "events.Events[].TurretKilled": "str",
    "events.Events[].InhibKilled": "str",
    "gameData": "object",
    "gameData.gameTime": _NUM,
    "gameData.gameMode": "str",
    "gameData.mapNumber": "int",
}


def _json_type(v: object) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        return "str"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "object"
    return "null" if v is None else type(v).__name__


def _type_ok(expected: str, got: str) -> bool:
    if expected == _NUM:
        return got in ("int", "float")
    return expected == got


def _object_shaped_list(v: object) -> bool:
    return (isinstance(v, dict) and bool(v)
            and all(isinstance(k, str) and _INT_KEY.fullmatch(k) for k in v))


# -- source scan ---------------------------------------------------------------

def _source_files(root: Path):
    for rel in SOURCE_DIRS:
        base = root / rel
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.suffix not in (".py", ".js") or not p.is_file():
                continue
            if _SKIP_PARTS.intersection(p.relative_to(root).parts):
                continue
            yield p
    for p in sorted(root.glob("*.py")):
        yield p


def scan_source(root: Path = REPO_ROOT) -> tuple[set[str], set[str]]:
    """Return (event_literals, key_names) per the module docstring method."""
    event_literals: set[str] = set()
    key_names: set[str] = set()
    for p in _source_files(root):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lits = set(_QUOTED.findall(text))
        key_names |= lits
        if p.suffix == ".js":
            key_names |= set(_JS_PROP.findall(text))
        if "EventName" in text:
            event_literals |= lits
    return event_literals, key_names


def consumed_event_names(root: Path = REPO_ROOT) -> set[str]:
    return scan_source(root)[0]


# -- payload walk --------------------------------------------------------------

def load_payloads(path: Path) -> list[dict]:
    """Load one capture or every ``*.json`` in a directory (non-recursive)."""
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    out: list[dict] = []
    for f in files:
        try:
            obj = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (isinstance(obj, dict) and "gameData" not in obj
                and isinstance(obj.get("data"), dict)):
            obj = obj["data"]
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _walk(node: object, path: str, sink: list) -> None:
    """Append (path, key, value) for every dict entry under ``node``."""
    if isinstance(node, list) or _object_shaped_list(node):
        items = node if isinstance(node, list) else list(node.values())
        for el in items:
            _walk(el, path + "[]", sink)
        return
    if not isinstance(node, dict):
        return
    for k, v in node.items():
        if not isinstance(k, str) or k.startswith("_"):
            continue
        child = f"{path}.{k}" if path else k
        sink.append((child, k, v))
        _walk(v, child, sink)


def event_names(payloads: list[dict]) -> set[str]:
    names: set[str] = set()
    for pl in payloads:
        sink: list = []
        _walk(pl, "", sink)
        for path, _k, v in sink:
            if path == "events.Events[].EventName" and isinstance(v, str):
                names.add(v)
    return names


def audit(payloads: list[dict], root: Path = REPO_ROOT) -> dict:
    """The three report lists, each sorted, as a dict."""
    event_literals, key_names = scan_source(root)
    seen_events: set[str] = set()
    mismatches: dict[tuple[str, str, str], list] = {}
    unread: set[str] = set()
    for pl in payloads:
        sink: list = []
        _walk(pl, "", sink)
        for path, key, v in sink:
            if path == "events.Events[].EventName" and isinstance(v, str):
                seen_events.add(v)
            want = SCHEMA.get(path)
            if want is not None:
                got = _json_type(v)
                if not _type_ok(want, got):
                    bucket = mismatches.setdefault((path, want, got), [])
                    if len(bucket) < 3 and v not in bucket:
                        bucket.append(v)
            if key not in key_names:
                unread.add(path)
    return {
        "unconsumed_events": sorted(seen_events - event_literals),
        "type_mismatches": [
            f"{p}: expected {w}, got {g} (e.g. {', '.join(repr(x) for x in ex)})"
            for (p, w, g), ex in sorted(mismatches.items())
        ],
        "unread_keys": sorted(unread),
    }


def format_report(rep: dict, n_payloads: int) -> str:
    lines = [f"Live Client shape audit over {n_payloads} payload(s)"]
    for title, key in (("EventName values with no RC consumer", "unconsumed_events"),
                       ("Modelled fields with a mismatched JSON type", "type_mismatches"),
                       ("Keys nothing in RC reads", "unread_keys")):
        rows = rep[key]
        lines.append("")
        lines.append(f"== {title} ({len(rows)}) ==")
        if rows:
            lines.extend(f"  {r}" for r in rows)
        else:
            lines.append("  (none)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", help="captured allgamedata JSON file or a directory of them")
    args = ap.parse_args(argv)
    payloads = load_payloads(Path(args.path))
    if not payloads:
        print(f"no readable allgamedata payloads at {args.path}", file=sys.stderr)
        return 0
    print(format_report(audit(payloads), len(payloads)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
