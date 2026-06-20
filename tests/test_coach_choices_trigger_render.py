# arch: RC2 5.3 - coach choice chip renders the trigger condition sub-line | section=web | frozen=no
"""Node-driven render tests for the RC2 5.3 trigger sub-line.

web/js/panels/coach_choices.js gains a `.rc-trigger` sub-line under the chip
label that shows the live CONDITION the option assumes (CoachChoice.trigger).
These are browser-free: they import the module's `_internals` (the bind of the
Alt+digit keydown handler is guarded by `typeof window`, so the ESM import is
node-safe) and assert `_chipHtml` / `_chipsSignature` behavior directly.

Mirrors the node-subprocess pattern in tests/snapshot_panels/test_xss_escaping.py.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MODULE = REPO / "web" / "js" / "panels" / "coach_choices.js"


def _run_node(script: str) -> dict:
    node = shutil.which("node")
    if not node:  # pragma: no cover - node is present on Legion
        pytest.skip("node not on PATH")
    uri = MODULE.resolve().as_uri()
    full = script.replace("__URI__", uri)
    res = subprocess.run(
        [node, "--input-type=module", "-e", full],
        capture_output=True, text=True, cwd=str(REPO), timeout=30,
    )
    assert res.returncode == 0, f"node failed: {res.stderr.strip()}"
    return json.loads(res.stdout)


def test_chip_html_renders_trigger_sub_line():
    out = _run_node(
        "import {_internals} from '__URI__';"
        "const h=_internals._chipHtml({key:'A',label:'Trade now',"
        "  trigger:'Zed, lvl 6',confidence:'mid'});"
        "process.stdout.write(JSON.stringify({h}));"
    )
    assert "rc-trigger" in out["h"]
    assert "rc-labelcol" in out["h"]
    assert "Zed, lvl 6" in out["h"]


def test_chip_html_omits_trigger_when_empty():
    out = _run_node(
        "import {_internals} from '__URI__';"
        "const h=_internals._chipHtml({key:'A',label:'Trade now',confidence:'mid'});"
        "process.stdout.write(JSON.stringify({h}));"
    )
    assert "rc-trigger" not in out["h"]
    # The labelcol wrapper still renders so the chip layout is stable.
    assert "rc-labelcol" in out["h"]


def test_chip_html_escapes_trigger():
    out = _run_node(
        "import {_internals} from '__URI__';"
        "const h=_internals._chipHtml({key:'A',label:'x',"
        "  trigger:'<img src=q onerror=1>',confidence:'mid'});"
        "process.stdout.write(JSON.stringify({h}));"
    )
    assert "<img" not in out["h"]
    assert "&lt;img" in out["h"]


def test_signature_changes_with_trigger():
    out = _run_node(
        "import {_internals} from '__URI__';"
        "const a=_internals._chipsSignature([{key:'A',label:'x',"
        "  confidence:'mid',trigger:'t1'}]);"
        "const b=_internals._chipsSignature([{key:'A',label:'x',"
        "  confidence:'mid',trigger:'t2'}]);"
        "process.stdout.write(JSON.stringify({a,b}));"
    )
    assert out["a"] != out["b"]


# --------------------------------------------------------------------------- #
# RC2 5.4 - the rebranch ("-> B if ...") condition-change sub-line.
# --------------------------------------------------------------------------- #
def test_chip_html_renders_rebranch_sub_line():
    out = _run_node(
        "import {_internals} from '__URI__';"
        "const h=_internals._chipHtml({key:'A',label:'All in now',"
        "  rebranch_when:'if Caitlyn goes missing',rebranch_to:'B',"
        "  confidence:'high'});"
        "process.stdout.write(JSON.stringify({h}));"
    )
    assert "rc-rebranch" in out["h"]
    assert "if Caitlyn goes missing" in out["h"]
    # The target key letter renders so the operator knows which chip to switch to.
    assert "B" in out["h"]


def test_chip_html_omits_rebranch_when_incomplete():
    # Both rebranch_when AND rebranch_to are required to render the hint.
    out = _run_node(
        "import {_internals} from '__URI__';"
        "const only_when=_internals._chipHtml({key:'A',label:'x',"
        "  rebranch_when:'if enemy roams',confidence:'mid'});"
        "const only_to=_internals._chipHtml({key:'A',label:'x',"
        "  rebranch_to:'B',confidence:'mid'});"
        "const none=_internals._chipHtml({key:'A',label:'x',confidence:'mid'});"
        "process.stdout.write(JSON.stringify({only_when,only_to,none}));"
    )
    assert "rc-rebranch" not in out["only_when"]
    assert "rc-rebranch" not in out["only_to"]
    assert "rc-rebranch" not in out["none"]


def test_chip_html_escapes_rebranch():
    out = _run_node(
        "import {_internals} from '__URI__';"
        "const h=_internals._chipHtml({key:'A',label:'x',"
        "  rebranch_when:'<img src=q onerror=1>',rebranch_to:'B',"
        "  confidence:'mid'});"
        "process.stdout.write(JSON.stringify({h}));"
    )
    assert "<img" not in out["h"]
    assert "&lt;img" in out["h"]


def test_signature_changes_with_rebranch():
    out = _run_node(
        "import {_internals} from '__URI__';"
        "const a=_internals._chipsSignature([{key:'A',label:'x',"
        "  confidence:'mid',rebranch_when:'w1',rebranch_to:'B'}]);"
        "const b=_internals._chipsSignature([{key:'A',label:'x',"
        "  confidence:'mid',rebranch_when:'w2',rebranch_to:'B'}]);"
        "process.stdout.write(JSON.stringify({a,b}));"
    )
    assert out["a"] != out["b"]
