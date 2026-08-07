"""tools/replay_laning_verdict_validate.py - the HZ-A laning-VERDICT flip gate.

Replay-validation harness for the SHIPPED HZ-A laning precompute ARTIFACT - the
on-disk ``data/daemon_slayer/laning_scenarios/<patch>/*.json`` cells that
``core.precomputed_laning_coach`` serves as the live A/B "trade / all-in / back
off" chip. It REPORTS how often the verdict the chip would show actually matched
the real lane outcome, so the orchestrator can decide whether the precomputed
laning coach is trustworthy enough to FLIP off its live Claude Haiku call.

How this differs from ``tools/replay_matchup_validate.py``
---------------------------------------------------------
That harness gates the ``compute_matchup`` ENGINE FUNCTION (net_swing) called
fresh in-process. THIS harness gates the PRECOMPUTE ARTIFACT end-to-end: it
reads the shipped JSON through the exact live path the coach uses
(``load_laning_scenarios`` -> ``lookup`` at the unknown-state baseline cell
band/full/all_up) and scores the discrete VERDICT ACTION (all_in / trade /
back_off), not just the swing sign. If the table build dropped, rounded, or
mis-keyed a cell, only this gate catches it; and only this gate answers "when
the chip says ALL-IN, did committing actually win?".

How it works
------------
1. Reuse the proven SR-match selection + same-lane pairing + solo-kill-duel
   extraction from ``replay_matchup_validate`` (no rebuild).
2. Per lane pair (champ_a on team 100, champ_b on team 200), at each replay
   level, resolve the shipped cell ``lookup(table, canon(a), canon(b),
   band_for_level(level), "full", "all_up")``. The full/all_up state is the
   live coach's documented unknown-mana / unknown-ult baseline read
   (``mana_state_for(None)`` -> full, ``cd_state_for(None)`` -> all_up), so the
   gate scores exactly what the chip shows when the live inputs are unknown.
3. The cell verdict gives champ_a's stance: ``all_in`` / ``trade`` -> a is
   favored to win the exchange; ``back_off`` -> a is unfavored (b favored);
   ``even`` (or |net_swing| below the dead-band) -> excluded.
4. GROUND TRUTH (same proxies + caveats as the matchup gate): lane gold at the
   chosen frame, and the direct solo-kill duel differential. Agreement =
   favored side == the side that actually came out ahead.
5. Also reports a per-verdict-ACTION breakdown: for each of all_in / trade /
   back_off, how often the favored side won. That is the headline flip signal.

RETIRED AS A FLIP GATE - 2026-08-06, ADR-013 (RM-155)
-----------------------------------------------------
The flip this harness gated has been RETIRED. The tool is still correct and
still worth running against a changed table, but no number it produces is
authority to flip the laning coach onto the precomputed verdict.

The deciding evidence was not the 0.4887 agreement on its own - a ~0.50 score
could equally mean the LABEL is dead. ``tools/laning_verdict_information_probe.py``
separated the two: a deliberately stupid held-out per-(role, champion) mean-gold
prior scores 0.5457 [0.5121, 0.5788] and 0.5394 [0.5030, 0.5754] against the
IDENTICAL label, and the solo-kill duel winner predicts the gold winner 0.7705
[0.7429, 0.7960]. The label is learnable and is coupled to the head-to-head
result; the shipped verdict is beaten by a champion-name lookup and does not
beat a coin (MI 0.00039 bits, 0.039 pct of label entropy, phi -0.023).

Interpreting the result
-----------------------
- agreement ~0.50 = the verdict carries no signal. This is the standing
  measurement and it is what ADR-013 retired the flip on.
- agreement meaningfully > 0.50 would CONTRADICT ADR-013. That is grounds to
  re-open the ADR with a ``laning_verdict_information_probe`` artifact attached,
  not grounds to flip. Re-running this file alone can never close that loop,
  because it cannot tell a good verdict from a coincidentally-aligned one.

Axis sweep (``--cd-state`` / ``--item-state``)
----------------------------------------------
Step 2 above scores ONE cell per pair. That silently collapsed two real axes,
so a flip decision rested on a single slice of the table. The sweep flags score
the cartesian product of the requested cd_states x item_states, reported per
combination under ``axis_sweep``. Both flags default to unset, and an unset run
resolves the identical baseline cell it always did - that is what keeps a new
number comparable against the 2026-06 baseline artifact.

Note that ``item_state`` is INERT against every table currently on disk: they
are all schema ``laning_scenarios/v3``, whose cd node IS the leaf cell, so
``lookup``'s descend-only fallback returns the same cell for every item_state.
Measuring that inertness is the point - it was previously unobservable.

THE ``--mode`` TRAP - the easiest way to produce a plausible wrong number
------------------------------------------------------------------------
``--mode`` swaps the shipped TABLE and never the CORPUS.
``replay_matchup_validate.select_sr_match_ids`` is
``WHERE game_mode = 'CLASSIC'`` unconditionally, so ``--mode aram`` scores the
ARAM table against SR lane outcomes. Measured 2026-08-06: it returned L6 n=1079
agreement 50.3 pct [47.3, 53.3] with an IDENTICAL ``pairs=1998
coverage=3978/3996`` to the sr run - only the agreement column moved. That reads
like a native ARAM measurement and is not one. **ARAM has no native gate
measurement and cannot have one:** Riot emits no ``team_position`` for ARAM or
Arena (20804 ARAM and 2792 CHERRY participant rows, every one empty), so
``extract_lane_pairs`` returns zero pairs for both, and neither mode has a lane
1v1 for a lane-outcome label to be about.

Output
------
- A JSON gate artifact at ``ops/runtime/laning_verdict_validation.json``
  (override with ``--out``). The durable deliverable.
- A concise human summary on stdout, including a BALANCE CENSUS
  (``label_base_rate_gold``) that separates "the verdict carries no signal"
  from "the harness cannot tell" - a ~0.50 agreement only indicts the verdict
  when the predictor and the label both actually vary.

Fail-soft: a malformed match / pair / cell never aborts the run - it is skipped
and counted. ASCII-only by hard rule.

"""

