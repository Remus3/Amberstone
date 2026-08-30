# arch: guard - no held-handle fault injection against the atomic writers | section=tests | frozen=no
"""LANE 8 CYCLE 26 - stop this lane reintroducing win32-only regression tests.

THE DEFECT THIS GUARD EXISTS FOR
--------------------------------
Five lane-8 cycles reproduced a failed atomic write by opening the destination
file and letting the operating system supply the fault::

    with open(target, encoding="utf-8"):
        with self.assertRaises(PermissionError):
            atomic_write_json(target, payload)

On win32 an open read handle share-locks the destination, so ``os.replace``
raises PermissionError (WinError 5) and the test passes on the machine that
wrote it. On POSIX the rename goes straight through. The asymmetry is what
makes this worth a guard rather than a code review note:

  * a test ASSERTING the failure goes RED on Linux - 9 of them did, on GitHub
    run 33332566593, and they had accumulated across cycles 12, 13, 20, 21 and
    23 before anyone counted them together;
  * a test asserting only the CLEANUP AFTER a failure goes vacuously GREEN,
    because no fault occurred and there was nothing to clean up. Those never
    appear in a CI failure list at all, which is why the count kept growing.

The consequence was that the exhaustion branch of
``core.polled_json._replace_with_retry`` - the re-raise after the last backoff,
in the primitive every polled writer in the tree funnels through - had never
executed on Linux. Its failure path was covered only by an accident of Windows
file-locking semantics.

THE REPLACEMENT
---------------
``tests/_replace_faults.replace_fails`` injects the fault at the ``os.replace``
boundary instead of borrowing it from the OS, so the retry loop, the backoff,
the scratch-file cleanup and the re-raise run identically everywhere. A
platform-gated test alongside it asserts the narrower OS-shaped claim - that a
held handle really does still share-lock a destination here - which is the only
part that was ever genuinely about Windows.

WHAT THIS GUARD ACTUALLY CHECKS, AND WHAT IT DOES NOT
-----------------------------------------------------
Stated plainly so the name cannot overclaim (feedback_guard_domain_narrower_
than_its_name): this guard is a STATIC check for a direct call to one of the
repo's named atomic-write helpers lexically inside a ``with open(...)`` block,
in a test that is not platform-gated.

It does NOT catch:
  * an indirect write - a route handler, a coach, or any wrapper that reaches a
    writer several frames down. ``_post({"action": "stop"})`` eventually writes
    STOP, and no static check can see that.
  * a held handle opened via ``os.open``, ``io.open``, a fixture, or a thread.
  * the same idiom in a non-test module.

So it is a ratchet on the commonest shape, not a proof of absence. The durable
protection is ``replace_fails`` itself, which raises when it never fires, so a
test built on it cannot pass vacuously.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_TESTS = _ROOT / "tests"

# Direct calls to these are the guarded domain. Keep this list in sync with the
# real writer surface - test_writer_list_covers_the_polled_json_surface below
# fails if core/polled_json.py grows a public writer this list does not name.
_ATOMIC_WRITERS = frozenset({
    "atomic_write_json",
    "atomic_write_bytes",
    "atomic_write_text",
    "_atomic_write_json",
    "_atomic_write_bytes",
    "_atomic_write_text",
    "_write_then_replace",
    "_replace_with_retry",
    "_write_pending",
})

# Substrings that mark a function or class as deliberately platform-gated. A
# gated test MAY use the real held-handle idiom - that is the point of the
# real-OS companion test.
_GATE_MARKERS = ("skipif", "skipunless", "sys.platform", "os.name",
                 "platform.system", "win32")


def _label(path: Path) -> str:
    """Repo-relative where possible - the self-test feeds in tmp_path files,
    which are not under the repo root and must not crash the reporter."""
    try:
        return path.relative_to(_ROOT).as_posix()
    except ValueError:
        return path.name


def _decorator_text(node: ast.AST) -> str:
    out = []
    for d in getattr(node, "decorator_list", []):
        try:
            out.append(ast.unparse(d))
        except Exception:  # noqa: BLE001 - unparse is best-effort diagnostics
            out.append("")
    return " ".join(out).lower()


def _is_open_call(node: ast.AST) -> bool:
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "open")


def _called_names(node: ast.AST) -> set[str]:
    names = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            fn = sub.func
            if isinstance(fn, ast.Name):
                names.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                names.add(fn.attr)
    return names


def _violations_in(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError as exc:  # a broken test file is a different failure
        return [f"{path.name}: unparseable ({exc})"]

    # A gate on the enclosing function OR its class counts, so the flag is
    # threaded down the walk rather than looked up per node.
    out: list[str] = []

    def _walk(node: ast.AST, gate: bool) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            text = _decorator_text(node)
            gate = gate or any(m in text for m in _GATE_MARKERS)
        if isinstance(node, ast.With) and any(
                _is_open_call(item.context_expr) for item in node.items):
            hits = _called_names(node) & _ATOMIC_WRITERS
            if hits and not gate:
                out.append(
                    f"{_label(path)}:{node.lineno}: "
                    f"held open() handle used as the fault injector for "
                    f"{sorted(hits)}")
        for child in ast.iter_child_nodes(node):
            _walk(child, gate)

    _walk(tree, False)
    return out


def test_no_test_uses_a_held_handle_to_fault_an_atomic_writer():
    """The ratchet. See the module docstring for the exact domain."""
    offenders: list[str] = []
    for path in sorted(_TESTS.rglob("test_*.py")):
        offenders.extend(_violations_in(path))
    assert offenders == [], (
        "A held open() handle is a win32-only fault injector: on POSIX the "
        "rename succeeds, so these tests are RED (if they assert the failure) "
        "or vacuously GREEN (if they assert the cleanup after it).\n"
        "Use tests/_replace_faults.replace_fails(target) to inject the fault "
        "at the os.replace boundary, which runs on every platform, and put "
        "any genuinely OS-shaped assertion in a platform-gated test.\n"
        + "\n".join(offenders)
    )


def test_writer_list_covers_the_polled_json_surface():
    """Keep _ATOMIC_WRITERS honest as core/polled_json grows.

    Without this, a new public writer would be silently outside the guard's
    domain and the ratchet would quietly stop ratcheting - the guard would stay
    green while covering less (reference_guard_can_be_green_while_self_
    excusing).
    """
    src = (_ROOT / "core" / "polled_json.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    public_writers = {
        n.name for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name.startswith("atomic_write")
    }
    assert public_writers, "parsed no atomic_write* helpers - has the file moved?"
    missing = sorted(public_writers - _ATOMIC_WRITERS)
    assert not missing, (
        f"core/polled_json.py exports {missing} which this guard does not "
        f"name, so the idiom would go uncaught against them. Add them to "
        f"_ATOMIC_WRITERS."
    )


def test_the_guard_actually_fires_on_the_shape_it_names(tmp_path):
    """Mutation-proof the guard itself.

    A static checker that silently matches nothing is the exact failure it was
    written to prevent, and it would look identical to a clean tree
    (feedback_empty_grep_is_a_claim_about_the_pattern). So feed it the real
    pre-fix shape and require a hit, then feed it the gated and the fixed
    shapes and require silence.
    """
    offending = tmp_path / "test_offender.py"
    offending.write_text(
        "def test_x(tmp_path):\n"
        "    p = tmp_path / 'f.json'\n"
        "    with open(p, encoding='utf-8'):\n"
        "        atomic_write_json(p, {})\n",
        encoding="utf-8")
    assert _violations_in(offending), (
        "the guard did not flag the exact idiom it exists to flag")

    gated = tmp_path / "test_gated.py"
    gated.write_text(
        "import pytest\n"
        "@pytest.mark.skipif(sys.platform != 'win32', reason='win32 only')\n"
        "def test_x(tmp_path):\n"
        "    p = tmp_path / 'f.json'\n"
        "    with open(p, encoding='utf-8'):\n"
        "        atomic_write_json(p, {})\n",
        encoding="utf-8")
    assert _violations_in(gated) == [], (
        "a deliberately platform-gated real-OS test must be allowed")

    fixed = tmp_path / "test_fixed.py"
    fixed.write_text(
        "def test_x(tmp_path):\n"
        "    p = tmp_path / 'f.json'\n"
        "    with replace_fails(p):\n"
        "        atomic_write_json(p, {})\n",
        encoding="utf-8")
    assert _violations_in(fixed) == [], "the portable replacement must pass"


def test_the_replace_faults_helper_is_present_and_refuses_to_pass_vacuously():
    """The guard points every reader at replace_fails, so pin that it exists
    and that its no-fire assertion is real - the pointer is worthless if the
    helper it names can itself produce a silent green."""
    from tests._replace_faults import replace_fails

    with pytest.raises(AssertionError, match="never fired"):
        with replace_fails(_ROOT / "no" / "such" / "file.json"):
            pass
