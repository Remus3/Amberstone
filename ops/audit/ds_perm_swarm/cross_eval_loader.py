"""Load the 2026-06-16 per-champion DS cross-eval JSON (ops/audit/ds_cross_eval/data/
<Champ>.json) into typed structures the WIN-anchor harness consumes.

The cross-eval file carries DS top-N rankings per enemy-comp bucket (comp_grid) plus
the per-item empirical WIN block already aggregated from rewind_history.db. DSP1 reads
the comp_grid (the "DS top-N" half) here and re-derives the WIN half live from the DB
in win_anchor.py, so the two halves can be cross-checked rather than trusted blind.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DSItem:
    rank: int
    id: str
    name: str
    score: float
    d_ehp: float
    d_dps: float
    gold: int


@dataclass(frozen=True)
class EmpiricalItem:
    id: str
    name: str
    n: int
    wr: float


@dataclass(frozen=True)
class EmpiricalBlock:
    n: int
    wr: float | None
    items: tuple[EmpiricalItem, ...]


@dataclass(frozen=True)
class CrossEval:
    champion: str
    archetype_primary: str
    scorer: str
    anchor_mode: str
    comp_grid: dict[str, tuple[DSItem, ...]]
    empirical: dict[str, EmpiricalBlock]


def _ds_item(d: dict) -> DSItem:
    return DSItem(
        rank=int(d["rank"]),
        id=str(d["id"]),
        name=str(d.get("name", "")),
        score=float(d.get("score", 0.0)),
        d_ehp=float(d.get("d_ehp", 0.0)),
        d_dps=float(d.get("d_dps", 0.0)),
        gold=int(d.get("gold", 0)),
    )


def _empirical_block(block: dict) -> EmpiricalBlock:
    items = tuple(
        EmpiricalItem(
            id=str(it["id"]),
            name=str(it.get("name", "")),
            n=int(it.get("n", 0)),
            wr=float(it["wr"]) if it.get("wr") is not None else 0.0,
        )
        for it in block.get("items", [])
    )
    wr = block.get("wr")
    return EmpiricalBlock(n=int(block.get("n", 0)), wr=float(wr) if wr is not None else None, items=items)


def cross_eval_from_dict(d: dict) -> CrossEval:
    comp_grid = {
        bucket: tuple(_ds_item(it) for it in rows)
        for bucket, rows in (d.get("comp_grid") or {}).items()
    }
    empirical: dict[str, EmpiricalBlock] = {}
    for mode, modeblock in (d.get("empirical") or {}).items():
        # Anchor on the population ("all") block; the operator-only "self" block is
        # too thin (single-digit n) to anchor an outcome signal.
        allblock = modeblock.get("all") if isinstance(modeblock, dict) else None
        if allblock is not None:
            empirical[mode] = _empirical_block(allblock)
    arch = d.get("archetype") or {}
    return CrossEval(
        champion=str(d.get("champion") or d.get("db_name") or ""),
        archetype_primary=str(arch.get("primary", "")),
        scorer=str(d.get("scorer", "")),
        anchor_mode=str(d.get("anchor_mode", "ARAM")),
        comp_grid=comp_grid,
        empirical=empirical,
    )


def load_cross_eval(path: str | Path) -> CrossEval:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return cross_eval_from_dict(data)


def load_cross_eval_dir(data_dir: str | Path) -> dict[str, CrossEval]:
    """name (file stem, e.g. 'Aatrox') -> CrossEval for every <Champ>.json in data_dir."""
    out: dict[str, CrossEval] = {}
    for p in sorted(Path(data_dir).glob("*.json")):
        out[p.stem] = load_cross_eval(p)
    return out
