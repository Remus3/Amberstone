"""tools/daemon_slayer_build_orders_generate.py - Lane B precomputed build-order table.

Generates a lookup table the coach reads at request time INSTEAD of invoking
the Daemon Slayer engine live each tick. Advances migrating coaching off live
:8860 calls: a champion x mode x enemy-comp-class build-order is computed once
(offline, against the engine) and serialized to
``data/daemon_slayer/<patch>/build_orders_<mode>.json``. At coach time the
recommendation is a dict lookup, not an HTTP round-trip.

WHY this is orthogonal to the curated loadouts
----------------------------------------------
``data/champion_loadouts.json`` (the build-chooser variants) is a hand-curated
+ engine-aligned per-archetype presentation. THIS is a NEW table keyed by
*enemy composition class* (ad_heavy / balanced / ap_heavy) so the coach can
serve a build that already adapted to the enemy AD/AP split without a live
``plan_build_order`` call. The two coexist; this does not touch the curated
loadouts.

What it produces (per mode, atomic write)
-----------------------------------------
``data/daemon_slayer/<patch>/build_orders_<mode>.json``::

    {
      "version": "<patch>",
      "generated_at": "<iso>",
      "mode": "<sr|aram|arena>",
      "build_orders": {
        "<champ display name>": {
          "ad_heavy": [id, id, ...],   # ordered item ids incl. boots
          "balanced": [id, ...],
          "ap_heavy": [id, ...]
        }
      }
    }

Per enemy-comp-class enemy stat profile
---------------------------------------
The class only swaps the enemy AD/AP *share* (which way the build leans);
the resolved typical-enemy stat block at level 11 is shared and reuses the
SR typical-enemy baseline already proven in ``tools/champion_loadout_align.py``
(armor ~80, mr ~60, max_hp ~2000, bonus_hp ~600). The share rides
``plan_build_order``'s ``rank_kwargs`` (the ``enemy_ad_share`` extra the
engine already documents) so the engine reranks anti-armor vs anti-MR items.

* ad_heavy -> enemy_ad_share 0.7 / enemy_ap_share 0.3
* balanced -> 0.5 / 0.5
* ap_heavy -> 0.3 / 0.7

Archetype + boots + no-double-unique are the engine's job
--------------------------------------------------------
Archetype resolves via ``core.archetype_picks.get_archetype_for(champ)``
(primary). ``plan_build_order`` already injects boots (one boots-family slot
per build) and enforces the no-double-unique-passive rule across the
sequence - we do NOT reimplement either.

Usage
-----
    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/daemon_slayer_build_orders_generate.py [--mode sr|aram|arena|all]
        [--champion <name>] [--dry-run] [--out <dir>]

* ``--mode all`` (default) generates for SR + ARAM + Arena.
* ``--champion`` runs only one champion (dev iteration shortcut).
* ``--dry-run`` prints per-mode counts but writes nothing.
* ``--out`` overrides the output directory (default resolves from
  ``data/daemon_slayer/current.txt``).

Like ``champion_loadout_autogen.py`` the non-dry path refuses to run when the
DS engine on :8860 is not responding (an offline engine would silently
produce empty / wrong tables). Run it with the engine up; the coach reads
the committed JSON with no engine dependency.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Iterable, Optional

# Project root: tools/ -> C:\Riot Commander\
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from core import archetype_picks
from core import daemon_slayer_client as dsc
from core.build_order import (
    SCORE_BY_DEFAULT,
    SCORE_BY_VALUES,
    plan_build_order,
)
# One shared exception type for an unresolvable roster across BOTH producers.
from core.build_order_precompute import (
    EXIT_EMPTY_TABLE,
    EXIT_NO_ROSTER,
    RosterUnavailableError,
)

_DATA_DIR = _ROOT / "data"
_DS_DIR = _DATA_DIR / "daemon_slayer"
_CURRENT_TXT = _DS_DIR / "current.txt"
_CHAMPS_PATH = _DATA_DIR / "meta" / "ddragon_champions.json"

# Patch fallback when current.txt is missing. The live patch is read from
# current.txt; this only guards a fresh checkout.
_FALLBACK_PATCH = "16.11.1"

MODES = ("sr", "aram", "arena")
# DS server accepts uppercased mode strings.
DS_MODE_BY_KEY = {"sr": "SR", "aram": "ARAM", "arena": "ARENA"}

# Enemy composition classes -> (enemy_ad_share, enemy_ap_share). Only the
# AD/AP lean changes per class; the resolved typical-enemy stat block is
# shared (see below). Order matters for stable JSON output.
ENEMY_COMP_CLASSES: tuple[str, ...] = ("ad_heavy", "balanced", "ap_heavy")
_COMP_SHARES: dict[str, tuple[float, float]] = {
    "ad_heavy": (0.7, 0.3),
    "balanced": (0.5, 0.5),
    "ap_heavy": (0.3, 0.7),
}

# Typical-enemy stat block at level 11. REUSED from the SR baseline proven
# in tools/champion_loadout_align.py (armor 80 / mr 60 / max_hp 2000 /
# bonus_hp 600) - NOT invented here. Level pinned to 11 per the table spec.
_TARGET_ARMOR    = 80.0
_TARGET_MR       = 60.0
_TARGET_MAX_HP   = 2000.0
_TARGET_BONUS_HP = 600.0
_LEVEL           = 11

# Full build = 6 item slots (incl. boots) in every mode.
_SLOTS = 6

# Per-engine-call timeout. Generous because this is an offline batch, not
# the per-tick path.
_TIMEOUT = 15.0


def resolve_patch() -> str:
    """Read the active patch from current.txt; fall back to _FALLBACK_PATCH."""
    try:
        txt = _CURRENT_TXT.read_text(encoding="utf-8").strip()
        if txt:
            return txt
    except FileNotFoundError:
        pass
    except Exception as exc:  # noqa: BLE001 - fail-soft to fallback
        print(f"WARN: current.txt read failed ({exc}); using {_FALLBACK_PATCH}",
              file=sys.stderr)
    return _FALLBACK_PATCH


def out_dir_for(patch: str, override: Optional[str]) -> Path:
    """Output directory for ``patch`` (or the override path verbatim)."""
    if override:
        return Path(override)
    return _DS_DIR / patch


def load_champions() -> list[str]:
    """Return ``[display_name, ...]`` for the full DDragon roster, sorted.

    Names are DISTINCT (first occurrence wins). DDragon ships NAME-COLLIDING
    entries that are NOT aliases of a champion already in the registry: the
    16.15.1 drop adds 60 ``Jade_<Champion>`` THROWBACK-MODE VARIANT rows at
    ``base_key + 60000``, each carrying its own older-patch stat line
    (``Jade_Ahri`` key 60103 hp 460 against ``Ahri`` key 103 hp 590), taking
    the file from 173 to 233 entries that still describe 173 champions.
    Appending one name per entry would silently inflate the display-name
    keyspace by 60 phantom duplicates and make the generator sweep each of
    them twice - and deduping by NAME instead of by KEY would absorb one row
    into the other and serve an older patch's stats. Classify by the key
    floor, never by the ``Jade_`` name prefix (see
    ``agents/daemon_slayer/mode_variants.py``).

    Raises :class:`RosterUnavailableError` when the registry resolves to zero
    champions. It previously returned ``[]`` for a wrong-shaped or empty
    registry, and main() then wrote a ZERO-champion table over a complete one
    and exited 0 - invisible downstream, because every consumer of a missing
    cell degrades silently.
    """
    raw = json.loads(_CHAMPS_PATH.read_text(encoding="utf-8"))
    data = raw.get("data", raw) if isinstance(raw, dict) else {}
    seen: dict[str, None] = {}
    for entry in (data.values() if isinstance(data, dict) else ()):
        if not isinstance(entry, dict):
            continue
        nm = entry.get("name") or entry.get("id")
        if nm:
            seen.setdefault(str(nm), None)  # insertion-ordered distinct names
    names = list(seen)
    if not names:
        raise RosterUnavailableError(
            f"DDragon champion registry {_CHAMPS_PATH} yielded no champions; "
            "refusing to generate a zero-champion table"
        )
    names.sort(key=str.lower)
    return names


def archetype_for(champion: str) -> str:
    """Resolve the primary archetype for ``champion`` (DDragon-tag default
    or operator pick). Falls back to ``carry`` on a blank resolve."""
    info = archetype_picks.get_archetype_for(champion)
    return str(info.get("primary") or "carry")


def build_order_for_class(
    champion: str,
    archetype: str,
    mode: str,
    comp_class: str,
    score_by: str = SCORE_BY_DEFAULT,
) -> list[str]:
    """Call ``plan_build_order`` for one (champion, archetype, mode,
    enemy-comp-class) cell. Returns the ordered item-id list (incl. boots),
    or ``[]`` when the engine cannot plan.

    The enemy-comp lean rides ``rank_kwargs={"enemy_ad_share": ...}`` (the
    engine's documented extra); the typical-enemy stat block + boots +
    no-double-unique are the engine's responsibility.
    """
    ad_share, ap_share = _COMP_SHARES[comp_class]
    ds_mode = DS_MODE_BY_KEY.get(mode, "SR")
    # A-21 / RM-90 S1 tail: the EHP metric the ranker sorts by. The default is
    # never inserted into the call, so a run that does not ask for the seam is
    # byte-identical to the pre-seam generator (core/build_order.py:571-576
    # would resolve it to the same value anyway, but omitting it keeps an
    # injected/older plan_build_order signature working).
    extra: dict = {}
    if score_by and score_by != SCORE_BY_DEFAULT:
        extra["score_by"] = score_by
    try:
        result = plan_build_order(
            champion,
            archetype,
            level=_LEVEL,
            owned_item_ids=[],
            mode=ds_mode,
            target_armor=_TARGET_ARMOR,
            target_mr=_TARGET_MR,
            target_max_hp=_TARGET_MAX_HP,
            target_bonus_hp=_TARGET_BONUS_HP,
            slots=_SLOTS,
            # Both shares must ride together: the engine rejects ad+ap > 1.0,
            # so passing ad alone leaves ap at its 0.5 default and an ad_heavy
            # 0.7 + 0.5 = 1.2 over-sum returns an empty plan.
            rank_kwargs={"enemy_ad_share": ad_share, "enemy_ap_share": ap_share},
            timeout=_TIMEOUT,
            **extra,
        )
    except Exception as exc:  # noqa: BLE001 - one bad cell never sinks the run
        print(f"WARN: plan_build_order raised for {champion}|{archetype}|"
              f"{mode}|{comp_class}: {exc}", file=sys.stderr)
        return []
    if result is None or not result.order:
        return []
    return [str(s.item_id) for s in result.order if s.item_id]


def build_orders_for_champion(
    champion: str,
    mode: str,
    score_by: str = SCORE_BY_DEFAULT,
) -> dict[str, list[str]]:
    """Return ``{comp_class: [id, ...]}`` for one champion in one mode."""
    archetype = archetype_for(champion)
    out: dict[str, list[str]] = {}
    for comp_class in ENEMY_COMP_CLASSES:
        out[comp_class] = build_order_for_class(
            champion, archetype, mode, comp_class, score_by=score_by,
        )
    return out


def generate_mode(
    mode: str,
    champions: Iterable[str],
    patch: str,
    score_by: str = SCORE_BY_DEFAULT,
) -> dict:
    """Build the full payload dict for one mode."""
    build_orders: dict[str, dict[str, list[str]]] = {}
    for champ in champions:
        build_orders[champ] = build_orders_for_champion(champ, mode, score_by=score_by)
    return {
        "version":       patch,
        "generated_at":  _now_iso(),
        "mode":          mode,
        "build_orders":  build_orders,
    }


def _now_iso() -> str:
    """UTC timestamp in ISO-8601, trimmed to seconds."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def atomic_write(payload: dict, out_path: Path) -> None:
    """Write ``payload`` to ``out_path`` via tmp + os.replace (atomic).

    Mirrors ``core.archetype_picks._atomic_write_picks`` /
    ``tools/champion_loadout_autogen.atomic_write_loadouts``: a reader
    (the coach) polling mid-write must never see a partial file. ASCII-only
    JSON.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=f".{out_path.stem}.", suffix=".tmp", dir=str(out_path.parent),
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=True, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp_path, str(out_path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _count_cells(payload: dict) -> tuple[int, int]:
    """Return (champ_count, nonempty_cell_count) for a mode payload."""
    bo = payload.get("build_orders") or {}
    champs = len(bo)
    cells = 0
    for classes in bo.values():
        for ids in (classes or {}).values():
            if ids:
                cells += 1
    return champs, cells


def _build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mode", default="all",
                    choices=("all", "sr", "aram", "arena"),
                    help="Restrict generation to one mode (default: all).")
    ap.add_argument("--champion", default="",
                    help="Single-champion mode (DDragon display name, e.g. 'Aatrox').")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print per-mode counts without writing the file(s).")
    ap.add_argument("--out", default="",
                    help="Override output directory (default: data/daemon_slayer/<patch>).")
    # A-21 / RM-90 S1 tail. Same whitelist as core/build_order.py so the two
    # keyspaces cannot drift apart on which metrics are legal.
    ap.add_argument("--score-by", default=SCORE_BY_DEFAULT,
                    choices=tuple(sorted(SCORE_BY_VALUES)),
                    help="EHP metric the ranker sorts by (default: %(default)s).")
    return ap


def main() -> int:
    ap = _build_arg_parser()
    args = ap.parse_args()

    if not args.dry_run and not dsc.is_engine_up(timeout=1.0):
        print("DS engine at 127.0.0.1:8860 is not responding. Start it via "
              "`$env:LOCALAPPDATA/Programs/Python/Python314/python.exe tools/start_daemon_slayer.py` and re-run (a non-dry run "
              "refuses to write tables against a dead engine).", file=sys.stderr)
        return 2

    patch = resolve_patch()
    out_dir = out_dir_for(patch, args.out or None)
    target_modes: tuple[str, ...] = MODES if args.mode == "all" else (args.mode,)

    try:
        champions = load_champions()
    except RosterUnavailableError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_NO_ROSTER
    if args.champion:
        champions = [c for c in champions if c == args.champion]
        if not champions:
            print(f"champion {args.champion!r} not in DDragon roster",
                  file=sys.stderr)
            return 2

    print(f"build-orders gen patch={patch} modes={target_modes} "
          f"champions={len(champions)} dry_run={args.dry_run} out={out_dir}")

    started = time.time()
    for mode in target_modes:
        payload = generate_mode(mode, champions, patch, score_by=args.score_by)
        champs, cells = _count_cells(payload)
        if args.dry_run:
            print(f"  [dry-run] {mode:5s}: {champs} champions, "
                  f"{cells} non-empty cells (file not written)")
        elif cells == 0:
            # is_engine_up() only catches an engine that was dead BEFORE the
            # run; one that dies mid-run is swallowed per-cell, so without
            # this an all-empty table would overwrite a good one and exit 0.
            print(f"ERROR: {mode}: run produced 0 non-empty cells across "
                  f"{champs} champions - refusing to write "
                  f"build_orders_{mode}.json (engine failure mid-run?)",
                  file=sys.stderr)
            return EXIT_EMPTY_TABLE
        else:
            out_path = out_dir / f"build_orders_{mode}.json"
            atomic_write(payload, out_path)
            print(f"  {mode:5s}: {champs} champions, {cells} non-empty cells "
                  f"-> {out_path.name}")

    print(f"done in {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
