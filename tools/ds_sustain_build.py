"""Build the sustain registry block for ``sustain.py`` (item 298).

Reads the 10-channel roster-fan-out result (the workflow JSON), validates every
classified entry against ``_SUSTAIN_KIND_WEIGHT`` (kind known; a vamp kind
carries a positive ``vamp_pct``; a ``REGEN`` carries a positive ``pct_max_hp``
or ``flat_hp``), then:

  * rewrites the ``# <ENTRIES>`` marker in ``agents/daemon_slayer/sustain.py``
    with the generated ``add(...)`` calls (grouped by champion, P/Q/W/E/R order),
    LF line endings;
  * writes the provenance sidecar
    ``agents/daemon_slayer/sustain_registry_notes.json`` (champion, spell, kind,
    magnitudes, duration, conditional, source_quote).

Reusable as a drift-guard re-build when the roster scan is re-run. Usage:
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/ds_sustain_build.py <workflow_output.json>
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODULE = ROOT / "agents" / "daemon_slayer" / "sustain.py"
NOTES = ROOT / "agents" / "daemon_slayer" / "sustain_registry_notes.json"
SPELLS = ("P", "Q", "W", "E", "R")
_VAMP_KINDS = ("OMNIVAMP", "LIFESTEAL", "SPELLVAMP", "DRAIN")

sys.path.insert(0, str(ROOT))
from agents.daemon_slayer.sustain import _SUSTAIN_KIND_WEIGHT  # noqa: E402


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
    parts = [f'    add("{r["champion"]}", "{r["spell"]}", "{r["kind"]}"']
    if r["kind"] == "REGEN":
        if r["pct_max_hp"]:
            parts.append(f', pct_max_hp={_fmt(r["pct_max_hp"])}')
        if r["flat_hp"]:
            parts.append(f', flat_hp={_fmt(r["flat_hp"])}')
    else:
        parts.append(f', vamp_pct={_fmt(r["vamp_pct"])}')
        if r["kind"] == "DRAIN" and r["duration_s"]:
            parts.append(f', duration_s={_fmt(r["duration_s"])}')
    if r["conditional"]:
        parts.append(", cond=True")
    parts.append(")")
    return "".join(parts)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: ds_sustain_build.py <workflow_output.json>")
    entries = _load_entries(sys.argv[1])

    problems: list[str] = []
    seen: set[tuple[str, str]] = set()
    clean: list[dict] = []

    for e in entries:
        champ = e.get("champion", "")
        spell = e.get("spell", "")
        kind = e.get("kind", "")
        vamp_pct = _num(e.get("vamp_pct"))
        pct_max_hp = _num(e.get("pct_max_hp"))
        flat_hp = _num(e.get("flat_hp"))
        duration_s = _num(e.get("duration_s"))
        cond = bool(e.get("conditional", False))
        key = (champ, spell)
        if spell not in SPELLS:
            problems.append(f"bad spell {champ} {spell!r}")
            continue
        if kind not in _SUSTAIN_KIND_WEIGHT:
            problems.append(f"unknown kind {champ} {spell} {kind!r}")
            continue
        if kind == "REGEN":
            if pct_max_hp <= 0 and flat_hp <= 0:
                problems.append(
                    f"bad REGEN {champ} {spell} pct={pct_max_hp} flat={flat_hp}"
                )
                continue
        elif vamp_pct <= 0:
            problems.append(f"bad vamp {champ} {spell} {kind} {vamp_pct}")
            continue
        if key in seen:
            continue
        seen.add(key)
        clean.append({
            "champion": champ, "spell": spell, "kind": kind,
            "vamp_pct": round(vamp_pct, 4), "pct_max_hp": round(pct_max_hp, 4),
            "flat_hp": round(flat_hp, 4), "duration_s": round(duration_s, 4),
            "conditional": cond,
            "source_quote": (e.get("source_quote") or "").strip(),
        })

    # ---- generate the add() block grouped by champion ----
    by_champ: dict[str, list[dict]] = {}
    for c in clean:
        by_champ.setdefault(c["champion"], []).append(c)
    lines: list[str] = []
    for champ in sorted(by_champ):
        rows = sorted(by_champ[champ], key=lambda r: SPELLS.index(r["spell"]))
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
            {"item": 298, "engine": "1.110.0", "count": len(clean),
             "entries": clean},
            fh, indent=1, ensure_ascii=True,
        )
        fh.write("\n")

    n_regen = sum(1 for c in clean if c["kind"] == "REGEN")
    print(f"entries_clean={len(clean)} champs={len(by_champ)} "
          f"regen={n_regen} conditional={sum(1 for c in clean if c['conditional'])}")
    if problems:
        print(f"PROBLEMS={len(problems)}")
        for p in problems[:25]:
            print("  ", p)
    else:
        print("PROBLEMS=0")


if __name__ == "__main__":
    main()
