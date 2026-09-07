"""SR champ-select overlay UI-audit regression guard (R118, cycle C2).

Companion to the 5-phase fixture audit of the Champ-Select SR surface
(STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY). Prior cycle C1
(6cbd6e15) audited the ARAM + Arena champ-select surfaces and OMITTED SR;
this guard locks the SR default surface - the branch where
champ_select.js `_csvDetectMode` returns "sr".

Pure file-read, CI-safe: reads the two authored web files as text and
asserts durable audit invariants. No network, no browser, no engine import
(mirrors the byte-scan pattern of tests/test_smart_quote_hygiene.py +
tests/test_u2500_hygiene.py).

Invariants locked here:
  1. ASCII hygiene - 0 non-ASCII bytes in champ_select.js AND
     champ_select_view.css (repo hard rule: 7-bit ASCII authored content).
  2. TYPOGRAPHY floor - every raw `font-size: Npx` with N < 16 (the --fs-xs
     floor) lives on a hard-coded documented-exception selector. A NEW
     undocumented sub-floor px font-size fails.
  3. HIT-TARGET floor - every raw `min-height: Npx` with N < 42 (the
     --hit-min click floor) lives on a documented-exception selector.
  4. STRUCTURE - the SR base grid keeps its 2-row area map
     (allies|mypick|enemies over pickban|mypick|suggestions) and the SR
     render dispatch keeps its dedicated pick-ban + suggestions calls.
  5. HIT-TARGET pin - the three SR interactive cells keep min-height set to
     var(--hit-min).

Each sub-floor exception is documented inline with a WHY comment at its
source line in champ_select_view.css (item 178 / item 202 / RC2 audit
notes). ARAM/Arena-only exceptions (.csv-bench-empty, .csv-duo-cell-tag,
.csv-arena-cell*) are C1 scope but are included in the allowlists here
because this guard reads the whole shared CSS file; they are tagged below.
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CSS = _REPO_ROOT / "web" / "css" / "panels" / "champ_select_view.css"
_JS = _REPO_ROOT / "web" / "js" / "panels" / "champ_select.js"

# --fs-xs floor (px): raw font-size below this must be a documented exception.
_FONT_FLOOR = 16
# --hit-min click-target floor (px): raw min-height below this must be
# documented (interactive floor).
_HIT_FLOOR = 42

# Documented sub-floor font-size exceptions: selector -> px. Each carries a
# WHY comment at its source line in champ_select_view.css.
_FONT_EXCEPTIONS = {
    ".csv-bench-empty": 13,                    # ARAM reroll empty-state copy (item 178)
    ".csv-build-spell.is-swapped::after": 10,  # 10px corner swap-dot micro-badge
    ".csv-build-spell.empty": 11,              # empty-slot placeholder glyph
    ".csv-duo-cell-tag": 11,                    # Arena ME/ALLY badge (item 178, C1)
    ".csv-arena-cell-name": 13,                # Arena dense-column champ name (C1)
}

# Documented sub-floor min-height exceptions: selector -> px.
_MINH_EXCEPTIONS = {
    ".csv-lock-btn": 32,         # full-width mouse-driven LOCK IN btn (UIX1 audit)
    ".csv-team-cell": 38,        # non-button ally/enemy display row
    ".csv-build-rune-main": 38,  # non-button cursor:help rune hover cell
    ".csv-arena-cell": 38,       # Arena non-button display cell (C1 scope)
}

# SR interactive cells that must keep the --hit-min click floor pinned.
_SR_HIT_MIN_CELLS = (
    ".csv-summspell-cell",
    ".csv-pb168-cell",
    ".csv-pb-ban",
)

_FS_RE = re.compile(r"font-size:\s*([^;}]+)")
_PX_RE = re.compile(r"(\d+)px")
_MH_RE = re.compile(r"min-height:\s*(\d+)px")


def _read_bytes(p: Path) -> bytes:
    assert p.is_file(), "missing web file: " + p.as_posix()
    return p.read_bytes()


def _non_ascii(raw: bytes) -> list[tuple[int, int]]:
    return [(i, b) for i, b in enumerate(raw) if b > 127]


def _leaf_rules(css_text: str) -> list[tuple[str, str]]:
    """Return (selector, body) for every leaf CSS rule.

    Comments are stripped first. At-rule wrappers (@media/@supports/
    @keyframes) are descended into so the inner leaf selectors get returned;
    the at-rule prelude itself is never returned as a selector. A leaf rule
    is a selector block whose body contains no nested braces.
    """
    css = re.sub(r"/\*.*?\*/", "", css_text, flags=re.S)
    out: list[tuple[str, str]] = []
    stack: list[tuple[str, int]] = []
    token_start = 0
    for i, ch in enumerate(css):
        if ch == "{":
            prelude = " ".join(css[token_start:i].split())
            stack.append((prelude, i))
            token_start = i + 1
        elif ch == "}":
            if stack:
                prelude, open_idx = stack.pop()
                body = css[open_idx + 1:i]
                if prelude and not prelude.startswith("@") and "{" not in body:
                    out.append((prelude, body))
            token_start = i + 1
    return out


def _css_text() -> str:
    return _CSS.read_text(encoding="utf-8")


def test_champ_select_js_is_ascii() -> None:
    """champ_select.js must be 7-bit ASCII (repo hard rule)."""
    na = _non_ascii(_read_bytes(_JS))
    assert not na, (
        "web/js/panels/champ_select.js has " + str(len(na))
        + " non-ASCII byte(s); first at offset " + str(na[0][0])
    )


def test_champ_select_css_is_ascii() -> None:
    """champ_select_view.css must be 7-bit ASCII (repo hard rule)."""
    na = _non_ascii(_read_bytes(_CSS))
    assert not na, (
        "web/css/panels/champ_select_view.css has " + str(len(na))
        + " non-ASCII byte(s); first at offset " + str(na[0][0])
    )


def test_this_guard_is_ascii() -> None:
    """This guard file itself must be 7-bit ASCII."""
    na = _non_ascii(Path(__file__).read_bytes())
    assert not na, (
        "tests/test_champ_select_sr_ui_audit.py has " + str(len(na))
        + " non-ASCII byte(s); first at offset " + str(na[0][0])
    )


def test_no_undocumented_subfloor_font_size() -> None:
    """Every raw font-size < 16px must be a documented-exception selector."""
    violations: list[str] = []
    for selector, body in _leaf_rules(_css_text()):
        for fm in _FS_RE.finditer(body):
            for pm in _PX_RE.finditer(fm.group(1)):
                px = int(pm.group(1))
                if px >= _FONT_FLOOR:
                    continue
                if _FONT_EXCEPTIONS.get(selector) != px:
                    violations.append(selector + " -> font-size " + str(px) + "px")
    assert not violations, (
        "Undocumented sub-floor (< " + str(_FONT_FLOOR) + "px) font-size in "
        "champ_select_view.css. Tokenize to var(--fs-xs) or add a documented "
        "exception (with a WHY comment at the source line) to _FONT_EXCEPTIONS. "
        "Offenders:\n  " + "\n  ".join(sorted(set(violations)))
    )


def test_no_undocumented_subfloor_min_height() -> None:
    """Every raw min-height < 42px must be a documented-exception selector."""
    violations: list[str] = []
    for selector, body in _leaf_rules(_css_text()):
        for mm in _MH_RE.finditer(body):
            px = int(mm.group(1))
            if px >= _HIT_FLOOR:
                continue
            if _MINH_EXCEPTIONS.get(selector) != px:
                violations.append(selector + " -> min-height " + str(px) + "px")
    assert not violations, (
        "Undocumented sub-floor (< " + str(_HIT_FLOOR) + "px) min-height in "
        "champ_select_view.css. Pin var(--hit-min) or add a documented "
        "exception to _MINH_EXCEPTIONS. Offenders:\n  "
        + "\n  ".join(sorted(set(violations)))
    )


def test_documented_font_exceptions_still_present() -> None:
    """Anti-rot: every allowlisted font selector still exists in the CSS."""
    selectors = {sel for sel, _ in _leaf_rules(_css_text())}
    missing = sorted(s for s in _FONT_EXCEPTIONS if s not in selectors)
    assert not missing, (
        "Allowlisted font-size exception selector(s) no longer in the CSS; "
        "prune _FONT_EXCEPTIONS: " + ", ".join(missing)
    )


def test_documented_min_height_exceptions_still_present() -> None:
    """Anti-rot: every allowlisted min-height selector still exists in the CSS."""
    selectors = {sel for sel, _ in _leaf_rules(_css_text())}
    missing = sorted(s for s in _MINH_EXCEPTIONS if s not in selectors)
    assert not missing, (
        "Allowlisted min-height exception selector(s) no longer in the CSS; "
        "prune _MINH_EXCEPTIONS: " + ", ".join(missing)
    )


def test_sr_grid_areas_intact() -> None:
    """STRUCTURE lock: the SR base grid keeps its row1/row2 area map."""
    flat = " ".join(_css_text().split())
    expected = '"allies mypick enemies" "pickban mypick suggestions"'
    assert expected in flat, (
        "SR base grid-template-areas changed. Expected row1 "
        "'allies mypick enemies' over row2 'pickban mypick suggestions'."
    )


def test_sr_click_targets_pin_hit_min() -> None:
    """HIT-TARGET lock: SR interactive cells pin min-height:var(--hit-min)."""
    bodies: dict[str, str] = {}
    for sel, body in _leaf_rules(_css_text()):
        bodies[sel] = bodies.get(sel, "") + " " + " ".join(body.split())
    missing = [
        sel for sel in _SR_HIT_MIN_CELLS
        if "min-height: var(--hit-min)" not in bodies.get(sel, "")
    ]
    assert not missing, (
        "SR interactive cell(s) no longer pin min-height: var(--hit-min): "
        + ", ".join(missing)
    )


def test_sr_render_dispatch_present() -> None:
    """STRUCTURE lock: SR keeps its dedicated pick-ban + suggestions render."""
    js = _JS.read_text(encoding="utf-8")
    assert "function _csvDetectMode" in js, "SR mode detector missing"
    assert 'return "sr";' in js, "SR default-mode branch missing"
    assert "_csvRenderPickBan" in js, "SR pick-ban render missing"
    assert "_csvRenderSuggestions" in js, "SR suggestions render missing"
