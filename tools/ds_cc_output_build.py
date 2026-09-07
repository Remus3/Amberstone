"""Build the offensive CC-output registry block for ``cc_output.py`` (item 294).

Reads the 12-agent roster-fan-out result (the workflow JSON), validates every
classified entry, reconciles each duration that the per-spell CC duration
registry already carries against that registry (single source of truth for the
108 existing durations), then:

  * rewrites the ``# <ENTRIES>`` marker in ``agents/daemon_slayer/cc_output.py``
    with the generated ``add(...)`` calls (grouped by champion, P/Q/W/E/R order),
    LF line endings;
  * writes the provenance sidecar
    ``agents/daemon_slayer/cc_output_registry_notes.json`` (champion, spell,
    cc_kind, duration, conditional, source_quote).

Reusable as a drift-guard re-build when the roster scan is re-run. Usage:
  C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe tools/ds_cc_output_build.py <workflow_output.json>
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODULE = ROOT / "agents" / "daemon_slayer" / "cc_output.py"
NOTES = ROOT / "agents" / "daemon_slayer" / "cc_output_registry_notes.json"
SPELLS = ("P", "Q", "W", "E", "R")

sys.path.insert(0, str(ROOT))
from agents.daemon_slayer._per_spell_cc import _PER_SPELL_CC_DURATIONS  # noqa: E402
from agents.daemon_slayer.cc_output import _CC_KIND_WEIGHT  # noqa: E402


def _load_entries(path: str) -> list[dict]:
    raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    result = raw.get("result", raw) if isinstance(raw, dict) else raw
    entries = result.get("entries") if isinstance(result, dict) else result
    if not isinstance(entries, list):
        raise SystemExit("no entries array found in result")
    return entries


def _fmt(dur: float) -> str:
    return repr(round(float(dur), 4))


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: ds_cc_output_build.py <workflow_output.json>")
    entries = _load_entries(sys.argv[1])

    roster = set(_PER_SPELL_CC_DURATIONS.keys())  # registered-CC subset only
    problems: list[str] = []
    reconciled = 0
    mismatches: list[str] = []
    seen: set[tuple[str, str]] = set()
    clean: list[dict] = []

    for e in entries:
        champ = e.get("champion", "")
        spell = e.get("spell", "")
        kind = e.get("cc_kind", "")
        dur = e.get("max_rank_duration_s")
        cond = bool(e.get("conditional", False))
        key = (champ, spell)
        if spell not in SPELLS:
            problems.append(f"bad spell {champ} {spell!r}")
            continue
        if kind not in _CC_KIND_WEIGHT:
            problems.append(f"unknown kind {champ} {spell} {kind!r}")
            continue
        if not isinstance(dur, (int, float)) or dur <= 0:
            problems.append(f"bad duration {champ} {spell} {dur!r}")
            continue
        if key in seen:
            continue
        seen.add(key)
        # Source-of-truth reconciliation: if the per-spell CC duration
        # registry already carries this champ+spell, ITS max-rank value
        # wins over the agent's transcription (no second source of truth).
        reg = _PER_SPELL_CC_DURATIONS.get(champ, {}).get(spell)
        if reg:
            reg_max = float(reg[-1])
            if abs(reg_max - float(dur)) > 1e-6:
                mismatches.append(
                    f"{champ} {spell}: agent {dur} -> registry {reg_max}"
                )
            dur = reg_max
            reconciled += 1
        clean.append({
            "champion": champ, "spell": spell, "cc_kind": kind,
            "duration_s": round(float(dur), 4), "conditional": cond,
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
            tail = ", True" if r["conditional"] else ""
            lines.append(
                f'    add("{champ}", "{r["spell"]}", "{r["cc_kind"]}", '
                f'{_fmt(r["duration_s"])}{tail})'
            )
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
            {"item": 294, "engine": "1.106.0", "count": len(clean),
             "entries": clean},
            fh, indent=1, ensure_ascii=True,
        )
        fh.write("\n")

    print(f"entries_clean={len(clean)} champs={len(by_champ)} "
          f"conditional={sum(1 for c in clean if c['conditional'])}")
    print(f"reconciled_existing={reconciled} mismatches={len(mismatches)}")
    for m in mismatches[:25]:
        print("  MISMATCH", m)
    if problems:
        print(f"PROBLEMS={len(problems)}")
        for p in problems[:25]:
            print("  ", p)
    else:
        print("PROBLEMS=0")


if __name__ == "__main__":
    main()
