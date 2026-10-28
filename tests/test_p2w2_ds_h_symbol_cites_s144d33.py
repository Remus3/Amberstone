"""Guard: the P2-W2 slice-H test cites by symbol, not line (RM-1053).

Measured 2026-10-28. tests/test_p2w2_ds_h.py listed 12 symbols with line
cites into the Phase 3 supervisor set, and every cite had drifted (cited
line -> line before this edit): ``_QuietHandler`` 27 -> 131, its
``_send_json`` 118 -> 314, ``_send_error`` 135 -> 335, ``_handle_input``
152 -> 361, ``_handle_adaptation`` 602 -> 823, ``spawn_ephemeral_llm``
102 -> 243, ``EphemeralSpawnFailed`` 45 -> 47, ``refresh_lock`` 359 -> 670,
``_atomic_write_json`` 226 -> 285, ``_STARTED_AT`` 170 -> 218,
``Supervisor.stop`` 315 -> 412 and ``InputParser`` 91 -> 112. A comment in
the spawn test cited the kit's git probe as ``fleet_headless.py:1613``; that
line is now inside an unrelated progress helper, and the probe is ``_git``.

Two prose claims had also gone false: the EphemeralSpawnFailed text no
longer reaches the /api/task/<id> body as ``last_error`` (RM-853: the
dispatcher stores ``TASK_FAILED_ERROR`` and the reply maps every value
through ``public_last_error``); the dispatcher still LOGS the text, which is
why the redaction stays. The tests below pin every claim the file's prose
makes, so a moved or deleted construct fails here.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TARGET = REPO / "tests" / "test_p2w2_ds_h.py"

_PATHS = {
    "_supervisor_http": REPO / "agents" / "_supervisor_http.py",
    "_supervisor_ephemeral": REPO / "agents" / "_supervisor_ephemeral.py",
    "_supervisor_common": REPO / "agents" / "_supervisor_common.py",
    "supervisor": REPO / "agents" / "supervisor.py",
    "input_parser": REPO / "agents" / "agent7_context" / "input_parser.py",
    "fleet_headless": REPO / "ops" / "fleet_kit" / "fleet_headless.py",
}

# ``(_supervisor_http.py:27)``, ``ops/fleet_kit/fleet_headless.py:1613``.
_LINE_CITE = re.compile(
    r"(?<![A-Za-z_])(?:_supervisor_\w+|supervisor|input_parser"
    r"|fleet_headless)\.py:\d"
)

# (label used in the symbol list, module key, dotted def / class).
_SYMBOLS = (
    ("_supervisor_http._QuietHandler", "_supervisor_http", "_QuietHandler"),
    ("_QuietHandler._send_json", "_supervisor_http",
     "_QuietHandler._send_json"),
    ("_QuietHandler._send_error", "_supervisor_http",
     "_QuietHandler._send_error"),
    ("_QuietHandler._handle_input", "_supervisor_http",
     "_QuietHandler._handle_input"),
    ("_QuietHandler._handle_adaptation", "_supervisor_http",
     "_QuietHandler._handle_adaptation"),
    ("_supervisor_http.public_last_error", "_supervisor_http",
     "public_last_error"),
    ("_supervisor_ephemeral.spawn_ephemeral_llm", "_supervisor_ephemeral",
     "spawn_ephemeral_llm"),
    ("_supervisor_ephemeral.EphemeralSpawnFailed", "_supervisor_ephemeral",
     "EphemeralSpawnFailed"),
    ("_supervisor_common.refresh_lock", "_supervisor_common",
     "refresh_lock"),
    ("_supervisor_common.acquire_lock", "_supervisor_common",
     "acquire_lock"),
    ("_supervisor_common._atomic_write_json", "_supervisor_common",
     "_atomic_write_json"),
    ("agents.supervisor.Supervisor.stop", "supervisor", "Supervisor.stop"),
    ("agent7_context.input_parser.InputParser", "input_parser",
     "InputParser"),
)

_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _source(key: str) -> str:
    return _PATHS[key].read_text(encoding="utf-8")


def _segment(key: str, dotted: str) -> str:
    src = _source(key)
    scope: list[ast.AST] = list(ast.parse(src).body)
    node: ast.AST | None = None
    for part in dotted.split("."):
        node = next(
            (n for n in scope if isinstance(n, _DEFS) and n.name == part),
            None,
        )
        assert node is not None, f"{key}.py has no {dotted}"
        scope = list(getattr(node, "body", []))
    return ast.get_source_segment(src, node) or ""


def _module_assign(key: str, name: str) -> ast.AST:
    for n in ast.parse(_source(key)).body:
        targets = (
            [n.target] if isinstance(n, ast.AnnAssign)
            else n.targets if isinstance(n, ast.Assign) else []
        )
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            return n
    raise AssertionError(f"{key}.py has no module-level {name}")


def test_pattern_matches_the_rotted_shapes():
    for sample in (
        "  _supervisor_http._QuietHandler                 (_supervisor_http.py:27)",
        "  _supervisor_common._STARTED_AT                 (_supervisor_common.py:170)",
        "  agents.supervisor.Supervisor.stop              (supervisor.py:315)",
        "  agent7_context.input_parser.InputParser        (input_parser.py:91)",
        "    #     ops/fleet_kit/fleet_headless.py:1613) - never the shared module",
    ):
        assert _LINE_CITE.search(sample), sample
    for sample in (
        "  _supervisor_http._QuietHandler",
        "agents/_supervisor_http.py, _supervisor_ephemeral.py,",
        "my_supervisor.py:12",
        "dps.py:284",
    ):
        assert not _LINE_CITE.search(sample), sample


def test_no_line_cite_left_in_target():
    hits = [
        f"{n}: {line.strip()}"
        for n, line in enumerate(
            TARGET.read_text(encoding="utf-8").splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


def test_every_listed_symbol_resolves():
    text = TARGET.read_text(encoding="utf-8")
    for label, key, dotted in _SYMBOLS:
        assert label in text, label
        _segment(key, dotted)
    assert "_supervisor_common._STARTED_AT" in text
    _module_assign("_supervisor_common", "_STARTED_AT")
    assert "_supervisor_http.TASK_FAILED_ERROR" in text
    _module_assign("_supervisor_http", "TASK_FAILED_ERROR")


def test_no_stale_last_error_wire_claim_left_in_target():
    text = TARGET.read_text(encoding="utf-8")
    assert "last_error`` -> the /api/task/<id> wire body" not in text
    assert "-> last_error -> the wire" not in text


def test_send_json_rejects_non_finite_tokens():
    body = _segment("_supervisor_http", "_QuietHandler._send_json")
    assert "allow_nan=False" in body


def test_send_error_keeps_the_cause_off_the_wire():
    body = _segment("_supervisor_http", "_QuietHandler._send_error")
    assert 'self._send_json(status, {"error": public_msg})' in body
    assert "log.warning(" in body


def test_spawn_failure_message_redacts_stderr():
    body = _segment("_supervisor_ephemeral", "spawn_ephemeral_llm")
    # The non-zero-exit raise; earlier raises cover setup failures.
    raise_at = body.find('f"claude exit {proc.returncode} for task')
    assert raise_at != -1
    assert "raise EphemeralSpawnFailed(" in body[raise_at - 60:raise_at]
    assert "_redact_secrets(proc.stderr" in body[raise_at:raise_at + 200]


def test_lock_writers_go_through_the_atomic_writer():
    for name in ("refresh_lock", "acquire_lock"):
        body = _segment("_supervisor_common", name)
        assert "_atomic_write_json(LOCKFILE" in body, name
    writer = _segment("_supervisor_common", "_atomic_write_json")
    assert "atomic_write_text(target, json.dumps(obj))" in writer


def test_stop_toggles_and_restores_raise_exceptions():
    body = _segment("supervisor", "Supervisor.stop")
    save = body.find("_prev_raise = logging.raiseExceptions")
    off = body.find("logging.raiseExceptions = False")
    restore = body.find("logging.raiseExceptions = _prev_raise")
    assert -1 not in (save, off, restore) and save < off < restore


def test_kit_git_probe_calls_subprocess_run():
    body = _segment("fleet_headless", "_git")
    assert "return subprocess.run(" in body
    assert "fleet_headless._git" in TARGET.read_text(encoding="utf-8")
