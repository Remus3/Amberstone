"""
tests/snapshot_panels/test_xss_escaping.py

Regression coverage for the P2-W3 web-surface audit (DEEP-AUDIT cycle 13).
The dominant finding class was un-escaped dynamic data interpolated into
innerHTML template literals - the browser analog of the server-side
"non-finite -> bare NaN/Infinity JSON token" class from cycles 7-12.

Two lenses:
  1. End-to-end (Playwright): a crafted HTML/JS payload placed in coach
     text + A/B choice labels must render as ESCAPED TEXT - it must never
     execute (onerror/onload) nor inject a live DOM element. Exercises the
     coach_choices._esc fix at #rn-choices plus main.js's escapeHtml on the
     coach action/immediate render path.
  2. Unit (node subprocess): the two exported escaping/guard primitives the
     panels now route through - lib/helpers.escHtml (the shared 5-char HTML
     escape) and lib/scorer_units.formatDsDelta (the non-finite -> "+0dps"
     guard, so a malformed engine row never paints "+NaNdps").

The node tests are deterministic and browser-free; the Playwright test
reuses the session mock_server + pw_browser fixtures from conftest.py.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent

# A single payload carrying every escape-sensitive character plus two
# script-execution vectors and one identifiable injected element. If any
# render path interpolates this raw into innerHTML, either window.__XSS_FIRED
# is set (onerror/onload ran) or #xss-marker exists as a live element.
_PAYLOAD = (
    '<i id="xss-marker">m</i>'
    '<img src=q onerror="window.__XSS_FIRED=1">'
    '<svg onload="window.__XSS_FIRED=1"></svg>'
    'tail&"\''
)


def _run_node(module_rel: str, script: str) -> dict:
    """Import an exported helper from web/js via a file: URL and return the
    JSON the script writes to stdout. Skips if node is unavailable."""
    node = shutil.which("node")
    if not node:  # pragma: no cover - node is present on Legion
        pytest.skip("node not on PATH")
    uri = (REPO / module_rel).resolve().as_uri()
    full = script.replace("__URI__", uri)
    res = subprocess.run(
        [node, "--input-type=module", "-e", full],
        capture_output=True, text=True, cwd=str(REPO), timeout=30,
    )
    assert res.returncode == 0, f"node failed: {res.stderr.strip()}"
    return json.loads(res.stdout)


def test_eschtml_escapes_five_chars_and_passes_benign():
    """lib/helpers.escHtml escapes & < > " ' and is a no-op for plain ASCII."""
    out = _run_node(
        "web/js/lib/helpers.js",
        "import {escHtml} from '__URI__';"
        "process.stdout.write(JSON.stringify({"
        "  xss: escHtml('<img src=x onerror=alert(1)>'),"
        "  amp: escHtml('a&b'),"
        "  quote: escHtml('\\\"q\\\"'),"
        "  apos: escHtml(\"'a'\"),"
        "  plain: escHtml('plain ASCII text 123'),"
        "  nul: escHtml(null),"
        "}));",
    )
    assert out["xss"] == "&lt;img src=x onerror=alert(1)&gt;"
    assert out["amp"] == "a&amp;b"
    assert out["quote"] == "&quot;q&quot;"
    assert out["apos"] == "&#39;a&#39;"
    assert out["plain"] == "plain ASCII text 123"
    assert out["nul"] == ""


def test_formatdsdelta_guards_non_finite():
    """lib/scorer_units.formatDsDelta coerces NaN/Infinity/null/"NaN" to
    "+0dps" (never "+NaNdps") and rounds finite deltas identically."""
    out = _run_node(
        "web/js/lib/scorer_units.js",
        "import {formatDsDelta} from '__URI__';"
        "process.stdout.write(JSON.stringify({"
        "  nan: formatDsDelta({delta_dps: NaN}),"
        "  inf: formatDsDelta({delta_dps: Infinity}),"
        "  nullrow: formatDsDelta(null),"
        "  strnan: formatDsDelta({delta_dps: 'NaN'}),"
        "  finite: formatDsDelta({delta_dps: 25.4}),"
        "  finite_ehp: formatDsDelta({delta_dps: 30, scorer: 'ehp'}),"
        "  missing: formatDsDelta({}),"
        "}));",
    )
    assert out["nan"] == "+0dps"
    assert out["inf"] == "+0dps"
    assert out["nullrow"] == "+0dps"
    assert out["strnan"] == "+0dps"
    assert out["finite"] == "+25dps"
    assert out["finite_ehp"] == "+30ehp"
    assert out["missing"] == "+0dps"


def test_state_payload_never_executes_or_injects(mock_server, pw_browser):
    """A crafted payload in coach action/immediate + A/B choice labels must
    render escaped: no script execution, no injected element, but visible as
    literal text in #rn-choices."""
    mock_server.set_fixture("sr")
    coach = mock_server._store["data"].setdefault("coach", {})
    coach["action"] = _PAYLOAD
    coach["immediate"] = _PAYLOAD
    coach["choices"] = [
        {"key": "A", "label": _PAYLOAD, "confidence": "high",
         "source_tag": _PAYLOAD, "expected_outcome": _PAYLOAD,
         "trigger": _PAYLOAD},
        {"key": "B", "label": "safe choice", "confidence": "mid",
         "source_tag": "synth"},
    ]

    from tests.snapshot_panels.conftest import _WS_STUB
    ctx = pw_browser.new_context(ignore_https_errors=True)
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        page.goto(mock_server.url + "/#last-match",
                  wait_until="domcontentloaded", timeout=15_000)
        page.add_style_tag(content=(
            'body[data-view="last-match"] main{display:block!important}'
            'body[data-view="last-match"] #view-last-match{display:none!important}'
        ))
        page.wait_for_function(
            "document.querySelectorAll('#rn-choices .rc-chip').length > 0",
            timeout=8_000,
        )
        assert not page.evaluate("window.__XSS_FIRED || null"), \
            "injected onerror/onload executed - payload was not escaped"
        assert page.query_selector("#xss-marker") is None, \
            "payload injected a live DOM element - innerHTML not escaped"
        choices_text = page.inner_text("#rn-choices")
        assert "xss-marker" in choices_text, \
            "escaped payload text missing - the choice chip did not render it"
        assert not errors, f"unhandled page errors: {errors}"
    finally:
        ctx.close()
