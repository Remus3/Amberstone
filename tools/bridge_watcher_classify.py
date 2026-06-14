"""bridge_watcher_classify.py - pure classification for bridge envelopes.

Phase 0 + Phase 2 per BRIDGE_WATCHER_PLAN.md S5:
  - escalate   : operator should drain via /process-bridge-tasks
  - ack-only   : log it, do nothing else
  - reject     : malformed; drop with reason
  - auto-read  : safe read-only auto-action (Phase 2 - Read/Grep/Glob)
  - auto-ops   : whitelisted ops auto-action (Phase 2 - Read/Grep/Glob/Bash)

Auto-* classifications are returned only when:
  - kind=task or kind=ask
  - targeted at this node
  - prompt does NOT trip the frozen-file intent gate
  - prompt matches a config-defined auto_read_pattern OR auto_ops_verb

Pure functions only - no I/O, no state. Easy to unit-test.
"""
from __future__ import annotations

import re
import os
from typing import Optional, Tuple

# Set of (source) values whose posts we never classify as work.
# A node never escalates its own posts back to itself.
_OWN_NODE_ALIASES = {
    "legion": {"legion", "rc", "rc-monitor"},
    "gamepc": {"gamepc"},
    "peer":    {"peer", "peer-host"},
}


def _is_own_post(envelope: dict, node: str) -> bool:
    src = (envelope.get("source") or "").strip().lower()
    return src in _OWN_NODE_ALIASES.get(node, {node})


def _is_targeted_at(envelope: dict, node: str) -> bool:
    """True if the envelope's target field matches this node (or alias)."""
    tgt = (envelope.get("target") or "").strip().lower()
    if not tgt:
        return False  # untargeted; not for us
    aliases = _OWN_NODE_ALIASES.get(node, {node})
    return tgt in aliases


def classify(envelope: dict, *, node: str,
             node_config: Optional[dict] = None,
             auto_action_enabled: bool = False) -> Tuple[str, str]:
    """Return (classification, reason).

    `node` is this machine's bridge label: 'legion', 'gamepc', or 'peer'.
    `node_config` is the per-node block from bridge_watcher_config.json
       (auto_read_patterns, auto_ops_verbs, escalate_always, etc.)
    `auto_action_enabled` - when False (default), never returns auto-* lanes
       even if patterns match. Phase 2 ships disabled-by-default; operator
       opts in via watcher --enable-auto-action flag.

    Classifications:
      "escalate"  - operator should action via /process-bridge-tasks
      "ack-only"  - log only, no operator surface
      "reject"    - malformed; drop, do not escalate
      "auto-read" - Phase 2: safe read-only auto-action (Read/Grep/Glob)
      "auto-ops"  - Phase 2: whitelisted ops (Bash with restricted regex)
    """
    if not isinstance(envelope, dict):
        return ("reject", "envelope is not a dict")

    if not envelope.get("id") and envelope.get("kind") in ("task", "ask"):
        return ("reject", "missing id field on actionable envelope")

    if _is_own_post(envelope, node):
        return ("ack-only", "own post; not escalating to self")

    kind = (envelope.get("kind") or "").strip().lower()

    if kind == "task":
        if not _is_targeted_at(envelope, node):
            return ("ack-only", "kind=task but not targeted at this node")
        # Phase 2: try auto-action lanes
        return _classify_actionable(envelope, node_config, auto_action_enabled,
                                    fallback_reason="kind=task")

    if kind == "ask":
        if not _is_targeted_at(envelope, node):
            return ("ack-only", "kind=ask but not targeted at this node")
        # ask is interactive by nature - don't auto-action even if pattern matches
        return ("escalate", "kind=ask targeted at this node - operator response needed")

    if kind == "result":
        body = envelope.get("body") or {}
        exit_code = body.get("exit_code") if isinstance(body, dict) else None
        if isinstance(exit_code, int) and exit_code != 0:
            return ("escalate", f"kind=result with exit_code={exit_code} - failure surfacing")
        return ("ack-only", "kind=result success - log only")

    if kind == "note":
        return ("ack-only", "kind=note - log only, context-carrying")

    if kind == "ack":
        return ("ack-only", "kind=ack - log only, lifecycle close")

    # Unknown kinds are conservative: escalate so operator sees them.
    return ("escalate", f"unknown kind={kind!r} - escalate by default")


