# arch: Lane A laning-scenario precompute (matchup-engine table) | section=core | frozen=no
"""Lane A laning-scenario precompute (HZ-A1) - PRIMARY north star: drive live
Haiku usage to ZERO.

PURPOSE
    Precompute, offline + deterministically, the laning trade verdict
    (``all_in`` / ``trade`` / ``back_off`` / ``even``) for a grid of
    ``(my_champ x enemy x level-band x mana-state x cooldown-state)`` so the live
    coach can read a dict at request time INSTEAD of round-tripping the
    "should I trade / all-in / back off" question through Claude Haiku. The
    verdict is the SHIPPED, deterministic Daemon Slayer matchup engine's
    (``agents.daemon_slayer.matchup.compute_matchup``) - this module is the
    sweep + persist + read layer around it, no new combat math.

DIMENSIONS (the lookup key)
    * my_champ x enemy : canonical DDragon id pair (the 1v1 trade).
    * level-band       : a representative level per lane phase (``LEVEL_BANDS``).
    * mana-state       : ``full`` (the full rotation) vs ``low`` (the affordable
      prefix at ``LOW_MANA_FRACTION`` of the pool, derived from the live
      ``mana_sim.compute_mana_bounded_combo`` per-cast cost ledger). A manaless
      champ collapses ``low`` -> ``full`` (flagged ``manaless``).
    * cooldown-state   : ``all_up`` (Q/W/E/R) vs ``no_ult`` (Q/W/E, ult on CD).

The mana-state + cd-state both resolve to the ``my`` champion's action-token
``sequence``, which threads into ``compute_matchup(sequence_a=...)`` - so a
low-mana / no-ult cell fires a SHORTER combo into the enemy and the verdict
shifts honestly (less burst -> fewer all-ins, more back-offs). The enemy side is
modelled at the same level + item set, at FULL mana, and at the SAME cd-state as
the cell (``sequence_b`` = ``combo_sequence(cd_state)``): a ``no_ult`` window has
ults down for BOTH laners (cooldowns cycle together in lane), an ``all_up`` window
has them up for both. We vary only MY mana state asymmetrically (mana pools are
champ-specific), so a same-level same-cd mirror is symmetric (net_swing 0 -> even)
in BOTH bands while a restricted MY mana state reads as a genuine disadvantage.
(Itemless; an item axis is a separate session, the HZ-B build-order precompute.
HZ-A2 adds the gold-income + power-spike ``economy`` block, not items.)

WHAT v1 IS (honest scope)
    BUILD + PERSIST + READ only. The live coach flip is EXCLUDED (charter 4b
    "do not flip blind" - needs real / replayed-game validation + operator OK;
    Haiku stays the interim floor). Itemless, single representative level per
    band, enemy level mirrors mine, enemy items unmodelled - the same honest
    lower-fidelity inputs ``core.laning_verdicts`` already documents for its live
    1v1 seam. The committed table seeds a documented archetype-diverse champion
    sample (``SEED_CHAMPIONS`` - a SAMPLE, not a tier list); ``--champions`` /
    ``--enemies`` expand it to the full roster offline.

SHAPE (per mode, atomic write to data/daemon_slayer/laning_scenarios/<patch>/)::

    {
      "version": "<patch>", "generated_at": "<iso>", "mode": "<sr|aram|arena>",
      "schema": "laning_scenarios/v3",
      "dimensions": {"level_bands": {...}, "mana_states": [...], "cd_states": [...],
                     "economy": {"income_per_min": <float>, "spike_ladder": [...],
                                 "recall_states": [...], "back_soon_window_s": <float>}},
      "scenarios": {
        "<my_champ>": {"<enemy>": {"<band>": {"<mana>": {"<cd>": {
            "verdict": "...", "net_swing": <float>, "pct_my_removed": <float>,
            "pct_enemy_removed": <float>,
            "economy": {"recall": "recall_now|back_soon|hold",
                        "next_spike": "component|first_item|two_item|three_item|complete",
                        "gold_at_band": <float>}}}}}}
      }
    }

Slim v3 leaf: only the reader-consumed fields are persisted (the derived
``my_can_full_combo`` / ``manaless`` / ``sequence`` and the intermediate
``economy.spike_eta_s`` are dropped) and the table is written COMPACT, halving
the full-roster (171x171x3-band) artifact. The HZ-A2 ``economy`` block is
gold-income + item-completion driven (the gold / spike math lives in
core.lead_projection): ``gold_at_band`` / ``next_spike`` are the expected economy
at the band's representative minute (the project_lead level<->minute curve);
``recall`` is the cell-varying back-timing verdict, keyed on the trade verdict +
mana / manaless state. BUILD + PERSIST only (same charter-4b do-not-flip-blind
boundary as the v1 verdict).

FAIL-SOFT (read side)
    A missing / unreadable / malformed table yields ``{}`` and every ``lookup``
    yields ``{}``. The coach surface degrades to "no precomputed verdict" (it
    falls back to the existing path), never an exception. Mirrors
    ``core.pickban_targets`` / ``core.laning_verdicts``.

The non-dry generator path (``main``) refuses to run when the DS data set will
not load, the same guard the other precompute generators use - an empty table is
worse than no table.
"""
from __future__ import annotations

