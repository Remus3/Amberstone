# arch: R213 - ARAM balance panel fetch-failure must not poison the cache | section=web | frozen=no
"""Node-driven regression tests for the ARAM balance panel's fetch failure path.

`web/js/panels/aram_balance.js` caches the `/api/aram-balance` map client-side
and re-fetches only while the cache is `null`. Before R213 the failure branches
assigned `{}` instead, so `{}` is not `null` and the one-shot fetch NEVER
retried: a single transient blip made every row render the positive claim
"no ARAM changes" for the rest of the page lifetime - the exact silent-wrong
answer CLAUDE.md "Error Handling" forbids, and a direct contradiction of the
module's own comment promising a retry.

These import the REAL module and drive the REAL function with a stubbed
`globalThis.fetch`; nothing here pins source text. Mirrors the node-subprocess
pattern in tests/test_coach_choices_trigger_render.py.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MODULE = REPO / "web" / "js" / "panels" / "aram_balance.js"

_PRELUDE = "import {__test} from '__URI__';const {_AB,_abEnsureFetched}=__test;"


def _run_node(script: str) -> dict:
    node = shutil.which("node")
    if not node:  # pragma: no cover - node is present on Legion
        pytest.skip("node not on PATH")
    uri = MODULE.resolve().as_uri()
    full = (_PRELUDE + script).replace("__URI__", uri)
    res = subprocess.run(
        [node, "--input-type=module", "-e", full],
        capture_output=True, text=True, cwd=str(REPO), timeout=30,
    )
    assert res.returncode == 0, f"node failed: {res.stderr.strip()}"
    return json.loads(res.stdout)


_REJECT = "globalThis.fetch=()=>{calls++;return Promise.reject(new Error('boom'));};"
_NON_OK = "globalThis.fetch=()=>{calls++;return Promise.resolve({ok:false});};"
_OK = ("globalThis.fetch=()=>{calls++;return Promise.resolve({ok:true,"
       "json:()=>Promise.resolve({ok:true,patch:'16.14.1',"
       "champions:{Aatrox:{aramDamageDealt:0.95}}})});};")
_SETTLE = "await new Promise(r=>setTimeout(r,60));"
_REPORT = ("process.stdout.write(JSON.stringify({calls,landed,"
           "champions:_AB.champions,failed:_AB.failedAt>0,"
           "fetching:_AB.fetching,patch:_AB.patch}));")


def test_network_rejection_leaves_cache_null_and_repaints():
    out = _run_node(
        "let calls=0,landed=0;" + _REJECT
        + "_abEnsureFetched(()=>{landed++;});" + _SETTLE + _REPORT
    )
    assert out["calls"] == 1
    assert out["champions"] is None, "a rejected fetch must leave the cache re-fetchable"
    assert out["failed"] is True
    assert out["fetching"] is False
    assert out["landed"] == 1, "the failure path must repaint so the panel can say so"


def test_non_ok_response_leaves_cache_null():
    out = _run_node(
        "let calls=0,landed=0;" + _NON_OK
        + "_abEnsureFetched(()=>{landed++;});" + _SETTLE + _REPORT
    )
    assert out["champions"] is None
    assert out["failed"] is True
    assert out["landed"] == 1


def test_success_populates_cache_and_clears_the_failure_stamp():
    out = _run_node(
        "let calls=0,landed=0;" + _OK
        + "_AB.failedAt=1;"
        + "_abEnsureFetched(()=>{landed++;});" + _SETTLE + _REPORT
    )
    assert out["champions"] == {"Aatrox": {"aramDamageDealt": 0.95}}
    assert out["failed"] is False
    assert out["patch"] == "16.14.1"
    assert out["calls"] == 1


def test_failure_is_rate_limited_then_retried():
    """The retry must not become a per-tick fetch storm: a fresh failure holds
    the cooldown, and only an expired stamp lets the next tick try again."""
    out = _run_node(
        "let calls=0,landed=0;" + _REJECT
        + "_abEnsureFetched(()=>{landed++;});" + _SETTLE
        + "_abEnsureFetched(()=>{landed++;});" + _SETTLE
        + "const during=calls;"
        + "_AB.failedAt=1;"
        + "_abEnsureFetched(()=>{landed++;});" + _SETTLE
        + "process.stdout.write(JSON.stringify({calls,landed,during,"
        + "champions:_AB.champions,failed:_AB.failedAt>0,"
        + "fetching:_AB.fetching,patch:_AB.patch}));"
    )
    assert out["during"] == 1, "a second tick inside the cooldown must not re-fetch"
    assert out["calls"] == 2, "an expired cooldown must let the next tick retry"
    assert out["champions"] is None


def test_empty_but_ok_payload_is_a_success_not_a_failure():
    """`{}` from a healthy route is a real answer (no champion carries
    modifiers this patch) and must terminate the fetch, not arm the retry."""
    out = _run_node(
        "let calls=0,landed=0;"
        "globalThis.fetch=()=>{calls++;return Promise.resolve({ok:true,"
        "json:()=>Promise.resolve({ok:true,patch:'',champions:{}})});};"
        + "_abEnsureFetched(()=>{landed++;});" + _SETTLE
        + "_abEnsureFetched(()=>{landed++;});" + _SETTLE + _REPORT
    )
    assert out["champions"] == {}
    assert out["failed"] is False
    assert out["calls"] == 1
