"""RM-452: the `tools/rc_facts.py` entrypoint dispatch, one arm per branch.

WHY THIS EXISTS. The flag dispatch and the session-id derivation used to sit
inline under `if __name__ == "__main__":`, where no in-process test could reach
them. Measured before the lift: the only subprocess-launched tests
(tests/test_hook_invocation_log.py, tests/test_inbox_reported_record.py) run
`--inbox-only`; neither the default SessionStart branch nor `--mark-inbox-seen`
nor the session-id hand-off was asserted anywhere.

The dispatch now lives in `_cli(argv)` and the `__main__` block only calls it.
Every arm stubs the branch targets (`main`, `report_inbox_only`,
`mark_inbox_seen`, `record_invocation`, the stdin reader), so no port, HTTP,
LCU or inbox probe runs and no store is written.

MUTATION ARMS ARE DURABLE. Each mutant is applied to the module SOURCE in
memory, executed into a fresh module object, and the named arm must FAIL
against it. A control arm runs every branch arm against the unmutated source
through the same exec path, so a mutant failure cannot be an exec artifact.
"""

from __future__ import annotations

import ast
import sys
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from tools import rc_facts  # noqa: E402

_SRC_PATH = _ROOT / "tools" / "rc_facts.py"
_VALID_SID = "0a1b2c3d-feed-4bad-8cab-123456789abc"
_PAYLOAD = {"hook_event_name": "ignored", "session_id": _VALID_SID}


class _Stubs:
    """Replaces every branch target on `mod` and records what was called."""

    def __init__(self, mod, payload=None, why="json"):
        self.calls: list[tuple] = []
        payload = dict(_PAYLOAD) if payload is None else payload
        self.payload = payload

        def reader(stream=None):
            self.calls.append(("read",))
            return payload, why

        def record(event, pl=None, path=None, stdin_state="n/a"):
            self.calls.append(("record", event, pl, stdin_state))

        def fake_main(session=None):
            self.calls.append(("main", session))
            return 3

        def fake_report(session=None):
            self.calls.append(("report", session))
            return 5

        def fake_mark():
            self.calls.append(("mark",))
            return 7

        mod._read_hook_payload_with_reason = reader
        mod.record_invocation = record
        mod.main = fake_main
        mod.report_inbox_only = fake_report
        mod.mark_inbox_seen = fake_mark

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]


# ---------------------------------------------------------------- the arms
# Each takes a module object so the same assertion runs against the real
# module, the exec'd control, and every mutant.


def arm_mark_inbox_seen(mod):
    s = _Stubs(mod)
    rc = mod._cli(["rc_facts.py", "--mark-inbox-seen"])
    assert rc == 7
    # A deliberate operator act: no stdin read, no hook record, no report.
    assert s.names() == ["mark"], s.calls


def arm_mark_wins_over_inbox_only(mod):
    s = _Stubs(mod)
    rc = mod._cli(["rc_facts.py", "--inbox-only", "--mark-inbox-seen"])
    assert rc == 7
    assert s.names() == ["mark"], s.calls


def arm_inbox_only(mod):
    s = _Stubs(mod)
    rc = mod._cli(["rc_facts.py", "--inbox-only"])
    assert rc == 5
    assert s.calls == [
        ("read",),
        ("record", "UserPromptSubmit", s.payload, "json"),
        ("report", _VALID_SID),
    ], s.calls


def arm_default_sessionstart(mod):
    s = _Stubs(mod, why="empty")
    rc = mod._cli(["rc_facts.py"])
    assert rc == 3
    assert s.calls == [
        ("read",),
        ("record", "SessionStart", s.payload, "empty"),
        ("main", _VALID_SID),
    ], s.calls


def arm_invalid_session_id_is_not_handed_on(mod):
    """`_session_id` validation stays in the path: a hostile id becomes None."""
    s = _Stubs(mod, payload={"session_id": "..\\..\\evil"})
    assert mod._cli(["rc_facts.py"]) == 3
    assert s.calls[-1] == ("main", None), s.calls


_ARMS = {
    "mark": arm_mark_inbox_seen,
    "mark-precedence": arm_mark_wins_over_inbox_only,
    "inbox-only": arm_inbox_only,
    "default": arm_default_sessionstart,
    "invalid-sid": arm_invalid_session_id_is_not_handed_on,
}


