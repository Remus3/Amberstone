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
same coarse-state dedup.

The offer comes from OCR, so it is read defensively before anything is written:
offered / picked read only a list or tuple, each name is a stripped non-blank
string (anything else is dropped), and every scalar is written only when it is
JSON-safe (a non-finite score is written as null). A row with no offered name,
or whose deterministic block carries no ranked row, is not written.

Dedup is CONSECUTIVE per target: a row is skipped when its mode, champion,
offered SET and picked SET equal the last row written to that target in this
process. A, B, A writes three rows; a re-scan of the same panel in another
order writes none.

Rows are appended as LF-terminated ASCII bytes under one process lock, so
concurrent threads cannot interleave a row or both pass the dedup check. A torn
last line left by a crash mid-append is closed with a newline before the next
row, so it costs one row, not two. A failed write is logged once at WARNING per
target until a write to that target succeeds.

summarize_agreement() is the offline reader (the laning lane's hz_shadow_report
analog) - name-normalized top-1 agreement + the rank at which Haiku's take sits in
the deterministic ranking, so flip-readiness has a number once rows accrue. An
exact normalized name wins over a substring match (the augment table carries
names that contain other names, e.g. "Stats!" / "Stats on Stats!"), and a line
that does not decode or parse is skipped on its own.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("rc.augment_shadow")

# Default shadow path - project root is two levels above this file (core/).
_APP_DIR = Path(__file__).parent.parent
SHADOW_PATH: Path = _APP_DIR / "data" / "augment_shadow.jsonl"

# Per-target dedup. Keyed by str(target_path) so an explicit test path and the
# live default each dedup independently.
_LAST_SIG: dict[str, str] = {}
# Targets whose last write failed and has already been warned about.
_WARNED: set[str] = set()
# One lock for the dedup check, the append and both containers above: a Windows
# append is not atomic, and check-then-write must not interleave.
_LOCK = threading.Lock()

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


def _names(value: object) -> list[str]:
    """Stripped non-blank string entries of a list or tuple, in order. Any other
    container (a str would iterate by character) reads as empty."""
    if not isinstance(value, (list, tuple)):
        return []
    out = []
    for c in value:
        if isinstance(c, str) and c.strip():
            out.append(c.strip())
    return out


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _number(value: object) -> int | float | None:
    """A finite int or float, else None. bool is refused (it is an int)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _scalar(value: object) -> object:
    """A JSON-safe scalar (None, bool, str, finite number), else None."""
    if value is None or isinstance(value, (bool, str)):
        return value
    return _number(value)


def _ranked_rows(d: dict) -> list[dict]:
    reco = d.get("aug_reco")
    if not isinstance(reco, (list, tuple)):
        return []
    return [s for s in reco if isinstance(s, dict)]


def _native_fields(d) -> dict:
    d = d if isinstance(d, dict) else {}
    return {k: (_text(d.get(k)) or "") for k in _NATIVE_KEYS}


def _det_block(d) -> dict:
    """Compact the reco_fields dict (see arena_coach._augment_recommendation)
    into the recorded deterministic block. Keeps only the ranked id/name/score/
    conf so the row stays small but the agreement is recomputable."""
    d = d if isinstance(d, dict) else {}
    ranked = [
        {
            "id": _scalar(s.get("id")),
            "name": _text(s.get("name")),
            "score": _number(s.get("score")),
            "conf": _number(s.get("conf")),
        }
        for s in _ranked_rows(d)
    ]
    n_matches = d.get("aug_reco_n_matches")
    external = d.get("aug_reco_external")
    return {
        "top": _text(d.get("aug_reco_top")),
        "top_score": _number(d.get("aug_reco_top_score")),
        "conf": _number(d.get("aug_reco_conf")),
        "external": external if isinstance(external, bool) else None,
        "n_matches": _number(n_matches) if isinstance(n_matches, int) else None,
        "ranked": ranked,
    }


def _torn_tail(target: Path) -> bool:
    """True when the file exists, is non-empty and does not end in a newline."""
    try:
        with target.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            if fh.tell() == 0:
                return False
            fh.seek(-1, os.SEEK_END)
            return fh.read(1) != b"\n"
    except FileNotFoundError:
        return False


def _append_row(target: Path, line: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    lead = b"\n" if _torn_tail(target) else b""
    with target.open("ab") as fh:
        fh.write(lead + line + b"\n")


def _note_failure(path: object, exc: BaseException) -> None:
    """WARNING on the first failure per target, DEBUG after. Never raises."""
    try:
        tkey = str(path if path is not None else SHADOW_PATH)
        with _LOCK:
            first = tkey not in _WARNED
            _WARNED.add(tkey)
        if first:
            log.warning("augment shadow write to %s failed: %s",
                        tkey, type(exc).__name__, exc_info=True)
        else:
            log.debug("augment_shadow.log_augment_advice failed", exc_info=True)
    except Exception:  # noqa: BLE001 - logging must not break the coach path
        pass


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
    augment name, or no ranked deterministic row to validate against), a dedup
    skip, or any failure (fail-soft). Never raises - safe on the live coach
    path."""
    try:
        if not isinstance(state, dict):
            return None
        offered = _names(state.get("offered"))
        if not offered:
            return None
        det = deterministic if isinstance(deterministic, dict) else {}
        if not _ranked_rows(det):
            return None
        picked = _names(state.get("picked"))
        mode = _text(state.get("mode"))
        champion = _text(state.get("champion"))

        target = path if path is not None else SHADOW_PATH
        tkey = str(target)
        sig = str((mode or "", champion or "",
                   tuple(sorted(offered)), tuple(sorted(picked))))

        try:
            from agents.daemon_slayer import ENGINE_VERSION  # noqa: PLC0415
        except Exception:  # noqa: BLE001 - the stamp is optional, the row is not
            ENGINE_VERSION = "?"  # type: ignore[assignment]

        ts = now_iso if now_iso is not None else datetime.now(timezone.utc).isoformat()

        record: dict = {
            "ts": ts,
            "mode": mode,
            "champion": champion,
            "round": _scalar(state.get("round")),
            "stage": _scalar(state.get("stage")),
            "offered": offered,
            "picked": picked,
            "engine_version": ENGINE_VERSION,
            "native": _native_fields(native),
            "deterministic": _det_block(det),
        }

        with _LOCK:
            if _LAST_SIG.get(tkey) == sig:
                return None
            # ensure_ascii (the default) keeps the row 7-bit; allow_nan=False
            # refuses a non-JSON token rather than writing one.
            line = json.dumps(record, allow_nan=False).encode("ascii")
            _append_row(target, line)
            _LAST_SIG[tkey] = sig
            _WARNED.discard(tkey)
        return record

    except Exception as exc:  # noqa: BLE001 - fail-soft on the live coach path
        _note_failure(path, exc)
        return None


