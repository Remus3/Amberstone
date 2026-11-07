# arch: champ-select pick-advisor shadow writer | section=core | frozen=no
"""core/champ_select_shadow.py - fail-soft champ-select pick-advisor shadow writer.

The do-not-flip-blind validation substrate for the Tier-2 champ-select
pick-advisor (the last champ-select Haiku call, coaches/champ_select_coach).
The live coach still answers via Haiku; this records, alongside that live
output, what the DETERMINISTIC advisor (core.champ_select_advisor_deterministic)
WOULD have offered for the same pick state, so the precompute path can be
validated against real games offline before any flip - WITHOUT changing any
live output.

Mirrors core.hz_choice_shadow / core.det_coach_shadow: same fail-soft contract
(never raises), same default-path-under-data layout, same engine-version stamp,
same coarse-state dedup.

The pick state is an HTTP POST body (dashboard/routes_coach.py forwards it
verbatim), so it is read with coach_pick's OWN rules before anything is
written: a champion coach_pick refuses writes no row, a list field reads only
a list or tuple of at most coach_pick's entry cap, every name is the sanitised
name the prompt carried, is_aram means what coach_pick took it to mean, and
queue_id is a plain integer or null. A row therefore describes the request
Haiku actually answered.

Dedup is CONSECUTIVE per target: a row is skipped when its pick state, and
whether the native reply carried advice, equal the last row written to that
target in this process. A, B, A writes three rows. A degraded native reply
("(coaching paused - retrying)") therefore never takes the slot of the real
reply for the same state.

Rows are appended as LF-terminated ASCII bytes under one process lock, so
concurrent handler threads cannot interleave a row or both pass the dedup
check. A torn last line left by a crash mid-append is closed with a newline
before the next row, so it costs one row, not two. A failed write is logged
once at WARNING per target until a write to that target succeeds.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("rc.champ_select_shadow")

# Default shadow path - project root is two levels above this file (core/).
_APP_DIR = Path(__file__).parent.parent
SHADOW_PATH: Path = _APP_DIR / "data" / "champ_select_shadow.jsonl"

# Per-target dedup. Keyed by str(target_path) so an explicit test path and the
# live default each dedup independently.
_LAST_SIG: dict[str, str] = {}
# Targets whose last write failed and has already been warned about.
_WARNED: set[str] = set()
# One lock for the dedup check, the append and both dicts above: the route runs
# on ThreadingHTTPServer handler threads, and a Windows append is not atomic.
_LOCK = threading.Lock()

_ADVICE_KEYS = ("advice", "swap", "summoners", "watchout")
# Riot queue ids are small non-negative integers (0 = custom / Practice Tool).
_QUEUE_ID_MAX = 2 ** 31 - 1


def _queue_id(value: object) -> int | None:
    """A plain in-range integer, else None. bool is refused (it is an int), and
    so is a float: NaN or Infinity would write a token strict JSON rejects."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= _QUEUE_ID_MAX else None


def _is_aram(state: dict, queue_id: int | None) -> bool:
    """ARAM exactly as coach_pick decides it: a real boolean true, or a queue
    that maps to the ARAM mode key."""
    if state.get("is_aram") is True:
        return True
    if queue_id is None:
        return False
    from core.queue_modes import mode_key_from_queue_id  # noqa: PLC0415
    return mode_key_from_queue_id(queue_id) == "aram"


def _advice_fields(d: object) -> dict:
    d = d if isinstance(d, dict) else {}
    out = {}
    for k in _ADVICE_KEYS:
        v = d.get(k, "")
        out[k] = v if isinstance(v, str) else ""
    return out


def _native_ok(native: object) -> bool:
    return isinstance(native, dict) and native.get("ok") is True


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


def log_champ_select_advice(
    state: dict,
    native,
    deterministic,
    *,
    path: Path | None = None,
    now_iso: str | None = None,
) -> dict | None:
    """Append one champ-select validation record (native Haiku advice vs the
    deterministic advisor) to the shadow jsonl.

    Returns the record dict on a fresh write, None on a gate miss (a pick state
    whose champion coach_pick refuses), a dedup skip, or any failure
    (fail-soft). Never raises - safe on the route path."""
    target = path if path is not None else SHADOW_PATH
    tkey = str(target)
    try:
        if not isinstance(state, dict):
            return None
        # coach_pick's own name rules (sanitised, length-capped, entry-capped),
        # so the shadow gate and the coach gate cannot disagree. Imported lazily:
        # the route already loaded the coach, and core must not import it at
        # module load.
        from coaches.champ_select_coach import _name, _names  # noqa: PLC0415

        my_champion = _name(state.get("my_champion"))
        if not my_champion:
            return None
        queue_id = _queue_id(state.get("queue_id"))
        is_aram = _is_aram(state, queue_id)
        my_team = _names(state.get("my_team"))
        their_team = _names(state.get("their_team"))
        bench = _names(state.get("bench"))
        sig = str((
            is_aram, queue_id, my_champion,
            tuple(sorted(my_team)), tuple(sorted(their_team)), tuple(sorted(bench)),
            _native_ok(native),
        ))

        try:
            from agents.daemon_slayer import ENGINE_VERSION  # noqa: PLC0415
        except Exception:  # noqa: BLE001 - the stamp is optional, the row is not
            ENGINE_VERSION = "?"  # type: ignore[assignment]

        ts = now_iso if now_iso is not None else datetime.now(timezone.utc).isoformat()
        record: dict = {
            "ts": ts,
            "is_aram": is_aram,
            "queue_id": queue_id,
            "my_champion": my_champion,
            "my_team": my_team,
            "their_team": their_team,
            "bench": bench,
            "engine_version": ENGINE_VERSION,
            "native": _advice_fields(native),
            "deterministic": _advice_fields(deterministic),
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

    except Exception as exc:  # fail-soft on the route path
        with _LOCK:
            first = tkey not in _WARNED
            _WARNED.add(tkey)
        if first:
            log.warning("champ-select shadow write to %s failed: %s",
                        tkey, type(exc).__name__, exc_info=True)
        else:
            log.debug("champ_select_shadow.log_champ_select_advice failed", exc_info=True)
        return None
