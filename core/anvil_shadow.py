# arch: arena item-anvil shadow writer | section=core | frozen=no
"""core/anvil_shadow.py - fail-soft arena item-anvil shadow writer + report.

The do-not-flip-blind validation substrate for the Tier-1 arena item-anvil Haiku
call (coaches/arena_coach.py purpose="arena_anvil"). The live coach still answers
via Haiku; the deterministic core.precomputed_anvil_advisor ranks the offered
anvil choices against the rule-based ideal build path, but the pair is never
recorded for offline det-vs-Haiku agreement analysis, so the anvil flip accrues
zero validation data. This module appends one JSON line per distinct anvil-offer
state capturing BOTH surfaces (the Haiku take AND the deterministic ranking), so
the precompute path can be validated against real games offline before any flip
- WITHOUT changing any live output.

Direct sibling of core.augment_shadow: same fail-soft contract (never raises),
same default-path-under-data layout, same engine-version stamp, same coarse-state
dedup. The anvil panel is shown once per anvil event, so the dedup keys on the
offered + already-owned set to write at most one record per distinct offer.

Unlike the augment writer, a low-conf substrate result (no offered item on the
ideal path) is NOT gated out: a no-match row is a real validation signal worth
recording. Only a missing offer or a non-dict deterministic block gates the write.

summarize_agreement() is the offline reader - name-normalized top-1 agreement of
the Haiku take vs the substrate take, plus the rank at which the Haiku take sits
in the substrate ranking, so flip-readiness has a number once rows accrue.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("rc.anvil_shadow")

# Default shadow path - project root is two levels above this file (core/).
_APP_DIR = Path(__file__).parent.parent
SHADOW_PATH: Path = _APP_DIR / "data" / "anvil_shadow.jsonl"

# Per-target dedup. Keyed by str(target_path) so an explicit test path and the
# live default each dedup independently.
_LAST_SIG: dict[str, str] = {}

_NATIVE_KEYS = ("take", "why")
_DET_KEYS = ("take", "take_rank", "n_matches", "conf", "ranked")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _norm(name: object) -> str:
    return _NON_ALNUM.sub("", str(name or "").lower())


def _names_match(a: str, b: str) -> bool:
    # Equal-or-substring tolerates display variants without id resolution.
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _sig(state: dict) -> str:
    return str((
        str(state.get("mode") or ""),
        str(state.get("champion") or ""),
        tuple(str(c) for c in (state.get("offered") or []) if c),
        tuple(sorted(str(c) for c in (state.get("owned") or []) if c)),
    ))


def _native_fields(d) -> dict:
    d = d if isinstance(d, dict) else {}
    return {k: d.get(k, "") for k in _NATIVE_KEYS}


def _det_block(d) -> dict:
    """Compact the compute_anvil_pick dict into the recorded deterministic
    block. Keeps take / take_rank / n_matches / conf and the per-choice ranked
    list so the row stays small but the agreement stays recomputable."""
    d = d if isinstance(d, dict) else {}
    ranked = []
    for s in (d.get("ranked") or []):
        if not isinstance(s, dict):
            continue
        ranked.append({
            "name": s.get("name"),
            "rank": s.get("rank"),
            "in_ideal_path": s.get("in_ideal_path"),
        })
    block = {k: d.get(k) for k in _DET_KEYS if k != "ranked"}
    block["ranked"] = ranked
    return block


def log_anvil_advice(
    state: dict,
    native,
    deterministic,
    *,
    path: Path | None = None,
    now_iso: str | None = None,
) -> dict | None:
    """Append one anvil validation record (native Haiku take vs the
    deterministic precomputed_anvil_advisor ranking) to the shadow jsonl.

    Returns the record dict on a fresh write, None on a gate miss (no offered
    anvil items, or a non-dict deterministic block), a dedup skip, or any
    failure (fail-soft). Never raises - safe on the live coach path."""
    try:
        if not isinstance(state, dict):
            return None
        offered = [c for c in (state.get("offered") or []) if c]
        if not offered:
            return None
        if not isinstance(deterministic, dict):
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
            "offered": offered,
            "owned": [c for c in (state.get("owned") or []) if c],
            "engine_version": ENGINE_VERSION,
            "native": _native_fields(native),
            "deterministic": _det_block(deterministic),
        }

        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        _LAST_SIG[tkey] = sig
        return record

    except Exception:  # noqa: BLE001
        log.debug("anvil_shadow.log_anvil_advice failed", exc_info=True)
        return None


def _take_rank(native_take: str, ranked: list) -> int | None:
    """1-based rank of the native take inside the substrate ranking, or None
    when the take does not match any offered/ranked item."""
    nt = _norm(native_take)
    if not nt:
        return None
    for row in ranked:
        if not isinstance(row, dict):
            continue
        if _names_match(nt, _norm(row.get("name"))):
            r = row.get("rank")
            return r if isinstance(r, int) else None
    return None


def summarize_agreement(rows_or_path) -> dict:
    """Offline det-vs-Haiku agreement over anvil shadow rows.

    Accepts a list of record dicts OR a Path/str to the jsonl. Returns counts:
      n                  - rows considered
      n_with_native_take - rows where Haiku named a take
      top1_agree         - rows where Haiku's take == the substrate take
      top1_agree_pct     - top1_agree / n_with_native_take * 100 (0.0 when none)
      take_rank_dist     - {"1": .., "3": .., "none": ..} rank of Haiku's take in
                           the substrate ranking
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
        native = r.get("native") if isinstance(r.get("native"), dict) else {}
        take = native.get("take")
        det = r.get("deterministic") if isinstance(r.get("deterministic"), dict) else {}
        ranked = det.get("ranked") or []
        det_take = det.get("take")
        if not take:
            continue
        n_with_take += 1
        rank = _take_rank(take, ranked)
        key = str(rank) if rank is not None else "none"
        rank_dist[key] = rank_dist.get(key, 0) + 1
        if det_take and _names_match(_norm(take), _norm(det_take)):
            top1 += 1

    pct = round(top1 / n_with_take * 100, 1) if n_with_take else 0.0
    return {
        "n": n,
        "n_with_native_take": n_with_take,
        "top1_agree": top1,
        "top1_agree_pct": pct,
        "take_rank_dist": rank_dist,
    }
