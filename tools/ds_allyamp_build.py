"""Build the ally-amplification registry block for ``allyamp.py`` (item 304).

Reads the 10-channel roster-fan-out result (the workflow JSON), validates every
classified entry against ``_ALLYAMP_KIND_WEIGHT`` / ``_ALLYAMP_SCOPE_MULT``
(kind known; scope known; source in P/Q/W/E/R/BASE; magnitude in (0, 1]), then:

  * rewrites the ``# <ENTRIES>`` marker in
    ``agents/daemon_slayer/allyamp.py`` with the generated ``add(...)`` calls
    (grouped by champion, P/Q/W/E/R/BASE order), LF line endings;
  * writes the provenance sidecar
    ``agents/daemon_slayer/allyamp_registry_notes.json`` (champion, source, kind,
    scope, magnitude, conditional, source_quote).

The ally-amplification axis is SPARSE (only champions who grant value to allies
appear), so unlike the threat-range / objective-damage builds this tool does not
expect full-roster coverage.

Reusable as a drift-guard re-build when the roster scan is re-run. Usage:
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/ds_allyamp_build.py <workflow_output.json>
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODULE = ROOT / "agents" / "daemon_slayer" / "allyamp.py"
NOTES = ROOT / "agents" / "daemon_slayer" / "allyamp_registry_notes.json"
SOURCES = ("P", "Q", "W", "E", "R", "BASE")

sys.path.insert(0, str(ROOT))
from agents.daemon_slayer.allyamp import (  # noqa: E402
    _ALLYAMP_KIND_WEIGHT,
    _ALLYAMP_SCOPE_MULT,
)


def _load_entries(path: str) -> list[dict]:
    raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    result = raw.get("result", raw) if isinstance(raw, dict) else raw
    entries = result.get("entries") if isinstance(result, dict) else result
    if not isinstance(entries, list):
        raise SystemExit("no entries array found in result")
    return entries


def _num(v: object) -> float:
    return float(v) if isinstance(v, (int, float)) else 0.0


def _fmt(x: float) -> str:
    return repr(round(float(x), 4))


def _emit(r: dict) -> str:
    """One ``add(...)`` call line from a clean entry dict."""
    parts = [
        f'    add("{r["champion"]}", "{r["source"]}", "{r["kind"]}", '
        f'"{r["scope"]}", magnitude={_fmt(r["magnitude"])}'
    ]
    if r["conditional"]:
        parts.append(", cond=True")
    parts.append(")")
    return "".join(parts)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: ds_allyamp_build.py <workflow_output.json>")
    entries = _load_entries(sys.argv[1])

    problems: list[str] = []
    seen: set[tuple[str, str]] = set()
    clean: list[dict] = []

    for e in entries:
        champ = e.get("champion", "")
        source = e.get("source", "")
        kind = e.get("kind", "")
        scope = e.get("scope", "")
        magnitude = _num(e.get("magnitude"))
        cond = bool(e.get("conditional", False))
        key = (champ, source)
        if source not in SOURCES:
            problems.append(f"bad source {champ} {source!r}")
            continue
        if kind not in _ALLYAMP_KIND_WEIGHT:
            problems.append(f"unknown kind {champ} {source} {kind!r}")
            continue
        if scope not in _ALLYAMP_SCOPE_MULT:
            problems.append(f"bad scope {champ} {source} {scope!r}")
            continue
        if not (0.0 < magnitude <= 1.0):
            problems.append(f"bad magnitude {champ} {source} {magnitude}")
            continue
        if key in seen:
            continue
        seen.add(key)
        clean.append({
            "champion": champ, "source": source, "kind": kind,
            "scope": scope, "magnitude": round(magnitude, 4),
            "conditional": cond,
            "source_quote": (e.get("source_quote") or "").strip(),
        })

    # ---- generate the add() block grouped by champion ----
    by_champ: dict[str, list[dict]] = {}
    for c in clean:
        by_champ.setdefault(c["champion"], []).append(c)
    lines: list[str] = []
    for champ in sorted(by_champ):
        rows = sorted(by_champ[champ], key=lambda r: SOURCES.index(r["source"]))
        lines.append(f"    # {champ}")
        for r in rows:
            lines.append(_emit(r))
    block = "\n".join(lines)

    # ---- splice into the module at the marker, LF endings ----
    src = MODULE.read_text(encoding="utf-8").replace("\r\n", "\n").replace(
        "\r", "\n"
    )
    marker = "    # <ENTRIES>"
    if marker not in src:
        raise SystemExit("marker '# <ENTRIES>' not found (already injected?)")
    src = src.replace(marker, block)
    with open(MODULE, "w", encoding="utf-8", newline="") as fh:
        fh.write(src)

    # ---- provenance sidecar ----
    with open(NOTES, "w", encoding="utf-8", newline="") as fh:
        json.dump(
            {"item": 304, "engine": "1.116.0", "count": len(clean),
             "entries": clean},
            fh, indent=1, ensure_ascii=True,
        )
        fh.write("\n")

    by_kind: dict[str, int] = {}
    by_scope: dict[str, int] = {}
    for c in clean:
        by_kind[c["kind"]] = by_kind.get(c["kind"], 0) + 1
        by_scope[c["scope"]] = by_scope.get(c["scope"], 0) + 1
    print(f"entries_clean={len(clean)} champs={len(by_champ)} "
          f"conditional={sum(1 for c in clean if c['conditional'])}")
    print("kinds=" + " ".join(f"{k}:{v}" for k, v in sorted(by_kind.items())))
    print("scope=" + " ".join(f"{k}:{v}" for k, v in sorted(by_scope.items())))
    if problems:
        print(f"PROBLEMS={len(problems)}")
        for p in problems[:25]:
            print("  ", p)
    else:
        print("PROBLEMS=0")


if __name__ == "__main__":
    main()