import argparse
import json
import logging
logger = logging.getLogger("rc.laning_scenario_precompute")
import math
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional, Sequence, Tuple

log = logging.getLogger(__name__)

# Bound at module scope so tests can stub them (the tests/test_pickban_targets
# pattern: mock.patch.object over a tiny roster). Importing these pulls the DS
# engine code modules (not data) - cheap; DataSnapshot.load() is only called when
# a sweep actually runs.
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.mana_sim import compute_mana_bounded_combo
from agents.daemon_slayer.matchup import compute_matchup

# HZ-A2: the gold-income + power-spike primitives live in lead_projection (the
# shared deterministic macro-economy authority); this module composes them into a
# per-cell recall/back-timing + spike-ETA economy block. Pure import (no cycle:
# lead_projection imports nothing from core).
from core import lead_projection as _lead

# Project root: core/ -> C:\Riot Commander\
_ROOT = Path(__file__).resolve().parent.parent
_DS_DIR = _ROOT / "data" / "daemon_slayer"
_CURRENT_TXT = _DS_DIR / "current.txt"
_OUT_SUBDIR = "laning_scenarios"

# Patch fallback when current.txt is missing (guards a fresh checkout only).
_FALLBACK_PATCH = "16.11.1"

# Representative level per lane phase. Keys are the lookup band labels; values
# are the level fed to the engine. L2 = early skirmish, L6 = first ult spike,
# L11 = 2-item mid, L16 = late-lane / roam.
LEVEL_BANDS: dict[str, int] = {"L2": 2, "L6": 6, "L11": 11, "L16": 16}

# Bands actually GENERATED into the NxN table. The laning phase is over by
# ~lvl 14, so L16 (late-lane / roam) is omitted from the sweep to keep the
# full-roster artifact ~half the size - the reader maps a lvl>=14 game to L16
# and fail-softs (no precomputed choice) there, which is correct for a laning
# coach. LEVEL_BANDS stays 4-entry so band_for_level's mapping is unchanged;
# GEN_BANDS is the subset the generator emits.
GEN_BANDS: Tuple[str, ...] = ("L2", "L6", "L11")

MANA_STATES: Tuple[str, ...] = ("full", "low")
CD_STATES: Tuple[str, ...] = ("all_up", "no_ult")

# The canonical full laning rotation in action tokens. The burst walker resolves
# each token to that champion's ability (a non-damaging / unleveled slot
# contributes 0), so one shared sequence works across the roster. no_ult drops R.
_FULL_COMBO: Tuple[str, ...] = ("Q", "W", "E", "R")

# "low mana" = this fraction of the resolved mana pool is available to spend on
# the trade. Tunable; 0.35 yields a 1-2 spell poke for a typical mid mana pool.
LOW_MANA_FRACTION: float = 0.35

VALID_VERDICTS: frozenset[str] = frozenset(
    {"all_in", "trade", "back_off", "even"}
)

