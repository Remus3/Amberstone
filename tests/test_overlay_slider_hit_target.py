"""
tests/test_overlay_slider_hit_target.py

HIT-TARGETS class guard for range inputs (slider thumb drag targets).

WHY: docs/UI_SCALE_SPEC_V2.md line 112 + 118 puts every slider thumb on the
--hit-min floor (tokens.css:119 = 42px). A wrapper row that reserves 42px does
NOT give the thumb a 42px drag target: Chromium's native input[type=range] box
is ~21px tall and, centered by align-items, the pointer only lands on the
control over half the reserved row. tests/test_overlay_launcher_hit_targets.py
locks the WRAPPER (.ovx-menu-slider min-height); this file locks the CONTROL.

The precedent fix is an explicit height ON the input:
  web/css/panels/header.css:2902              height: var(--hit-min)
  web/css/panels/overlay_ds_controls.css:231  height: var(--hit-min, 42px)
web/css/overlay.css:866 (the launcher-menu op/sz sliders built by
web/js/lib/overlay_layout.js:734 + :745) shipped without it.

This is a CLASS guard, not a one-off:
  1. every input[type=range] CSS rule repo-wide must resolve to a height or
     min-height >= --hit-min (state rules like :focus and pseudo-element rules
     like ::-webkit-slider-thumb are enumerated but exempt - they do not own the
     control's box);
  2. every range input in MARKUP is censused against RANGE_MARKUP_CENSUS with a
     cited covering selector, and that selector is re-checked against the CSS on
     every run - so a new slider cannot ship unstyled, and a census entry cannot
     go stale into a green pass.

There is deliberately NO exception allowlist: at authoring time all four target
keys clear the floor. The HIT_MIN_EXCEPTION marker below exists so a future
deliberate exception is a documented, greppable inline comment rather than a
silent edit to this file.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS_ROOT = ROOT / "web" / "css"
TOKENS_CSS = CSS_ROOT / "tokens.css"

# An inline "/* HIT-MIN-EXCEPTION: <why> */" inside a rule (or its leading
# comment) opts that rule out. Deliberate + greppable, per the launcher-square
# precedent in overlay.css.
HIT_MIN_EXCEPTION = "HIT-MIN-EXCEPTION"

RANGE_SELECTOR_RE = re.compile(r"""input\s*\[\s*type\s*=\s*["']?range["']?\s*\]""")
SIZE_DECL_RE = re.compile(r"(?<![\w-])(min-height|height)\s*:\s*([^;}]+)", re.I)
PX_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*px")

# Markup census: every range input that RC renders, with the CSS selector that
# grants it the --hit-min floor. Key is (repo-relative path, anchor) where the
# anchor is the element id for markup and the JS variable for createElement.
# Adding a slider without adding a row here fails test_range_markup_census.
RANGE_MARKUP_CENSUS = {
    ("web/index.html", "set-pgr-baseline"): '.settings-row input[type="range"]',
    ("web/index.html", "replay-slider"): ".replay-slider",
    ("web/js/panels/overlay_ds_controls.js", "ovset-opacity"):
        '.ovset-range > input[type="range"]',
    ("web/js/lib/overlay_layout.js", "op"):
        'body[data-shell="overlay"] .ovx-launcher-menu .ovx-menu-slider '
        'input[type="range"]',
    ("web/js/lib/overlay_layout.js", "sc"):
        'body[data-shell="overlay"] .ovx-launcher-menu .ovx-menu-slider '
        'input[type="range"]',
}

MARKUP_SOURCES = (
    "web/index.html",
    "web/js/panels/overlay_ds_controls.js",
    "web/js/lib/overlay_layout.js",
)

HTML_INPUT_RE = re.compile(r"<input\b[^>]*>", re.S)
JS_RANGE_ASSIGN_RE = re.compile(r"""(\w+)\s*\.\s*type\s*=\s*["']range["']""")
ID_ATTR_RE = re.compile(r"""\bid\s*=\s*["']([^"']+)["']""")
TYPE_RANGE_ATTR_RE = re.compile(r"""\btype\s*=\s*["']range["']""")


def _blank_comments(text):
    """Replace /* */ comment bodies with spaces so byte offsets and line counts
    stay identical to the raw source."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end == -1 else end + 2
            out.append("".join("\n" if c == "\n" else " " for c in text[i:end]))
            i = end
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _parse_block(src, start, end):
    """Yield (selector, body, selector_offset, context_offset, block_end) for
    declaration rules in src[start:end], descending into at-rule blocks
    (@media / @supports). context_offset backs up over the rule's leading
    comment so an inline exception marker there is still visible."""
    i = start
    tok = start
    while i < end:
        ch = src[i]
        if ch == "{":
            raw_selector = src[tok:i]
            selector = raw_selector.strip()
            lead = len(raw_selector) - len(raw_selector.lstrip())
            depth = 1
            j = i + 1
            while j < end and depth:
                if src[j] == "{":
                    depth += 1
                elif src[j] == "}":
                    depth -= 1
                j += 1
            body_start, body_end = i + 1, j - 1
            if selector.startswith("@"):
                yield from _parse_block(src, body_start, body_end)
            else:
                yield selector, src[body_start:body_end], tok + lead, tok, j
            i = j
            tok = j
        elif ch == ";":
            i += 1
            tok = i
        else:
            i += 1


def _split_selectors(selector):
    """Split a comma selector list, ignoring commas nested in :not(...) etc."""
    parts = []
    depth = 0
    buf = []
    for ch in selector:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _normalize(selector):
    """Canonical form so `.a > input[type=range]` and `.a>input[type='range']`
    group onto one target key."""
    out = RANGE_SELECTOR_RE.sub('input[type="range"]', selector)
    out = re.sub(r"\s*([>+~])\s*", r" \1 ", out)
    return re.sub(r"\s+", " ", out).strip()


def _strip_state(selector):
    """Drop trailing pseudo-classes (:focus, :hover, :disabled, ...) so a state
    rule maps onto the base target it decorates."""
    return re.sub(r"(?<!:):(?!:)[\w-]+(?:\([^)]*\))?\s*$", "", selector).strip()


def _css_files():
    return sorted(CSS_ROOT.rglob("*.css"))


def _rules():
    """Every CSS rule under web/css as dicts with raw context for the exception
    marker and a 1-based line number for reporting."""
    collected = []
    for path in _css_files():
        raw = path.read_text(encoding="utf-8")
        src = _blank_comments(raw)
        for selector, body, offset, ctx, block_end in _parse_block(src, 0, len(src)):
            collected.append({
                "path": path,
                "rel": path.relative_to(ROOT).as_posix(),
                "line": src.count("\n", 0, offset) + 1,
                "selector": selector,
                "body": body,
                "raw_context": raw[ctx:block_end],
            })
    return collected


def _hit_min_px():
    tokens = TOKENS_CSS.read_text(encoding="utf-8")
    match = re.search(r"--hit-min\s*:\s*(-?\d+(?:\.\d+)?)px", tokens)
    assert match, "tokens.css must define --hit-min in px"
    return float(match.group(1))


def _clears_floor(body, floor_px):
    """True when a declaration block resolves height/min-height to the floor."""
    for _prop, value in SIZE_DECL_RE.findall(body):
        if "--hit-min" in value:
            return True
        px = PX_RE.search(value)
        if px and float(px.group(1)) >= floor_px:
            return True
    return False


def _selector_index(rules):
    """Normalized selector -> merged declaration text across every rule that
    targets it (a target's height can land in any one of its rules)."""
    index = {}
    for rule in rules:
        for one in _split_selectors(rule["selector"]):
            key = _normalize(one)
            index.setdefault(key, []).append(rule["body"])
    return {k: "\n".join(v) for k, v in index.items()}


def _range_targets(rules):
    """Group range-input rules into base targets, state variants, and
    pseudo-element variants. Only base targets own the control's box."""
    base, decorative = {}, []
    for rule in rules:
        for one in _split_selectors(rule["selector"]):
            if not RANGE_SELECTOR_RE.search(one):
                continue
            norm = _normalize(one)
            site = f"{rule['rel']}:{rule['line']}  {norm}"
            if "::" in norm:
                decorative.append((site, "pseudo-element"))
                continue
            stripped = _strip_state(norm)
            if stripped != norm:
                decorative.append((site, "state variant of " + stripped))
                continue
            entry = base.setdefault(norm, {"sites": [], "body": [], "raw": []})
            entry["sites"].append(site)
            entry["body"].append(rule["body"])
            entry["raw"].append(rule["raw_context"])
    return base, decorative


def test_range_inputs_meet_hit_min():
    """Every input[type=range] target repo-wide sizes its own box to --hit-min.

    A wrapper min-height is not enough: the native control keeps its ~21px
    height and only the middle of the reserved row is draggable.
    """
    floor = _hit_min_px()
    rules = _rules()
    base, decorative = _range_targets(rules)
    assert base, "no input[type=range] rule found under web/css - guard is blind"

    failures = []
    for target, entry in sorted(base.items()):
        merged = "\n".join(entry["body"])
        if _clears_floor(merged, floor):
            continue
        if any(HIT_MIN_EXCEPTION in raw for raw in entry["raw"]):
            continue
        sites = "; ".join(entry["sites"])
        failures.append(f"  {target}\n      declared at: {sites}")

    inventory = "\n".join(f"  {site} -> {why}" for site, why in sorted(decorative)) or "  (none)"
    joined = "\n".join(failures)
    assert not failures, (
        f"range inputs below the --hit-min ({floor:g}px) drag-target floor:\n{joined}\n\n"
        "Fix: set `height: var(--hit-min)` ON the input (precedent: "
        "web/css/panels/header.css:2902, "
        "web/css/panels/overlay_ds_controls.css:231), or add an inline "
        f"/* {HIT_MIN_EXCEPTION}: why */ comment.\n\n"
        f"exempt (decorative) rules seen:\n{inventory}"
    )


def test_range_markup_census():
    """Every rendered range input is censused with a covering selector.

    Catches the case the CSS-only sweep cannot see: a slider added to markup
    with no rule that sizes it at all.
    """
    found = set()
    for rel in MARKUP_SOURCES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        for tag in HTML_INPUT_RE.findall(text):
            if not TYPE_RANGE_ATTR_RE.search(tag):
                continue
            ident = ID_ATTR_RE.search(tag)
            found.add((rel, ident.group(1) if ident else tag.strip()))
        for var in JS_RANGE_ASSIGN_RE.findall(text):
            found.add((rel, var))

    expected = set(RANGE_MARKUP_CENSUS)
    assert found == expected, (
        "range-input markup census drift.\n"
        f"  new / unrecorded: {sorted(found - expected)}\n"
        f"  recorded but gone: {sorted(expected - found)}\n"
        "Add each new slider to RANGE_MARKUP_CENSUS with the CSS selector that "
        "gives it the --hit-min floor."
    )


def test_census_covering_selectors_still_grant_the_floor():
    """The cited covering selectors are re-verified against the live CSS, so a
    census row cannot rot into a green pass after its rule is edited."""
    floor = _hit_min_px()
    index = _selector_index(_rules())
    failures = []
    for (rel, anchor), selector in sorted(RANGE_MARKUP_CENSUS.items()):
        key = _normalize(selector)
        body = index.get(key)
        if body is None:
            failures.append(f"{rel}#{anchor} -> selector {selector!r} not found in web/css")
        elif not _clears_floor(body, floor):
            failures.append(
                f"{rel}#{anchor} -> {selector!r} no longer sets "
                f"height/min-height >= {floor:g}px"
            )
    assert not failures, "\n".join(failures)