from __future__ import annotations

import argparse
import copy as _copy
import datetime as _dt
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# Resolve project root + the tools dir so both the package imports (core.*) and
# the sibling-module reuse (replay_matchup_validate) work regardless of CWD.
_THIS = Path(__file__).resolve()
_ROOT = _THIS.parent.parent
for _p in (str(_ROOT), str(_THIS.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Reuse the proven replay scaffolding (selection / pairing / duel truth / stats).
from replay_matchup_validate import (  # noqa: E402
    LanePair,
    LevelResult,
    extract_kill_counts,
    extract_lane_pairs,
    select_sr_match_ids,
    wilson_interval,
)

# ----------------------------------------------------------------- tunable defaults
_DEFAULT_DB = _ROOT / "data" / "rewind_history.db"
_DEFAULT_OUT = _ROOT / "ops" / "runtime" / "laning_verdict_validation.json"
_DEFAULT_LIMIT = 400
# Levels chosen to land in distinct bands: 6 -> L6 (first-ult spike), 11 -> L11
# (two-item mid). L2 mirrors are mostly even so are not a default.
_DEFAULT_LEVELS = (6, 11)
_DEFAULT_GOLD_FRAME_MIN = 10

# |net_swing| below this counts as "even" - excluded from the denominator. Same
# scale + default as the matchup gate (the table bakes the engine net_swing).
_EVEN_BAND = 0.02

# The unknown-state baseline cell: what the live chip resolves when mana / ult /
# items are unknown (``mana_state_for(None)`` -> full, ``cd_state_for(None)`` ->
# all_up, and ``lookup``'s own item_state default). These are pinned as module
# constants rather than call-site literals so the sweep can vary an axis WITHOUT
# moving the default - the 2026-06 baseline is only comparable against a run
# that still scores this exact cell.
_DEFAULT_MANA_STATE = "full"
_DEFAULT_CD_STATE = "all_up"
_DEFAULT_ITEM_STATE = "none"

# Verdict -> champ_a stance. all_in/trade = a commits (a favored); back_off = a
# yields (b favored); even = no decisive call.
_AGGRESSIVE = ("all_in", "trade")
_DEFENSIVE = ("back_off",)
_ACTION_VERDICTS = _AGGRESSIVE + _DEFENSIVE

# RETIREMENT STAMP (ADR-013, 2026-08-06). This harness is still a valid
# instrument and is still worth running against a changed table - but it is NO
# LONGER a flip-readiness gate, because the flip it gated has been retired. The
# stamp rides in every artifact so a re-run cannot be mistaken for pending work:
# the number has been at chance since 2026-06-18, and the deciding evidence is
# that a held-out per-champion gold prior BEATS it (0.5457 / 0.5394, both Wilson
# lower bounds above 0.50) against the identical label. The label is learnable;
# the verdict does not learn it. Re-open with
# tools/laning_verdict_information_probe.py, not with a re-run of this file.
_DECISION = {
    "status": "RETIRED",
    "adr": "ADR-013",
    "roadmap_row": "RM-155",
    "decided": "2026-08-06",
    "summary": (
        "The HZ-A laning-verdict flip is retired. This gate reports a valid "
        "measurement; it is not a pending flip decision. Do NOT flip the laning "
        "coach onto the precomputed verdict on any number this tool produces."
    ),
    "evidence": (
        "SR L6 n=1107 agreement 0.4887 (Wilson [0.45935, 0.51814]), mutual "
        "information 0.00039 bits = 0.039 pct of label entropy, and the "
        "Miller-Madow bias-corrected MI is NEGATIVE (-0.000262 bits at L6, "
        "-0.000329 at L11): the association is smaller than what pure noise "
        "produces at this n. A held-out per-(role, champion) mean-gold prior "
        "scores 0.5457 [0.5121, 0.5788] and 0.5394 [0.5030, 0.5754] on the same "
        "label, so the label is learnable and the verdict is the dead half. "
        "Dropping JUNGLE and pooling the four genuine lane roles still gives "
        "0.5124 [0.4891, 0.5356] over n=1778. The live compute_matchup engine "
        "measured on the same corpus has no headroom either (lane gold 49.0 pct "
        "L6 / 48.5 pct L11, solo-kill 51.3 / 51.5 pct, every interval straddling "
        "0.50), so a table regen has nothing to recover."
    ),
    "traps": [
        "--mode swaps the shipped TABLE and never the CORPUS: select_sr_match_ids "
        "is WHERE game_mode = 'CLASSIC' unconditionally. A --mode aram run scores "
        "the ARAM table against SR lane outcomes and returns a plausible wrong "
        "number. ARAM has no native gate measurement and cannot have one - Riot "
        "emits no team_position for ARAM or Arena, so extract_lane_pairs yields "
        "zero pairs there.",
        "--item-state is INERT on every shipped table: they are all schema "
        "laning_scenarios/v3, in which the cd_state node IS the leaf, so lookup's "
        "descend-only fallback returns the same cell for every item_state.",
        "'SR is stranded on 16.12.1' is WRONG - 16.13.1 ships all three modes.",
        "The RM-158 correction to data/hz_choice_shadow.jsonl cannot move this "
        "number: this gate reads data/rewind_history.db and the shipped tables "
        "and never opens the shadow corpus.",
    ],
}


# --------------------------------------------------------------------- verdict access
def make_verdict_fn(
    table: object,
    cd_state: str = _DEFAULT_CD_STATE,
    item_state: str = _DEFAULT_ITEM_STATE,
    mana_state: str = _DEFAULT_MANA_STATE,
) -> Callable[[str, str, str], Tuple[Optional[str], object]]:
    """Closure over the loaded HZ-A table -> ``(champ_a, champ_b, level) ->
    (verdict, net_swing)`` via the live coach lookup path. Missing cell / any
    error -> ``(None, None)`` (counted as uncovered). Imported lazily so unit
    tests that inject their own verdict_fn never need the real data files.

    The three state axes are keyword arguments defaulting to the unknown-state
    baseline, so an un-flagged call resolves exactly the cell this gate has
    always scored. ``item_state`` is a no-op against the v3 tables currently on
    disk (a v3 cd node IS the leaf cell), which is precisely why the axis needs
    to be sweepable rather than assumed - the collapse is invisible otherwise."""
    from core.archetype_picks import canonical_champion_id
    from core.laning_scenario_precompute import lookup
    from core.precomputed_laning_coach import band_for_level

    def _verdict(champ_a: str, champ_b: str, level: object) -> Tuple[Optional[str], object]:
        try:
            cell = lookup(
                table,
                canonical_champion_id(champ_a),
                canonical_champion_id(champ_b),
                band_for_level(level),
                mana_state,
                cd_state,
                item_state,
            )
        except Exception:  # noqa: BLE001
            return (None, None)
        if not isinstance(cell, dict):
            return (None, None)
        return (cell.get("verdict"), cell.get("net_swing"))

    return _verdict


def _parse_states(raw: Optional[str], default: str) -> List[str]:
    """Comma-separated axis states -> ordered, de-duplicated list. An absent or
    all-blank value yields ``[default]`` so the caller always has one column."""
    out: List[str] = []
    for chunk in str(raw or "").split(","):
        chunk = chunk.strip()
        if chunk and chunk not in out:
            out.append(chunk)
    return out or [default]


def sweep_axis_combos(
    cd_states: Sequence[str], item_states: Sequence[str]
) -> List[Tuple[str, str]]:
    """Cartesian product of the two swept axes, cd-major (so the printed sweep
    groups every item_state under its cd_state)."""
    return [(cd, item) for cd in cd_states for item in item_states]


def favored_side(verdict: Optional[str], net_swing: object, even_band: float) -> Optional[bool]:
    """Which side the shipped cell favors: ``True`` -> champ_a, ``False`` ->
    champ_b, ``None`` -> excluded (uncovered / even / below the dead-band).

    The discrete action verdict is authoritative when present (``all_in`` /
    ``trade`` -> a; ``back_off`` -> b); otherwise the net_swing sign decides.
    """
    if verdict in _AGGRESSIVE:
        return True
    if verdict in _DEFENSIVE:
        return False
    if verdict == "even":
        # An explicit even verdict is a decisive no-call - exclude it, do NOT
        # fall through to the swing sign (the table assigns even at |swing|~0,
        # but a defensive guard keeps a labelled even out of the denominator).
        return None
    # An unlabeled cell (verdict is None): fall back to the swing sign, dead-banded.
    try:
        swing = float(net_swing)
    except (TypeError, ValueError):
        return None
    if abs(swing) < even_band:
        return None
    return swing > 0.0


# --------------------------------------------------------------------------- scoring
def score_pair_gold(
    pair: LanePair,
    level: int,
    verdict_fn: Callable[[str, str, str], Tuple[Optional[str], object]],
    even_band: float = _EVEN_BAND,
) -> Tuple[str, bool, Optional[str]]:
    """Score one lane pair against the lane-gold ground truth at one level.

    Returns ``(status, agreed, verdict)`` where status is one of ``uncovered``
    (no shipped cell), ``even`` (excluded), ``gold_tie`` (no decisive truth) or
    ``decisive`` (``agreed`` meaningful). ``verdict`` is echoed for the action
    breakdown.
    """
    verdict, swing = verdict_fn(pair.champ_a, pair.champ_b, level)
    if verdict is None and swing is None:
        return ("uncovered", False, None)
    fav_a = favored_side(verdict, swing, even_band)
    if fav_a is None:
        return ("even", False, verdict)
    if pair.gold_a == pair.gold_b:
        return ("gold_tie", False, verdict)
    gold_favors_a = pair.gold_a > pair.gold_b
    return ("decisive", fav_a == gold_favors_a, verdict)


def score_pair_duel(
    pair: LanePair,
    level: int,
    verdict_fn: Callable[[str, str, str], Tuple[Optional[str], object]],
    a_kills_b: int,
    b_kills_a: int,
    even_band: float = _EVEN_BAND,
) -> Tuple[str, bool, Optional[str]]:
    """Score one lane pair against the direct solo-kill duel differential.

    status adds ``no_duel`` (the pair never killed each other) and ``kill_tie``
    (equal kills) to the gold path's set. The duel winner is whoever killed the
    other more - the most direct proxy for the trade the chip claims.
    """
    verdict, swing = verdict_fn(pair.champ_a, pair.champ_b, level)
    if verdict is None and swing is None:
        return ("uncovered", False, None)
    fav_a = favored_side(verdict, swing, even_band)
    if fav_a is None:
        return ("even", False, verdict)
    if a_kills_b == 0 and b_kills_a == 0:
        return ("no_duel", False, verdict)
    if a_kills_b == b_kills_a:
        return ("kill_tie", False, verdict)
    duel_favors_a = a_kills_b > b_kills_a
    return ("decisive", fav_a == duel_favors_a, verdict)


class _LabelBaseRate:
    """Predictor-vs-label balance over the scored pairs.

    Exists to separate two readings of a ~0.50 agreement that look identical in
    the headline number: a verdict that carries no signal, versus a harness that
    cannot tell. If the predictor is degenerate (always one side) or the label is
    one-sided, the agreement is an artifact and says nothing about the verdict.
    Only when BOTH vary does 0.50 mean zero mutual information."""

    def __init__(self) -> None:
        self.n = 0
        self.pred_a = 0
        self.label_a = 0
        self.label_b = 0
        self.label_ties = 0

    def record(self, fav_a: bool, truth_a: float, truth_b: float) -> None:
        self.n += 1
        if fav_a:
            self.pred_a += 1
        if truth_a == truth_b:
            self.label_ties += 1
        elif truth_a > truth_b:
            self.label_a += 1
        else:
            self.label_b += 1

    def to_dict(self) -> dict:
        label_n = self.label_a + self.label_b
        return {
            "n": self.n,
            "predictor_favors_a_rate": (self.pred_a / self.n) if self.n else None,
            "label_favors_a_rate": (self.label_a / label_n) if label_n else None,
            "label_decisive_n": label_n,
            "label_ties": self.label_ties,
        }


class _ActionBreakdown:
    """Per-verdict-ACTION agreement accumulator (all_in / trade / back_off)."""

    def __init__(self) -> None:
        self.by_verdict: Dict[str, Dict[str, int]] = {
            v: {"n": 0, "agree": 0} for v in _ACTION_VERDICTS
        }

    def record(self, verdict: Optional[str], agreed: bool) -> None:
        slot = self.by_verdict.get(verdict or "")
        if slot is None:
            return
        slot["n"] += 1
        if agreed:
            slot["agree"] += 1

    def to_dict(self) -> dict:
        out = {}
        for verdict, slot in self.by_verdict.items():
            n = slot["n"]
            lo, hi = wilson_interval(slot["agree"], n)
            out[verdict] = {
                "n": n,
                "agree": slot["agree"],
                "agreement": (slot["agree"] / n) if n else None,
                "wilson_95_lo": lo,
                "wilson_95_hi": hi,
            }
        return out


# ----------------------------------------------------------------------- orchestration
def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    """Open the replay corpus read-only, falling back to a plain connect when
    the URI form is unavailable so an odd path never fails the whole gate."""
    try:
        uri = "file:" + str(db_path).replace("\\", "/") + "?mode=ro"
        return sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return sqlite3.connect(str(db_path))


def run_validation(
    db_path: Path,
    levels: Sequence[int],
    limit: int,
    gold_frame_min: int,
    verdict_fn: Callable[[str, str, str], Tuple[Optional[str], object]],
    even_band: float = _EVEN_BAND,
) -> dict:
    """Walk the SR replays, score every lane pair vs gold + duel truth at each
    level, and build the report (gold agreement, duel agreement, per-action
    breakdown, coverage)."""
    # Read-only URI connect: this is the operator's live 1.8GB history DB in WAL
    # mode, and a read-write handle would touch its -wal/-shm sidecars for a run
    # that only ever SELECTs.
    conn = _connect_readonly(db_path)
    try:
        match_ids = select_sr_match_ids(conn, limit)
        gold: Dict[int, LevelResult] = {lvl: LevelResult(level=lvl) for lvl in levels}
        duel: Dict[int, LevelResult] = {lvl: LevelResult(level=lvl) for lvl in levels}
        action_gold = _ActionBreakdown()
        action_duel = _ActionBreakdown()
        base_rate = _LabelBaseRate()

        n_matches_used = 0
        n_matches_skipped = 0
        n_pairs_total = 0
        n_uncovered = 0
        n_covered = 0

        for mid in match_ids:
            try:
                pairs = extract_lane_pairs(conn, mid, gold_frame_min)
            except Exception:  # noqa: BLE001
                n_matches_skipped += 1
                continue
            if not pairs:
                n_matches_skipped += 1
                continue
            n_matches_used += 1
            n_pairs_total += len(pairs)
            for pair in pairs:
                try:
                    kc = extract_kill_counts(conn, mid, pair.pid_a, pair.pid_b)
                except Exception:  # noqa: BLE001
                    kc = {"solo": (0, 0), "any": (0, 0)}
                a_solo, b_solo = kc["solo"]
                for lvl in levels:
                    # Balance census, kept independent of the agreement tally so
                    # a 0.50 headline can be attributed to the verdict rather
                    # than to a degenerate predictor or a one-sided label.
                    _bv, _bs = verdict_fn(pair.champ_a, pair.champ_b, lvl)
                    _bfav = favored_side(_bv, _bs, even_band)
                    if _bfav is not None:
                        base_rate.record(_bfav, pair.gold_a, pair.gold_b)

                    g_status, g_agree, g_verdict = score_pair_gold(
                        pair, lvl, verdict_fn, even_band)
                    if g_status == "uncovered":
                        n_uncovered += 1
                    else:
                        n_covered += 1
                    _tally_gold(gold[lvl], g_status, g_agree, pair.lane)
                    if g_status == "decisive":
                        action_gold.record(g_verdict, g_agree)

                    d_status, d_agree, d_verdict = score_pair_duel(
                        pair, lvl, verdict_fn, a_solo, b_solo, even_band)
                    _tally_duel(duel[lvl], d_status, d_agree, pair.lane)
                    if d_status == "decisive":
                        action_duel.record(d_verdict, d_agree)
    finally:
        conn.close()

    covered_total = n_covered + n_uncovered
    return {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "db": str(db_path),
        "gate": "hz_a_laning_verdict",
        "surface": "core.precomputed_laning_coach (shipped artifact)",
        "gold_frame_min": gold_frame_min,
        "even_band": even_band,
        "limit": limit,
        "matches_selected": len(match_ids),
        "matches_used": n_matches_used,
        "matches_skipped": n_matches_skipped,
        "pairs_total": n_pairs_total,
        "coverage": {
            "covered": n_covered,
            "uncovered": n_uncovered,
            "covered_fraction": (n_covered / covered_total) if covered_total else None,
        },
        "levels_gold": [gold[lvl].to_dict() for lvl in levels],
        "levels_duel": [duel[lvl].to_dict() for lvl in levels],
        "action_breakdown_gold": action_gold.to_dict(),
        "action_breakdown_duel": action_duel.to_dict(),
        "label_base_rate_gold": base_rate.to_dict(),
        # DEEP copy: _DECISION carries a nested `traps` list, and a shallow
        # dict() would hand every report the SAME list object - one caller
        # appending to it poisons the module constant for every later report in
        # the process. The stamp is the retirement record; it must not be
        # mutable by accident.
        "decision": _copy.deepcopy(_DECISION),
        "interpretation": (
            "Gold + solo-kill duel are noisy lane-outcome proxies (ganks / roams "
            "/ missed-assist kills), so treat the agreement as an honest lower-"
            "fidelity signal, not a 1v1 oracle. The full/all_up baseline cell is "
            "scored because that is what the chip shows when live mana/ult are "
            "unknown. THIS IS NO LONGER A FLIP GATE (ADR-013): the flip was "
            "retired on 2026-08-06 after a held-out per-champion gold prior beat "
            "the shipped verdict on the identical label, so a number above 0.50 "
            "here is NOT authority to flip the laning coach off Haiku - it is "
            "grounds to re-open ADR-013 with a "
            "tools/laning_verdict_information_probe.py artifact attached. "
            "action_breakdown remains the most legible slice: when the chip says "
            "all_in/trade, how often the aggressor actually came out ahead."
        ),
    }


def _tally_gold(lr: LevelResult, status: str, agreed: bool, lane: str) -> None:
    if status == "uncovered" or status == "even":
        lr.n_even += 1
    elif status == "gold_tie":
        lr.n_gold_tie += 1
    elif status == "decisive":
        lr.record(lane, agreed)


def _tally_duel(lr: LevelResult, status: str, agreed: bool, lane: str) -> None:
    if status == "uncovered" or status == "even":
        lr.n_even += 1
    elif status == "no_duel":
        lr.n_no_duel += 1
    elif status == "kill_tie":
        lr.n_kill_tie += 1
    elif status == "decisive":
        lr.record(lane, agreed)


# ----------------------------------------------------------------------------- output
def _fmt_pct(x: Optional[float]) -> str:
    return "  n/a" if x is None else f"{x * 100:5.1f}%"


def print_summary(report: dict) -> None:
    """Concise human-readable summary on stdout (ASCII only)."""
    print("")
    print("=== Replay HZ-A laning-VERDICT validation (RETIRED gate - ADR-013) ===")
    dec = report.get("decision") or {}
    if dec.get("status"):
        print(f"  [{dec['status']} {dec.get('adr', '')} {dec.get('decided', '')}] "
              f"{dec.get('summary', '')}")
    cov = report["coverage"]
    print(
        f"db={report['db']}  gate={report['gate']}  even_band={report['even_band']}"
    )
    print(
        f"matches: selected={report['matches_selected']} used={report['matches_used']} "
        f"skipped={report['matches_skipped']}  pairs={report['pairs_total']}  "
        f"coverage={cov['covered']}/{cov['covered'] + cov['uncovered']}"
    )
    for label, key in (("GOLD@frame", "levels_gold"), ("SOLO-KILL DUEL", "levels_duel")):
        print("")
        print(f"  -- {label} --")
        print(f"  {'level':>5}  {'n':>6}  {'agree':>6}  {'95% Wilson':>16}")
        print("  " + "-" * 44)
        for lv in report[key]:
            ci = ""
            if lv["wilson_95_lo"] is not None:
                ci = f"[{lv['wilson_95_lo'] * 100:4.1f}, {lv['wilson_95_hi'] * 100:4.1f}]"
            print(
                f"  {lv['level']:>5}  {lv['n_decisive']:>6}  {_fmt_pct(lv['agreement'])}  "
                f"{ci:>16}"
            )
    for label, key in (("ACTION vs GOLD", "action_breakdown_gold"),
                       ("ACTION vs DUEL", "action_breakdown_duel")):
        print("")
        print(f"  -- {label} (per-verdict agreement) --")
        for verdict, slot in report[key].items():
            print(f"    {verdict:<9} n={slot['n']:>5}  agree={_fmt_pct(slot['agreement'])}")
    br = report.get("label_base_rate_gold") or {}
    if br.get("n"):
        print("")
        print("  -- BALANCE CENSUS (is 0.50 the verdict, or the harness?) --")
        print(f"    scored pairs          n={br['n']}")
        print(f"    predictor favors a    {_fmt_pct(br['predictor_favors_a_rate'])}")
        print(f"    label     favors a    {_fmt_pct(br['label_favors_a_rate'])}"
              f"  (n={br['label_decisive_n']}, ties={br['label_ties']})")
        print("    Both near 50% + agreement near 50% = zero mutual information,")
        print("    i.e. the VERDICT is uninformative (not a broken label).")
    for entry in report.get("axis_sweep") or []:
        print("")
        print(f"  -- AXIS SWEEP cd_state={entry['cd_state']} "
              f"item_state={entry['item_state']} --")
        for lv in entry["levels_gold"]:
            print(f"    gold L{lv['level']:<3} n={lv['n_decisive']:>6}  "
                  f"agree={_fmt_pct(lv['agreement'])}")
    print("")
    print("interpretation:")
    print("  " + report["interpretation"])
    print("")


# ----------------------------------------------------------------------------- loaders
def _load_table(mode: str):
    """Load the shipped HZ-A laning table for ``mode`` (lazy import)."""
    from core.precomputed_laning_coach import load_laning_scenarios

    return load_laning_scenarios(mode)


def _write_report(report: dict, out_path: Path) -> None:
    """Atomic JSON write of the gate artifact (ASCII-only)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    os.replace(str(tmp), str(out_path))


def _parse_levels(raw: str) -> List[int]:
    out: List[int] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            out.append(int(chunk))
        except ValueError:
            continue
    return out or list(_DEFAULT_LEVELS)


def build_arg_parser() -> argparse.ArgumentParser:
    """The CLI surface, split out so the flag defaults are directly testable -
    an accidentally-defaulted sweep flag would silently move the scored cell."""
    ap = argparse.ArgumentParser(
        description="Replay-validate the shipped HZ-A laning verdict (laning-coach Haiku-flip gate)."
    )
    ap.add_argument("--db", default=str(_DEFAULT_DB), help="Path to rewind_history.db")
    ap.add_argument("--mode", default="sr", help="Table mode (sr/aram/arena). Default %(default)s.")
    ap.add_argument("--limit", type=int, default=_DEFAULT_LIMIT,
                    help="Max SR matches to replay (0 = all). Default %(default)s.")
    ap.add_argument("--levels", default=",".join(str(x) for x in _DEFAULT_LEVELS),
                    help="Comma-separated replay levels. Default %(default)s.")
    ap.add_argument("--gold-frame", type=int, default=_DEFAULT_GOLD_FRAME_MIN,
                    help="Minute of the timeline frame used as lane-gold truth. Default %(default)s.")
    ap.add_argument("--even-band", type=float, default=_EVEN_BAND,
                    help="|net_swing| below this is excluded as even. Default %(default)s.")
    ap.add_argument("--out", default=str(_DEFAULT_OUT), help="Output JSON gate artifact path.")
    # Both default to None, NOT to the baseline state: an explicit None is how
    # main() tells "no sweep requested" from "sweep the baseline column", which
    # keeps an un-flagged run byte-comparable with the 2026-06 baseline.
    ap.add_argument("--cd-state", default=None,
                    help="Comma-separated cd_states to sweep (e.g. all_up,no_ult). "
                         "Absent = score only the all_up baseline, as before.")
    ap.add_argument("--item-state", default=None,
                    help="Comma-separated item_states to sweep (e.g. none,first_item). "
                         "Absent = score only the lookup default. No-op on v3 tables.")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: db not found: {db_path}", file=sys.stderr)
        return 2

    levels = _parse_levels(args.levels)
    print(f"Loading shipped HZ-A table (mode={args.mode})...", file=sys.stderr)
    table = _load_table(args.mode)
    verdict_fn = make_verdict_fn(table)

    report = run_validation(
        db_path=db_path, levels=levels, limit=args.limit,
        gold_frame_min=args.gold_frame, verdict_fn=verdict_fn, even_band=args.even_band,
    )

    if args.cd_state is not None or args.item_state is not None:
        combos = sweep_axis_combos(
            _parse_states(args.cd_state, _DEFAULT_CD_STATE),
            _parse_states(args.item_state, _DEFAULT_ITEM_STATE),
        )
        sweep = []
        for cd, item in combos:
            print(f"sweeping cd_state={cd} item_state={item}...", file=sys.stderr)
            sub = run_validation(
                db_path=db_path, levels=levels, limit=args.limit,
                gold_frame_min=args.gold_frame,
                verdict_fn=make_verdict_fn(table, cd_state=cd, item_state=item),
                even_band=args.even_band,
            )
            sweep.append({
                "cd_state": cd,
                "item_state": item,
                "mana_state": _DEFAULT_MANA_STATE,
                "coverage": sub["coverage"],
                "levels_gold": sub["levels_gold"],
                "levels_duel": sub["levels_duel"],
                "action_breakdown_gold": sub["action_breakdown_gold"],
                "label_base_rate_gold": sub["label_base_rate_gold"],
            })
        report["axis_sweep"] = sweep

    out_path = Path(args.out)
    _write_report(report, out_path)
    print_summary(report)
    print(f"gate artifact written: {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
