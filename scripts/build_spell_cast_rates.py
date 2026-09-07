"""Phase 4b (s178, 2026-05-12) - Derive per-spell cast rates from rewind_history.db.

Generates ``data/daemon_slayer/spell_cast_rates.json`` carrying median casts/sec
for each of the 4 active spells (Q/W/E/R) per champion x mode. Phase 4b's
``compute_ability_dps()`` reads this to scale per-cast damage into per-spell
ability DPS - a measured cast rate already encodes mana/cooldown downtime, so
no separate uptime modeling is needed at the consumer level.

Mirror of the (undocumented) s145 ad-hoc query that built
``ult_cast_rates.json`` for the Malignance Hatefog proc, generalised to the
full Q/W/E/R surface and re-runnable so future patches can refresh.

Schema (output)::

  {
    "by_champ_mode": {
      "Veigar": {
        "SR":     {"Q": 0.123, "W": 0.041, "E": 0.038, "R": 0.014},
        "ARAM":   {"Q": 0.145, ...},
        "ARENA":  {...},
        "global": {...}
      },
      ...
    },
    "global_fallback": {"Q": 0.110, "W": 0.080, "E": 0.060, "R": 0.012},
    "generated_at": "2026-05-12",
    "source": "data/rewind_history.db (NNNN matches, spell[1-4]_casts / game_duration_s)",
    "note": "Casts/sec - measured median across all observed games per champion x mode."
  }

Mode mapping (queue_id -> bucket):
  420, 400, 430, 440, 700 -> SR
  450, 100              -> ARAM
  1700, 1710            -> ARENA
  other                 -> not bucketed; rolled into "global" only

Sample-size policy:
  >= 5 samples per champion x mode -> real median
  <  5 samples                    -> omit that bucket (consumer falls back to
                                    champion's "global" entry, then global_fallback)

Run::

  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts\build_spell_cast_rates.py
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "rewind_history.db"
OUTPUT = ROOT / "data" / "daemon_slayer" / "spell_cast_rates.json"

MIN_SAMPLES = 5

SR_QUEUES = {420, 400, 430, 440, 700}
ARAM_QUEUES = {450, 100}
ARENA_QUEUES = {1700, 1710}

SPELL_KEYS: tuple[str, ...] = ("Q", "W", "E", "R")
SPELL_COLS = {
    "Q": "spell1_casts",
    "W": "spell2_casts",
    "E": "spell3_casts",
    "R": "spell4_casts",
}


def _bucket(queue_id: int | None) -> str | None:
    if queue_id is None:
        return None
    if queue_id in SR_QUEUES:
        return "SR"
    if queue_id in ARAM_QUEUES:
        return "ARAM"
    if queue_id in ARENA_QUEUES:
        return "ARENA"
    return None


def _safe_median(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.median(values))


def main() -> int:
    if not DB_PATH.exists():
        print(f"FATAL: rewind DB missing at {DB_PATH}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM matches")
    n_matches = cur.fetchone()[0]
    print(f"rewind DB: {n_matches} matches", file=sys.stderr)

    # Pull per-participant rows joined to match metadata. Filter game_duration_s>0
    # to avoid div-by-zero on aborted games.
    cur.execute(
        """
        SELECT p.champion_name, p.spell1_casts, p.spell2_casts, p.spell3_casts,
               p.spell4_casts, m.game_duration_s, m.queue_id
          FROM participants p
          JOIN matches m ON p.match_id = m.match_id
         WHERE p.champion_name IS NOT NULL
           AND m.game_duration_s > 60
        """
    )

    # by_champ_mode[champion][mode]["Q"|...] = list of casts/sec floats
    by_champ_mode: dict[str, dict[str, dict[str, list[float]]]] = {}

    for champ, q_casts, w_casts, e_casts, r_casts, dur, queue_id in cur.fetchall():
        if dur is None or dur <= 0:
            continue
        bucket = _bucket(queue_id)
        # Always record into "global" - sample size is best when not partitioned.
        targets: list[str] = ["global"]
        if bucket:
            targets.append(bucket)
        casts = {
            "Q": (q_casts or 0) / dur,
            "W": (w_casts or 0) / dur,
            "E": (e_casts or 0) / dur,
            "R": (r_casts or 0) / dur,
        }
        per_mode = by_champ_mode.setdefault(champ, {})
        for tgt in targets:
            per_key = per_mode.setdefault(tgt, {k: [] for k in SPELL_KEYS})
            for k in SPELL_KEYS:
                per_key[k].append(casts[k])

    # Reduce to medians with sample-size policy.
    reduced: dict[str, dict[str, dict[str, float]]] = {}
    n_buckets_kept = 0
    n_buckets_dropped = 0
    for champ, per_mode in sorted(by_champ_mode.items()):
        reduced_per_mode: dict[str, dict[str, float]] = {}
        for mode, per_key in per_mode.items():
            # Sample size measured on a non-zero spell (use Q as the canon, all
            # 4 have the same row count by construction).
            n = len(per_key["Q"])
            if n < MIN_SAMPLES and mode != "global":
                # Allow "global" through even with low N; mode-specific buckets
                # need at least MIN_SAMPLES to pin a number.
                n_buckets_dropped += 1
                continue
            reduced_per_mode[mode] = {k: _safe_median(per_key[k]) for k in SPELL_KEYS}
            n_buckets_kept += 1
        if reduced_per_mode:
            reduced[champ] = reduced_per_mode

    # Global fallback - median of medians per spell across champions' "global".
    global_fallback: dict[str, float] = {}
    for k in SPELL_KEYS:
        vals = [
            v["global"][k]
            for v in reduced.values()
            if "global" in v
        ]
        global_fallback[k] = _safe_median(vals)

    payload = {
        "by_champ_mode": reduced,
        "global_fallback": global_fallback,
        "generated_at": dt.date.today().isoformat(),
        "source": (
            f"data/rewind_history.db ({n_matches} matches, "
            f"spell[1-4]_casts / game_duration_s)"
        ),
        "note": (
            "Casts/sec - measured median across observed games per "
            "champion x mode. Q=spell1, W=spell2, E=spell3, R=spell4. "
            "Used by daemon_slayer.cast_rates.get_spell_casts_per_sec(). "
            "Mode-specific buckets require >= "
            f"{MIN_SAMPLES} samples; 'global' falls through."
        ),
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(OUTPUT)

    print(
        f"wrote {OUTPUT.relative_to(ROOT)} - {len(reduced)} champs, "
        f"{n_buckets_kept} buckets kept, {n_buckets_dropped} dropped "
        f"(< {MIN_SAMPLES} samples)",
        file=sys.stderr,
    )
    print(
        f"global_fallback: Q={global_fallback['Q']:.4f} "
        f"W={global_fallback['W']:.4f} E={global_fallback['E']:.4f} "
        f"R={global_fallback['R']:.4f}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