# -- Phase 2 helpers -----------------------------------------------------


_WRITE_VERBS = frozenset({
    "edit", "write", "replace", "modify", "patch", "delete", "remove",
    "alter", "change", "fix", "rewrite", "rename", "swap", "overwrite",
    "rm", "remove-item", "set-content", "out-file",
})
_INTENT_PROXIMITY = 80


def _has_frozen_intent(prompt: str, frozen_files: list) -> Optional[str]:
    """Return reason string if prompt suggests writing a frozen file, else None.

    Same logic as bridge_watcher_actions._has_frozen_intent - duplicated here
    to keep classifier import-free of the actions module (which imports
    subprocess / claude binary / etc.). Tested in actions module's _test().
    """
    if not prompt or not frozen_files:
        return None
    p_lower = prompt.lower()
    for path in frozen_files:
        path_lower = str(path).lower()
        basename = os.path.basename(path_lower)
        for needle in (path_lower, basename):
            idx = 0
            while True:
                pos = p_lower.find(needle, idx)
                if pos == -1:
                    break
                window_start = max(0, pos - _INTENT_PROXIMITY)
                window_end = min(len(p_lower), pos + len(needle) + _INTENT_PROXIMITY)
                window = p_lower[window_start:window_end]
                for verb in _WRITE_VERBS:
                    if re.search(rf"\b{re.escape(verb)}\b", window):
                        return f"frozen-file write intent: '{verb}' near '{path}'"
                idx = pos + len(needle)
    return None


def _matches_pattern(prompt: str, patterns) -> Optional[str]:
    if not prompt or not patterns:
        return None
    p_lower = prompt.lower()
    for pat in patterns:
        try:
            if re.search(pat.lower(), p_lower):
                return pat
        except re.error:
            continue
    return None


def _classify_actionable(envelope: dict, node_config: Optional[dict],
                         auto_action_enabled: bool,
                         *, fallback_reason: str) -> Tuple[str, str]:
    """For kind=task targeted at this node: pick auto-* lane or escalate."""
    body = envelope.get("body") or {}
    prompt = ""
    if isinstance(body, dict):
        prompt = str(body.get("prompt") or "")

    # Frozen-file intent gate ALWAYS runs, even when auto-action disabled.
    # If hit, escalate with the reason - never auto-action.
    if node_config:
        frozen = node_config.get("escalate_always") or []
        intent_hit = _has_frozen_intent(prompt, frozen)
        if intent_hit:
            return ("escalate", intent_hit)

    if not auto_action_enabled or not node_config:
        return ("escalate", f"{fallback_reason} targeted at this node - operator action needed (auto-action disabled)")

    # Try auto-read patterns first (cheaper, safer)
    read_pat = _matches_pattern(prompt, node_config.get("auto_read_patterns") or [])
    if read_pat:
        return ("auto-read", f"matches auto_read_pattern: {read_pat!r}")

    # Then auto-ops verbs
    ops_verb = _matches_pattern(prompt, node_config.get("auto_ops_verbs") or [])
    if ops_verb:
        return ("auto-ops", f"matches auto_ops_verb: {ops_verb!r}")

    return ("escalate", f"{fallback_reason} - no auto-action pattern match")


# -- Self-test (run via: C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe tools/bridge_watcher_classify.py) ----------


