# arch: every web/js module must actually PARSE as an ES module | section=tests | frozen=no
"""Repo-wide guard: parse every `web/js/**/*.js` as a real ES module.

WHY THIS EXISTS, AND WHY `node --check` IS NOT ENOUGH. MEASURED 2026-07-31: a
duplicate `const st` in one scope of `web/js/panels/dev.js` killed the entire
Mission Control panel in the browser - the card rendered its placeholder and
nothing else. Every check in front of it was GREEN:

    node --check web/js/panels/dev.js                        -> exit 0
    node --input-type=module -e 'import("./.../dev.js")'     -> exit 1, line 753
    35 source-contract tests over the same file              -> all passed

The mechanism, isolated on node v24.15.0 with four one-file probes:

    duplicate const + `export default`        -> node --check exit 1  (caught)
    duplicate const, plain CommonJS           -> node --check exit 1  (caught)
    duplicate const + a leading `import ...`  -> node --check exit 0  (MISSED)
    same, duplicate inside a function body    -> node --check exit 0  (MISSED)

So `--check` goes blind on exactly the shape every module in this tree has: a
file that opens with `import`. RE-MEASURED 2026-11-12 (RM-2101): node v24.22.2
on the CI image ubuntu-26.04 (20261101.186, nightly run 43260688399) CATCHES
the third shape - `--check` exits 1 with "Identifier 'a' has already been
declared". The hole is therefore version-dependent, which is why the pin below
is too; the sweep is not, because the local runtime and an older CI image
still sit on the blind side. The source-level tests grep text rather than
running a parser, so they cannot see it either. Only a real module parse does.
The bug was found by loading the page and reading the console, which is the
slowest possible feedback loop for a one-token mistake.

So the guard is the module parse, run over the whole tree. It is fast (one node
process for the whole sweep) and it fails on exactly the class that a text grep
structurally cannot see: duplicate bindings, `await` outside async, a stray
brace, an import that is not at the top level.

Scope note: parsing is NOT executing. A module that parses can still throw at
runtime; that is what the panel contract tests and the live checks are for.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_JS = ROOT / "web" / "js"

# THE web/mc TREE IS GONE, AND REMOVING IT FROM THIS SWEEP IS THE WHOLE POINT
# OF THIS COMMENT. The Mission Control web UI was retired, taking mc.js and
# arm_confirm.js with it. A second root was listed here; leaving it listed
# would have been the ADR-015 empty-enumeration trap in its purest form,
# because `Path.rglob` on a missing directory yields nothing and does NOT
# raise. web/js alone clears the `assert files` floor below, so the sweep would
# have stayed GREEN while two modules silently left its corpus and the
# docstring above quietly became false. The root is DELETED rather than left
# to fail, and the floor is now a claim about a tree that exists.
_SKIP_SUFFIXES = (".test.mjs",)


def _modules() -> list[Path]:
    return sorted(
        p
        for p in WEB_JS.rglob("*.js")
        if not p.name.endswith(_SKIP_SUFFIXES)
    )


# RM-2101: the two MEASURED `node --check` outcomes on the import-leading probe
# in test_node_check_goes_blind_on_a_file_that_leads_with_import. Both bounds
# are measurements, not guesses; the fix landed somewhere in
# (_LAST_MEASURED_BLIND, _FIRST_MEASURED_CAUGHT] and nothing in between was run.
#   blind:  node v24.15.0, local, 2026-07-31 (exit 0; module docstring).
#   caught: node v24.22.2, CI image ubuntu-26.04 20261101.186, nightly run
#           43260688399, 2026-11-12 (exit 1, "Identifier 'a' has already been
#           declared"; version read from the node stderr in that run's log).
# Assumptions, stated because each one decides a branch:
#   1. Every release AT OR AFTER 24.22.2 keeps the fix, later majors included.
#      If one measures blind, the pin goes red; record it as a new data point,
#      never by weakening the sweep.
#   2. Every release AT OR BELOW 24.15.0 is blind. Only 24.15.0 itself was
#      measured; the rest inherits the pre-RM-2101 pin, which asserted blind on
#      every version.
#   3. Strictly between the bounds the outcome is UNMEASURED, so the pin
#      accepts either exit code there rather than invent a threshold. A run on
#      such a version that wants to narrow the gap moves one bound to it.
_LAST_MEASURED_BLIND = (24, 15, 0)
_FIRST_MEASURED_CAUGHT = (24, 22, 2)

_NODE_VERSION_RE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)(?:[-+]\S*)?")


def _parse_node_version(text: str) -> tuple[int, int, int]:
    """`node --version` output -> (major, minor, patch); raises on anything else."""
    m = _NODE_VERSION_RE.fullmatch(text.strip())
    if m is None:
        raise ValueError(f"not a node version string: {text!r}")
    major, minor, patch = (int(g) for g in m.groups())
    return (major, minor, patch)


def _expected_node_check_outcome(version: tuple[int, int, int]) -> str:
    """'blind' | 'caught' | 'unmeasured' for `node --check` on the probe."""
    if version <= _LAST_MEASURED_BLIND:
        return "blind"
    if version >= _FIRST_MEASURED_CAUGHT:
        return "caught"
    return "unmeasured"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_every_web_js_module_parses_as_an_es_module():
    """One node process, every module, real ESM parse.

    `import()` is used rather than `--check` because that is the difference the
    measurement turned on. The dynamic import is not awaited to completion for
    side effects - a parse error rejects the promise, which is what is caught.
    """
    files = _modules()
    # 90 modules measured 2026-09-20, after web/mc/ left the sweep. The floor
    # sits below that so it is a floor and not a pin, but far enough above
    # zero that a collapsed glob cannot pass.
    assert len(files) >= 80, (
        f"only {len(files)} web/js modules found - the glob is wrong, not the "
        "tree. A bare `assert files` would pass on a single surviving module, "
        "which is how a tree silently leaves a sweep.")

    script = r"""
