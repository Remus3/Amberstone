"""The inbox responder's cycle: one funnel, twenty-six gates, one row.

No test creates a process through `real_spawner`. `main` defaults `spawner` to
`real_spawner` only when `RC_RESPONDER_REAL_SPAWN=1` is in its environment and
otherwise raises `RealSpawnDisabled` before any subprocess exists; the CI suite
never sets that variable; the `__main__` block is the only code that sets it,
so the operator's interactive `--dry-cycle` and the task's `--cycle` are the
only paths that spawn by default.

ONE FUNNEL. Every cycle of `run_once` leaves exactly one START line, one END
line and one metrics row carrying the same `cycle_id`, written by the single
`_finish` call site in the `finally`, including cycles that raise inside a
gate. A prelude failure in `main` - before `run_once` exists to fail - leaves
the same triple through `main`'s own fixed-shape writer `prelude_row`, never
through `_finish` and never through `fallback_row`, whose `metrics-invalid`
detail and `row_replaced` state would describe a cycle that never started.

ONE CALL SITE PER GATE. Each gate is exactly one `# GATE:<tag>` line here.
Nothing else in the responder calls those functions, and no helper guards
itself: a helper that checks its own precondition is not a guard the runner is
SHOWN to call, and a mutation of it reddens nothing at the call site.

NO AMBIENT STATE. `run_once` reads no `__file__`, no `os.environ` and no PATH.
`log_root`, `parent_env` and the pre-resolved `config.claude_exe` /
`config.git_exe` all arrive as arguments; `main` is what resolves them.
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import json
import os
import re
import shutil
import stat
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ops.loop import slots, winmutex
from tools.inbox_responder import (
    Cycle,
    _sender_code,
    is_stopped,
    pending_notes,
    record_responded,
    validate_proposal,
)
from tools.inbox_responder_exec import (
    GRAMMAR_A5,
    GRAMMAR_LATENCY_ONLY,
    MEASURE_ENV_EXTRA,
    assemble_body,
    default_measure_runner,
    filter_body,
    harden_measure_argv,
    precheck_measure,
    scrub_output,
    scrub_text,
)
from tools.inbox_responder_export import ExportFailed, ensure_export
from tools.inbox_responder_procs import KillBudget, popen_capture
from tools.inbox_responder_prompt import NonceCollision, build_envelope
from tools.inbox_responder_spawn import (
    RealSpawnDisabled,
    Spawner,
    build_request,
    child_env,
    resolve_claude_exe,
    spawn_ok,
)
from tools.inbox_responder_spawn import real_spawner
from tools.rc_facts import _append_atomic

# ---------------------------------------------------------------------------
# Constants. Each assigned exactly ONCE at module level: the summed-timeout arm
# in tests/test_inbox_responder_task.py derives the task execution time limit
# from these names by census, across this file and the procs module.
# ---------------------------------------------------------------------------

MODEL = "claude-sonnet-4-5"
MAX_TURNS = 12

SLOT_TIMEOUT_S = 20
# MEASURED 2026-09-08, not guessed. The spec listed 120 under UNMEASURED, and
# the first dry cycle terminated `spawn-failed / timeout` on it: the spawn cwd
# is a 618 MB tracked-only export and the session Reads and Greps it under
# MAX_TURNS. 240 keeps every section 11 bound: the worst-case cycle sums to 500
# and the two-process export case to 560, both under TASK_ETL_S 600, and the
# refuted per-call-kill sum still exceeds it. tests/test_inbox_responder_task.py
# re-derives all three from these names, so a further raise reddens there first.
SPAWN_TIMEOUT_S = 240
EXPORT_TIMEOUT_S = 60
EXPORT_MAX_BYTES = 2 * 1024 * 1024 * 1024
MEASURE_TIMEOUT_S = 15
PRECHECK_TIMEOUT_S = 5
# Also defined in tools/inbox_responder_exec.py, which is what enforces it. It
# is restated here because the timeout census reads the RUNNER's names, and an
# arm pins the two values equal so they cannot drift apart.
PRECHECK_CALLS_PER_MEASURE = 2
MAX_MEASURES = 4
SLACK_S = 20
TASK_ETL_S = 600
POLL_INTERVAL_S = 300

MAX_SPAWN_ATTEMPTS = 3

NOTE_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{4}-from-[A-Z]{2,4}-[A-Za-z0-9._-]{1,80}\.md$")
NOTE_NAME_MAX = 120
NOTE_MAX_BYTES = 1024 * 1024
ROW_NOTE_RE = re.compile(r"^[A-Za-z0-9._?-]{1,80}$")
CYCLE_ID_RE = re.compile(r"^\d{8}T\d{6}-\d+-[0-9a-f]{6}$")
# The one detail carrying `exhaust` that a non-exhausted row may hold: gate
# 11's own exception tag, `exception:<gate-tag>:<cls>`, which names WHERE the
# runner raised and never claims the cycle was exhausted. Anchored on both
# ends so nothing may be appended to it - see `metrics_row_ok`.
EXHAUSTED_GATE_TAG_RE = re.compile(r"^exception:exhausted:[A-Za-z_][A-Za-z0-9_]*$")
PARTICIPANT_CODE_RE = re.compile(r"^[A-Z]{2,4}$")

LABEL_A5_TEMPLATE = (
    "RC-authored deliveries under agreement {agreement_id}, ONE SIDE of the exchange; "
    "a LOWER BOUND on the channel's hops-to-quiescence under measurement-only grammar (A5); "
    "channel figure = this plus the counterparty's own count"
)
LABEL_LATENCY_ONLY = (
    "LATENCY-ONLY grammar: M1 not measured; hops omitted, not zero; M2 is the only figure"
)
LABEL_NOT_ESTABLISHED = (
    "grammar not established this cycle (agreement not loaded, absent, malformed, expired, "
    "or row replaced); not a trial-grammar row"
)

M1_BASIS = "delivered entries only; the budget counter may exceed this"
M2_LABEL = (
    "note mtime on RC disk to reply write mtime, same host clock, includes up to one poll interval"
)
M3_COST_BASIS = "CLI total_cost_usd under Max login, notional"
NOTE_ARRIVAL_BASIS = "mtime per settled ordering rule"

# The details on which m3 is legitimately null: nothing parsed, because nothing
# was spawned or nothing came back that could parse.
M3_NULL_DETAILS = frozenset(
    {"slot-timeout", "attempt-cap", "binary-not-found", "timeout", "bad-json",
     "stdout-oversize", "nonce-collision"}
)

ACTION_KINDS = frozenset({"measure", "suite", "vendor", "pin", "reply"})
ROW_KINDS = ACTION_KINDS | {"other"}
TERMINATIONS = frozenset(
    {"disarmed", "window", "empty", "budget", "spawn-failed", "exhausted", "refused",
     "delivered", "runner-failed"}
)
REFUSED_STAGES = frozenset({"input", "validator", "filter", "destination"})
AGREEMENT_STATES = frozenset(
    {"not_loaded", "absent", "malformed", "expired", "ok", "row_replaced"}
)

INVOCATION_LOG_KEEP = 4000
STOP_FLAG_NAME = "INBOX_RESPONDER_STOP"
DRY_FLAG_NAME = "INBOX_RESPONDER_DRY"
AGREEMENT_NAME = "inbox_responder_agreement.json"
ATTEMPTS_NAME = "inbox_responder_attempts.json"
DELIVERIES_NAME = "inbox_responder_deliveries.jsonl"
METRICS_NAME = "responder_metrics.jsonl"
INVOCATIONS_NAME = "responder_invocations.jsonl"
HELD_DIR_NAME = "responder_held"
OUTBOX_DIR_NAME = "responder_outbox"
SLOT_DIR_NAME = "responder_slots"
MUTEX_NAME = "Global\\RC_INBOX_RESPONDER"
EVENT_NAME = "InboxResponder"

_GRAMMARS = (GRAMMAR_A5, GRAMMAR_LATENCY_ONLY)
_AGREEMENT_FIELDS = (
    "counterparties", "note", "window_open", "window_close", "hop_budget", "grammar", "expires",
)


class MetricsRowInvalid(Exception):
    """A row that `metrics_row_ok` refused. Held as `bad_row.json`."""


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class RunnerConfig:
    """Everything a cycle needs that is not per-cycle. No dollar-cap field."""

    claude_exe: Optional[Path] = None
    model: str = MODEL
    max_turns: int = MAX_TURNS
    spawn_timeout_s: int = SPAWN_TIMEOUT_S
    export_timeout_s: int = EXPORT_TIMEOUT_S
    export_max_bytes: int = EXPORT_MAX_BYTES
    measure_timeout_s: int = MEASURE_TIMEOUT_S
    precheck_timeout_s: int = PRECHECK_TIMEOUT_S
    slot_timeout_s: int = SLOT_TIMEOUT_S
    git_exe: str = ""
    max_slots: int = 2
    spawn_exe_source: Optional[str] = None


@dataclass
class CycleResult:
    """What `run_once` computed and `_finish` writes. Never partly written."""

    cycle_id: str
    ts: str
    pid: int
    dry: bool
    root: Path
    log_root: Path
    termination: str = "runner-failed"
    termination_detail: str = "exception:start:Unset"
    disarmed_by: Optional[str] = None
    refused_stage: Optional[str] = None
    agreement_id: Optional[str] = None
    agreement_note: Optional[str] = None
    agreement_state: str = "not_loaded"
    grammar: Optional[str] = None
    note: Optional[str] = None
    note_sha12: Optional[str] = None
    sender: Optional[str] = None
    budget_consumed: int = 0
    slot_waits: int = 0
    spawn_attempts: int = 0
    notes_at_cap: int = 0
    delivered: int = 0
    m2: Optional[float] = None
    m2_flag: Optional[str] = None
    m2_basis_skew_s: Optional[float] = None
    note_arrival: Optional[dict] = None
    reply: Optional[dict] = None
    m3: Optional[dict] = None
    m4: Optional[dict] = None
    m5: Optional[dict] = None
    delivery: Optional[dict] = None
    permission_denials: Optional[int] = None
    scrub_count: int = 0
    spawn_exe_source: Optional[str] = None


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def _runtime(root) -> Path:
    return Path(root) / "ops" / "runtime"


def metrics_path(log_root) -> Path:
    return _runtime(log_root) / METRICS_NAME


def invocations_path(log_root) -> Path:
    return _runtime(log_root) / INVOCATIONS_NAME


def deliveries_path(root) -> Path:
    return _runtime(root) / DELIVERIES_NAME


def attempts_path(root) -> Path:
    return _runtime(root) / ATTEMPTS_NAME


def agreement_path(root) -> Path:
    return _runtime(root) / AGREEMENT_NAME


def held_dir(root, cycle_id) -> Path:
    return _runtime(root) / HELD_DIR_NAME / cycle_id


def outbox_dir(root, cycle_id) -> Path:
    return _runtime(root) / OUTBOX_DIR_NAME / cycle_id


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def new_cycle_id(now: Callable[[], datetime]) -> str:
    """Clock, pid and three random bytes. No sender byte can reach it."""
    return f"{now():%Y%m%dT%H%M%S}-{os.getpid()}-{os.urandom(3).hex()}"


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S")


def safe_name(name: str) -> str:
    """The ONE projection for every sink reached before the name grammar passes."""
    return re.sub(r"[^A-Za-z0-9._-]", "?", name)[:80]


def note_sha12(name: str) -> str:
    """`surrogatepass`, never `surrogateescape`.

    NTFS permits any invalid UTF-16 name, and `surrogateescape` raises on a lone
    surrogate outside U+DC80..U+DCFF, which would turn a hostile filename into a
    runner exception that re-cycles the note on every tick.
    """
    return hashlib.sha256(name.encode("utf-8", "surrogatepass")).hexdigest()[:12]


def kind_of(raw: object) -> str:
    """Project a MODEL-EMITTED kind before it enters a row."""
    return raw if isinstance(raw, str) and raw in ACTION_KINDS else "other"


def reply_filename(now: datetime, note_name: str) -> str:
    """Zero sender bytes. Siblings parse the sender as `RC`."""
    return f"{now:%Y-%m-%d-%H%M}-from-RC-RESPONDER-re-{note_sha12(note_name)}.md"


def classify_exhausted(proposal: object) -> bool:
    """Exhausted is `actions == []` and nothing else."""
    return isinstance(proposal, dict) and proposal.get("actions") == []


def note_shape_ok(path, name: str, *, sink: Optional[list] = None) -> list:
    """Judge one note's NAME and FILE. Empty list means it may be answered.

    `sink`, when given, receives the note bytes read from the very fd whose
    identity was checked, so the link checks and the read share one open file
    rather than leaving a window between them.
    """
    problems = []
    if not name.isascii() or len(name) > NOTE_NAME_MAX or not NOTE_NAME_RE.fullmatch(name):
        problems.append("name-grammar")
    path = Path(path)
    try:
        lst = os.lstat(path)
    except OSError:
        return problems or ["note-shape:linked"]
    if stat.S_ISLNK(lst.st_mode):
        problems.append("note-shape:linked")
    elif os.name == "nt" and getattr(lst, "st_file_attributes", 0) & 0x400:
        problems.append("note-shape:linked")
    elif lst.st_nlink != 1:
        problems.append("note-shape:linked")
    if lst.st_size > NOTE_MAX_BYTES:
        problems.append("note-oversize")
    if problems:
        return problems
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = None
    try:
        fd = os.open(path, flags)
        fst = os.fstat(fd)
        if (fst.st_dev, fst.st_ino) != (lst.st_dev, lst.st_ino):
            return ["note-shape:linked"]
        data = b""
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            data += chunk
            if len(data) > NOTE_MAX_BYTES:
                return ["note-oversize"]
    except OSError:
        return ["note-shape:linked"]
    finally:
        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)
    if sink is not None:
        sink.append(data)
    return []


# ---------------------------------------------------------------------------
# Agreement
# ---------------------------------------------------------------------------


def agreement_id_of(record: Mapping[str, Any]) -> str:
    """Canonical over the SEMANTIC fields only.

    A CRLF save, a trailing newline or reordered keys keep the id, the budget
    and the M1 chain; changing `hop_budget` or the window is a new agreement.
    """
    semantic = {k: record.get(k) for k in _AGREEMENT_FIELDS}
    blob = json.dumps(semantic, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _parse_iso(value: object) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def load_agreement(root, participants: Mapping[str, Any], *, now: datetime):
    """Return `(record, detail)`. `record is None` means disarmed; fails closed."""
    path = agreement_path(root)
    if not path.exists():
        return None, "no_agreement"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "malformed:json"
    if not isinstance(record, dict):
        return None, "malformed:json"

    parties = record.get("counterparties")
    if not isinstance(parties, list) or not parties or not all(isinstance(p, str) for p in parties):
        return None, "malformed:counterparties"
    if any(p not in participants for p in parties):
        return None, "malformed:counterparties"
    if not isinstance(record.get("note"), str):
        return None, "malformed:note"
    budget = record.get("hop_budget")
    if not isinstance(budget, int) or isinstance(budget, bool) or not 1 <= budget <= 64:
        return None, "malformed:hop_budget"
    if record.get("grammar") not in _GRAMMARS:
        return None, "malformed:grammar"
    opened = _parse_iso(record.get("window_open"))
    closed = _parse_iso(record.get("window_close"))
    expires = _parse_iso(record.get("expires"))
    if opened is None:
        return None, "malformed:window_open"
    if closed is None:
        return None, "malformed:window_close"
    if expires is None:
        return None, "malformed:expires"
    if opened >= closed:
        return None, "malformed:window_open"
    if expires < closed:
        return None, "malformed:expires"
    if now >= expires:
        return None, "expired"
    return record, ""


def window_open(record: Mapping[str, Any], now: datetime) -> bool:
    """`open <= now < close`, naive local ISO throughout."""
    opened = _parse_iso(record.get("window_open"))
    closed = _parse_iso(record.get("window_close"))
    if opened is None or closed is None:
        return False
    return opened <= now < closed


# ---------------------------------------------------------------------------
# Counters. Two of them, and they answer different questions.
# ---------------------------------------------------------------------------


def _delivery_entries(root) -> Optional[list]:
    path = deliveries_path(root)
    if not path.exists():
        return []
    out = []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            return None
        if not isinstance(entry, dict):
            return None
        out.append(entry)
    return out


def budget_consumed(root, agreement_id: Optional[str]) -> Optional[int]:
    """Governs the hop budget. Counts `attempted` too, so it fails CLOSED."""
    entries = _delivery_entries(root)
    if entries is None:
        return None
    return sum(
        1
        for e in entries
        if e.get("agreement_id") == agreement_id
        and not e.get("dry")
        and e.get("status") in ("attempted", "delivered")
    )


def delivered_count(root, agreement_id: Optional[str]) -> int:
    """M1's operand: replies that provably appeared. Never the attempted ones."""
    entries = _delivery_entries(root) or []
    return sum(
        1
        for e in entries
        if e.get("agreement_id") == agreement_id
        and not e.get("dry")
        and e.get("status") == "delivered"
    )