# HZ-A2 recall/back-timing tuning (gold-income + spike driven; the gold/spike
# math itself lives in core.lead_projection). The next spike within this many
# seconds reads "back_soon" (hold the wave, plan the back); a resource-starved
# mana champ backs now once a back is worth the lane time (>= _MIN_BACK_GOLD).
RECALL_BACK_SOON_WINDOW_S: float = 60.0
_MIN_BACK_GOLD: float = 500.0
RECALL_STATES: Tuple[str, ...] = ("recall_now", "back_soon", "hold")
VALID_RECALLS: frozenset[str] = frozenset(RECALL_STATES)

# Archetype-diverse laner SAMPLE for the committed seed table. NOT a tier list -
# a neutral spread of damage types + resource types (Garen = manaless bruiser,
# Annie = AP burst mana, Caitlyn = AD marksman, Malphite = AP tank, ...). Expand
# to the full roster offline with --champions / --enemies.
SEED_CHAMPIONS: Tuple[str, ...] = (
    "Garen", "Darius", "Annie", "Ahri", "Caitlyn",
    "Ezreal", "Lux", "Malphite", "Jax", "Syndra",
)

# Read cache keyed (mode, patch) -> (mtime, payload). mtime-aware: a stale entry
# is dropped when the file on disk is newer than what we cached.
_CACHE: dict[Tuple[str, str], Tuple[float, dict]] = {}


# --------------------------------------------------------------------------- #
# Pure dimension helpers (no engine, no snapshot)
# --------------------------------------------------------------------------- #
def combo_sequence(cd_state: str) -> Tuple[str, ...]:
    """Action-token sequence for a cooldown-state.

    ``all_up`` -> the full Q/W/E/R rotation; ``no_ult`` -> Q/W/E (ult on CD).
    Any unrecognized state degrades to the full rotation (fail-soft).
    """
    if cd_state == "no_ult":
        return tuple(t for t in _FULL_COMBO if t != "R")
    return _FULL_COMBO


def level_for_band(band: str) -> int:
    """Representative level for a band label (raises KeyError on an unknown band -
    band labels are a closed set the caller controls)."""
    return LEVEL_BANDS[band]


