# arch: RC2 6.3 - SSE stream-level render dedup gate | section=web | frozen=no
"""Node-driven tests for web/js/lib/idempotent_render.js makeStreamGate().

RC2 6.3 client-side debounce/idempotency: the SSE intake in main.js runs the
full render pipeline on EVERY event, including the 15s forced heartbeat which
carries byte-identical data, and (with L4's 0.5s tick) any near-duplicate.
makeStreamGate() is the stream-level analogue of idempotentRender (which is
per-container): it holds the last payload signature and reports whether the
incoming payload actually changed, so the caller can skip a redundant
full-pipeline re-render while still updating liveness (state.lastSseTs).

Browser-free: the helper is a pure factory with no window/DOM deps, imported
directly in node. Mirrors tests/test_coach_choices_trigger_render.py.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MODULE = REPO / "web" / "js" / "lib" / "idempotent_render.js"


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


def test_first_payload_always_changed():
    out = _run_node(
        "import {makeStreamGate} from '__URI__';"
        "const g=makeStreamGate();"
        "process.stdout.write(JSON.stringify({a:g.changed('{\"x\":1}')}));"
    )
    assert out["a"] is True


def test_identical_payload_is_unchanged():
    out = _run_node(
        "import {makeStreamGate} from '__URI__';"
        "const g=makeStreamGate();"
        "const first=g.changed('{\"x\":1}');"
        "const dup=g.changed('{\"x\":1}');"
        "process.stdout.write(JSON.stringify({first,dup}));"
    )
    assert out["first"] is True
    assert out["dup"] is False


def test_changed_payload_passes_then_dedupes():
    out = _run_node(
        "import {makeStreamGate} from '__URI__';"
        "const g=makeStreamGate();"
        "const seq=[g.changed('A'),g.changed('A'),g.changed('B'),g.changed('B'),g.changed('A')];"
        "process.stdout.write(JSON.stringify({seq}));"
    )
    # A(new), A(dup), B(new), B(dup), A(new-again: gate holds only the LAST sig)
    assert out["seq"] == [True, False, True, False, True]


def test_reset_clears_last_sig():
    out = _run_node(
        "import {makeStreamGate} from '__URI__';"
        "const g=makeStreamGate();"
        "g.changed('A');"
        "const beforeReset=g.changed('A');"
        "g.reset();"
        "const afterReset=g.changed('A');"
        "process.stdout.write(JSON.stringify({beforeReset,afterReset}));"
    )
    assert out["beforeReset"] is False
    assert out["afterReset"] is True


def test_null_and_undefined_coerced_stably():
    # A null/undefined sig must coerce to a stable string so two nulls dedupe
    # (never throw on String(null)).
    out = _run_node(
        "import {makeStreamGate} from '__URI__';"
        "const g=makeStreamGate();"
        "const a=g.changed(null);"
        "const b=g.changed(null);"
        "process.stdout.write(JSON.stringify({a,b}));"
    )
    assert out["a"] is True
    assert out["b"] is False
