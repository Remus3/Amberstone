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
file that opens with `import`. The source-level tests grep text rather than
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
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_JS = ROOT / "web" / "js"

# Test doubles live beside their modules and are already run by `node --test`.
_SKIP_SUFFIXES = (".test.mjs",)


def _modules() -> list[Path]:
    return sorted(p for p in WEB_JS.rglob("*.js")
                  if not p.name.endswith(_SKIP_SUFFIXES))


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_every_web_js_module_parses_as_an_es_module():
    """One node process, every module, real ESM parse.

    `import()` is used rather than `--check` because that is the difference the
    measurement turned on. The dynamic import is not awaited to completion for
    side effects - a parse error rejects the promise, which is what is caught.
    """
    files = _modules()
    assert files, "no web/js modules found - the glob is wrong, not the tree"

    script = r"""
const files = JSON.parse(process.argv[1]);
const bad = [];
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
})();
"""
    out = subprocess.run(
        ["node", "--input-type=module", "-e", script, json.dumps([str(f) for f in files])],
        capture_output=True, text=True, timeout=180, cwd=str(ROOT),
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

    If a future Node closes this hole the test goes red; correct the docstring
    above rather than weakening the sweep, because the sweep is right either way.
    """
    (tmp_path / "other.js").write_text("export const x = 1;\n", encoding="utf-8")
    probe = tmp_path / "probe.js"
    probe.write_text(
        'import { x } from "./other.js";\n'
        "function f() {\n  const a = 1;\n  const a = 2;\n  return [a, x];\n}\n"
        "export default f;\n",
        encoding="utf-8")

    chk = subprocess.run(["node", "--check", str(probe)],
                         capture_output=True, text=True, timeout=60)
    esm = subprocess.run(
        ["node", "--input-type=module", "-e",
         "import('file:///' + process.argv[1].replace(/\\\\/g,'/').replace(/ /g,'%20'))"
         ".then(()=>process.exit(0)).catch(e=>process.exit(e && e.name === 'SyntaxError' ? 1 : 2))",
         str(probe)],
        capture_output=True, text=True, timeout=60)

    assert chk.returncode == 0, (
        "node --check now CATCHES a duplicate const in an import-leading file - "
        "update the docstring above; do NOT drop the ESM sweep")
    assert esm.returncode == 1, (
        "the ESM parse must raise SyntaxError where --check stayed silent")