def _round(value: object) -> float:
    """Round a scalar to 4 dp for stable JSON (NaN / non-numeric -> 0.0)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(f) or math.isinf(f):
        return 0.0
    return round(f, 4)


# --------------------------------------------------------------------------- #
# HZ-A2 economy verdict (recall/back-timing + power-spike-ETA)
# --------------------------------------------------------------------------- #
def _recall_verdict(
    gold_at_band: float,
    spike_eta_s: float,
    mana_state: str,
    manaless: bool,
    next_spike_label: str,
) -> str:
    """Recall/back-timing verdict for one cell - gold-income + spike driven.

    The trade verdict is a COMBAT read, not an economy one, so it does NOT drive
    recall; the cell-level economy input is the mana state. Priority:
      1. A mana champ on its low-mana combo (resource-starved) with a back-worthy
         gold count backs now to refill + shop. A manaless champ's ``low`` cell is
         NOT resource-starved (no pool to run dry).
      2. Core build complete -> no item spike to back for; hold (macro phase).
      3. The next spike is imminent -> hold the wave, plan the back for it.
      4. The spike is far but you are already sitting on a completed item's worth
         of unspent gold -> back now to convert gold into power.
      5. Otherwise hold and keep farming toward the spike."""
    if mana_state == "low" and not manaless and gold_at_band >= _MIN_BACK_GOLD:
        return "recall_now"
    if next_spike_label == _lead.SPIKE_COMPLETE:
        return "hold"
    if spike_eta_s <= RECALL_BACK_SOON_WINDOW_S:
        return "back_soon"
    if gold_at_band >= _lead.spike_threshold("first_item"):
        return "recall_now"
    return "hold"


def economy_cell(
    band: str,
    mana_state: str,
    mode: str = "SR",
    manaless: bool = False,
) -> dict:
    """Gold-income + power-spike economy verdict for one scenario cell (HZ-A2).

    Reuses ``core.lead_projection`` for the band->minute bridge, the gross-income
    benchmark, and the cumulative-gold spike ladder. Pure + deterministic - no
    engine, no snapshot, no network. Returns ``{recall, next_spike,
    gold_at_band}``. ``gold_at_band`` / ``next_spike`` are band-constant (the
    expected economy at the band's representative minute); ``recall`` is the
    cell-varying field, driven by the mana / manaless state + spike timing (NOT
    the combat trade verdict). ``spike_eta_s`` is computed to drive ``recall``
    but NOT persisted in the slim leaf (no reader consumes it)."""
    minutes = _lead.minutes_for_level(level_for_band(band))
    gold = _lead.expected_gold_earned(minutes, mode)
    label, target = _lead.next_spike(gold)
    eta = _lead.spike_eta_seconds(gold, target, mode)
    recall = _recall_verdict(gold, eta, mana_state, manaless, label)
    return {
        "recall": recall,
        "next_spike": label,
        "gold_at_band": _round(gold),
    }


# --------------------------------------------------------------------------- #
# Engine-backed cell + sequence derivation
# --------------------------------------------------------------------------- #
def _affordable_sequence(
    snapshot: DataSnapshot,
    champion: str,
    level: int,
    item_ids: Sequence[str | int],
    base_seq: Tuple[str, ...],
    budget_frac: float,
    mode: str,
) -> Tuple[Tuple[str, ...], bool]:
    """The prefix of ``base_seq`` affordable on ``budget_frac`` of the mana pool.

    Walks the live ``compute_mana_bounded_combo`` per-cast cost ledger and keeps
    tokens while the cumulative cost stays within budget (always at least one -
    you can always throw a single spell). Returns ``(sequence, manaless)``; a
    manaless / poolless champ has no restriction so ``base_seq`` rides through
    with ``manaless=True``. Fail-soft: any engine error returns ``base_seq``.
    """
    try:
        r = compute_mana_bounded_combo(
            str(champion), int(level), item_ids=list(item_ids),
            sequence=list(base_seq), mode=mode, snapshot=snapshot,
        )
    except Exception:  # noqa: BLE001 - one bad cell never sinks the sweep
        return tuple(base_seq), False
    pool = float(r.mana_pool)
    if not math.isfinite(pool) or pool <= 0.0:
        return tuple(base_seq), True
    budget = pool * float(budget_frac)
    out: list[str] = []
    spent = 0.0
    for hit in r.hits:
        cost = float(getattr(hit, "cost", 0.0) or 0.0)
        if out and spent + cost > budget:
            break
        spent += cost
        out.append(str(hit.action))
    if not out:
        out = [str(r.hits[0].action)] if r.hits else list(base_seq[:1])
    return tuple(out), False


def derive_sequence(
    snapshot: DataSnapshot,
    champion: str,
    level: int,
    mana_state: str,
    cd_state: str,
    mode: str = "SR",
    item_ids: Sequence[str | int] = (),
) -> Tuple[Tuple[str, ...], bool]:
    """Resolve ``(sequence, manaless)`` for one (champ, level, mana, cd) cell.

    ``full`` mana uses the full cd-state rotation (the engine still mana-gates it
    internally for the ``my_can_full_combo`` flag); ``low`` mana truncates to the
    affordable prefix. Returns the action-token tuple + whether the champ is
    manaless (low == full).
    """
    base = combo_sequence(cd_state)
    if mana_state == "low":
        return _affordable_sequence(
            snapshot, champion, level, item_ids, base, LOW_MANA_FRACTION, mode
        )
    # full: still probe the pool so the manaless flag is honest on full cells.
    _, manaless = _affordable_sequence(
        snapshot, champion, level, item_ids, base, 1.0, mode
    )
    return base, manaless


def _matchup(
    snapshot: DataSnapshot,
    my_champion: str,
    enemy: str,
    level: int,
    seq: Sequence[str],
    cd_state: str,
    mode: str,
    item_ids: Sequence[str | int],
):
    """Fire MY ``seq`` into the enemy, with the enemy-modelling rule in ONE place.

    The enemy fires the SAME cd-state rotation as the cell (``sequence_b`` =
    ``combo_sequence(cd_state)``): ult-up (``all_up``) -> the full Q/W/E/R, ult
    on cd (``no_ult``) -> Q/W/E on BOTH sides. Cooldowns cycle together in lane,
    so a ``no_ult`` window means NEITHER laner has ult up - modelling MY ult down
    while the enemy still lands theirs over-states incoming damage (the item-575
    back_off->trade over-kill). The enemy stays at FULL mana (no per-cell
    truncation - mana pools are champ-specific, so ``mana_state`` is MY axis
    only); only MY mana state varies the asymmetry per cell. A same-level same-cd
    mirror is therefore symmetric (net_swing 0 -> even) in BOTH bands."""
    return compute_matchup(
        snapshot, str(my_champion), str(enemy), level, level,
        item_ids_a=list(item_ids), item_ids_b=list(item_ids),
        mode=mode, sequence_a=list(seq), sequence_b=list(combo_sequence(cd_state)),
    )


def _cell_from_result(result, economy: Optional[dict] = None) -> dict:
    """Shape a MatchupResult into the persisted SLIM leaf dict (single source so
    compute_cell + generate_table never drift). ``net_swing`` > 0 = my champ
    favored; ``pct_my_removed`` is the fraction of MY effective HP the enemy
    combo removes. ``economy`` (HZ-A2) is the optional recall/back-timing block;
    omitted when None. Slim v3 persists ONLY the reader-consumed fields - the
    derived ``my_can_full_combo`` / ``manaless`` / ``sequence`` are dropped to
    halve the full-roster NxN artifact (no consumer reads them)."""
    cell = {
        "verdict": str(result.verdict),
        "net_swing": _round(result.net_swing),
        "pct_my_removed": _round(result.pct_a_removed),
        "pct_enemy_removed": _round(result.pct_b_removed),
    }
    if economy is not None:
        cell["economy"] = economy
    return cell


def compute_cell(
    snapshot: DataSnapshot,
    my_champion: str,
    enemy: str,
    band: str,
    mana_state: str,
    cd_state: str,
    mode: str = "SR",
    item_ids: Sequence[str | int] = (),
) -> dict:
    """Compute ONE scenario cell via the DS matchup engine.

    Resolves the level from the band + the ``my`` action sequence from
    (mana, cd), then fires ``compute_matchup`` (my champ as A, enemy at full
    resources). The returned dict is the persisted leaf shape.
    """
    level = level_for_band(band)
    seq, manaless = derive_sequence(
        snapshot, my_champion, level, mana_state, cd_state,
        mode=mode, item_ids=item_ids,
    )
    result = _matchup(snapshot, my_champion, enemy, level, seq, cd_state, mode, item_ids)
    economy = economy_cell(band, mana_state, mode=mode, manaless=manaless)
    return _cell_from_result(result, economy)


def generate_table(
    snapshot: DataSnapshot,
    champions: Sequence[str],
    enemies: Sequence[str],
    mode: str = "SR",
    bands: Optional[Sequence[str]] = None,
    item_ids: Sequence[str | int] = (),
) -> dict:
    """Sweep the full (champ x enemy x band x mana x cd) grid into a payload dict.

    Cell order is deterministic (champions outer, then enemies, bands,
    mana-states, cd-states). Every leaf is a ``compute_cell`` dict; a champ's
    sequence is memoized across enemies (enemy does not change my rotation).
    """
    band_keys = list(bands) if bands is not None else list(GEN_BANDS)
    seq_cache: dict[Tuple[str, int, str, str], Tuple[Tuple[str, ...], bool]] = {}

    def _seq(champ: str, level: int, mana: str, cd: str) -> Tuple[Tuple[str, ...], bool]:
        key = (champ, level, mana, cd)
        if key not in seq_cache:
            seq_cache[key] = derive_sequence(
                snapshot, champ, level, mana, cd, mode=mode, item_ids=item_ids
            )
        return seq_cache[key]

    scenarios: dict = {}
    skipped = 0
    for my in champions:
        per_enemy: dict = {}
        for enemy in enemies:
            # Per-pair fail-soft: a champion the engine cannot model for some
            # (band, mana, cd) must not abort a full-roster (171x171) sweep -
            # drop the offending pair whole (a partial pair is worse than a
            # missing one; the reader fail-softs uncovered pairs) and continue.
            try:
                per_band: dict = {}
                for band in band_keys:
                    level = level_for_band(band)
                    per_mana: dict = {}
                    for mana in MANA_STATES:
                        per_cd: dict = {}
                        for cd in CD_STATES:
                            seq, manaless = _seq(my, level, mana, cd)
                            result = _matchup(
                                snapshot, my, enemy, level, seq, cd, mode, item_ids
                            )
                            economy = economy_cell(
                                band, mana, mode=mode, manaless=manaless,
                            )
                            per_cd[cd] = _cell_from_result(result, economy)
                        per_mana[mana] = per_cd
                    per_band[band] = per_mana
            except Exception as exc:  # noqa: BLE001 - one bad pair must not abort
                skipped += 1
                log.warning(
                    "laning gen: skipped pair %s vs %s (%s)", my, enemy, exc
                )
                continue
            per_enemy[enemy] = per_band
        scenarios[my] = per_enemy
    if skipped:
        log.warning("laning gen: %d (my, enemy) pairs skipped", skipped)

    return {
        "version": resolve_patch(),
        "generated_at": _now_iso(),
        "mode": str(mode).lower(),
        "schema": "laning_scenarios/v3",
        "dimensions": {
            "level_bands": {k: LEVEL_BANDS[k] for k in band_keys},
            "mana_states": list(MANA_STATES),
            "cd_states": list(CD_STATES),
            "economy": {
                "income_per_min": _lead.gold_income_per_min(mode),
                "spike_ladder": _lead.spike_ladder(),
                "recall_states": list(RECALL_STATES),
                "back_soon_window_s": RECALL_BACK_SOON_WINDOW_S,
            },
        },
        "scenarios": scenarios,
    }


# --------------------------------------------------------------------------- #
# Persist
# --------------------------------------------------------------------------- #
def resolve_patch() -> str:
    """Read the active patch from current.txt; fall back to _FALLBACK_PATCH."""
    try:
        txt = _CURRENT_TXT.read_text(encoding="utf-8").strip()
        if txt:
            return txt
    except Exception:  # noqa: BLE001 - fail-soft to fallback
        pass
    return _FALLBACK_PATCH


def _now_iso() -> str:
    """UTC timestamp in ISO-8601, trimmed to seconds."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def out_dir_for(patch: str, override: Optional[str] = None) -> Path:
    """Output directory for ``patch`` (or the override path verbatim)."""
    if override:
        return Path(override)
    return _DS_DIR / _OUT_SUBDIR / patch


def atomic_write(payload: dict, out_path: Path) -> None:
    """Write ``payload`` to ``out_path`` via tmp + os.replace (atomic).

    A reader polling mid-write must never see a partial file (CLAUDE.md hard
    rule). ASCII-only, sorted keys for a deterministic byte-stable artifact.
    COMPACT (no indent, no key/item spaces): the full-roster NxN table is
    ~468k leaf cells - compact keeps it ~55MB instead of ~290MB pretty, and the
    blob is machine-read not hand-diffed, so readability is moot.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=f".{out_path.stem}.", suffix=".tmp", dir=str(out_path.parent),
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            json.dump(
                payload, fh, ensure_ascii=True,
                separators=(",", ":"), sort_keys=True,
            )
            fh.write("\n")
        os.replace(tmp_path, str(out_path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# --------------------------------------------------------------------------- #
# Read (fail-soft) - the coach-time lookup layer
# --------------------------------------------------------------------------- #
def _db_path(mode: str, patch: str) -> Path:
    return _DS_DIR / _OUT_SUBDIR / patch / f"laning_scenarios_{str(mode).lower()}.json"


def load_laning_scenarios(mode: str = "sr", patch: Optional[str] = None) -> dict:
    """Return the laning-scenarios payload for ``mode`` + patch (or ``{}``).

    Cached + mtime-aware; fail-soft to ``{}`` on any missing / parse error.
    """
    use_patch = patch or resolve_patch()
    key = (str(mode).lower(), use_patch)
    path = _db_path(mode, use_patch)
    try:
        mtime = path.stat().st_mtime
    except Exception:  # noqa: BLE001 - missing file -> empty
        _CACHE.pop(key, None)
        return {}
    cached = _CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            payload = {}
    except Exception:  # noqa: BLE001 - malformed -> empty
        payload = {}
    _CACHE[key] = (mtime, payload)
    return payload


def lookup(
    payload: dict,
    my_champion: str,
    enemy: str,
    band: str,
    mana_state: str,
    cd_state: str,
) -> dict:
    """Navigate a loaded payload to one scenario cell (``{}`` when any key is
    absent). Pure - operates on an already-loaded dict so it is trivially
    testable + reusable by a future live consumer (HZ-C1)."""
    node: object = payload.get("scenarios") if isinstance(payload, dict) else None
    for step in (my_champion, enemy, band, mana_state, cd_state):
        if not isinstance(node, dict):
            return {}
        node = node.get(step)
    return node if isinstance(node, dict) else {}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
_MODE_KEYS = ("sr", "aram", "arena")
_DS_MODE_BY_KEY = {"sr": "SR", "aram": "ARAM", "arena": "ARENA"}


def _parse_csv(value: str) -> list[str]:
    return [tok.strip() for tok in str(value).split(",") if tok.strip()]


def _count_leaves(payload: dict) -> int:
    total = 0
    for per_enemy in (payload.get("scenarios") or {}).values():
        for per_band in (per_enemy or {}).values():
            for per_mana in (per_band or {}).values():
                for per_cd in (per_mana or {}).values():
                    total += len(per_cd or {})
    return total


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mode", default="all",
                    choices=("all",) + _MODE_KEYS,
                    help="Restrict generation to one mode (default: all).")
    ap.add_argument("--champions", default="",
                    help="CSV of my-champ DDragon ids (default: SEED_CHAMPIONS).")
    ap.add_argument("--enemies", default="",
                    help="CSV of enemy DDragon ids (default: == --champions).")
    ap.add_argument("--bands", default="",
                    help="CSV of level-band labels (default: GEN_BANDS, the "
                         "laning-phase subset L2/L6/L11; L16 is omitted).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print per-mode leaf counts without writing.")
    ap.add_argument("--out", default="",
                    help="Override output directory (default: "
                         "data/daemon_slayer/laning_scenarios/<patch>).")
    args = ap.parse_args(argv)

    champions = _parse_csv(args.champions) or list(SEED_CHAMPIONS)
    enemies = _parse_csv(args.enemies) or list(champions)
    bands = _parse_csv(args.bands) or list(GEN_BANDS)
    for band in bands:
        if band not in LEVEL_BANDS:
            logger.info(f"unknown band {band!r} (valid: {list(LEVEL_BANDS)})",
                  file=sys.stderr)
            return 2

    try:
        snapshot = DataSnapshot.load()
    except Exception as exc:  # noqa: BLE001 - a dead data set must not write
        logger.info(f"DataSnapshot.load() failed ({exc}); refusing to write an empty "
              "table.", file=sys.stderr)
        return 2

    patch = resolve_patch()
    out_dir = out_dir_for(patch, args.out or None)
    target_modes = _MODE_KEYS if args.mode == "all" else (args.mode,)

    logger.info(f"laning-scenarios gen patch={patch} modes={target_modes} "
          f"champions={len(champions)} enemies={len(enemies)} bands={bands} "
          f"dry_run={args.dry_run} out={out_dir}")

    started = time.time()
    for mode_key in target_modes:
        payload = generate_table(
            snapshot, champions, enemies,
            mode=_DS_MODE_BY_KEY.get(mode_key, "SR"), bands=bands,
        )
        leaves = _count_leaves(payload)
        if args.dry_run:
            logger.info(f"  [dry-run] {mode_key:5s}: {leaves} leaf cells (not written)")
        else:
            out_path = out_dir / f"laning_scenarios_{mode_key}.json"
            atomic_write(payload, out_path)
            logger.info(f"  {mode_key:5s}: {leaves} leaf cells -> {out_path.name}")

    logger.info(f"done in {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