@pytest.mark.parametrize("name", sorted(_ARMS))
def test_branch_against_the_real_module(name, monkeypatch):
    # monkeypatch every attribute the stubs replace so the real module is
    # restored for the rest of the session.
    for attr in ("_read_hook_payload_with_reason", "record_invocation", "main",
                 "report_inbox_only", "mark_inbox_seen"):
        monkeypatch.setattr(rc_facts, attr, getattr(rc_facts, attr))
    _ARMS[name](rc_facts)


# ------------------------------------------------------ the __main__ wiring


def _main_block(tree: ast.Module) -> ast.If:
    blocks = [n for n in tree.body if isinstance(n, ast.If)
              and isinstance(n.test, ast.Compare)
              and isinstance(n.test.left, ast.Name) and n.test.left.id == "__name__"]
    assert len(blocks) == 1, "expected exactly one `if __name__ == ...` block"
    return blocks[0]


def _check_main_block_calls_cli(source: str) -> None:
    block = _main_block(ast.parse(source))
    assert len(block.body) == 1, "the __main__ block must only call _cli"
    got = ast.unparse(block.body[0])
    assert got == "sys.exit(_cli(sys.argv))", got


def test_main_block_only_delegates_to_cli():
    _check_main_block_calls_cli(_SRC_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------- mutation arms


def _exec_module(source: str) -> types.ModuleType:
    mod = types.ModuleType("rc_facts_mutant")
    mod.__file__ = str(_SRC_PATH)
    exec(compile(source, str(_SRC_PATH), "exec"), mod.__dict__)  # noqa: S102
    return mod


def _cli_segment(source: str) -> tuple[int, int]:
    start = source.index("def _cli(")
    end = source.index("\n\n\n", start)
    return start, end


# (mutant id, old text inside _cli, new text, arm that must kill it)
_CLI_MUTANTS = [
    ("mark-falls-through", "return mark_inbox_seen()", "mark_inbox_seen()", "mark"),
    ("mark-flag-position-sensitive",'if "--mark-inbox-seen" in argv:', 'if "--mark-inbox-seen" in argv[:2]:',
     "mark-precedence"),
    ("inbox-wrong-event", 'record_invocation("UserPromptSubmit"', 'record_invocation("SessionStart"',
     "inbox-only"),
    ("inbox-calls-main", "return report_inbox_only(session=sid)", "return main(session=sid)",
     "inbox-only"),
    ("default-no-record",
     'record_invocation("SessionStart", payload, stdin_state=why)\n    return main(',
     "return main(", "default"),
    ("default-drops-sid", "return main(session=sid)", "return main(session=None)", "default"),
    ("sid-unvalidated", "sid = _session_id(payload)", "sid = payload.get('session_id')",
     "invalid-sid"),
]


def _mutate_cli(source: str, old: str, new: str) -> str:
    start, end = _cli_segment(source)
    seg = source[start:end]
    assert seg.count(old) == 1, f"mutant anchor {old!r} is not unique in _cli"
    return source[:start] + seg.replace(old, new) + source[end:]


def test_control_every_arm_passes_on_the_exec_path():
    mod = _exec_module(_SRC_PATH.read_text(encoding="utf-8"))
    for arm in _ARMS.values():
        arm(mod)


@pytest.mark.parametrize("mid,old,new,arm", _CLI_MUTANTS, ids=[m[0] for m in _CLI_MUTANTS])
def test_each_cli_mutant_is_killed_by_its_arm(mid, old, new, arm):
    mutated = _mutate_cli(_SRC_PATH.read_text(encoding="utf-8"), old, new)
    mod = _exec_module(mutated)
    with pytest.raises(AssertionError):
        _ARMS[arm](mod)


@pytest.mark.parametrize("new", ["sys.exit(_cli([]))", "sys.exit(main())",
                                 "sys.exit(_cli(sys.argv))\n    main()"])
def test_main_block_mutant_is_killed(new):
    source = _SRC_PATH.read_text(encoding="utf-8")
    old = "    sys.exit(_cli(sys.argv))"
    assert source.count(old) == 1
    mutated = source.replace(old, "    " + new)
    with pytest.raises(AssertionError):
        _check_main_block_calls_cli(mutated)
