"""
tests/test_oq3_objective_gauge_mocks.py

OQ3 (OPERATOR-DECIDED 2026-07-01, QA11) - characterization contract for the
3-variant peripheral-timer + ring-gauge overlay MOCKUP set.

These are STATIC design mockups (no live wire, no JS/API dependency) the
operator picks from; the build waits on the pick. Each variant renders the
four neutral/utility objectives (drake / baron / elder / summs) as periphery
ring / arc gauges for at-a-glance reads while playing.

Contract locked here (so the 3 parallel build slices stay consistent):
  - all 4 variant/gallery files exist under web/mock/;
  - each variant is a standalone HTML doc carrying data-oq3-variant + all four
    objective labels + at least one SVG ring/arc gauge;
  - the Hextech palette law holds (doctrine section 5): every objective hue is
    one of the four sanctioned overlay tokens (BARON gold #C8AA6E, DRAKE warn
    #E8A33D, ELDER red #E84057, SUMMS cyan #0AC8B9) - no off-palette literal;
  - each variant carries a one-line tradeoff note (data-oq3-tradeoff);
  - ASCII only (no em/en dash, no smart quote) - the repo-wide hard rule;
  - the /mock/ static route serves the files as text/html so they render in a
    browser at https://legion-rc:8888/mock/oq3_index.html (not download).
"""
from __future__ import annotations

import re
from pathlib import Path

from dashboard import routes_static

ROOT = Path(__file__).resolve().parent.parent
MOCK_DIR = ROOT / "web" / "mock"

VARIANTS = ("a", "b", "c")
VARIANT_FILES = {v: MOCK_DIR / f"oq3_variant_{v}.html" for v in VARIANTS}
INDEX_FILE = MOCK_DIR / "oq3_index.html"

# The four objectives, in the order the design surfaces them.
OBJECTIVES = ("DRAKE", "BARON", "ELDER", "SUMMS")

# Hextech palette law (overlay.css section 0): the only hues an overlay widget
# may paint. Per-objective mapping keeps every gauge on-palette.
OBJ_HUE = {
    "BARON": "#C8AA6E",   # gold - the premium high-value objective
    "DRAKE": "#E8A33D",   # warn amber
    "ELDER": "#E84057",   # emergency red - the dangerous late objective
    "SUMMS": "#0AC8B9",   # cyan - info / utility
}


class _StubHandler:
    """Minimal BaseHTTPRequestHandler stand-in capturing _send(...)."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.sent: tuple | None = None

    def _send(self, code: int, body: bytes, ctype: str, *a, **k) -> None:
        self.sent = (code, body, ctype)


def _mock_route_matches(path: str) -> bool:
    """True if any GET route matcher claims `path`."""
    return any(matcher(path) for matcher, _handler in routes_static.GET_ROUTES)


# --------------------------------------------------------------------------- files exist
def test_all_mock_files_exist():
    missing = [str(p) for p in (*VARIANT_FILES.values(), INDEX_FILE) if not p.is_file()]
    assert not missing, f"OQ3 mockup files not authored yet: {missing}"


# --------------------------------------------------------------------------- per-variant contract
def test_each_variant_is_standalone_html_doc():
    for v, p in VARIANT_FILES.items():
        html = p.read_text(encoding="utf-8").lower()
        assert "<!doctype html>" in html, f"variant {v}: missing <!doctype html>"
        assert "<html" in html and "</html>" in html, f"variant {v}: not a full html doc"
        assert f'data-oq3-variant="{v}"' in html, f"variant {v}: missing data-oq3-variant marker"


def test_each_variant_shows_all_four_objectives():
    for v, p in VARIANT_FILES.items():
        html = p.read_text(encoding="utf-8")
        for obj in OBJECTIVES:
            assert obj in html, f"variant {v}: objective label {obj} not present"


def test_each_variant_has_svg_ring_or_arc_geometry():
    for v, p in VARIANT_FILES.items():
        html = p.read_text(encoding="utf-8").lower()
        assert "<svg" in html, f"variant {v}: no inline <svg> (ring/arc gauge medium)"
        # A ring/arc gauge is a stroked circle or an arc path with a dash sweep.
        has_gauge = ("stroke-dasharray" in html) or ("<circle" in html) or ("<path" in html)
        assert has_gauge, f"variant {v}: no ring/arc gauge primitive (circle/path/dash sweep)"


def test_each_variant_holds_the_hextech_palette_law():
    for v, p in VARIANT_FILES.items():
        html = p.read_text(encoding="utf-8").upper()
        for obj, hue in OBJ_HUE.items():
            assert hue.upper() in html, (
                f"variant {v}: objective {obj} hue {hue} (Hextech token) not present - "
                "every objective must map to a sanctioned overlay palette hue"
            )


def test_each_variant_carries_a_tradeoff_note():
    for v, p in VARIANT_FILES.items():
        html = p.read_text(encoding="utf-8")
        m = re.search(r'data-oq3-tradeoff="([^"]+)"', html)
        assert m and m.group(1).strip(), f"variant {v}: missing non-empty data-oq3-tradeoff note"


# --------------------------------------------------------------------------- gallery index
def test_index_links_all_three_variants():
    html = INDEX_FILE.read_text(encoding="utf-8")
    for v in VARIANTS:
        assert f"oq3_variant_{v}.html" in html, f"index does not reference variant {v}"


# --------------------------------------------------------------------------- ASCII hygiene
def test_all_mock_files_are_ascii_only():
    for p in (*VARIANT_FILES.values(), INDEX_FILE):
        raw = p.read_bytes()
        bad = [(i, b) for i, b in enumerate(raw) if b > 0x7F]
        assert not bad, f"{p.name}: non-ASCII byte(s) at {bad[:5]} - repo is 7-bit ASCII only"


# --------------------------------------------------------------------------- /mock/ route
def test_mock_route_is_registered():
    assert _mock_route_matches("/mock/oq3_index.html"), "/mock/ prefix not in GET_ROUTES"


def test_mock_route_serves_html_as_text_html():
    h = _StubHandler("/mock/oq3_index.html")
    routes_static._serve_web_asset(h)
    assert h.sent is not None, "handler never called _send"
    code, body, ctype = h.sent
    assert code == 200, f"/mock/oq3_index.html did not serve 200 (got {code})"
    assert len(body) > 0
    assert "text/html" in ctype, f"mock html served as {ctype!r}, not text/html (would download)"
