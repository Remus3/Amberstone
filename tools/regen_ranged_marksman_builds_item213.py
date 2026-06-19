"""Item 213 - regenerate ranged-marksman build_paths through the fixed
DPS-scorer off-class filter so polluted melee-bruiser / tank items
(Trinity Force, Heartsteel, Bastionbreaker, Umbral Glaive, ...) are
purged from every Caitlyn / Jinx / Ezreal class ADC build across all
modes (SR / ARAM / Arena).

Why a bespoke regen (not the existing align/collapse tools):
  * data/champion_loadouts.json is ALREADY collapsed (items 178/179) -
    each champion carries sr-collapsed / aram-collapsed / arena-collapsed
    variants with a build_paths[] list. The collapse tool only reorganizes
    source variants; it does NOT call the engine, so re-running it would
    preserve the polluted item lists verbatim.
  * champion_loadout_align.py only engine-regenerates SR, and operates on
    the PRE-collapse schema.

This script walks the collapsed build_paths for ranged marksmen
(Marksman tag + attackrange >= 500 per the engine's own gate) and
regenerates each carry-axis path's items through plan_build_order. The
fixed engine's ranged-marksman deny-set fires through the DPS scorer so
the regenerated items are clean by construction. The unique-passive
no-double rule is enforced by the engine. Non-carry alt-paths on a
marksman (e.g. an AP / mage / bruiser flavor path) are left as-is EXCEPT
that any deny-set item is stripped in-place (defense-in-depth).

The engine is reached via plan_build_order -> the HTTP DS client. Since
the LIVE :8893 server runs the OLD engine, this script spins up the
worktree's FIXED engine on a temp port in a background thread and
monkeypatches the client port for the duration of the run.

ORDERING: build_paths items follow purchase order (boots integral for
SR/ARAM at slot ~2, excluded for Arena). plan_build_order injects boots
for SR/ARAM and is called with inject_boots=False for Arena.

Atomic write (tmp.write_text + tmp.replace, ensure_ascii=True) with a
timestamped backup of the prior file.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agents.daemon_slayer.data_loader import DataSnapshot  # noqa: E402
from agents.daemon_slayer.rank import (  # noqa: E402
    OFFCLASS_MARKSMAN_ITEM_NAMES,
    _is_ranged_marksman,
)

_LOADOUTS = _ROOT / "data" / "champion_loadouts.json"

# Mode -> (engine mode string, inject boots, level, enemy baseline).
_SR = ("SR", True)
_ARAM = ("ARAM", True)
_ARENA = ("ARENA", False)
_MODE_FOR_COLLAPSED = {
    "sr-collapsed": _SR,
    "aram-collapsed": _ARAM,
    "arena-collapsed": _ARENA,
}
_TARGET_ARMOR = 80.0
_TARGET_MR = 60.0
_TARGET_MAX_HP = 2000.0
_TARGET_BONUS_HP = 600.0
_LEVEL = 14
_SLOTS = 6

# Variant-key tokens that mark a carry-axis (ADC) build path. These are
# regenerated through the carry / dps scorer (clean ADC pool). Non-carry
# tokens (mage / bruiser / assassin flavor on a marksman) are NOT
# regenerated - only their deny-set items are stripped in place.
_CARRY_TOKENS = (
    "carry", "adc", "crit", "on-hit", "onhit", "ad-", "lethality",
    "manamune", "primary",
)


def _is_carry_path(path_key: str) -> bool:
    k = (path_key or "").lower()
    return any(tok in k for tok in _CARRY_TOKENS)


def _start_worktree_engine(port: int) -> threading.Thread:
    """Start the worktree's fixed DS engine on ``port`` in a daemon thread
    and monkeypatch the client to point at it. Returns the thread."""
    from agents.daemon_slayer import server as ds_server
    import core.daemon_slayer_client as client

    snap = DataSnapshot.load()
    srv = ds_server.start_server("127.0.0.1", port, snapshot=snap)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    client.DEFAULT_PORT = port  # type: ignore[attr-defined]
    # Give the client a generous timeout - the regen is offline, not live.
    client.DEFAULT_TIMEOUT = 15.0  # type: ignore[attr-defined]
    # Wait for /health.
    import urllib.request
    for _ in range(50):
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=2.0
            ) as r:
                if r.status == 200:
                    return t
        except Exception:  # noqa: BLE001
            time.sleep(0.1)
    raise RuntimeError("worktree DS engine did not come up on temp port")


def _regen_carry_path(champion: str, engine_mode: str, inject_boots: bool):
    """Return the regenerated item-name list for a carry-axis path, or
    None if the engine could not plan."""
    from core.build_order import plan_build_order

    res = plan_build_order(
        champion,
        "carry",
        level=_LEVEL,
        owned_item_ids=[],
        mode=engine_mode,
        target_armor=_TARGET_ARMOR,
        target_mr=_TARGET_MR,
        target_max_hp=_TARGET_MAX_HP,
        target_bonus_hp=_TARGET_BONUS_HP,
        slots=_SLOTS,
        inject_boots=inject_boots,
        timeout=15.0,
    )
    if res is None or not res.order:
        return None
    return [s.item_name for s in res.order]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=18893,
                    help="temp port for the worktree DS engine")
    ap.add_argument("--dry-run", action="store_true",
                    help="report changes without writing")
    ap.add_argument("--champion", default=None,
                    help="limit to a single champion (debug)")
    args = ap.parse_args(argv)

    snap = DataSnapshot.load()
    data = json.loads(_LOADOUTS.read_text(encoding="utf-8"))
    champs = data["champions"]

    deny = OFFCLASS_MARKSMAN_ITEM_NAMES
    # The loadout file uses display names ("Kai'Sa", "Miss Fortune") while
    # the engine champions dict is keyed by id ("Kaisa", "MissFortune").
    # Resolve via the server's display revmap so display-vs-id drift
    # (Kai'Sa / Kog'Maw / Miss Fortune are ranged marksmen) is not missed.
    from agents.daemon_slayer.server import _resolve_champion_id

    ranged: list[str] = []
    for n in champs:
        eid = _resolve_champion_id(snap, n)
        rec = snap.champions.get(eid)
        if rec and _is_ranged_marksman(rec):
            ranged.append(n)
    if args.champion:
        ranged = [n for n in ranged if n == args.champion]

    _start_worktree_engine(args.port)

    regen_cache: dict[tuple[str, str], list[str] | None] = {}
    n_regen = 0
    n_stripped = 0
    touched_champs: set[str] = set()

    for champion in ranged:
        entry = champs[champion]
        for ck, cmode in _MODE_FOR_COLLAPSED.items():
            variant = (entry.get("variants") or {}).get(ck)
            if not variant:
                continue
            engine_mode, inject_boots = cmode
            for path in variant.get("build_paths") or []:
                items = path.get("items") or []
                path_key = path.get("key") or ""
                has_pollution = any(it in deny for it in items)
                if not has_pollution:
                    # Already clean (e.g. item-208 hand-fixed SR builds).
                    # Leave the curated distinct build untouched - preserves
                    # Crit vs Lethality vs On-Hit path distinctness.
                    continue
                # Strip deny-set items in place first (preserves the
                # curated build's identity / distinctness).
                cleaned = [it for it in items if it not in deny]
                if _is_carry_path(path_key) and len(cleaned) < 5:
                    # Carry-axis path went too short after stripping - the
                    # whole build was off-class junk. Regenerate the full
                    # sequence through the fixed clean dps pool so the path
                    # is a real 6-item ADC build, not a 2-item stub.
                    cache_key = (champion, engine_mode)
                    if cache_key not in regen_cache:
                        regen_cache[cache_key] = _regen_carry_path(
                            champion, engine_mode, inject_boots
                        )
                    regen = regen_cache[cache_key]
                    if regen:
                        path["items"] = list(regen)
                        n_regen += 1
                        touched_champs.add(champion)
                        continue
                # Otherwise keep the stripped-in-place build (preserves a
                # genuinely off-class flavor path's identity, and keeps a
                # carry path that still has >=5 clean items distinct).
                if cleaned != items:
                    path["items"] = cleaned
                    n_stripped += 1
                    touched_champs.add(champion)
            # Keep the collapsed variant-level items in sync with
            # build_paths[0] (the primary) per the collapse contract.
            paths = variant.get("build_paths") or []
            if paths:
                variant["items"] = list(paths[0].get("items") or [])

    print(
        f"ranged marksmen: {len(ranged)} | paths regenerated: {n_regen} | "
        f"non-carry paths stripped: {n_stripped} | champs touched: "
        f"{len(touched_champs)}"
    )

    if args.dry_run:
        print("(dry-run; no write)")
        return 0

    if not touched_champs:
        print("nothing to write")
        return 0

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = _LOADOUTS.with_suffix(f".json.bak-item213-{ts}")
    backup.write_bytes(_LOADOUTS.read_bytes())
    tmp = _LOADOUTS.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(_LOADOUTS)
    print(f"wrote {_LOADOUTS} (backup {backup.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