def within_budget(consumed: Optional[int], budget: object) -> bool:
    """An unreadable counter is not permission to send."""
    if consumed is None or not isinstance(budget, int):
        return False
    return consumed < budget


def attempts_of(root) -> dict:
    path = attempts_path(root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _record_attempt(root, sha: str) -> int:
    data = attempts_of(root)
    count = int(data.get(sha, 0)) + 1
    data[sha] = count
    path = attempts_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8", newline="\n")
    tmp.replace(path)
    return count


def pick_note(names, attempts: Mapping[str, Any]) -> Optional[str]:
    """The oldest pending note still BELOW the automatic spawn-attempt cap.

    A note at the cap is held for the operator: it is not retired, not answered
    and not skipped forever - it simply stops consuming automatic spawns while
    a younger eligible note is answered ahead of it.
    """
    names = [n for n in names if int(attempts.get(note_sha12(n), 0)) < MAX_SPAWN_ATTEMPTS]
    return names[0] if names else None


def notes_at_cap(names, attempts: Mapping[str, Any]) -> int:
    return sum(1 for n in names if int(attempts.get(note_sha12(n), 0)) >= MAX_SPAWN_ATTEMPTS)


# ---------------------------------------------------------------------------
# Participants
# ---------------------------------------------------------------------------


def load_participants(repo_root) -> tuple:
    """Return `(map, dropped_detail)`; keys never reach a log line.

    A code that failed the allowlist is arbitrary text, and a path-shaped key is
    a path. The END line carries a count and a digest of the sorted dropped set,
    which is enough to notice a change and carries nothing to leak.
    """
    path = Path(repo_root) / "ops" / "moon_sync_repos.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, ""
    raw = data.get("participants") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return {}, ""
    keep = {}
    dropped = []
    for code, base in sorted(raw.items()):
        if not isinstance(code, str) or not PARTICIPANT_CODE_RE.fullmatch(code) or not isinstance(base, str):
            dropped.append(str(code))
            continue
        inbox = Path(base) / "moon_sync_inbox"
        try:
            ok = inbox.is_dir() and Path(inbox).resolve() == Path(inbox)
            if ok and os.name == "nt":
                ok = not (os.lstat(inbox).st_file_attributes & 0x400)
        except OSError:
            ok = False
        if ok:
            keep[code] = inbox
        else:
            dropped.append(code)
    detail = ""
    if dropped:
        digest = hashlib.sha256("\n".join(sorted(dropped)).encode("utf-8")).hexdigest()[:8]
        detail = f"participants-dropped:{len(dropped)}:{digest}"
    return keep, detail


# ---------------------------------------------------------------------------
# The invocation log
# ---------------------------------------------------------------------------


def _trim(path: Path, keep: int = INVOCATION_LOG_KEEP) -> None:
    """This log's OWN trimmer. The hook log's 32 KB rule would evict hook fires."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines(True)
    except OSError:
        return
    if len(lines) <= keep:
        return
    tmp = path.with_suffix(".jsonl.tmp")
    try:
        tmp.write_text("".join(lines[-keep:]), encoding="utf-8", newline="")
        tmp.replace(path)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()


def _append_line(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _append_atomic(path, (json.dumps(payload, ensure_ascii=True) + "\n").encode("ascii"))


def log_start(log_root, cycle_id: str, dry: bool, ts: str, pid: int) -> None:
    path = invocations_path(log_root)
    _append_line(path, {"ts": ts, "event": EVENT_NAME, "phase": "start",
                        "cycle_id": cycle_id, "dry": bool(dry), "pid": pid})
    _trim(path)


def log_end(log_root, payload: dict) -> None:
    path = invocations_path(log_root)
    _append_line(path, payload)
    _trim(path)


def _end_payload(result: CycleResult) -> dict:
    detail = result.termination_detail
    return {
        "ts": result.ts,
        "event": EVENT_NAME,
        "phase": "end",
        "cycle_id": result.cycle_id,
        "agreement_id": result.agreement_id,
        "agreement_state": result.agreement_state,
        "dry": bool(result.dry),
        "pid": result.pid,
        "termination": result.termination,
        "termination_detail": detail,
        "refused_stage": result.refused_stage,
        "note": result.note,
        "note_sha12": result.note_sha12,
        "sender": result.sender,
    }


# ---------------------------------------------------------------------------
# The metrics row
# ---------------------------------------------------------------------------


def _m1(grammar: Optional[str], agreement_id: Optional[str], hops: Optional[int]) -> dict:
    if grammar == GRAMMAR_A5:
        status, label, value = "LOWER_BOUND", LABEL_A5_TEMPLATE.format(agreement_id=agreement_id), hops
    elif grammar == GRAMMAR_LATENCY_ONLY:
        status, label, value = "INAPPLICABLE", LABEL_LATENCY_ONLY, None
    else:
        status, label, value = "GRAMMAR_NOT_ESTABLISHED", LABEL_NOT_ESTABLISHED, None
    return {"status": status, "hops": value, "label": label, "side": "RC",
            "agreement_id": agreement_id, "basis": M1_BASIS}


def _row_skeleton(cycle_id: str, ts: str, pid: int, dry: bool) -> dict:
    return {
        "ts": ts, "cycle_id": cycle_id, "dry": bool(dry), "pid": pid,
        "agreement_id": None, "agreement_note": None, "agreement_state": "not_loaded",
        "note": None, "note_sha12": None, "sender": None, "grammar": None,
        "termination": "runner-failed", "termination_detail": "", "disarmed_by": None,
        "refused_stage": None,
        "m1": _m1(None, None, None),
        "budget_consumed": 0, "slot_waits": 0, "spawn_attempts": 0, "notes_at_cap": 0,
        "m2_arrival_to_reply_s": None, "m2_source": "note_st_mtime", "m2_flag": None,
        "m2_basis_skew_s": None, "m2_label": M2_LABEL, "poll_interval_s": POLL_INTERVAL_S,
        "note_arrival": None, "reply": None,
        "m3": None, "m4": None, "m5": None,
        "m6": {"settling_delay_s": 0, "withdrawal_interval_s": None},
        "delivery": None, "permission_denials": None, "scrub_count": 0,
        "spawn_exe_source": None,
    }


def build_row(result: CycleResult) -> dict:
    """The one row builder for a cycle that started. `fallback_row` is its net."""
    row = _row_skeleton(result.cycle_id, result.ts, result.pid, result.dry)
    row.update({
        "agreement_id": result.agreement_id,
        "agreement_note": result.agreement_note,
        "agreement_state": result.agreement_state,
        "note": result.note,
        "note_sha12": result.note_sha12,
        "sender": result.sender,
        "grammar": result.grammar,
        "termination": result.termination,
        "termination_detail": result.termination_detail,
        "disarmed_by": result.disarmed_by,
        "refused_stage": result.refused_stage,
        "m1": _m1(result.grammar, result.agreement_id, result.delivered),
        "budget_consumed": result.budget_consumed,
        "slot_waits": result.slot_waits,
        "spawn_attempts": result.spawn_attempts,
        "notes_at_cap": result.notes_at_cap,
        "m2_arrival_to_reply_s": result.m2,
        "m2_flag": result.m2_flag,
        "m2_basis_skew_s": result.m2_basis_skew_s,
        "note_arrival": result.note_arrival,
        "reply": result.reply,
        "m3": result.m3,
        "m4": result.m4,
        "m5": result.m5,
        "delivery": result.delivery,
        "permission_denials": result.permission_denials,
        "scrub_count": result.scrub_count,
        "spawn_exe_source": result.spawn_exe_source,
    })
    return row


def fallback_row(result: CycleResult) -> dict:
    """Reached ONLY from `_finish`, so the error path cannot raise a second time."""
    row = _row_skeleton(result.cycle_id, result.ts, result.pid, result.dry)
    grammar = result.grammar if result.grammar in _GRAMMARS else None
    row.update({
        "agreement_id": result.agreement_id,
        "agreement_note": result.agreement_note,
        "agreement_state": "row_replaced",
        "grammar": grammar,
        "termination": "runner-failed",
        "termination_detail": f"metrics-invalid:{result.termination}",
        "m1": _m1(grammar, result.agreement_id, result.delivered),
    })
    return row


def prelude_row(cycle_id: str, ts: str, pid: int, stage: str, cls: str, dry: bool) -> dict:
    """`main`'s ONE row writer, for a failure before `run_once` existed.

    Not `fallback_row`: `metrics-invalid` and `row_replaced` describe a rejected
    row for a cycle that ran, and this cycle never started. It reads no config
    and no disk, so it cannot itself raise.
    """
    row = _row_skeleton(cycle_id, ts, pid, dry)
    row["termination"] = "runner-failed"
    row["termination_detail"] = f"prelude:{stage}:{cls}"
    return row


def _stripped_detail(detail: str) -> str:
    base = detail.split(";", 1)[0]
    if base.endswith(":attempt-cap"):
        base = base[: -len(":attempt-cap")]
    return base


def metrics_row_ok(row: Mapping[str, Any], *, delivered: Optional[int] = None,
                   held_root: Optional[Path] = None) -> bool:
    """Raise `MetricsRowInvalid` on any row that would mislead a reader.

    Every invariant here exists because the alternative is a row that PARSES
    and says something false: a hop count that exceeds the replies that
    appeared, a grammar whose M1 label belongs to the other grammar, or the
    substring `exhaust` on a row that was not exhausted. The one exemption is
    `EXHAUSTED_GATE_TAG_RE`: gate 11's exception tag names the GATE that
    raised, not the outcome, and destroying it would cost the attribution the
    gate-exception row exists to carry.
    """
    def bad(msg: str):
        raise MetricsRowInvalid(msg)

    if not isinstance(row, Mapping):
        bad("row must be a mapping")
    if not CYCLE_ID_RE.fullmatch(str(row.get("cycle_id", ""))):
        bad("cycle_id shape")
    if row.get("termination") not in TERMINATIONS:
        bad("termination enum")
    detail = row.get("termination_detail")
    if not isinstance(detail, str) or not detail:
        bad("termination_detail must be non-empty")
    if row.get("agreement_state") not in AGREEMENT_STATES:
        bad("agreement_state enum")
    stage = row.get("refused_stage")
    if stage is not None and stage not in REFUSED_STAGES:
        bad("refused_stage enum")
    note = row.get("note")
    if note is not None and not ROW_NOTE_RE.fullmatch(str(note)):
        bad("note projection")

    if ("exhaust" in detail and row["termination"] != "exhausted"
            and not EXHAUSTED_GATE_TAG_RE.fullmatch(detail)):
        bad("the substring exhaust on a non-exhausted row")
    if "refus" in detail and row["termination"] != "refused":
        bad("the substring refus on a non-refused row")

    grammar = row.get("grammar")
    m1 = row.get("m1")
    if not isinstance(m1, Mapping):
        bad("m1 must be an object")
    hops = m1.get("hops")
    if grammar == GRAMMAR_A5:
        if m1.get("status") != "LOWER_BOUND" or not isinstance(hops, int) or isinstance(hops, bool):
            bad("A5 requires LOWER_BOUND with an int hops")
        if m1.get("label") != LABEL_A5_TEMPLATE.format(agreement_id=row.get("agreement_id")):
            bad("A5 label must be the rendered template")
    elif grammar == GRAMMAR_LATENCY_ONLY:
        if m1.get("status") != "INAPPLICABLE" or hops is not None:
            bad("LATENCY-ONLY requires INAPPLICABLE with null hops")
        if m1.get("label") != LABEL_LATENCY_ONLY:
            bad("LATENCY-ONLY label")
    elif grammar is None:
        if m1.get("status") != "GRAMMAR_NOT_ESTABLISHED" or hops is not None:
            bad("no grammar requires GRAMMAR_NOT_ESTABLISHED with null hops")
        if m1.get("label") != LABEL_NOT_ESTABLISHED:
            bad("not-established label")
    else:
        bad("grammar enum")
    if isinstance(hops, int) and delivered is not None and hops > delivered:
        bad("m1.hops exceeds the delivered entries")

    m4 = row.get("m4")
    require_m4 = (stage in ("validator", "filter", "destination")
                  or row["termination"] in ("exhausted", "delivered"))
    # `or (spawn parsed)`: a cycle that raised after the proposal was judged
    # legitimately carries m4, and m3 is what says a result parsed.
    permit_m4 = require_m4 or row.get("m3") is not None
    if require_m4 and m4 is None:
        bad("m4 required for this termination")
    if not permit_m4 and m4 is not None:
        bad("m4 present where nothing was ever judged")
    if isinstance(m4, Mapping):
        for action in m4.get("actions") or []:
            if action.get("kind") not in ROW_KINDS:
                bad("m4 action kind outside the enum")

    base = _stripped_detail(detail)
    reached_spawn = (
        grammar != GRAMMAR_LATENCY_ONLY
        and stage != "input"
        and row["termination"] in ("exhausted", "refused", "delivered", "spawn-failed")
        and base not in M3_NULL_DETAILS
        # `exit:<n>` joins the null set by MEASUREMENT rather than by decision:
        # `spawn_ok` returns on a non-zero exit before it parses anything, so a
        # row carrying that detail can never hold an m3.
        and not base.startswith(("exc:", "exit:", "export:", "exception:"))
    )
    if reached_spawn and row.get("m3") is None:
        bad("m3 must be populated once a result parsed")

    if held_root is not None:
        want_draft = stage in ("filter", "destination") or base == "stop_flag_late" or base.startswith("delivery:")
        has_draft = (Path(held_root) / "draft.md").exists()
        if want_draft != has_draft:
            bad("held draft.md presence does not match the termination")

    flag = row.get("m2_flag")
    if flag not in (None, "negative", "future-arrival"):
        bad("m2_flag enum")
    m2 = row.get("m2_arrival_to_reply_s")
    if isinstance(m2, (int, float)) and m2 < 0 and flag is None:
        bad("a negative M2 must be flagged")
    return True


def trial_rows(path, agreement_id: str) -> list:
    """The rows an arming note may quote: live, this agreement, grammar established."""
    out = []
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError:
        return out
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        if row.get("dry") or row.get("agreement_id") != agreement_id or row.get("grammar") is None:
            continue
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# The funnel
# ---------------------------------------------------------------------------


def _finish(result: CycleResult) -> CycleResult:
    """The ONE writer of an END line and a row, for every outcome of a cycle.

    The row is built and judged BEFORE the END line is written, so an END line
    can never claim an outcome the row it accompanies does not carry.
    """
    row = build_row(result)
    try:
        metrics_row_ok(row, delivered=delivered_count(result.root, result.agreement_id),
                       held_root=held_dir(result.root, result.cycle_id))
    except MetricsRowInvalid:
        _hold_write(result, "bad_row.json", json.dumps(row, indent=2, ensure_ascii=True))
        row = fallback_row(result)
        result.termination = row["termination"]
        result.termination_detail = row["termination_detail"]
        result.agreement_state = row["agreement_state"]
    log_end(result.log_root, _end_payload(result))
    _append_line(metrics_path(result.log_root), row)
    return result


def _terminate(result: CycleResult, termination: str, detail: str, *,
               disarmed_by: Optional[str] = None,
               refused_stage: Optional[str] = None) -> CycleResult:
    result.termination = termination
    result.termination_detail = detail
    result.disarmed_by = disarmed_by
    result.refused_stage = refused_stage
    return result


def _hold_write(result: CycleResult, name: str, text: str) -> Path:
    target = held_dir(result.root, result.cycle_id)
    target.mkdir(parents=True, exist_ok=True)
    path = target / name
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="ascii", errors="backslashreplace", newline="\n")
    tmp.replace(path)
    return path


def _export_git_runner(config: RunnerConfig, repo_root, env, kill_budget):
    """The export's git seam: `config.git_exe` prepended, everything else bound.

    The export module therefore names no executable, no PATH and no environment,
    and issues no process of its own.
    """
    def _run(args, *, timeout_s):
        return popen_capture([str(config.git_exe), *list(args)], cwd=repo_root, env=env,
                             stdin_bytes=b"", timeout_s=timeout_s, kill_budget=kill_budget)
    return _run


def scrub_reasons(entries) -> list:
    """Scrub every `reason` IN PLACE. The ONE `scrub_text` call site in the runner.

    `Decision.reason` is model-tainted - the validator interpolates argv, target,
    path, targets and kind into it - so nothing carrying a reason reaches a row,
    a held file or a body without passing through here first.
    """
    for entry in entries:
        entry["reason"] = scrub_text(str(entry.get("reason", "")))
    return entries


def decision_rows(decisions) -> list:
    """`decisions.json`: the validator's constant rule plus a scrubbed reason."""
    return scrub_reasons([{"rule": d.rule, "reason": d.reason} for d in decisions])


def _m3_of(parsed: Mapping[str, Any]) -> dict:
    return {
        "input_tokens_uncached": parsed.get("input_tokens"),
        "cache_creation_input_tokens": parsed.get("cache_creation_input_tokens"),
        "cache_read_input_tokens": parsed.get("cache_read_input_tokens"),
        "output_tokens": parsed.get("output_tokens"),
        "cost_usd_notional": parsed.get("total_cost_usd"),
        "cost_basis": M3_COST_BASIS,
        "wall_ms": parsed.get("duration_ms"),
        "api_ms": parsed.get("duration_api_ms"),
        "num_turns": parsed.get("num_turns"),
        "complete": bool(parsed.get("complete")),
    }


def run_once(*, cycle_id: str, root, repo_root, inbox, participants: Mapping[str, Any],
             spawner: "Spawner", parent_env: Mapping[str, str], now: Callable[[], datetime],
             measure_runner=default_measure_runner, export=ensure_export,
             slot_root=None, config: Optional[RunnerConfig] = None, dry: bool = False,
             log_root=None) -> CycleResult:
    """One tick. Reads no environment, resolves nothing, returns through `_finish`."""
    root = Path(root)
    repo_root = Path(repo_root)
    inbox = Path(inbox)
    log_root = Path(log_root) if log_root is not None else root
    config = config if config is not None else RunnerConfig()
    slot_root = Path(slot_root) if slot_root is not None else _runtime(root) / SLOT_DIR_NAME
    ts = now()

    result = CycleResult(cycle_id=cycle_id, ts=_iso(ts), pid=os.getpid(), dry=bool(dry),
                         root=root, log_root=log_root,
                         spawn_exe_source=config.spawn_exe_source)
    kill_budget = KillBudget()
    child = child_env(parent_env)
    measure = functools.partial(measure_runner, git_exe=config.git_exe, repo_root=repo_root,
                                env=child, kill_budget=kill_budget)
    stage = "start"
    log_start(log_root, cycle_id, dry, result.ts, result.pid)  # GATE:start
    try:
        stage = "stop-pre"
        if is_stopped(root):  # GATE:stop-pre
            return _terminate(result, "disarmed", "stop_flag", disarmed_by="stop_flag")

        stage = "agreement"
        agreement, detail = load_agreement(root, participants, now=ts)  # GATE:agreement
        if agreement is None:
            result.agreement_state = ("absent" if detail == "no_agreement"
                                      else "expired" if detail == "expired" else "malformed")
            return _terminate(result, "disarmed", detail, disarmed_by=detail)
        result.agreement_state = "ok"
        result.agreement_id = agreement_id_of(agreement)
        result.agreement_note = agreement.get("note")
        result.grammar = agreement["grammar"]
        result.delivered = delivered_count(root, result.agreement_id)

        stage = "window"
        if not window_open(agreement, ts):  # GATE:window
            return _terminate(result, "window",
                              f"outside:{agreement['window_open']}..{agreement['window_close']}")

        stage = "pending"
        codes = tuple(sorted(set(agreement["counterparties"]) & set(participants)))
        names = pending_notes(inbox, root, participants=codes)  # GATE:pending
        if not names:
            return _terminate(result, "empty", "none_pending")

        stage = "attempt-cap"
        attempts = attempts_of(root)
        result.notes_at_cap = notes_at_cap(names, attempts)
        name = pick_note(names, attempts)  # GATE:attempt-cap
        if name is None:
            return _terminate(result, "runner-failed", "attempt-cap")
        sha = note_sha12(name)

        stage = "budget"
        consumed = budget_consumed(root, result.agreement_id)
        result.budget_consumed = consumed or 0
        if not within_budget(consumed, agreement["hop_budget"]):  # GATE:budget
            return _terminate(result, "budget",
                              "deliveries-unreadable" if consumed is None
                              else f"consumed={consumed} budget={agreement['hop_budget']}")

        stage = "note-shape"
        note_path = inbox / name
        result.note = safe_name(name)
        result.note_sha12 = sha
        result.sender = _sender_code(result.note)
        note_sink: list = []
        problems = note_shape_ok(note_path, name, sink=note_sink)  # GATE:note-shape
        if problems:
            _hold_write(result, "status.txt", problems[0])
            _hold_write(result, "note.txt", f"{result.note}\n{sha}\n")
            _hold_write(result, "reasons.json",
                        json.dumps({"stage": "input", "problems": problems}, indent=2))
            record_responded(root, name)
            return _terminate(result, "refused", problems[0], refused_stage="input")
        note_bytes = note_sink[0] if note_sink else b""

        arrival = os.stat(note_path)
        arrived_iso = _iso(datetime.fromtimestamp(arrival.st_mtime))
        delivery_number = result.budget_consumed + 1
        reply_targets = (result.sender,)

        model_body = ""
        measurements: list = []
        held_actions: list = []
        decisions: list = []
        proposal: Any = None
        targets: list = [result.sender]
        m4_actions: list = []
        executed = 0

        stage = "latency-only"
        latency = result.grammar == GRAMMAR_LATENCY_ONLY  # GATE:latency-only
        if not latency:
            stage = "export"
            try:
                export_dir = export(repo_root, root, ref="origin/main",
                                    runner=_export_git_runner(config, repo_root,
                                                              dict(child) | MEASURE_ENV_EXTRA,
                                                              kill_budget),
                                    timeout_s=config.export_timeout_s,
                                    max_bytes=config.export_max_bytes)  # GATE:export
            except ExportFailed as exc:
                return _terminate(result, "runner-failed", f"export:{exc.detail}")
            except Exception as exc:  # noqa: BLE001 - section 2 gate 8 files any export fault
                return _terminate(result, "runner-failed", f"export:exc:{type(exc).__name__}")

            stage = "slot"
            try:
                with slots.hold(config.max_slots, root=slot_root, repo="rc-responder",
                                run_id=cycle_id, timeout=config.slot_timeout_s):  # GATE:slot
                    stage = "envelope"
                    try:
                        envelope = build_envelope(  # GATE:envelope
                            cycle_id=cycle_id, note_filename=name, sender_code=result.sender,
                            reply_target=result.sender, arrived_on_rc_disk=arrived_iso,
                            delivery_number=delivery_number, grammar=result.grammar,
                            note_bytes=note_bytes,
                        )
                    except NonceCollision:
                        return _terminate(result, "runner-failed", "nonce-collision")

                    stage = "spawn"
                    exe = config.claude_exe
                    if exe is None or not Path(exe).is_file():
                        return _terminate(result, "spawn-failed", "binary-not-found")
                    request = build_request(config, envelope, export_dir, kill_budget, env=child)
                    spawn_res = spawner(request)
                    spawn_detail, parsed = spawn_ok(spawn_res)  # GATE:spawn
                    if parsed is not None:
                        result.m3 = _m3_of(parsed)
                        result.permission_denials = parsed.get("permission_denials")
                    if spawn_detail is not None:
                        result.spawn_attempts = _record_attempt(root, sha)
                        if result.spawn_attempts >= MAX_SPAWN_ATTEMPTS:
                            spawn_detail = f"{spawn_detail}:attempt-cap"
                            _hold_write(result, "status.txt", "attempt-cap")
                        # `timed_out` / `survived_kill` / `kill_skipped` are the
                        # cycle's kill-allowance record (section 3): booleans
                        # the runner owns, coerced here so nothing
                        # model-controlled can reach the hold through them.
                        _hold_write(result, "spawn.json", json.dumps(
                            {"cycle_id": cycle_id, "detail": spawn_detail,
                             "attempts": result.spawn_attempts, "parsed": parsed,
                             "timed_out": bool(spawn_res.timed_out),
                             "survived_kill": bool(spawn_res.survived_kill),
                             "kill_skipped": bool(spawn_res.kill_skipped)}, indent=2))
                        return _terminate(result, "spawn-failed", spawn_detail)
                    proposal = parsed["structured_output"]
            except slots.SlotTimeout:
                result.slot_waits += 1
                return _terminate(result, "runner-failed", "slot-timeout")

            stage = "exhausted"
            if classify_exhausted(proposal):  # GATE:exhausted
                _hold_write(result, "status.txt", "empty-proposal")
                _hold_write(result, "proposal.json", json.dumps(proposal, indent=2))
                result.m4 = {"proposed": 0, "allowed": 0, "executed": 0, "held": 0,
                             "refused": 0, "actions": []}
                record_responded(root, name)
                return _terminate(result, "exhausted", "empty-proposal")

            stage = "validate"
            cycle = Cycle(reply_targets=reply_targets, root=repo_root)
            decisions = validate_proposal(proposal, cycle)  # GATE:validate
            actions = proposal.get("actions") if isinstance(proposal, dict) else []
            actions = actions if isinstance(actions, list) else []

            # FIRST PASS: judge everything and find the reply. No process runs
            # until a destination exists - output with nowhere to go is never
            # produced, so a proposal carrying measures and no reply costs zero.
            reply_decision = None
            reply_action = None
            saw_reply = False
            runnable: list = []
            for action, decision in zip(actions, decisions):
                raw_kind = action.get("kind") if isinstance(action, dict) else None
                kind = kind_of(raw_kind)
                entry = {"kind": kind, "rule": decision.rule, "allowed": bool(decision.allowed),
                         "executed_or_held": "n/a", "reason": decision.reason,
                         "filter_gates": [], "exit_code": None, "timed_out": False,
                         "kill_skipped": False, "stdout_truncated": False, "wall_ms": None}
                m4_actions.append(entry)
                if raw_kind == "reply":
                    saw_reply = True
                    if decision.allowed and reply_action is None:
                        reply_action = action
                        reply_decision = decision
                    elif reply_decision is None:
                        reply_decision = decision
                if not decision.allowed:
                    entry["executed_or_held"] = "refused"
                elif kind == "measure":
                    runnable.append((action, entry))
                elif kind != "reply":
                    entry["executed_or_held"] = "held"
                    entry["rule"] = "executor:held-this-build"
                    entry["reason"] = "held pending the cited-note corroboration reader"
                    held_actions.append({"kind": kind, "rule": entry["rule"],
                                         "reason": entry["reason"]})

            if reply_action is None:
                refusal = (f"validator:{reply_decision.rule}" if saw_reply and reply_decision
                           else "no-reply-action")
                scrub_reasons(m4_actions)
                result.m4 = _m4_totals(m4_actions)
                _hold_write(result, "status.txt", refusal)
                _hold_write(result, "proposal.json", json.dumps(proposal, indent=2))
                _hold_write(result, "decisions.json",
                            json.dumps(decision_rows(decisions), indent=2))
                _hold_write(result, "reasons.json",
                            json.dumps({"stage": "validator", "detail": refusal}, indent=2))
                record_responded(root, name)
                return _terminate(result, "refused", refusal, refused_stage="validator")
            model_body = reply_action.get("body") or ""
            targets = list(reply_action.get("targets") or [])

            # SECOND PASS: the executor, in the order the mutant table pins.
            for action, entry in runnable:
                argv = action.get("argv") or []
                stage = "harden"
                rule = harden_measure_argv(argv)  # GATE:harden
                if rule is None:
                    stage = "measure-cap"
                    if executed >= MAX_MEASURES:  # GATE:measure-cap
                        rule = "executor:measure-cap"
                    else:
                        stage = "precheck"
                        rule = precheck_measure(argv, runner=measure,  # GATE:precheck
                                                timeout_s=config.precheck_timeout_s)
                if rule is not None:
                    entry["executed_or_held"] = "held"
                    entry["rule"] = rule
                    entry["reason"] = "held by the executor before any process ran"
                    held_actions.append({"kind": entry["kind"], "rule": rule,
                                         "reason": entry["reason"]})
                    continue

                stage = "measure"
                mres = measure(list(argv), timeout_s=config.measure_timeout_s)  # GATE:measure
                executed += 1
                stage = "scrub"
                text, count = scrub_output(mres.stdout)  # GATE:scrub
                result.scrub_count += count
                entry.update({"executed_or_held": "executed", "exit_code": mres.exit_code,
                              "timed_out": bool(mres.timed_out),
                              "kill_skipped": bool(mres.kill_skipped),
                              "stdout_truncated": bool(mres.stdout_truncated),
                              "wall_ms": mres.wall_ms})
                measurements.append({"argv": list(argv), "stdout": text,
                                     "exit_code": mres.exit_code, "timed_out": mres.timed_out,
                                     "wall_ms": mres.wall_ms,
                                     "stdout_truncated": mres.stdout_truncated})

        stage = "reason-scrub"
        scrub_reasons(m4_actions)  # GATE:reason-scrub
        result.m4 = _m4_totals(m4_actions)

        stage = "assemble"
        assembled = assemble_body(  # GATE:assemble
            grammar=result.grammar, cycle_id=cycle_id, note_filename=result.note,
            delivery_number=delivery_number, budget=agreement["hop_budget"],
            model_body=model_body, measurements=measurements, held=held_actions,
            arrived_iso=arrived_iso,
        )

        stage = "filter"
        hits = filter_body(assembled, model_body, targets, reply_targets, result.grammar)  # GATE:filter
        if hits:
            for entry in m4_actions:
                if entry["kind"] == "reply":
                    entry["filter_gates"] = list(hits)
            result.m4 = _m4_totals(m4_actions)
            _hold_write(result, "status.txt", "filter")
            _hold_write(result, "draft.md", assembled)
            _hold_write(result, "reasons.json",
                        json.dumps({"stage": "filter", "gates": hits}, indent=2))
            _hold_write(result, "proposal.json", json.dumps(proposal, indent=2))
            _hold_write(result, "decisions.json", json.dumps(decision_rows(decisions), indent=2))
            record_responded(root, name)
            return _terminate(result, "refused", "filter:" + ",".join(hits), refused_stage="filter")

        filename = reply_filename(ts, name)
        result.m5 = {"tag": assembled.splitlines()[0], "filename": filename}

        stage = "stop-late"
        if is_stopped(root):  # GATE:stop-late
            _hold_write(result, "status.txt", "stop_flag_late")
            _hold_write(result, "draft.md", assembled)
            return _terminate(result, "disarmed", "stop_flag_late", disarmed_by="stop_flag_late")

        stage = "deliver"
        dest = Path(participants[result.sender])
        outcome = _deliver(result, dest, filename, assembled, name, agreement, arrival, ts)  # GATE:deliver
        if outcome is not None:
            _hold_write(result, "draft.md", assembled)
            return outcome

        return _terminate(result, "delivered",
                          f"delivery={delivery_number} of {agreement['hop_budget']}")
    except Exception as exc:  # noqa: BLE001 - the one-funnel principle, section 2
        return _terminate(result, "runner-failed", f"exception:{stage}:{type(exc).__name__}")
    finally:
        _finish(result)  # GATE:finish


def _m4_totals(actions: list) -> dict:
    return {
        "proposed": len(actions),
        "allowed": sum(1 for a in actions if a["allowed"]),
        "executed": sum(1 for a in actions if a["executed_or_held"] == "executed"),
        "held": sum(1 for a in actions if a["executed_or_held"] == "held"),
        "refused": sum(1 for a in actions if a["executed_or_held"] == "refused"),
        "actions": actions,
    }


def deliver_link(tmp: Path, dest: Path) -> None:
    """`os.link`, never `os.rename`.

    The content is complete at the instant the final name appears, and NTFS and
    POSIX both raise FileExistsError - `os.replace` silently overwrites on
    POSIX, which is where CI runs.
    """
    os.link(tmp, dest)


def _deliver(result: CycleResult, dest: Path, filename: str, assembled: str, note_name: str,
             agreement: Mapping[str, Any], arrival, ts: datetime) -> Optional[CycleResult]:
    """Steps 2 to 8 of section 7. Returns None on success, a terminated result otherwise."""
    outbox = outbox_dir(result.root, result.cycle_id)
    outbox.mkdir(parents=True, exist_ok=True)
    (outbox / filename).write_text(assembled, encoding="ascii", newline="\n")

    record_responded(result.root, note_name)

    entry = {"cycle_id": result.cycle_id, "agreement_id": result.agreement_id,
             "filename": filename, "target_code": result.sender, "ts": result.ts,
             "status": "attempted", "dry": bool(result.dry)}
    _append_line(deliveries_path(result.root), entry)

    tmp = dest / ("_" + filename + ".tmp")
    final = dest / filename
    payload = assembled.encode("ascii")
    try:
        with open(tmp, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        deliver_link(tmp, final)
    except FileExistsError:
        with contextlib.suppress(OSError):
            tmp.unlink()
        return _terminate(result, "refused", "destination-exists", refused_stage="destination")
    except OSError as exc:
        with contextlib.suppress(OSError):
            tmp.unlink()
        return _terminate(result, "runner-failed",
                          f"delivery:{type(exc).__name__}:{exc.errno}")
    with contextlib.suppress(OSError):
        tmp.unlink()

    reply_stat = final.stat()
    digest = hashlib.sha256(payload).hexdigest()
    done = dict(entry)
    done.update({"status": "delivered", "sha256": digest, "st_mtime": reply_stat.st_mtime})
    _append_line(deliveries_path(result.root), done)
    result.delivery = {"target_code": result.sender, "sha256": digest,
                       "st_mtime": reply_stat.st_mtime}
    result.delivered = delivered_count(result.root, result.agreement_id)

    created = getattr(arrival, "st_birthtime", None) or arrival.st_ctime
    result.note_arrival = {"st_mtime": arrival.st_mtime, "st_birthtime_or_ctime": created,
                           "basis": NOTE_ARRIVAL_BASIS}
    result.reply = {"st_mtime": reply_stat.st_mtime}
    result.m2 = reply_stat.st_mtime - arrival.st_mtime
    result.m2_basis_skew_s = arrival.st_mtime - created
    # `future-arrival` is checked FIRST: a sender can `os.utime` the note, and a
    # negative M2 caused by a forward stamp is better named by its cause.
    if arrival.st_mtime > ts.timestamp() + 60:
        result.m2_flag = "future-arrival"
    elif result.m2 < 0:
        result.m2_flag = "negative"
    return None


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def _default_spawner(env: Mapping[str, str]) -> "Spawner":
    """The ONE code line naming the real spawner. Armed by one variable only."""
    if env.get("RC_RESPONDER_REAL_SPAWN") == "1":
        return real_spawner
    raise RealSpawnDisabled(
        "a real spawn was defaulted to but not armed; set RC_RESPONDER_REAL_SPAWN=1 "
        "in the __main__ block, never in a test"
    )


@contextlib.contextmanager
def _default_singleton():
    with winmutex.hold(MUTEX_NAME, timeout=0.0) as token:
        yield token


def _load_config(parent_env: Mapping[str, str]) -> RunnerConfig:
    config = RunnerConfig()
    config.git_exe = shutil.which("git", path=parent_env.get("PATH")) or "git"
    config.claude_exe, config.spawn_exe_source = resolve_claude_exe(config, parent_env)
    return config


def _load_max_slots(repo_root) -> int:
    try:
        data = json.loads((Path(repo_root) / "ops" / "loop" / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 2
    value = data.get("max_concurrent_lanes") if isinstance(data, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 2


def _consume_dry_flag(root) -> tuple:
    """Unlink FIRST, so a crash costs one dry tick and never a repeat."""
    flag = _runtime(root) / DRY_FLAG_NAME
    if not flag.exists():
        return False, None
    try:
        scratch = flag.read_text(encoding="utf-8").strip()
    except OSError:
        scratch = ""
    with contextlib.suppress(OSError):
        flag.unlink()
    return True, (scratch or None)


def _enter_dry_world(scratch_dir) -> dict:
    """Build the section 13 scratch world and return the `run_once` arguments."""
    scratch = Path(scratch_dir)
    root = scratch / "rc"
    (root / "ops" / "runtime").mkdir(parents=True, exist_ok=True)
    inbox = root / "moon_sync_inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    sibling = scratch / "Sibling RSC" / "moon_sync_inbox"
    sibling.mkdir(parents=True, exist_ok=True)
    note = inbox / "2026-09-07-2200-from-RSC-dry-cycle.md"
    if not note.exists():
        note.write_text(
            "Please report `git rev-parse --short origin/main` and "
            "`git ls-remote --heads origin` for the record.\n",
            encoding="ascii", newline="\n")
    opened = datetime.now() - timedelta(minutes=1)
    agreement = {
        "counterparties": ["RSC"], "note": note.name,
        "window_open": _iso(opened), "window_close": _iso(opened + timedelta(hours=1)),
        "hop_budget": 1, "grammar": GRAMMAR_A5,
        "expires": _iso(opened + timedelta(hours=2)),
        "authored_by": "operator", "authored_at": _iso(datetime.now()),
    }
    agreement_path(root).write_text(json.dumps(agreement, indent=2), encoding="ascii", newline="\n")
    return {"root": root, "inbox": inbox, "participants": {"RSC": sibling}}


def _schema_rejection_probe(config: RunnerConfig, spawner, parent_env, cwd) -> dict:
    """Interactive only: one extra spawn under an unsatisfiable schema.

    Two 120 s spawns in one task invocation would approach the execution time
    limit, so the flag-file path never runs this.
    """
    envelope = build_envelope(
        cycle_id="probe", note_filename="probe.md", sender_code="RSC", reply_target="RSC",
        arrived_on_rc_disk=_iso(datetime.now()), delivery_number=0, grammar=GRAMMAR_A5,
        note_bytes=b"Return a proposal.\n")
    request = build_request(config, envelope, cwd, KillBudget(), env=child_env(parent_env))
    res = spawner(request)
    return {"exit_code": res.exit_code, "stdout": res.stdout[:2000].decode("ascii", "backslashreplace")}


def main(argv=None, *, run=run_once, spawner=None, export=None, singleton=None,
         log_root=None, parent_env=None) -> int:
    """Resolve everything the cycle may not resolve, then run exactly one cycle."""
    args = list(argv or [])
    now = datetime.now
    cycle_id = new_cycle_id(now)
    parent_env = parent_env if parent_env is not None else dict(os.environ)
    log_root = Path(log_root) if log_root is not None else ROOT
    holder = singleton if singleton is not None else _default_singleton
    ts = _iso(now())
    pid = os.getpid()

    def _pair(termination: str, detail: str, is_dry: bool = False) -> None:
        """The pair `main` writes only when it never reached `run_once`."""
        log_start(log_root, cycle_id, is_dry, ts, pid)
        log_end(log_root, {"ts": ts, "event": EVENT_NAME, "phase": "end", "cycle_id": cycle_id,
                           "agreement_id": None, "agreement_state": "not_loaded", "dry": is_dry,
                           "pid": pid, "termination": termination, "termination_detail": detail,
                           "refused_stage": None, "note": None, "note_sha12": None,
                           "sender": None})

    dry = False
    stage = "singleton"
    try:
        cm = holder()
        with cm as token:
            if token is None:
                _pair("mutex-unavailable", "mutex-unavailable")
                return 3

            try:
                stage = "config"
                config = _load_config(parent_env)
                stage = "participants"
                participants, dropped = load_participants(ROOT)
                stage = "dry-flag"
                scratch = None
                if "--dry-cycle" in args:
                    dry = True
                    scratch = args[args.index("--scratch") + 1] if "--scratch" in args else None
                else:
                    dry, scratch = _consume_dry_flag(ROOT)
                stage = "loop-config"
                config.max_slots = _load_max_slots(ROOT)
                stage = "spawner"
                if spawner is None:
                    spawner = _default_spawner(os.environ)
                if export is None:
                    export = ensure_export
            except BaseException as exc:  # noqa: BLE001 - section 9: no prelude failure is silent
                cls = type(exc).__name__
                _pair("runner-failed", f"prelude:{stage}:{cls}", dry)
                _append_line(metrics_path(log_root),
                             prelude_row(cycle_id, ts, pid, stage, cls, dry))
                return 2

            if "--probe" in args:
                for code, path in sorted(participants.items()):
                    print(f"{code} -> {path}")
                print(f"dropped: {dropped or 'none'}")
                print(f"claude_exe: {config.claude_exe} ({config.spawn_exe_source})")
                return 0

            world = {"root": ROOT, "inbox": ROOT / "moon_sync_inbox", "participants": participants}
            if dry and scratch:
                world = _enter_dry_world(scratch)

            run(cycle_id=cycle_id, root=world["root"], repo_root=ROOT, inbox=world["inbox"],
                participants=world["participants"], spawner=spawner, parent_env=parent_env,
                now=now, measure_runner=default_measure_runner, export=export, slot_root=None,
                config=config, dry=dry, log_root=log_root)
            if "--dry-cycle" in args:
                print(_schema_rejection_probe(config, spawner, parent_env, ROOT))
            return 0
    except winmutex.MutexTimeout:
        _pair("overlap", "overlap")
        return 3


if __name__ == "__main__":  # pragma: no cover - the one arming site
    os.environ["RC_RESPONDER_REAL_SPAWN"] = "1"
    raise SystemExit(main(sys.argv[1:]))
