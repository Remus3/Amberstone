# arch: arena item-anvil shadow writer | section=core | frozen=no
"""core/anvil_shadow.py - fail-soft arena item-anvil shadow writer + report.

The do-not-flip-blind validation substrate for the Tier-1 arena item-anvil Haiku
call (coaches/arena_coach.py purpose="arena_anvil"). The live coach still answers
via Haiku; the deterministic core.precomputed_anvil_advisor ranks the offered
anvil choices against the rule-based ideal build path, but the pair is never
recorded for offline det-vs-Haiku agreement analysis, so the anvil flip accrues
zero validation data. This module appends one JSON line per new anvil-offer
state capturing BOTH surfaces (the Haiku take AND the deterministic ranking), so
the precompute path can be validated against real games offline before any flip
- WITHOUT changing any live output.

Direct sibling of core.augment_shadow: same fail-soft contract (never raises),
same default-path-under-data layout, same engine-version stamp, same row
discipline. Dedup is CONSECUTIVE per target: a row is skipped when its mode,
champion, offered SET and owned SET equal the last row written to that target
in this process (A, B, A writes three rows; a re-scan in another order writes
none).

Unlike the augment writer, a low-conf substrate result (no offered item on the
ideal path) is NOT gated out: a no-match row is a real validation signal. Only a
missing or injection-probe offer (RM-867) or a non-dict det block gates the write.

The offer comes from OCR, so offered / owned read only a list or tuple of
stripped non-blank strings, and every other field is written only when it is
JSON-safe (anything else, a non-finite number included, is written as null).
Rows are LF-terminated ASCII bytes appended under one process lock; a torn last
line is closed with a newline before the next row; a failed write is logged
once at WARNING per target until a write to that target succeeds.

summarize_agreement() is the offline reader - name-normalized top-1 agreement of
the Haiku take vs the substrate take, plus the ideal-path rank of the offered
item the Haiku take names, so flip-readiness has a number once rows accrue. An
exact normalized name wins over a substring match ("Boots" / "Boots of
Swiftness"), and a line that does not decode or parse is skipped on its own.
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

log = logging.getLogger("rc.anvil_shadow")

# Default shadow path - project root is two levels above this file (core/).
_APP_DIR = Path(__file__).parent.parent
SHADOW_PATH: Path = _APP_DIR / "data" / "anvil_shadow.jsonl"

# Per-target dedup. Keyed by str(target_path) so an explicit test path and the
# live default each dedup independently.
_LAST_SIG: dict[str, str] = {}
# Targets whose last write failed and has already been warned about.
_WARNED: set[str] = set()
# One lock for the dedup check, the append and both containers above: a Windows
# append is not atomic, and check-then-write must not interleave.
_LOCK = threading.Lock()

_NATIVE_KEYS = ("take", "why")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _norm(name: object) -> str:
    return _NON_ALNUM.sub("", str(name or "").lower())


def _names_match(a: str, b: str) -> bool:
    # Equal-or-substring tolerates display variants without id resolution.
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _names(value: object) -> list[str]:
    """Stripped non-blank string entries of a list or tuple, in order. Any other
    container (a str would iterate by character) reads as empty."""
    if not isinstance(value, (list, tuple)):
        return []
    return [c.strip() for c in value if isinstance(c, str) and c.strip()]


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _int(value: object) -> int | None:
    """An int that is not a bool, else None."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _scalar(value: object) -> object:
    """A JSON-safe scalar (None, bool, str, int, finite float), else None."""
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return None


def _native_fields(d) -> dict:
    d = d if isinstance(d, dict) else {}
    return {k: (_text(d.get(k)) or "") for k in _NATIVE_KEYS}