const files = JSON.parse(process.argv[1]);
const bad = [];
// A timer a module registered while it evaluated, and that throws later
// (no DOM in node), is a runtime throw too - out of scope like the catch
// below - and must not crash the harness before it reports. S144-U-264:
// map_state.js's import stopped throwing at its top, so its 1 s spell
// tick now runs here and reads `document`.
process.on('uncaughtException', (e) => {
  if (e && e.name === 'SyntaxError') bad.push({file: '<timer>', msg: String(e.message)});
});
(async () => {
  for (const f of files) {
    try {
      await import('file:///' + f.replace(/\\/g, '/').replace(/ /g, '%20'));
    } catch (e) {
      // A module that PARSES but throws on evaluation is out of scope here -
      // only syntax is being asserted. Everything else is a real finding.
      if (e && e.name === 'SyntaxError') bad.push({file: f, msg: String(e.message)});
    }
  }
  console.log(JSON.stringify(bad));
  // Exit now: a module timer must not run on after the report.
  process.exit(0);
})();
"""
    out = subprocess.run(
        ["node", "--input-type=module", "-e", script, json.dumps([str(f) for f in files])],
        capture_output=True, text=True, timeout=180, cwd=str(ROOT), check=False,
    )
    assert out.returncode == 0, f"node harness failed: {out.stderr[-800:]}"
    tail = (out.stdout or "").strip().splitlines()
    bad = json.loads(tail[-1]) if tail else []
    assert not bad, "web/js modules with SYNTAX errors:\n" + "\n".join(
        f"  {b['file']}: {b['msg']}" for b in bad)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_node_check_goes_blind_on_a_file_that_leads_with_import(tmp_path):
    """Pins the measurement this file exists for.

    The probe deliberately has the SHAPE of a real module here - it opens with
    an `import` - because that is the shape `--check` misses. A probe that opens
    with `export` is caught, which is why the earlier version of this test
    'proved' the opposite of the real behaviour.

    RM-2101: the expected `--check` outcome now follows the running Node's
    version (`_expected_node_check_outcome`): blind where blindness was
    measured, caught where the catch was measured, either way in the unmeasured
    gap between. The ESM parse must raise SyntaxError on EVERY version - that
    half is the sweep's own premise and is never relaxed. If a Node contradicts
    its region the test goes red; record the new measurement in the bounds
    above rather than weakening the sweep, because the sweep is right either way.
    """
    ver = subprocess.run(["node", "--version"],
                         capture_output=True, text=True, timeout=60, check=False)
    assert ver.returncode == 0, f"node --version failed: {ver.stderr[-400:]}"
    version = _parse_node_version(ver.stdout)
    expected = _expected_node_check_outcome(version)

    (tmp_path / "other.js").write_text("export const x = 1;\n", encoding="utf-8")
    probe = tmp_path / "probe.js"
    probe.write_text(
        'import { x } from "./other.js";\n'
        "function f() {\n  const a = 1;\n  const a = 2;\n  return [a, x];\n}\n"
        "export default f;\n",
        encoding="utf-8")

    chk = subprocess.run(["node", "--check", str(probe)],
                         capture_output=True, text=True, timeout=60, check=False)
    esm = subprocess.run(
        ["node", "--input-type=module", "-e",
         "import('file:///' + process.argv[1].replace(/\\\\/g,'/').replace(/ /g,'%20'))"
         ".then(()=>process.exit(0)).catch(e=>process.exit(e && e.name === 'SyntaxError' ? 1 : 2))",
         str(probe)],
        capture_output=True, text=True, timeout=60, check=False)

    shown = "v{}.{}.{}".format(*version)
    if expected == "blind":
        assert chk.returncode == 0, (
            f"node {shown} --check now CATCHES a duplicate const in an "
            "import-leading file, inside the measured-blind region - record "
            "the new measurement in _LAST_MEASURED_BLIND / "
            "_FIRST_MEASURED_CAUGHT and the module docstring; do NOT drop the "
            "ESM sweep")
    elif expected == "caught":
        assert chk.returncode != 0, (
            f"node {shown} --check is BLIND again on a duplicate const in an "
            "import-leading file, inside the measured-caught region - record "
            "the new measurement in the bounds above; the ESM sweep stays")
    # "unmeasured": either exit code is accepted; nothing pinned it there.
    assert esm.returncode == 1, (
        f"node {shown}: the ESM parse must raise SyntaxError on the probe "
        f"(--check exit {chk.returncode}); the sweep depends on it")


# RM-2101: the pure decision the live pin above turns on, covered on BOTH sides
# without needing a second Node install. Neither test needs node on PATH.

@pytest.mark.parametrize(("text", "want"), [
    ("v24.15.0\n", (24, 15, 0)),
    ("v24.22.2", (24, 22, 2)),
    ("24.22.2", (24, 22, 2)),
    ("v26.0.0-nightly20261101abcdef", (26, 0, 0)),
])
def test_node_version_text_parses_to_a_tuple(text, want):
    assert _parse_node_version(text) == want


@pytest.mark.parametrize("text", ["", "node", "v24.15", "Node.js v24.22.2"])
def test_unparseable_node_version_text_raises(text):
    # Fail loud: a version that silently parsed to (0, 0, 0) would land in the
    # "blind" region and re-pin the hole on a Node nobody measured.
    with pytest.raises(ValueError):
        _parse_node_version(text)


@pytest.mark.parametrize(("version", "want"), [
    # measured blind (local, 2026-07-31) and everything at or below it
    ((24, 15, 0), "blind"),
    ((24, 14, 9), "blind"),
    # measured caught (CI nightly 43260688399, 2026-11-12) and everything after
    ((24, 22, 2), "caught"),
    ((24, 22, 3), "caught"),
    ((24, 23, 0), "caught"),
    ((26, 1, 0), "caught"),
    # strictly between the two measurements: nobody ran the probe there
    ((24, 15, 1), "unmeasured"),
    ((24, 16, 0), "unmeasured"),
    ((24, 22, 1), "unmeasured"),
])
def test_expected_node_check_outcome_follows_the_measured_bounds(version, want):
    assert _expected_node_check_outcome(version) == want


def test_the_measured_bounds_do_not_overlap():
    # If a new measurement is recorded with the bounds crossed, one version
    # would be both "blind" and "caught" and the first branch would silently
    # win. Pin the ordering so that edit fails here instead.
    assert _LAST_MEASURED_BLIND < _FIRST_MEASURED_CAUGHT
