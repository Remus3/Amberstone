"""Agent 0 - Gatekeeper. Evaluates cross-machine tasks against the six
criteria from S7 and returns an accept/reject Decision.

LEGACY (1-PC, ADR-011): the six criteria below gated the 2-PC Legion ->
Game-PC SMB push path. Since the 2026-05-29 single-PC consolidation Game-PC
is out of the pipeline, and the push module itself was deleted 2026-10-22
(C6 F4, phase3-d026), so this evaluator gates no live cross-machine write.
The evaluator and its traversal guard are KEPT as the standing safety net
(phase3-d026); logic + the S7 contract are preserved.

Agent 0 is **not** a security boundary against the user. Direct user orders
bypass this evaluator (Agent 1 applies that override before invoking us).

Rejection dispositions (S7 hybrid d):
  * reasons 1, 2, 3, 6  -> ``dead_letter_immediately``
  * reasons 4, 5        -> ``auto_retry_once_then_dead_letter``

The caller (Agent 1) is responsible for applying the disposition.

Every Task field is filer-controlled (supervisor file-task -> scheduler), so
the gate fails CLOSED on junk (S144-T-686): a wrong-typed or overlong field
is a ``malformed_task`` dead letter, never an exception; the declared
``payload_ext`` must match the path's own suffix; NTFS streams, control
bytes, reserved device names and trailing dots / spaces are rejected; the
traversal check decodes percent-encoding to a fixed point; a config list
given as a bare string drops its entry instead of being read per character;
a raising game-state probe blocks a forwarder restart; and the repeat
window sweeps stale signatures.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEF_ALLOWED_OPS = _PROJECT_ROOT / "agents" / "agent0_gatekeeper" / "allowed_ops.json"
_DEF_TARGET_ALLOWLIST = _PROJECT_ROOT / "agents" / "agent0_gatekeeper" / "target_allowlist.json"

logger = logging.getLogger("agent0.evaluator")

# Rejection reason codes map to criterion number in S7.
REASON_TARGET = 1            # target machine mismatch
REASON_PAYLOAD = 2           # payload type mismatch
REASON_DESTINATION = 3       # destination outside allowlist
REASON_PROTECTED_WINDOW = 4  # blocked by active game (transient)
REASON_REPEAT = 5            # same op signature 3x / 60s (transient)
REASON_AUTHORITY = 6         # originating agent lacks authority

DEAD_LETTER_REASONS = {REASON_TARGET, REASON_PAYLOAD, REASON_DESTINATION, REASON_AUTHORITY}
RETRY_REASONS = {REASON_PROTECTED_WINDOW, REASON_REPEAT}


@dataclass
class Task:
    """Shape of a cross-machine task as Agent 1 hands it to Agent 0."""
    op: str
    originating_agent: str            # "2", "5", etc.
    remote_path: str                  # UNC path target
    payload_ext: str                  # ".html", ".py", ...
    tag: str | None = None            # e.g. "restart-forwarder" - marks protected-window sensitive ops
    signature: str | None = None      # for repeat detection; falls back to op+remote_path+payload_ext
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Rejection:
    reason_code: int
    reason_label: str
    message: str
    disposition: str                  # "dead_letter" or "retry_once"


@dataclass
class Decision:
    accepted: bool
    task: Task
    rejection: Rejection | None = None
    criteria_passed: list[int] = field(default_factory=list)


class _RepeatWindow:
    """Rolling-window repeat detector - signature -> list[timestamps].

    Stale signatures are swept at most once per window, so a long-running
    supervisor does not keep one bucket per signature it ever saw.
    """

    def __init__(self, window_sec: float = 60.0, max_in_window: int = 3) -> None:
        self.window = window_sec
        self.limit = max_in_window
        self._events: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._last_sweep: float | None = None

    def _sweep(self, t: float) -> None:
        """Drop every signature whose newest event left the window."""
        if self._last_sweep is not None and t - self._last_sweep < self.window:
            return
        self._last_sweep = t
        stale = [s for s, b in self._events.items() if not b or t - b[-1] >= self.window]
        for s in stale:
            del self._events[s]

    def observe_and_check(self, sig: str, now: float | None = None) -> bool:
        """Record a signature firing. Returns True if the signature has now
        fired >= ``limit`` times within the window (i.e. should be rejected)."""
        t = now if now is not None else time.monotonic()
        with self._lock:
            self._sweep(t)
            bucket = self._events.setdefault(sig, [])
            bucket[:] = [ts for ts in bucket if t - ts < self.window]
            bucket.append(t)
            return len(bucket) >= self.limit


# Longest ``remote_path`` the gate will look at; a web asset path is short,
# and a bound keeps the rejection log line bounded too.
_MAX_PATH_LEN = 1024
# Longest op / payload_ext / tag / signature / agent id; each is a short token.
_MAX_TOKEN_LEN = 256
# Percent-decoding rounds before a still-changing path is called hostile.
_MAX_DECODE_ROUNDS = 4
# Bytes Windows forbids in a name, plus ``:`` (an NTFS stream or a drive).
_FORBIDDEN_CHARS = frozenset('<>:"|?*')
# Reserved DOS device names: ``CON.html`` opens the console device, not a file.
_RESERVED_STEMS = frozenset(
    {"con", "prn", "aux", "nul", "conin$", "conout$"}
    | {f"{dev}{n}" for dev in ("com", "lpt")
       for n in ("0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
                 "\u00b9", "\u00b2", "\u00b3")}
)


def _segments(path: str) -> list[str]:
    """Path segments with both separators honoured, empty runs dropped."""
    return [p for p in path.replace("/", "\\").split("\\") if p]


def _decode_fully(path: str) -> str | None:
    """Percent-decode until stable; None when it never settles (hostile)."""
    cur = path
    for _ in range(_MAX_DECODE_ROUNDS):
        nxt = unquote(cur)
        if nxt == cur:
            return cur
        cur = nxt
    return None


def _str_list(value: Any) -> list[str] | None:
    """A JSON list of str / int ids as strings; None for any other shape.

    A bare string is NOT a list: iterating ``"25"`` would authorise agents
    ``"2"`` and ``"5"``.
    """
    if not isinstance(value, list):
        return None
    out: list[str] = []
    for v in value:
        if isinstance(v, bool):
            continue
        if isinstance(v, (str, int)):
            out.append(str(v))
    return out


def _load_ops(raw: Any) -> dict[str, dict[str, Any]]:
    """Validate ``allowed_ops.json``; a malformed op is DROPPED (fail closed:
    its tasks then reject as ``unknown_operation``)."""
    ops = raw.get("operations") if isinstance(raw, dict) else None
    if not isinstance(ops, dict):
        logger.warning("agent0 allowed_ops: 'operations' is not a mapping - every op rejects")
        return {}
    out: dict[str, dict[str, Any]] = {}
    for name, spec in ops.items():
        if not isinstance(spec, dict):
            logger.warning("agent0 allowed_ops: op %r is not a mapping - dropped", name)
            continue
        agents = _str_list(spec.get("authorized_agents"))
        exts = _str_list(spec.get("payload_extensions"))
        sub = spec.get("target_subdir", "")
        if agents is None or exts is None or not isinstance(sub, str):
            logger.warning("agent0 allowed_ops: op %r has a malformed field - dropped", name)
            continue
        exts = [e.lower() for e in exts
                if len(e) >= 2 and e.startswith(".") and not (set(e) & set("\\/")) and e != ".."]
        out[name] = {"authorized_agents": agents, "payload_extensions": exts,
                     "target_subdir": sub}
    return out


def _load_allowlist(raw: Any) -> tuple[str | None, tuple[str, ...]]:
    """Validate ``target_allowlist.json``. A junk share is None (criterion 1
    then matches only the hostname form, which criterion 3 rejects); a
    prefix is kept only when it is a str under the share ending in ``\\``."""
    raw = raw if isinstance(raw, dict) else {}
    share = raw.get("share_unc")
    if not (isinstance(share, str) and share.startswith("\\\\") and len(share) > 2):
        logger.warning("agent0 allowlist: share_unc is malformed - target check fails closed")
        share = None
    prefixes = _str_list(raw.get("allowed_prefixes")) or []
    kept: list[str] = []
    for p in prefixes:
        pl = p.lower()
        if share is not None and pl.startswith(share.lower() + "\\") and pl.endswith("\\"):
            kept.append(pl)
        else:
            logger.warning("agent0 allowlist: prefix %r dropped (not under the share)", p)
    return (share.lower() if share is not None else None), tuple(kept)


class Evaluator:
    def __init__(
        self,
        allowed_ops_path: Path = _DEF_ALLOWED_OPS,
        target_allowlist_path: Path = _DEF_TARGET_ALLOWLIST,
        game_state_probe=None,
    ) -> None:
        # A missing or unparseable file still raises: that is a deployment
        # error. A parseable file with a junk SHAPE fails closed instead.
        self._ops = _load_ops(json.loads(allowed_ops_path.read_text(encoding="utf-8")))
        self._target_share, self._target_prefixes = _load_allowlist(
            json.loads(target_allowlist_path.read_text(encoding="utf-8"))
        )
        self._repeat = _RepeatWindow()
        # game_state_probe is a callable returning str ("NONE", "IN_PROGRESS", etc.).
        # None -> protected-window check is permissive; a RAISING probe blocks.
        self._game_state_probe = game_state_probe

    # ----- helpers --------------------------------------------------
    @staticmethod
    def _malformed(task: Task) -> str | None:
        """Name the first filer-controlled field with a wrong type, else None."""
        for name in ("op", "remote_path", "payload_ext"):
            if not isinstance(getattr(task, name), str):
                return name
        agent = task.originating_agent
        if isinstance(agent, bool) or not isinstance(agent, (str, int)):
            return "originating_agent"
        for name in ("tag", "signature"):
            v = getattr(task, name)
            if v is not None and not isinstance(v, str):
                return name
        if len(task.remote_path) > _MAX_PATH_LEN:
            return "remote_path"
        for name in ("op", "payload_ext", "tag", "signature", "originating_agent"):
            v = getattr(task, name)
            if isinstance(v, str) and len(v) > _MAX_TOKEN_LEN:
                return name
        return None

    def _target_machine_ok(self, remote_path: str) -> bool:
        # Accept the configured numeric UNC exactly, plus hostname-form
        # (legion-pc-style mDNS). The hostname form never matches a numeric
        # allowlisted prefix, so criterion 3 still rejects it.
        rp = remote_path.lower()
        if self._target_share is not None and rp.startswith(self._target_share + "\\"):
            return True
        # mDNS/hostname form e.g. \\GAME-PC\RCClient\...
        mdns_match = re.match(r"^\\\\([a-z0-9\-]+(?:\.local)?)\\rcclient\\", rp)
        return mdns_match is not None

    def _destination_prefix_ok(self, remote_path: str) -> bool:
        rp = remote_path.lower()
        return any(rp.startswith(p) for p in self._target_prefixes)

    @staticmethod
    def _has_traversal(remote_path: str) -> bool:
        """Reject ``..`` in any spelling. The path is percent-decoded to a
        fixed point first (partial, double and triple encoding; ``%5c`` /
        ``%2f`` separators), and a segment made only of dots and spaces is
        rejected because Windows strips trailing dots and spaces, so ``.. ``
        and ``...`` are ambiguous. A path that never stops decoding is
        rejected too. See audit P-audit-h1 - this guard is the only path
        check left now that the retired SMB push module (and its own
        relative_to check) is deleted.
        """
        decoded = _decode_fully(remote_path)
        if decoded is None:
            return True
        return any(not seg.strip(". ") for seg in _segments(decoded))

    @staticmethod
    def _has_unsafe_name(remote_path: str) -> bool:
        """Reject a name Windows would write somewhere else: a control byte,
        a forbidden char (``:`` = NTFS stream), a trailing dot or space
        (silently stripped), or a reserved device stem (``CON.html``).
        Checked on the raw AND the decoded path; the leading ``\\\\`` of the
        UNC root is not a segment."""
        decoded = _decode_fully(remote_path) or remote_path
        for path in {remote_path, decoded}:
            if any(ord(c) < 32 or ord(c) == 0x7F for c in path):
                return True
            for seg in _segments(path):
                if _FORBIDDEN_CHARS & set(seg):
                    return True
                if seg[-1] in ". ":
                    return True
                if seg.split(".", 1)[0].rstrip(" ").lower() in _RESERVED_STEMS:
                    return True
        return False

    @staticmethod
    def _path_suffix(remote_path: str) -> str:
        """The lower-cased ``.ext`` of the final segment ('' for none or a
        path ending in a separator)."""
        norm = remote_path.replace("/", "\\")
        last = norm.rsplit("\\", 1)[-1]
        if "." not in last:
            return ""
        return "." + last.rsplit(".", 1)[-1].lower()

    def _payload_ok(self, op_spec: dict[str, Any], payload_ext: str) -> bool:
        return payload_ext.lower() in op_spec["payload_extensions"]

    def _authority_ok(self, op_spec: dict[str, Any], originating_agent: str | int) -> bool:
        return str(originating_agent) in op_spec["authorized_agents"]

    def _subdir_ok(self, op_spec: dict[str, Any], remote_path: str) -> bool:
        """Require the op's target subdir to immediately follow the share
        root (``RCClient\\``) - not just appear anywhere in the path.

        This fixes audit finding M3 (substring vs prefix match) which was
        made exploitable by the H1 traversal gap.
        """
        sub = op_spec.get("target_subdir", "")
        if not sub:
            return True
        rp = remote_path.lower()
        needle = f"\\rcclient\\{sub.lower()}\\"
        # Must appear AT MOST once AND before any further path components
        # that could re-route the target.
        idx = rp.find(needle)
        if idx < 0:
            return False
        # Everything after the share root must start with this subdir.
        share_end = rp.find("\\rcclient\\")
        return not (share_end < 0 or idx != share_end)

    def _protected_window_blocks(self, task: Task) -> bool:
        # Only ``tag`` values that contain "restart-forwarder" are sensitive
        # to game state per S7.4.
        if not task.tag:
            return False
        if "restart-forwarder" not in task.tag.lower():
            return False
        if self._game_state_probe is None:
            return False
        try:
            state = str(self._game_state_probe() or "").upper()
        except Exception as e:  # noqa: BLE001 - an arbitrary injected callable
            # Unknown game state: block (transient, retried once) rather than
            # restart the forwarder into what may be a live match.
            logger.warning("game_state_probe raised %s - treating as an active match",
                           type(e).__name__)
            return True
        return state not in ("", "NONE", "LOBBY", "CHAMP_SELECT_POST")

    def _reject(self, task: Task, code: int, label: str, message: str) -> Decision:
        dispo = "dead_letter" if code in DEAD_LETTER_REASONS else "retry_once"
        # %r keeps a filer-controlled CR / LF from forging a log line.
        logger.warning("agent0 REJECT code=%d label=%s op=%r path=%r: %r",
                       code, label, task.op, task.remote_path, message)
        return Decision(
            accepted=False,
            task=task,
            rejection=Rejection(
                reason_code=code,
                reason_label=label,
                message=message,
                disposition=dispo,
            ),
        )

    # ----- entry point ---------------------------------------------
    def evaluate(self, task: Task) -> Decision:
        # A wrong-typed field is a permanent payload defect, rejected before
        # any helper can raise on it.
        bad = self._malformed(task)
        if bad is not None:
            return self._reject(task, REASON_PAYLOAD, "malformed_task",
                                f"task field {bad!r} is malformed")

        # First resolve the op spec - unknown ops fail criterion 1 (bad op) or 6 (authority).
        op_spec = self._ops.get(task.op)
        if op_spec is None:
            return self._reject(task, REASON_AUTHORITY, "unknown_operation",
                                f"op {task.op!r} is not in allowed_ops.json")

        passed: list[int] = []

        # Traversal and unsafe-name checks run BEFORE host/payload/destination
        # checks so mixed-separator attacks (e.g. ``.../web/../../x``) can't
        # hide behind an earlier rejection reason. Classed under criterion 3
        # (destination) because that's what they attack.
        if self._has_traversal(task.remote_path):
            return self._reject(task, REASON_DESTINATION, "destination_traversal",
                                f"path contains traversal segment: {task.remote_path}")
        if self._has_unsafe_name(task.remote_path):
            return self._reject(task, REASON_DESTINATION, "destination_unsafe_name",
                                f"path contains a name Windows rewrites: {task.remote_path!r}")

        # 1. Target machine
        if not self._target_machine_ok(task.remote_path):
            return self._reject(task, REASON_TARGET, "target_mismatch",
                                f"remote_path {task.remote_path!r} does not target expected machine")
        passed.append(1)

        # 2. Payload type matches declared op, and the path really is that type
        if not self._payload_ok(op_spec, task.payload_ext):
            return self._reject(task, REASON_PAYLOAD, "payload_mismatch",
                                f"payload ext {task.payload_ext!r} not allowed for op {task.op}")
        if self._path_suffix(task.remote_path) != task.payload_ext.lower():
            return self._reject(task, REASON_PAYLOAD, "payload_suffix_mismatch",
                                f"payload ext {task.payload_ext!r} does not match the path suffix")
        passed.append(2)

        # 3. Destination under an allowlisted subdirectory + matches op's subdir
        if not self._destination_prefix_ok(task.remote_path):
            return self._reject(task, REASON_DESTINATION, "destination_outside_allowlist",
                                f"{task.remote_path} not under any allowlisted prefix")
        if not self._subdir_ok(op_spec, task.remote_path):
            return self._reject(task, REASON_DESTINATION, "subdir_mismatch_for_op",
                                f"op {task.op} requires subdir {op_spec.get('target_subdir')}, got {task.remote_path}")
        passed.append(3)

        # 4. Protected window (active match)
        if self._protected_window_blocks(task):
            return self._reject(task, REASON_PROTECTED_WINDOW, "active_match_protected",
                                "forwarder-restart rejected during active match - retry post-match")
        passed.append(4)

        # 5. Repeat-retry pattern
        sig = task.signature or f"{task.op}|{task.remote_path.lower()}|{task.payload_ext.lower()}"
        if self._repeat.observe_and_check(sig):
            return self._reject(task, REASON_REPEAT, "repeat_pattern",
                                f"signature {sig} fired >=3 in 60s window")
        passed.append(5)

        # 6. Originating agent has authority for this op/target
        if not self._authority_ok(op_spec, task.originating_agent):
            return self._reject(task, REASON_AUTHORITY, "agent_not_authorized",
                                f"agent {task.originating_agent} not authorized for op {task.op}")
        passed.append(6)

        logger.info("agent0 ACCEPT op=%r agent=%r path=%r",
                    task.op, task.originating_agent, task.remote_path)
        return Decision(accepted=True, task=task, criteria_passed=passed)


# Module-level convenience.
_default_eval: Evaluator | None = None
_lock = threading.Lock()


def evaluate(task: Task) -> Decision:
    global _default_eval
    if _default_eval is None:
        with _lock:
            if _default_eval is None:
                _default_eval = Evaluator()
    return _default_eval.evaluate(task)
