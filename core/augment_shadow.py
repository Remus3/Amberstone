# arch: arena augment-select shadow writer | section=core | frozen=no
"""core/augment_shadow.py - fail-soft arena augment-select shadow writer + report.

The do-not-flip-blind validation substrate for the Tier-1 arena augment-select
Haiku call (coaches/arena_coach.py purpose="arena_aug_select"). The live coach
still answers via Haiku; the deterministic core.augment_recommender ALREADY runs
in parallel (S5 design) and is persisted alongside Haiku's pick, but the pair is
never recorded for offline det-vs-Haiku agreement analysis, so the augment-select
flip accrues zero validation data. This module appends one JSON line per distinct
augment-offer state capturing BOTH surfaces (the Haiku take AND the deterministic
ranking), so the precompute path can be validated against real games offline
before any flip - WITHOUT changing any live output.

Mirrors core.champ_select_shadow / core.hz_choice_shadow: same fail-soft contract
(never raises), same default-path-under-data layout, same engine-version stamp,
same coarse-state dedup. The augment panel is shown once per augment round, so the
dedup keys on the offered + already-picked set to write at most one record per
distinct offer situation.

summarize_agreement() is the offline reader (the laning lane's hz_shadow_report
analog) - name-normalized top-1 agreement + the rank at which Haiku's take sits in
the deterministic ranking, so flip-readiness has a number once rows accrue.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("rc.augment_shadow")

# Default shadow path - project root is two levels above this file (core/).
_APP_DIR = Path(__file__).parent.parent
SHADOW_PATH: Path = _APP_DIR / "data" / "augment_shadow.jsonl"

# Per-target dedup. Keyed by str(target_path) so an explicit test path and the
# live default each dedup independently.
_LAST_SIG: dict[str, str] = {}

_NATIVE_KEYS = ("take", "why", "plan")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _norm(name: object) -> str:
    """Normalize an augment display name for cross-surface matching: lower-case,
    strip every non-alphanumeric byte. 'Blade  Waltz!' -> 'bladewaltz'."""
    return _NON_ALNUM.sub("", str(name or "").lower())


def _names_match(a: str, b: str) -> bool:
    """Equal-or-substring on normalized names - tolerates display variants
    ('Blade Waltz' vs 'Blade Waltz (Prismatic)') without an id-resolution dep."""
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _sig(state: dict) -> str:
    return str((
        str(state.get("mode") or ""),
        str(state.get("champion") or ""),
        tuple(str(c) for c in (state.get("offered") or []) if c),
        tuple(sorted(str(c) for c in (state.get("picked") or []) if c)),
    ))


def _native_fields(d) -> dict:
    d = d if isinstance(d, dict) else {}
    return {k: d.get(k, "") for k in _NATIVE_KEYS}


def _det_block(d) -> dict:
    """Compact the reco_fields dict (see arena_coach._augment_recommendation)
    into the recorded deterministic block. Keeps only the ranked id/name/score/
    conf so the row stays small but the agreement is recomputable."""
    d = d if isinstance(d, dict) else {}
    ranked = []
    for s in (d.get("aug_reco") or []):
        if not isinstance(s, dict):
            continue
        ranked.append({
            "id": s.get("id"),
            "name": s.get("name"),
            "score": s.get("score"),
            "conf": s.get("conf"),
        })
    return {
        "top": d.get("aug_reco_top"),
        "top_score": d.get("aug_reco_top_score"),
        "conf": d.get("aug_reco_conf"),
        "external": d.get("aug_reco_external"),
        "n_matches": d.get("aug_reco_n_matches"),
        "ranked": ranked,
    }


def log_augment_advice(
    state: dict,
    native,
    deterministic,
    *,
    path: Path | None = None,
    now_iso: str | None = None,
) -> dict | None:
    """Append one augment-select validation record (native Haiku take vs the
    deterministic augment_recommender ranking) to the shadow jsonl.

    Returns the record dict on a fresh write, None on a gate miss (no offered
    augments, or no deterministic ranking to validate against), a dedup skip,
    or any failure (fail-soft). Never raises - safe on the live coach path."""
    try:
        if not isinstance(state, dict):
            return None
        offered = [c for c in (state.get("offered") or []) if c]
        if not offered:
            return None
        det = deterministic if isinstance(deterministic, dict) else {}
        if not (det.get("aug_reco") or []):
            return None

        target = path if path is not None else SHADOW_PATH
        tkey = str(target)
        sig = _sig(state)
        if _LAST_SIG.get(tkey) == sig:
            return None

        try:
            from agents.daemon_slayer import ENGINE_VERSION  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            ENGINE_VERSION = "?"  # type: ignore[assignment]

        ts = now_iso if now_iso is not None else datetime.now(timezone.utc).isoformat()

        record: dict = {
            "ts": ts,
            "mode": state.get("mode"),
            "champion": state.get("champion"),
            "round": state.get("round"),
            "stage": state.get("stage"),
            "offered": offered,
            "picked": [c for c in (state.get("picked") or []) if c],
            "engine_version": ENGINE_VERSION,
            "native": _native_fields(native),
            "deterministic": _det_block(det),
        }

        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        _LAST_SIG[tkey] = sig
        return record

    except Exception:  # noqa: BLE001
        log.debug("augment_shadow.log_augment_advice failed", exc_info=True)
        return None


def _take_rank(native_take: str, ranked: list) -> int | None:
    """1-based rank of the native take inside the deterministic ranking, or
    None when the take does not match any offered/ranked augment."""
    nt = _norm(native_take)
    if not nt:
        return None
    for i, row in enumerate(ranked):
        if not isinstance(row, dict):
            continue
        if _names_match(nt, _norm(row.get("name"))):
            return i + 1
    return None


def summarize_agreement(rows_or_path) -> dict:
    """Offline det-vs-Haiku agreement over augment-select shadow rows.

    Accepts a list of record dicts OR a Path/str to the jsonl. Returns counts:
      n                  - rows considered
      n_with_native_take - rows where Haiku named a take
      top1_agree         - rows where Haiku's take == the deterministic top pick
      top1_agree_pct     - top1_agree / n_with_native_take * 100 (0.0 when none)
      take_rank_dist     - {"1": .., "2": .., "none": ..} rank of Haiku's take in
                           the deterministic ranking
    Never raises - skips malformed rows."""
    rows: list = []
    try:
        if isinstance(rows_or_path, (str, Path)):
            p = Path(rows_or_path)
            if p.exists():
                rows = [
                    json.loads(ln)
                    for ln in p.read_text(encoding="utf-8").splitlines()
                    if ln.strip()
                ]
        elif rows_or_path:
            rows = list(rows_or_path)
    except Exception:  # noqa: BLE001
        rows = []

    n = 0
    n_with_take = 0
    top1 = 0
    rank_dist: dict[str, int] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        n += 1
        take = (r.get("native") or {}).get("take") if isinstance(r.get("native"), dict) else None
        det = r.get("deterministic") if isinstance(r.get("deterministic"), dict) else {}
        ranked = det.get("ranked") or []
        if not take:
            continue
        n_with_take += 1
        rank = _take_rank(take, ranked)
        key = str(rank) if rank is not None else "none"
        rank_dist[key] = rank_dist.get(key, 0) + 1
        if rank == 1:
            top1 += 1

    pct = round(top1 / n_with_take * 100, 1) if n_with_take else 0.0
    return {
        "n": n,
        "n_with_native_take": n_with_take,
        "top1_agree": top1,
        "top1_agree_pct": pct,
        "take_rank_dist": rank_dist,
    }
