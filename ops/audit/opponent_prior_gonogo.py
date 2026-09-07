# arch: opponent-prior confidence-gate GO/NO-GO probe | section=ops/audit | frozen=no
"""GO/NO-GO for the opponent completion-prior confidence gate (2026-06-30 synth).

Offline capture-replay feasibility test (no live game, no gate code needed): mine the
ARAM + CLASSIC completion priors from data/rewind_history.db and measure whether per-champion
enemy build VARIANCE is large enough for a per-enemy resist prediction to ever beat the coarse
'assume tanky' anti_tank regime.

For each enemy champion (n>=30 final builds) it computes E[item armor] and E[item MR] = sum over
stat items of P(item in final build) * item resist (the completion prior, raw MLE presence for
the probe; production uses core/smoothed_rates.shrink). A wide spread with a clear LOW cohort
(squishy / lethality builders who will NOT stack the wall) is the dissent signal: those are the
champs a coarse 'they will be tanky -> lean %armor-pen' assumption gets wrong, and exactly where
the gate adds value. A flat distribution => CUT the gate.

Read-only; safe to run during a live game. This is a necessary-condition feasibility check, NOT
the production gate. Run:
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe ops/audit/opponent_prior_gonogo.py
"""
from __future__ import annotations

import collections
import json
import os
import sqlite3
import statistics

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ITEMS = os.path.join(_ROOT, "data", "meta", "ddragon_items.json")
_DB = os.path.join(_ROOT, "data", "rewind_history.db")
_MIN_ROWS = 30


def _load_resist_index():
    raw = json.loads(open(_ITEMS, encoding="utf-8").read())
    data = raw.get("data", raw)
    out = {}
    for iid, entry in data.items():
        s = entry.get("stats") or {}
        a = float(s.get("FlatArmorMod") or 0.0)
        m = float(s.get("FlatSpellBlockMod") or 0.0)
        if a or m:
            out[str(iid)] = (a, m)
    return out


def _analyze(con, mode, resist):
    cur = con.execute(
        "SELECT p.champion_name, p.item0, p.item1, p.item2, p.item3, p.item4, p.item5, p.item6 "
        "FROM participants p JOIN matches m ON p.match_id = m.match_id "
        "WHERE m.game_mode = ?", (mode,))
    builds = collections.defaultdict(list)
    for row in cur:
        champ = str(row[0])
        items = {str(x) for x in row[1:8] if x and int(x) != 0}
        builds[champ].append(items)
    out = []
    for champ, bl in builds.items():
        n = len(bl)
        if n < _MIN_ROWS:
            continue
        cnt = collections.Counter()
        for b in bl:
            for it in b:
                if it in resist:
                    cnt[it] += 1
        e_armor = sum((cnt[it] / n) * resist[it][0] for it in cnt)
        e_mr = sum((cnt[it] / n) * resist[it][1] for it in cnt)
        out.append((champ, n, e_armor, e_mr))
    out.sort(key=lambda r: r[2])
    return out


def main():
    if not os.path.exists(_DB):
        print(f"NO DB at {_DB}")
        return
    resist = _load_resist_index()
    con = sqlite3.connect(_DB)
    try:
        for mode in ("ARAM", "CLASSIC"):
            res = _analyze(con, mode, resist)
            if not res:
                print(f"=== {mode}: no champ cells with n>={_MIN_ROWS}")
                continue
            armors = [r[2] for r in res]
            spread = max(armors) - min(armors)
            print(f"=== {mode}: {len(res)} champs n>={_MIN_ROWS} | E[item armor] "
                  f"min={min(armors):.0f} median={statistics.median(armors):.0f} "
                  f"max={max(armors):.0f} spread={spread:.0f}")
            print("  LOW (won't stack -> dissent candidates the coarse regime misjudges):")
            for champ, n, ea, em in res[:8]:
                print(f"    {champ:>18} n={n:>4}  E_armor={ea:5.0f}  E_mr={em:5.0f}")
            print("  HIGH (walls -> anti_tank already right):")
            for champ, n, ea, em in res[-6:]:
                print(f"    {champ:>18} n={n:>4}  E_armor={ea:5.0f}  E_mr={em:5.0f}")
            low = min(armors)
            verdict = "GATE VIABLE" if (spread >= 40.0 and low <= 25.0) else "LEAN CUT"
            print(f"  VERDICT[{mode}]: {verdict} "
                  f"(build-armor variance {'LARGE' if spread >= 40 else 'small'}; "
                  f"low cohort {'present' if low <= 25 else 'absent'})\n")
    finally:
        con.close()


if __name__ == "__main__":
    main()
