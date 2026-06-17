"""WIN-rate anchor: per-(champion x mode) baseline win-rate + per-item win-rate, read
live from a rewind_history.db sqlite connection.

This is the OUTCOME half of DSP1. It takes a sqlite3.Connection rather than a path so
the hermetic tests can pass an in-memory db and never touch the 1.8GB gitignored
data/rewind_history.db (clean-checkout safe). An item is "in" a participant row if its
id appears in any of the item0..item6 slots (slot 0 = empty, never counted). A row's
win flag credits every distinct item it carried, mirroring the cross-eval empirical
block so the two can be cross-checked.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

# map_id -> mode bucket. Queues collapse onto the map; the cross-eval anchors ARAM + SR.
MODE_BY_MAP: dict[int, str] = {
    11: "SR",
    12: "ARAM",
    21: "NEXUSBLITZ",
    30: "ARENA",
}

_ITEM_SLOTS = ("item0", "item1", "item2", "item3", "item4", "item5", "item6")


def resolve_mode(map_id: int | None, game_mode: str | None) -> str | None:
    """Resolve a (map_id, game_mode) pair to a coarse mode bucket, or None if unmapped."""
    if map_id is not None and map_id in MODE_BY_MAP:
        return MODE_BY_MAP[map_id]
    return None


def _maps_for_mode(mode: str) -> list[int]:
    return [m for m, name in MODE_BY_MAP.items() if name == mode]


@dataclass(frozen=True)
class ItemWinRate:
    item_id: str
    n: int
    wins: int

    @property
    def wr(self) -> float:
        return round(100.0 * self.wins / self.n, 4) if self.n else 0.0


@dataclass(frozen=True)
class ChampModeWin:
    champion: str
    mode: str
    n: int
    wins: int
    baseline_wr: float | None
    items: dict[str, ItemWinRate] = field(default_factory=dict)


def _accumulate(rows) -> tuple[int, int, dict[str, list[int]]]:
    """rows = iterable of (win, item0..item6). Returns (n, wins, {item_id: [n, wins]})."""
    n = 0
    wins = 0
    per_item: dict[str, list[int]] = {}
    for row in rows:
        win = int(row[0] or 0)
        n += 1
        wins += win
        seen: set[str] = set()
        for slot in row[1:8]:
            if not slot:
                continue
            iid = str(int(slot))
            if iid in seen:
                continue
            seen.add(iid)
            agg = per_item.setdefault(iid, [0, 0])
            agg[0] += 1
            agg[1] += win
    return n, wins, per_item


def compute_champ_win(conn: sqlite3.Connection, champion: str, mode: str) -> ChampModeWin:
    maps = _maps_for_mode(mode)
    if not maps:
        return ChampModeWin(champion, mode, 0, 0, None, {})
    placeholders = ",".join("?" for _ in maps)
    sql = (
        "SELECT p.win, p.item0, p.item1, p.item2, p.item3, p.item4, p.item5, p.item6 "
        "FROM participants p JOIN matches m ON p.match_id = m.match_id "
        f"WHERE p.champion_name = ? AND m.map_id IN ({placeholders})"
    )
    rows = conn.execute(sql, (champion, *maps)).fetchall()
    n, wins, per_item = _accumulate(rows)
    items = {iid: ItemWinRate(iid, c[0], c[1]) for iid, c in per_item.items()}
    baseline = round(100.0 * wins / n, 4) if n else None
    return ChampModeWin(champion, mode, n, wins, baseline, items)


def compute_win_rates(
    conn: sqlite3.Connection, modes: tuple[str, ...] = ("ARAM", "SR")
) -> dict[tuple[str, str], ChampModeWin]:
    """(champion, mode) -> ChampModeWin for every champion present in each mode."""
    out: dict[tuple[str, str], ChampModeWin] = {}
    for mode in modes:
        maps = _maps_for_mode(mode)
        if not maps:
            continue
        placeholders = ",".join("?" for _ in maps)
        champ_sql = (
            "SELECT DISTINCT p.champion_name FROM participants p "
            "JOIN matches m ON p.match_id = m.match_id "
            f"WHERE m.map_id IN ({placeholders}) AND p.champion_name <> ''"
        )
        champs = [r[0] for r in conn.execute(champ_sql, tuple(maps)).fetchall()]
        for champ in champs:
            out[(champ, mode)] = compute_champ_win(conn, champ, mode)
    return out
