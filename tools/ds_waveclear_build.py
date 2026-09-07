"""Build the wave-clear registry block for ``waveclear.py`` (item 300).

Reads the 10-channel roster-fan-out result (the workflow JSON), validates every
classified entry against ``_WAVECLEAR_KIND_WEIGHT`` / ``_WAVECLEAR_RANGE_MULT``
(kind known; range_band known; source in P/Q/W/E/R/BASE; magnitude in (0, 1]),
then:

  * rewrites the ``# <ENTRIES>`` marker in ``agents/daemon_slayer/waveclear.py``
    with the generated ``add(...)`` calls (grouped by champion, P/Q/W/E/R/BASE
    order), LF line endings;
  * writes the provenance sidecar
    ``agents/daemon_slayer/waveclear_registry_notes.json`` (champion, source,
    kind, range_band, magnitude, conditional, source_quote).

Reusable as a drift-guard re-build when the roster scan is re-run. Usage:
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/ds_waveclear_build.py <workflow_output.json>
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODULE = ROOT / "agents" / "daemon_slayer" / "waveclear.py"
NOTES = ROOT / "agents" / "daemon_slayer" / "waveclear_registry_notes.json"
SOURCES = ("P", "Q", "W", "E", "R", "BASE")

sys.path.insert(0, str(ROOT))
from agents.daemon_slayer.waveclear import (  # noqa: E402
    _WAVECLEAR_KIND_WEIGHT,
    _WAVECLEAR_RANGE_MULT,
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
        f'band="{r["range_band"]}", magnitude={_fmt(r["magnitude"])}'
    ]
    if r["conditional"]:
        parts.append(", cond=True")
    parts.append(")")
    return "".join(parts)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: ds_waveclear_build.py <workflow_output.json>")
    entries = _load_entries(sys.argv[1])

    problems: list[str] = []
    seen: set[tuple[str, str]] = set()
    clean: list[dict] = []

    for e in entries:
        champ = e.get("champion", "")
        source = e.get("source", "")
        kind = e.get("kind", "")
        band = e.get("range_band", "")
        magnitude = _num(e.get("magnitude"))
        cond = bool(e.get("conditional", False))
        key = (champ, source)
        if source not in SOURCES:
            problems.append(f"bad source {champ} {source!r}")
            continue
        if kind not in _WAVECLEAR_KIND_WEIGHT:
            problems.append(f"unknown kind {champ} {source} {kind!r}")
            continue
        if band not in _WAVECLEAR_RANGE_MULT:
            problems.append(f"bad range_band {champ} {source} {band!r}")
            continue
        if not (0.0 < magnitude <= 1.0):
            problems.append(f"bad magnitude {champ} {source} {magnitude}")
            continue
        if key in seen:
            continue
        seen.add(key)
        clean.append({
            "champion": champ, "source": source, "kind": kind,
            "range_band": band, "magnitude": round(magnitude, 4),
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
            {"item": 300, "engine": "1.112.0", "count": len(clean),
             "entries": clean},
            fh, indent=1, ensure_ascii=True,
        )
        fh.write("\n")

    by_kind: dict[str, int] = {}
    by_band: dict[str, int] = {}
    for c in clean:
        by_kind[c["kind"]] = by_kind.get(c["kind"], 0) + 1
        by_band[c["range_band"]] = by_band.get(c["range_band"], 0) + 1
    print(f"entries_clean={len(clean)} champs={len(by_champ)} "
          f"conditional={sum(1 for c in clean if c['conditional'])}")
    print("kinds=" + " ".join(f"{k}:{v}" for k, v in sorted(by_kind.items())))
    print("bands=" + " ".join(f"{k}:{v}" for k, v in sorted(by_band.items())))
    if problems:
        print(f"PROBLEMS={len(problems)}")
        for p in problems[:25]:
            print("  ", p)
    else:
        print("PROBLEMS=0")


if __name__ == "__main__":
    main()