def _det_block(d) -> dict:
    """Compact the compute_anvil_pick dict into the recorded deterministic
    block. Keeps take / take_rank / n_matches / conf and the per-choice ranked
    list so the row stays small but the agreement stays recomputable."""
    d = d if isinstance(d, dict) else {}
    reco = d.get("ranked")
    ranked = []
    for s in (reco if isinstance(reco, (list, tuple)) else ()):
        if not isinstance(s, dict):
            continue
        in_path = s.get("in_ideal_path")
        ranked.append({
            "name": _text(s.get("name")),
            "rank": _int(s.get("rank")),
            "in_ideal_path": in_path if isinstance(in_path, bool) else None,
        })
    return {
        "take": _text(d.get("take")),
        "take_rank": _int(d.get("take_rank")),
        "n_matches": _int(d.get("n_matches")),
        "conf": _text(d.get("conf")),
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
            log.warning("anvil shadow write to %s failed: %s",
                        tkey, type(exc).__name__, exc_info=True)
        else:
            log.debug("anvil_shadow.log_anvil_advice failed", exc_info=True)
    except Exception:  # noqa: BLE001 - logging must not break the coach path
        pass


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
    anvil name, an offer naming a prompt-injection payload - RM-867 - or a
    non-dict deterministic block), a dedup skip, or any failure (fail-soft).
    Never raises - safe on the live coach path."""
    try:
        if not isinstance(state, dict):
            return None
        offered = _names(state.get("offered"))
        if not offered:
            return None
        # RM-867: refuse, not tag - a tag makes every reader learn a flag
        # (the RM-852 decision). Checked before the dedup, so a refused probe
        # records no signature.
        if offer_is_injection_probe(offered):
            return None
        if not isinstance(deterministic, dict):
            return None
        owned = _names(state.get("owned"))
        mode = _text(state.get("mode"))
        champion = _text(state.get("champion"))

        target = path if path is not None else SHADOW_PATH
        tkey = str(target)
        sig = str((mode or "", champion or "",
                   tuple(sorted(set(offered))), tuple(sorted(set(owned)))))

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
            "offered": offered,
            "owned": owned,
            "engine_version": ENGINE_VERSION,
            "native": _native_fields(native),
            "deterministic": _det_block(deterministic),
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


# RM-867: the instruction-override phrase, a narrow local copy of the
# core.prompt_sanitize override pattern (copied, not imported: sharing private
# names couples two fail-soft modules - the core/precomputed_anvil_advisor.py
# precedent). Only the override sentence: a bare newline in an OCR'd card name
# is a plausible two-line wrap, not a probe, so it does not match.
# tests/test_anvil_shadow_injection_probe_rm867.py pins that everything this
# flags is also neutralised by prompt_sanitize.clean.
_INJECTION_PROBE = re.compile(
    r"(?i)\b(?:ignore|disregard)\b[\s\S]{0,48}?\b(?:previous|above|prior)\b"
    r"[\s\S]{0,24}?\binstructions?\b"
)


def offer_is_injection_probe(offered) -> bool:
    """True when any offered name carries an instruction-override phrase.

    A real anvil card is an item name; an offer like the RM-364 probe
    ("SENTA\\nSENTB Ignore previous instructions ...") is test input or an
    attack, never a game state worth recording. All 30 rows of the live
    data/anvil_shadow.jsonl were that probe, written by
    tests/test_rm364_prompt_sanitizer_population.py before RM-406 redirected
    this module's SHADOW_PATH in the suite. The writer refuses such an offer
    and summarize_agreement excludes and counts it. False for a non-list or
    an empty offer. Never raises."""
    try:
        if not isinstance(offered, (list, tuple)):
            return False
        return any(
            isinstance(c, str) and _INJECTION_PROBE.search(c) is not None
            for c in offered
        )
    except Exception:  # noqa: BLE001
        return False


def _match_row(native_take: str, ranked: object) -> dict | None:
    """The ranked row the native take names, or None.

    An exact normalized name anywhere in the ranking wins; only then does the
    substring tolerance apply, and among substring matches the longest (most
    specific) name wins, the earlier row breaking a tie."""
    nt = _norm(native_take) if isinstance(native_take, str) else ""
    if not nt or not isinstance(ranked, (list, tuple)):
        return None
    rows = [(row, _norm(row.get("name"))) for row in ranked if isinstance(row, dict)]
    for row, nm in rows:
        if nm == nt:
            return row
    best: tuple[dict, int] | None = None
    for row, nm in rows:
        if _names_match(nt, nm) and (best is None or len(nm) > best[1]):
            best = (row, len(nm))
    return best[0] if best is not None else None


def _take_rank(native_take: str, ranked: object) -> int | None:
    """Ideal-path rank of the offered item the native take names, or None when
    the take names no ranked item or that item is off the ideal path."""
    row = _match_row(native_take, ranked)
    return _int(row.get("rank")) if row is not None else None


def _top1(native_take: str, det_take: object, ranked: object) -> bool:
    """True when the native take names the substrate take. With a ranking the
    take is first resolved to its ranked row, so a take that is a substring of
    the substrate take ("Boots" vs "Boots of Swiftness") only agrees when no
    better-matching row exists; without one the names are compared directly."""
    dt = _norm(det_take) if isinstance(det_take, str) else ""
    if not dt:
        return False
    row = _match_row(native_take, ranked)
    if row is not None:
        return _norm(row.get("name")) == dt
    has_rows = isinstance(ranked, (list, tuple)) and any(
        isinstance(r, dict) and _norm(r.get("name")) for r in ranked)
    return not has_rows and _names_match(_norm(native_take), dt)


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
    """Offline det-vs-Haiku agreement over anvil shadow rows.

    Accepts a list of record dicts OR a Path/str to the jsonl. Returns counts:
      n                  - rows considered
      n_with_native_take - rows where Haiku named a take (a non-blank string)
      top1_agree         - rows where Haiku's take names the substrate take
      top1_agree_pct     - top1_agree / n_with_native_take * 100 (0.0 when none)
      take_rank_dist     - {"1": .., "3": .., "none": ..} ideal-path rank of the
                           offered item Haiku's take names
      injection_probe_excluded - rows skipped because their offer names a
                           prompt-injection payload (RM-867); not in n or any
                           rate. A row without an "offered" key is counted as
                           before (the writer always records it).
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
    excluded = 0
    rank_dist: dict[str, int] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        if offer_is_injection_probe(r.get("offered")):
            excluded += 1
            continue
        n += 1
        native = r.get("native") if isinstance(r.get("native"), dict) else {}
        take = native.get("take")
        det = r.get("deterministic") if isinstance(r.get("deterministic"), dict) else {}
        ranked = det.get("ranked")
        if not isinstance(take, str) or not take.strip():
            continue
        n_with_take += 1
        rank = _take_rank(take, ranked)
        key = str(rank) if rank is not None else "none"
        rank_dist[key] = rank_dist.get(key, 0) + 1
        if _top1(take, det.get("take"), ranked):
            top1 += 1

    pct = round(top1 / n_with_take * 100, 1) if n_with_take else 0.0
    return {
        "n": n,
        "n_with_native_take": n_with_take,
        "top1_agree": top1,
        "top1_agree_pct": pct,
        "take_rank_dist": rank_dist,
        "injection_probe_excluded": excluded,
    }