def _test() -> None:
    # Phase 0 cases - auto-action disabled
    cases = [
        # (envelope, node, kwargs, expected_class)
        ({"source": "legion", "kind": "note"}, "legion", {}, "ack-only"),
        ({"source": "peer", "kind": "task", "target": "legion", "id": "task-1"}, "legion", {}, "escalate"),
        ({"source": "peer", "kind": "task", "target": "gamepc", "id": "task-2"}, "legion", {}, "ack-only"),
        ({"source": "gamepc", "kind": "result", "body": {"exit_code": 0}}, "legion", {}, "ack-only"),
        ({"source": "gamepc", "kind": "result", "body": {"exit_code": 1}}, "legion", {}, "escalate"),
        ({"source": "peer", "kind": "note"}, "legion", {}, "ack-only"),
        ({"source": "peer", "kind": "ack"}, "legion", {}, "ack-only"),
        ({"source": "peer", "kind": "ask", "target": "legion", "id": "ask-1"}, "legion", {}, "escalate"),
        ({"source": "peer", "kind": "task"}, "legion", {}, "reject"),
        ({"source": "peer", "kind": "task", "id": "t-3", "target": "rc"}, "legion", {}, "escalate"),
        (None, "legion", {}, "reject"),
    ]
    # Phase 2 cases - auto-action enabled, node_config wired
    legion_cfg = {
        "auto_read_patterns": ["tail .* log", "show .* state"],
        "auto_ops_verbs":     ["restart RC"],
        "escalate_always":    ["main.py", "core/log_setup.py"],
    }
    cases.extend([
        # auto-read pattern match
        ({"source": "peer", "kind": "task", "target": "legion", "id": "p2-1",
          "body": {"prompt": "tail today's log"}},
         "legion", {"node_config": legion_cfg, "auto_action_enabled": True},
         "auto-read"),
        # auto-ops verb match
        ({"source": "peer", "kind": "task", "target": "legion", "id": "p2-2",
          "body": {"prompt": "please restart RC"}},
         "legion", {"node_config": legion_cfg, "auto_action_enabled": True},
         "auto-ops"),
        # frozen-file intent: gate ALWAYS runs, even read patterns can't bypass
        ({"source": "peer", "kind": "task", "target": "legion", "id": "p2-3",
          "body": {"prompt": "edit main.py to add new mode"}},
         "legion", {"node_config": legion_cfg, "auto_action_enabled": True},
         "escalate"),
        # frozen-file READ (no verb) -> falls through to no-pattern -> escalate
        ({"source": "peer", "kind": "task", "target": "legion", "id": "p2-4",
          "body": {"prompt": "show me main.py last 20 lines"}},
         "legion", {"node_config": legion_cfg, "auto_action_enabled": True},
         "escalate"),  # no pattern match (would need "show .* main.py" pattern)
        # No pattern match -> escalate
        ({"source": "peer", "kind": "task", "target": "legion", "id": "p2-5",
          "body": {"prompt": "deploy to prod"}},
         "legion", {"node_config": legion_cfg, "auto_action_enabled": True},
         "escalate"),
        # auto-action disabled but pattern would match -> escalate (gate works)
        ({"source": "peer", "kind": "task", "target": "legion", "id": "p2-6",
          "body": {"prompt": "tail today's log"}},
         "legion", {"node_config": legion_cfg, "auto_action_enabled": False},
         "escalate"),
        # Frozen intent escalates BEFORE pattern check
        ({"source": "peer", "kind": "task", "target": "legion", "id": "p2-7",
          "body": {"prompt": "tail today's log then edit main.py"}},
         "legion", {"node_config": legion_cfg, "auto_action_enabled": True},
         "escalate"),
    ])
    fail = 0
    for env, node, kwargs, expected in cases:
        got, reason = classify(env, node=node, **kwargs)
        ok = got == expected
        marker = "OK " if ok else "FAIL"
        env_str = (str(env)[:60] + "...") if env and len(str(env)) > 60 else str(env)
        print(f"  [{marker}] node={node} {env_str} -> {got}  ({reason[:80]})")
        if not ok:
            fail += 1
    print(f"\n{len(cases) - fail}/{len(cases)} passed")
    raise SystemExit(0 if fail == 0 else 1)


if __name__ == "__main__":
    _test()
