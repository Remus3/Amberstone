"""Agent 0 - Gatekeeper. Evaluates cross-machine tasks against the six
criteria from S7 and returns an accept/reject Decision.

LEGACY (1-PC, ADR-011): the six criteria below gate the 2-PC Legion ->
Game-PC SMB-push path (``agents/agent2_backend/smb_push.py``). Since the
2026-05-29 single-PC consolidation Game-PC is out of the pipeline and that
push path is dead, so this evaluator no longer gates any live cross-machine
write. Kept as dead code pending a separate cleanup pass; logic + the S7
contract are preserved for historical reference.

Agent 0 is **not** a security boundary against the user. Direct user orders
bypass this evaluator (Agent 1 applies that override before invoking us).

Rejection dispositions (S7 hybrid d):
  * reasons 1, 2, 3, 6  -> ``dead_letter_immediately``
  * reasons 4, 5        -> ``auto_retry_once_then_dead_letter``

The caller (Agent 1) is responsible for applying the disposition.
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
    """Rolling-window repeat detector - signature -> list[timestamps]."""

    def __init__(self, window_sec: float = 60.0, max_in_window: int = 3) -> None:
        self.window = window_sec
        self.limit = max_in_window
        self._events: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def observe_and_check(self, sig: str, now: float | None = None) -> bool:
        """Record a signature firing. Returns True if the signature has now
        fired >= ``limit`` times within the window (i.e. should be rejected)."""
        t = now if now is not None else time.monotonic()
        with self._lock:
            bucket = self._events.setdefault(sig, [])
            bucket[:] = [ts for ts in bucket if t - ts < self.window]
            bucket.append(t)
            return len(bucket) >= self.limit


class Evaluator:
    def __init__(
        self,
        allowed_ops_path: Path = _DEF_ALLOWED_OPS,
        target_allowlist_path: Path = _DEF_TARGET_ALLOWLIST,
        game_state_probe=None,
    ) -> None:
        self._ops: dict[str, dict[str, Any]] = json.loads(
            allowed_ops_path.read_text(encoding="utf-8")
        ).get("operations", {})
        al = json.loads(target_allowlist_path.read_text(encoding="utf-8"))
        self._target_share = al["share_unc"]
        self._target_prefixes: tuple[str, ...] = tuple(
            p.lower() for p in al["allowed_prefixes"]
        )
        self._repeat = _RepeatWindow()
        # game_state_probe is a callable returning str ("NONE", "IN_PROGRESS", etc.).
        # None -> protected-window check is permissive.
        self._game_state_probe = game_state_probe

    # ----- helpers --------------------------------------------------
    def _target_machine_ok(self, remote_path: str) -> bool:
        # Accept the configured numeric UNC exactly, plus hostname-form
        # (legion-pc-style mDNS) that resolves to the same prefix.
        rp = remote_path.lower()
        configured = self._target_share.lower()
        if rp.startswith(configured):
            return True
        # mDNS/hostname form e.g. \\GAME-PC\RCClient\...
        mdns_match = re.match(r"^\\\\([a-z0-9\-]+(?:\.local)?)\\rcclient\\", rp)
        return mdns_match is not None

    def _destination_prefix_ok(self, remote_path: str) -> bool:
        rp = remote_path.lower()
        return any(rp.startswith(p) for p in self._target_prefixes)

    @staticmethod
    def _has_traversal(remote_path: str) -> bool:
        """Reject any path containing ``..`` or URL-encoded ``%2e%2e`` as a
        distinct segment. Handles both / and \\ separators mixed. See audit
        P-audit-h1 - defends the share even when callers bypass ``smb_push``.
        """
        norm = remote_path.replace("/", "\\").lower()
        parts = [p for p in norm.split("\\") if p]
        if ".." in parts:
            return True
        if any("%2e%2e" in p for p in parts):
            return True
        # Also reject embedded trailing dots that Windows may treat as "..".
        return False

    def _payload_ok(self, op_spec: dict[str, Any], payload_ext: str) -> bool:
        allowed = [e.lower() for e in op_spec.get("payload_extensions", [])]
        return payload_ext.lower() in allowed

    def _authority_ok(self, op_spec: dict[str, Any], originating_agent: str) -> bool:
        return str(originating_agent) in [str(a) for a in op_spec.get("authorized_agents", [])]

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
        if share_end < 0 or idx != share_end:
            return False
        return True

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
        except Exception as e:  # noqa: BLE001
            logger.warning("game_state_probe raised %s - treating as NONE", e)
            return False
        return state not in ("", "NONE", "LOBBY", "CHAMP_SELECT_POST")

    def _reject(self, task: Task, code: int, label: str, message: str) -> Decision:
        dispo = "dead_letter" if code in DEAD_LETTER_REASONS else "retry_once"
        logger.warning("agent0 REJECT code=%d label=%s op=%s path=%s: %s",
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
        # First resolve the op spec - unknown ops fail criterion 1 (bad op) or 6 (authority).
        op_spec = self._ops.get(task.op)
        if op_spec is None:
            return self._reject(task, REASON_AUTHORITY, "unknown_operation",
                                f"op {task.op!r} is not in allowed_ops.json")

        passed: list[int] = []

        # Traversal check runs BEFORE host/payload/destination checks so
        # mixed-separator attacks (e.g. ``.../web/../../x``) can't hide
        # behind an earlier rejection reason. Classed under criterion 3
        # (destination) because that's what it attacks.
        if self._has_traversal(task.remote_path):
            return self._reject(task, REASON_DESTINATION, "destination_traversal",
                                f"path contains traversal segment: {task.remote_path}")

        # 1. Target machine
        if not self._target_machine_ok(task.remote_path):
            return self._reject(task, REASON_TARGET, "target_mismatch",
                                f"remote_path {task.remote_path!r} does not target expected machine")
        passed.append(1)

        # 2. Payload type matches declared op
        if not self._payload_ok(op_spec, task.payload_ext):
            return self._reject(task, REASON_PAYLOAD, "payload_mismatch",
                                f"payload ext {task.payload_ext!r} not allowed for op {task.op}")
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

        logger.info("agent0 ACCEPT op=%s agent=%s path=%s", task.op, task.originating_agent, task.remote_path)
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