def _take_rank(native_take: str, ranked: list) -> int | None:
    """1-based rank of the native take inside the deterministic ranking, or
    None when the take does not match any offered/ranked augment.

    An exact normalized name anywhere in the ranking wins; only then does the
    substring tolerance apply, and among substring matches the longest (most
    specific) name wins, the earlier rank breaking a tie."""
    nt = _norm(native_take) if isinstance(native_take, str) else ""
    if not nt or not isinstance(ranked, (list, tuple)):
        return None
    names = [(i + 1, _norm(row.get("name")))
             for i, row in enumerate(ranked) if isinstance(row, dict)]
    for rank, nm in names:
        if nm == nt:
            return rank
    best: tuple[int, int] | None = None
    for rank, nm in names:
        if _names_match(nt, nm) and (best is None or len(nm) > best[1]):
            best = (rank, len(nm))
    return best[0] if best is not None else None


def _read_rows(p: Path) -> list:
    """Every line of the jsonl that decodes as UTF-8 and parses as JSON; any
    other line is skipped on its own. Accepts LF and CRLF line ends."""
    rows = []
    for raw in p.read_bytes().split(b"\n"):
        if not raw.strip():
            continue
        try:
            rows.append(json.loads(raw.decode("utf-8")))
        except ValueError:  # JSONDecodeError and UnicodeDecodeError
            continue
    return rows


def summarize_agreement(rows_or_path) -> dict:
    """Offline det-vs-Haiku agreement over augment-select shadow rows.

    Accepts a list of record dicts OR a Path/str to the jsonl. Returns counts:
      n                  - rows considered
      n_with_native_take - rows where Haiku named a take (a non-blank string)
      top1_agree         - rows where Haiku's take == the deterministic top pick
      top1_agree_pct     - top1_agree / n_with_native_take * 100 (0.0 when none)
      take_rank_dist     - {"1": .., "2": .., "none": ..} rank of Haiku's take in
                           the deterministic ranking
    Never raises - skips malformed rows and lines."""
    rows: list = []
    try:
        if isinstance(rows_or_path, (str, Path)):
            p = Path(rows_or_path)
            if p.exists():
                rows = _read_rows(p)
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
        ranked = det.get("ranked")
        if not isinstance(take, str) or not take.strip():
            continue
        n_with_take += 1
        rank = _take_rank(take, ranked if isinstance(ranked, list) else [])
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
