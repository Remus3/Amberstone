"""Y-13 (external reference L2): an unknown sub-probe must not read green.

Defect measured 2026-10-04 at origin/main d1d078aab, dashboard/routes_state.py
_serve_health_all: the agent6 block already reports the honest third state
("unknown" on an incomplete scan, `{"error", "status": "unknown"}` when the
probe raises, :568-581) but the verdict only tested `status == "yellow"`
(:611), so an unmeasured agent6 still rolled up to a confident GREEN. The
client dot (web/js/main.js refreshHealth) removed only green/yellow/red and had
no `.health-dot.unknown` style (web/css/panels/primitives.css:95-97).

The rule now: every sub-probe whose result is unknown (status "unknown") or
errored (a truthy "error" key) is named in a `why` list, and a non-empty `why`
caps the rollup at yellow. Red still wins.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest import mock

from dashboard import api_schema
from dashboard import routes_state as rs

ROOT = Path(__file__).resolve().parent.parent


class _H:
    def __init__(self):
        self.code = None
        self.body = None

    def _send(self, code, body, ctype):
        self.code = code
        self.body = body


class _R:
    def __init__(self, body: bytes):
        self._b = body

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _healthy_urlopen(url, timeout=None):
    if "8889" in url:
        return _R(b'{"alive": true, "uptime_s": 60}')
    return _R(b'{"status": "ok", "engine_version": "x", "items": 1, "champions": 1}')


class _Tracker:
    def banner_state(self):
        return "ok"

    def daily_spend(self):
        return {"total_usd": 0.0}


def _serve(*, a6=None, a6_raises=False, read_json=None, rc_alive=True):
    """Serve /api/health/all with every probe healthy unless overridden."""
    def _rj(rel):
        if read_json is not None:
            return read_json(rel)
        return {"alive": rc_alive} if rel.endswith("health.json") else {"pid": 1}

    if a6_raises:
        a6_patch = mock.patch.object(rs, "_agent6_audit_outcomes_ex",
                                     side_effect=OSError("boom"))
    else:
        a6_patch = mock.patch.object(rs, "_agent6_audit_outcomes_ex",
                                     return_value=a6 if a6 is not None else ([], True))
    h = _H()
    with mock.patch.object(rs, "read_json", side_effect=_rj), \
            mock.patch.object(rs.urllib.request, "urlopen", _healthy_urlopen), \
            mock.patch("core.cost_tracker.get_tracker", lambda: _Tracker()), \
            mock.patch("ops.rc_dev_runtime.fatal_stats",
                       return_value={"count": 0, "last_at": None, "recent": []}), \
            a6_patch:
        rs._serve_health_all(h)
    assert h.code == 200, h.code
    return json.loads(h.body.decode("utf-8"))


def test_positive_control_all_probes_healthy_is_green():
    body = _serve()
    assert body["status"] == "green", body
    assert body["why"] == []


def test_incomplete_agent6_scan_is_not_green_and_names_agent6():
    body = _serve(a6=([], False))
    assert body["agent6"]["status"] == "unknown"
    assert body["status"] == "yellow", body["status"]
    assert body["why"] == ["agent6"]


def test_raising_agent6_probe_is_not_green_and_names_agent6():
    body = _serve(a6_raises=True)
    assert body["agent6"]["status"] == "unknown"
    assert "error" in body["agent6"]
    assert body["status"] == "yellow", body["status"]
    assert body["why"] == ["agent6"]


def test_an_errored_supervisor_probe_is_named_and_caps_at_yellow():
    def rj(rel):
        if rel.endswith("supervisor.pid"):
            return None  # .get() on None raises inside the supervisor probe
        return {"alive": True}

    body = _serve(read_json=rj)
    assert "error" in body["supervisor"]
    assert body["status"] == "yellow"
    assert body["why"] == ["supervisor"]


def test_red_still_wins_over_unknown():
    body = _serve(a6=([], False), rc_alive=False)
    assert body["status"] == "red"
    assert "agent6" in body["why"]


def test_schema_documents_why_and_validates_the_payload():
    assert "why" in api_schema.HealthAllResponse.model_fields
    body = _serve(a6=([], False))
    parsed = api_schema.HealthAllResponse.model_validate(body)
    assert parsed.why == ["agent6"]
    js = (ROOT / "web" / "js" / "lib" / "state_schema.js").read_text(encoding="utf-8")
    block = js[js.index("@typedef {Object} HealthAllResponse"):]
    block = block[:block.index("*/")]
    assert "@property {Array} why" in block


# -- client dot --------------------------------------------------------------

def _refresh_health_src() -> str:
    src = (ROOT / "web" / "js" / "main.js").read_text(encoding="utf-8")
    i = src.index('fetch("/api/health/all")')
    return src[i:i + 1500]


def test_client_dot_removes_the_unknown_class():
    seg = _refresh_health_src()
    m = re.search(r"dot\.classList\.remove\(([^)]*)\)", seg)
    assert m, "refreshHealth no longer removes status classes - re-measure"
    removed = set(re.findall(r'"([a-z]+)"', m.group(1)))
    assert {"green", "yellow", "red", "unknown"} <= removed, removed


def _css_rule(css: str, selector: str) -> str:
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"no rule for {selector}"
    return m.group(1)


def test_unknown_dot_style_exists_and_every_var_is_defined():
    css_dir = ROOT / "web" / "css"
    prim = (css_dir / "panels" / "primitives.css").read_text(encoding="utf-8")
    body = _css_rule(prim, ".health-dot.unknown")
    used = set(re.findall(r"var\(\s*(--[A-Za-z0-9_-]+)", body))
    assert used, "the unknown dot style uses no tokens - re-check the rule"
    defined: set[str] = set()
    for f in css_dir.rglob("*.css"):
        defined |= set(re.findall(r"(--[A-Za-z0-9_-]+)\s*:", f.read_text(encoding="utf-8")))
    assert len(defined) > 20  # non-empty anchor
    undefined = sorted(used - defined)
    assert not undefined, f"undefined CSS vars in .health-dot.unknown: {undefined}"
