# arch: GET /api/moon-sync-status - read-only moon_sync poller liveness | section=dashboard | frozen=no
"""GET /api/moon-sync-status - is the cross-repo moon_sync poller still alive?

A thin, additive, READ-ONLY reader over the poller's own ``status.md``. It adds
zero pixels: there is no panel and no UI fixture ritual, only JSON, so the
answer is one browser tab or one curl away from any machine that can reach
``https://legion-rc:8888``.

WHY A DUPLICATE OF THE POLLER'S RULE LIVES HERE. ``status_verdict`` below is a
deliberate second copy of the poller's own grading rule, not an oversight. The
two ship as independent slices and neither imports the other at module scope -
the dashboard must not grow an import edge into a tools/ script that runs under
a different task identity. ``tests/test_moon_sync_status_route.py`` binds the
two copies with a parity test over the whole case table, so they cannot drift
silently; if you change one rule, change both and let that test prove it.

THE ONE RULE, in order:

  FAULT    the header carries a fault line. It outranks everything - a poller
           that is running and stamping while its seen-store is unreadable is
           not LIVE, and a header fact this route failed to carry would grade
           LIVE, which is the exact failure this ordering exists to prevent.
  DEAD     the recorded pid is PROVABLY gone. Only a positive proof counts:
           an unprobeable pid (no pid line, or OpenProcess access-denied) is
           ``None``, never ``False``, so a pre-fleet-view status.md - the shape
           that persists if the pid line is never added - is graded by TIME
           alone and can never be reported DEAD on no evidence.
  OVERDUE  now is past the header's own promised "expect next poll by".
  STALE    the stamp is older than twice the header's PROMISED interval plus
           60s. The promise is read, never assumed: the poller climbs its
           interval when the desktop is idle, so a hardcoded ceiling would call
           a healthy idle poller stale every night.
  LIVE     none of the above.

UNMEASURED is the verdict when status.md is absent or carries no parseable
stamp. A missing file is never a fabricated DEAD and never an empty 200 - the
one thing a liveness surface must not do is go quiet in the same way the thing
it watches goes quiet.

FAULT OUTRANKS THE MISSING-STAMP SHORTCUT TOO, and the code says so rather than
leaving it to the prose. ``build_moon_sync_status`` takes its UNMEASURED
shortcut only when there is no fault line; with one, it delegates to
``status_verdict``, whose step 1 returns FAULT. The shape this closes is
production-reachable and precisely the one a liveness surface must not
mis-grade: a poller that faults BEFORE it stamps writes a header carrying
``- fault:``, ``- pid:`` and ``- next interval:`` and NO ``- checked:`` line.
Graded by the missing gate alone that read UNMEASURED, which is the opposite of
what step 1 promises. ``status_missing`` stays True on that shape - the stamp
really is absent - so the two facts are reported separately and neither is
inferred from the other. Pinned by
``test_fault_before_the_stamp_is_fault_not_unmeasured``, whose second arm holds
the un-faulted shape at UNMEASURED so the fix cannot over-correct.

WHAT REACHES THE WIRE. Codes and counts only. Note names and inbox filenames
never leave the box: the per-repo rows carry a short CODE plus integers plus a
status token from a fixed vocabulary, and the free-text header facts are
scrubbed of path-shaped runs before serialisation. ``unmapped roots`` is
reported as an integer COUNT for the same reason - a list of roots is a list of
names.

READS DO NOT WRITE. This route creates no directory (not even the state dir),
writes no file and touches no mtime. Pinned by
``test_route_reads_only_and_creates_nothing``, whose absent-directory arm is
what catches a stray mkdir.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dashboard._errors import send_error
from dashboard._matchers import equals

log = logging.getLogger("rc.moon_sync_status")

STATUS_FILENAME = "status.md"

# The verdict vocabulary, so a reader never has to guess the closed set.
VERDICTS = ("LIVE", "OVERDUE", "STALE", "DEAD", "FAULT", "UNMEASURED")

# A per-repo row may end in one of these and nothing else. A fixed vocabulary
# stops a fragment of a filename from being promoted to a "status".
_CODE_STATUSES = frozenset(
    {"LIVE", "OVERDUE", "STALE", "DEAD", "FAULT", "UNMEASURED", "QUIET", "OK"}
)

# `- NEW: <name>` / `- WITHDRAWN: <name>` are the poller's per-note body lines
# and their values ARE note names. They look like code rows and must never be
# parsed as one.
_NOT_CODES = frozenset({"NEW", "WITHDRAWN"})

_KV = re.compile(r"^-\s*([^:]+):\s*(.*)$")
_CODE = re.compile(r"^[A-Z][A-Z0-9_-]{0,7}$")
# A drive-letter or UNC path run, up to the next separator of a list.
_PATHISH = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\)[^,;]*")


def _now() -> datetime:
    """Seam: the single clock read, so tests can pin a fixed now."""
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


def _state_dir_path() -> Path:
    """The poller's shared state directory - resolved, NEVER created.

    Same rule as the poller's own resolver: an explicit ``RC_MOON_SYNC_STATE``
    override wins, otherwise ``%LOCALAPPDATA%/moonsync`` with the poller's TMP
    and cwd fallbacks. The mkdir the poller does is deliberately absent here -
    a read-only surface that creates the thing it reports on can report on its
    own side effect.
    """
    override = os.environ.get("RC_MOON_SYNC_STATE")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TMP") or "."
    return Path(base) / "moonsync"


def _scrub(value: str) -> str:
    """Strip path-shaped runs out of a free-text header fact."""
    return _PATHISH.sub("<path>", value).strip()[:200]


def _parse_dt(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value.strip())
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_int(value: str) -> int | None:
    m = re.search(r"-?\d+", value or "")
    return int(m.group(0)) if m else None


def _normalise_key(raw: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", raw.strip().lower()).strip("_")


def _count_roots(value: str) -> int:
    """`unmapped roots` as a COUNT. A bare integer is taken as written; any
    other value is counted as a comma-separated list, so a list of roots can
    never reach the wire as a list of names."""
    value = (value or "").strip()
    if not value or value in {"-", "none", "0"}:
        return 0
    if value.isdigit():
        return int(value)
    return len([t for t in value.split(",") if t.strip()])


def _parse_code_row(code: str, rest: str) -> dict | None:
    """One per-repo row -> code, counts and a status token. Returns None when
    the line carries no count and no known status, which is how a note-name
    body line is rejected rather than half-parsed."""
    entries = None
    m = re.search(r"(\d+)\s*entr", rest)
    if m:
        entries = int(m.group(1))
    arrivals = None
    m = re.search(r"\+\s*(\d+)", rest)
    if m:
        arrivals = int(m.group(1))
    withdrawals = None
    m = re.search(r"(?:^|[\s,])-\s*(\d+)", rest)
    if m:
        withdrawals = int(m.group(1))
    status = None
    for token in re.findall(r"[A-Z]{2,}", rest):
        if token in _CODE_STATUSES:
            status = token
    if entries is None and arrivals is None and withdrawals is None and status is None:
        return None
    return {
        "code": code,
        "entries": entries,
        "arrivals": arrivals,
        "withdrawals": withdrawals,
        "status": status,
    }


def parse_status_header(text: str) -> dict:
    """Parse the poller's status.md into facts. Tolerant by design: an unknown
    or missing line yields None for that fact rather than an exception, so a
    header that grows a field never 500s this route."""
    facts: dict = {
        "checked": None,
        "checked_dt": None,
        "next_interval_s": None,
        "pid": None,
        "fleet_view": False,
        "expect_next_poll_by": None,
        "expect_dt": None,
        "fault": None,
        "boot": None,
        "unmapped_roots": 0,
        "prompt_half": None,
        "prompt_half_dead": False,
        "per_code": [],
    }
    for line in (text or "").splitlines():
        m = _KV.match(line.strip())
        if not m:
            continue
        raw_key, value = m.group(1).strip(), m.group(2).strip()
        if _CODE.match(raw_key) and raw_key not in _NOT_CODES:
            row = _parse_code_row(raw_key, value)
            if row is not None:
                facts["per_code"].append(row)
            continue
        key = _normalise_key(raw_key)
        if key == "checked":
            facts["checked_dt"] = _parse_dt(value)
            facts["checked"] = value if facts["checked_dt"] else None
        elif key == "next_interval":
            facts["next_interval_s"] = _parse_int(value)
        elif key == "pid":
            facts["fleet_view"] = True
            facts["pid"] = _parse_int(value)
        elif key == "expect_next_poll_by":
            facts["expect_dt"] = _parse_dt(value)
            facts["expect_next_poll_by"] = value if facts["expect_dt"] else None
        elif key == "fault":
            facts["fault"] = _scrub(value) or None
        elif key == "boot":
            facts["boot"] = _scrub(value) or None
        elif key == "unmapped_roots":
            facts["unmapped_roots"] = _count_roots(value)
        elif key == "prompt_half":
            facts["prompt_half"] = _scrub(value) or None
            facts["prompt_half_dead"] = re.search(r"\bDEAD\b", value) is not None
    return facts


def _pid_alive(pid: int) -> bool | None:
    """Tri-state pid probe: True alive, False PROVABLY gone, None unprobeable.

    Same OpenProcess idiom as ops/loop/slots.py:49-82, with one deliberate
    difference: that helper answers a boolean because a lock holder it cannot
    see must be treated as alive. Here "I could not look" is its own answer -
    reporting DEAD on an access-denied handle would be a fabricated verdict.
    """
    if pid is None or pid <= 0:
        return None
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return None
        except OSError:
            return None
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    ERROR_INVALID_PARAMETER = 87
    try:
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False if k32.GetLastError() == ERROR_INVALID_PARAMETER else None
        try:
            code = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return None
            return code.value == STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    except OSError:
        return None


def status_verdict(fault, pid_alive, checked, expect, interval_s, now) -> str:
    """THE ONE RULE. See the module docstring for the ordering and why each
    step is where it is. Duplicated from the poller on purpose; the parity test
    is what keeps the two copies honest."""
    if fault:
        return "FAULT"
    if pid_alive is False:
        return "DEAD"
    if expect is not None and now > expect:
        return "OVERDUE"
    if checked is not None and interval_s:
        if (now - checked).total_seconds() > (2 * interval_s) + 60:
            return "STALE"
    if checked is None and expect is None:
        return "UNMEASURED"
    return "LIVE"


def build_moon_sync_status() -> dict:
    """Read status.md once and grade it. No writes, no mkdir, no exceptions
    for the ordinary absent-file case."""
    now = _now()
    path = _state_dir_path() / STATUS_FILENAME
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = None

    facts = parse_status_header(text) if text is not None else parse_status_header("")
    missing = text is None or facts["checked_dt"] is None

    pid = facts["pid"]
    pid_alive = _pid_alive(pid) if pid is not None else None

    # THE ONE RULE step 1 is FAULT and it outranks everything - the missing
    # shortcut included. A poller that faults BEFORE it stamps produces exactly
    # that shape, so the fault line is evaluated FIRST by delegating to
    # status_verdict, which is the single owner of the rule. The shortcut stays
    # for the un-faulted missing case, where UNMEASURED is the honest answer.
    if missing and not facts["fault"]:
        verdict = "UNMEASURED"
    else:
        verdict = status_verdict(
            fault=facts["fault"],
            pid_alive=pid_alive,
            checked=facts["checked_dt"],
            expect=facts["expect_dt"],
            interval_s=facts["next_interval_s"],
            now=now,
        )

    age = None
    if facts["checked_dt"] is not None:
        age = int((now - facts["checked_dt"]).total_seconds())

    return {
        "ok": True,
        "verdict": verdict,
        "status_missing": missing,
        "status_age_s": age,
        "checked": facts["checked"],
        "next_interval_s": facts["next_interval_s"],
        "expect_next_poll_by": facts["expect_next_poll_by"],
        "pid": pid,
        "pid_alive": pid_alive,
        "fleet_view": facts["fleet_view"],
        "fault": facts["fault"],
        "boot": facts["boot"],
        "unmapped_roots": facts["unmapped_roots"],
        "prompt_half": facts["prompt_half"],
        "prompt_half_dead": facts["prompt_half_dead"],
        "per_code": facts["per_code"],
        "updated_at": now.isoformat(timespec="seconds"),
    }


def _serve_moon_sync_status(h) -> None:
    """GET /api/moon-sync-status handler."""
    try:
        payload = build_moon_sync_status()
        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001 - last-resort guard
        log.warning("api/moon-sync-status: %s", exc)
        try:
            send_error(h, exc)
        except Exception:  # noqa: BLE001
            pass


GET_ROUTES = [
    (equals("/api/moon-sync-status"), _serve_moon_sync_status),
]

POST_ROUTES: list = []
