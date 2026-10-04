"""
tests/test_data_viz_tier_y07.py

Y-07 (external reference P; RM-531) - the League-domain DATA-VIZ token tier.

web/css/tokens.css declares a --data-* tier in its base :root, shaped exactly
like the --prim-* primitive layer (bare "R, G, B" parts, so a consumer dials
alpha per use with rgb()/rgba()). It names DOMAIN meaning, not status:

  team side ....... --data-ally  --data-enemy  --data-neutral
  damage type ..... --data-dmg-physical  --data-dmg-magic  --data-dmg-true
                    --data-dmg-onhit
  resource ........ --data-gold  --data-xp  --data-cs

Before this tier, team side was painted three different ways (one blue/red
literal pair in spike_curve / ward_heat / ds_sweep, a SIDE-keyed lavender /
coral pair in map_state that flipped with the map side, and the good/bad
STATUS hues in pgr_winprob.css), and the damage hues lived only as literals
in threat_donut.js.

What this file locks (all computed from the CSS source, no browser):

  MANIFEST   every manifest token is declared in the base :root as parts; no
             --data-* name is declared or consumed anywhere under web/ unless
             it is in the manifest (no orphans); every manifest token is either
             consumed somewhere or listed in RESERVED with a reason, and a
             RESERVED token that gains a consumer must leave RESERVED.
  RESOLVES   every token resolves to valid parts in EVERY theme scope (the
             themes.css :root[data-theme] blocks, enumerated from the source
             AND cross-checked against web/js/lib/theme.js THEMES) and in the
             overlay shell scope (body[data-shell="overlay"]) layered over every
             theme. An overlay re-point may only reference --ovx-* parts
             (overlay palette law), and the damage hues MUST be re-pointed there
             because threat_donut renders inside the overlay build widget.
  CONTRAST   every resolved hue clears 4.5:1 (WCAG relative luminance) against
             every canvas of its scope: --canvas / --surface / --surface-2 per
             theme (hextech base from panels/base.css), and --ovx-bg /
             --ovx-bg-nested in the overlay. 4.5 (not the 3:1 graphics floor)
             because the pgr legend and the ward-heat side label set TEXT in
             these hues.
  TEAM       ally/enemy never route through a good/bad token (--signal-good /
             --signal-bad / --prim-green / --prim-red / --ovx-good / --ovx-red)
             and sit at least TEAM_STATUS_MIN_DE (OKLab distance x100) from
             every theme's resolved good and bad hue, so team identity cannot
             be read as status in any theme; ally and enemy sit at least
             TEAM_PAIR_MIN_DE apart.
  CONSUMERS  the six panel sites read the tier (and SVG sites use style= or a
             class, never a presentation attribute: var() inside an SVG
             presentation attribute is not spec-promised, even though the
             2026-10-04 Chromium read resolved it); the canvas painter
             reads the tier from document.body, never documentElement (RM-139:
             --data-* overlay re-points are body-scoped).

Every checker returns a list of problems so the positive controls at the
bottom can plant a defect in an in-memory copy and prove the checker goes red.
The base-scope + canvases + resolution are also refused when they enumerate
nothing (an empty enumeration is never a pass).
"""
from __future__ import annotations

import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
TOKENS = WEB / "css" / "tokens.css"
THEMES_CSS = WEB / "css" / "themes.css"
OVERLAY_CSS = WEB / "css" / "overlay.css"
BASE_CSS = WEB / "css" / "panels" / "base.css"
THEME_JS = WEB / "js" / "lib" / "theme.js"
PANELS = WEB / "js" / "panels"

MANIFEST = (
    "--data-ally",
    "--data-enemy",
    "--data-neutral",
    "--data-dmg-physical",
    "--data-dmg-magic",
    "--data-dmg-true",
    "--data-dmg-onhit",
    "--data-gold",
    "--data-xp",
    "--data-cs",
)

# Declared-once tokens with no consumer yet. Each needs a reason; the
# ratchet test fails the day one of them gains a consumer and is not removed.
RESERVED = {
    "--data-gold": "resource hue for the gold-diff / income charts (X-12 / X-25 consume the tier)",
    "--data-xp": "resource hue for xp-diff charts; no xp chart ships yet",
    "--data-cs": "resource hue for cs/min charts; no cs chart ships yet",
}

# Must be re-pointed inside the overlay scope (doctrine section 5: no colour
# outside the --ovx-* table reaches an overlay widget). threat_donut renders
# in the overlay build widget (active_match.js THREATS strip).
OVERLAY_REQUIRED = (
    "--data-dmg-physical",
    "--data-dmg-magic",
    "--data-dmg-true",
    "--data-dmg-onhit",
)

CONTRAST_MIN = 4.5
TEAM_STATUS_MIN_DE = 8.0
TEAM_PAIR_MIN_DE = 20.0

_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_DECL = re.compile(r"(--[A-Za-z0-9_-]+)\s*:\s*([^;]+);")
_VAR = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)\s*(?:,[^()]*)?\)")
_PARTS = re.compile(r"\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*")
# A whole token name; a family glob in prose ("--data-dmg-*") is not a name.
_DATA_NAME = re.compile(r"--data-[a-z0-9-]*[a-z0-9](?![\w*-])")


# ------------------------------------------------------------------ parsing
def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _strip(css: str) -> str:
    return _COMMENT.sub("", css)


def _decls(block: str) -> dict[str, str]:
    """Declarations of one block; a later declaration of the same name wins
    (the cascade within a rule - themes.css restates hex then oklch)."""
    out: dict[str, str] = {}
    for name, val in _DECL.findall(block):
        out[name] = val.strip()
    return out


def base_root(tokens_css: str) -> dict[str, str]:
    m = re.search(r"(?<![\w\]-]):root\s*\{([^}]*)\}", _strip(tokens_css))
    return _decls(m.group(1)) if m else {}


def theme_blocks(themes_css: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for m in re.finditer(r':root\[data-theme="([a-z]+)"\]\s*\{([^}]*)\}', _strip(themes_css)):
        out.setdefault(m.group(1), {}).update(_decls(m.group(2)))
    return out


def overlay_block(overlay_css: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in re.finditer(r'(?<![\w-])body\[data-shell="overlay"\]\s*\{([^}]*)\}', _strip(overlay_css)):
        out.update(_decls(m.group(1)))
    return out


def theme_js_names(theme_js: str) -> list[str]:
    m = re.search(r"export const THEMES\s*=\s*\[([^\]]*)\]", theme_js)
    return re.findall(r'"([a-z]+)"', m.group(1)) if m else []


# --------------------------------------------------------------- colour math
def _oklch_to_rgb(L: float, C: float, h: float) -> tuple[int, int, int]:
    a = C * math.cos(math.radians(h))
    b = C * math.sin(math.radians(h))
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    lin = (
        4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
        -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
        -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_,
    )

    def enc(x: float) -> int:
        x = min(max(x, 0.0), 1.0)
        v = 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055
        return round(v * 255)

    return tuple(enc(v) for v in lin)  # type: ignore[return-value]


def colour(value: str) -> tuple[int, int, int] | None:
    """A resolved declaration value -> sRGB triple, or None if unparseable.
    Accepts bare parts, #rrggbb, rgb(parts) and oklch(L C h)."""
    v = value.strip()
    m = re.fullmatch(r"rgba?\((.*)\)", v)
    if m:
        v = m.group(1)
    pm = _PARTS.fullmatch(v)
    if pm:
        rgb = tuple(int(x) for x in pm.groups())
        return rgb if all(0 <= c <= 255 for c in rgb) else None  # type: ignore[return-value]
    hm = re.fullmatch(r"#([0-9a-fA-F]{6})", v)
    if hm:
        h = hm.group(1)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    om = re.fullmatch(r"oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\)", v)
    if om:
        return _oklch_to_rgb(*(float(x) for x in om.groups()))
    return None


def _lin(c: int) -> float:
    x = c / 255
    return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4


def luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (_lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def oklab_de(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    def lab(rgb):
        r, g, bl = (_lin(c) for c in rgb)
        lms = (
            (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * bl) ** (1 / 3),
            (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * bl) ** (1 / 3),
            (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * bl) ** (1 / 3),
        )
        l_, m_, s_ = lms
        return (
            0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
        )
    return 100 * math.dist(lab(a), lab(b))


# ---------------------------------------------------------------- resolution
def resolve(name: str, scope: dict[str, str], depth: int = 0) -> str | None:
    """Substitute var() heads against ``scope`` until none remain. None on a
    missing name or a cycle (depth cap) - the computed-value-time failure."""
    if depth > 12 or name not in scope:
        return None
    val = scope[name]
    while True:
        m = _VAR.search(val)
        if not m:
            return val
        sub = resolve(m.group(1), scope, depth + 1)
        if sub is None:
            return None
        val = val[:m.start()] + sub + val[m.end():]


def scopes(tokens_css: str, themes_css: str, overlay_css: str, base_css: str):
    """(label, scope dict, canvas names) for every theme, and the overlay
    shell layered over every theme."""
    base = dict(base_root(base_css))
    base.update(base_root(tokens_css))
    out = [("hextech", base, ("--canvas", "--surface", "--surface-2"))]
    for theme, decls in sorted(theme_blocks(themes_css).items()):
        sc = dict(base)
        sc.update(decls)
        out.append((theme, sc, ("--canvas", "--surface", "--surface-2")))
    ov = overlay_block(overlay_css)
    for label, sc, _c in list(out):
        layered = dict(sc)
        layered.update(ov)
        out.append((f"overlay/{label}", layered, ("--ovx-bg", "--ovx-bg-nested")))
    return out


# ------------------------------------------------------------------ checkers
def check_manifest(tokens_css: str) -> list[str]:
    root = base_root(tokens_css)
    probs = []
    if not root:
        probs.append("base :root block not found in tokens.css (empty enumeration)")
    for name in MANIFEST:
        val = root.get(name)
        if val is None:
            probs.append(f"{name} not declared in the base :root")
        elif not _PARTS.fullmatch(val) or colour(val) is None:
            probs.append(f"{name} = {val!r} is not bare 'R, G, B' parts")
    return probs


def check_orphans(css_texts: dict[str, str], consumer_texts: dict[str, str]) -> list[str]:
    probs = []
    for label, text in css_texts.items():
        for name, _v in _DECL.findall(_strip(text)):
            if name.startswith("--data-") and name not in MANIFEST:
                probs.append(f"{label}: declares {name}, not in the manifest")
    for label, text in consumer_texts.items():
        for name in set(_DATA_NAME.findall(text)):
            if name not in MANIFEST:
                probs.append(f"{label}: consumes {name}, not in the manifest")
    return probs


def consumed_tokens(consumer_texts: dict[str, str]) -> set[str]:
    used: set[str] = set()
    for label, text in consumer_texts.items():
        body = text if not label.endswith(".css") else _strip(text)
        if label.endswith("tokens.css") or label.endswith("overlay.css"):
            continue  # the declaring files, not consumers
        used.update(n for n in _DATA_NAME.findall(body) if n in MANIFEST)
    return used


def check_resolution(all_scopes) -> list[str]:
    probs = []
    if len(all_scopes) < 2:
        probs.append("fewer than two scopes enumerated (empty enumeration)")
    for label, sc, _c in all_scopes:
        for name in MANIFEST:
            val = resolve(name, sc)
            if val is None or colour(val) is None:
                probs.append(f"{label}: {name} does not resolve to a colour ({val!r})")
    return probs


def check_contrast(all_scopes) -> tuple[list[str], dict[str, tuple[float, str]]]:
    probs = []
    worst: dict[str, tuple[float, str]] = {}
    for label, sc, canvases in all_scopes:
        backs = []
        for cn in canvases:
            v = resolve(cn, sc)
            rgb = colour(v) if v is not None else None
            if rgb is None:
                probs.append(f"{label}: canvas {cn} unresolved ({v!r})")
            else:
                backs.append((cn, rgb))
        if not backs:
            probs.append(f"{label}: no canvas resolved (empty enumeration)")
        for name in MANIFEST:
            v = resolve(name, sc)
            rgb = colour(v) if v is not None else None
            if rgb is None:
                continue  # reported by check_resolution
            for cn, back in backs:
                r = contrast(rgb, back)
                if name not in worst or r < worst[name][0]:
                    worst[name] = (r, f"{label} {cn}")
                if r < CONTRAST_MIN:
                    probs.append(f"{label}: {name} {rgb} on {cn} {back} = {r:.2f}:1 < {CONTRAST_MIN}")
    return probs, worst


_STATUS_TOKENS = ("--signal-good", "--signal-bad", "--prim-green", "--prim-red",
                  "--ovx-good", "--ovx-red", "--good", "--bad")


def check_team(all_scopes) -> list[str]:
    probs = []
    for label, sc, _c in all_scopes:
        status = []
        for sn in ("--prim-green", "--prim-red", "--ovx-good", "--ovx-red"):
            v = resolve(sn, sc)
            rgb = colour(v) if v is not None else None
            if rgb is not None:
                status.append((sn, rgb))
        if not status:
            probs.append(f"{label}: no good/bad status hue resolved (empty enumeration)")
        team = {}
        for tn in ("--data-ally", "--data-enemy"):
            raw = sc.get(tn, "")
            for bad in _STATUS_TOKENS:
                if re.search(re.escape(bad) + r"(?![\w-])", raw):
                    probs.append(f"{label}: {tn} routes through status token {bad}")
            v = resolve(tn, sc)
            rgb = colour(v) if v is not None else None
            if rgb is None:
                continue
            team[tn] = rgb
            for sn, srgb in status:
                de = oklab_de(rgb, srgb)
                if de < TEAM_STATUS_MIN_DE:
                    probs.append(f"{label}: {tn} {rgb} is {de:.1f} dE from {sn} {srgb}")
        if len(team) == 2:
            de = oklab_de(team["--data-ally"], team["--data-enemy"])
            if de < TEAM_PAIR_MIN_DE:
                probs.append(f"{label}: ally/enemy only {de:.1f} dE apart")
    return probs


def check_overlay(overlay_css: str) -> list[str]:
    ov = overlay_block(overlay_css)
    probs = []
    if not ov:
        probs.append("no body[data-shell=overlay] block found (empty enumeration)")
    for name in OVERLAY_REQUIRED:
        if name not in ov:
            probs.append(f"overlay does not re-point {name}")
    for name, val in ov.items():
        if not name.startswith("--data-"):
            continue
        heads = _VAR.findall(val)
        if not heads or any(not h.startswith("--ovx-") for h in heads) or _VAR.sub("", val).strip():
            probs.append(f"overlay {name}: {val!r} must be exactly var(--ovx-*) (palette law)")
    return probs


# Per-site consumer contract: (relative path, tokens that MUST appear,
# regexes that must NOT match).
_PRES_ATTR = r'(?:stroke|fill)="\$\{_(?:ALLY|ENEMY|LINE)_COLOR\}"'
SITES = (
    ("web/js/panels/spike_curve.js", ("--data-ally", "--data-enemy"),
     (r'"#5096ff"', r'"#ff5050"', _PRES_ATTR, r'fill="\$\{color\}"', r'stroke="\$\{color\}"')),
    ("web/js/panels/ds_sweep.js", ("--data-ally",),
     (r'"#5096ff"', _PRES_ATTR)),
    ("web/js/panels/ward_heat.js", ("--data-ally", "--data-enemy"),
     (r"\[\s*80,\s*150,\s*255\s*\]", r"\[\s*255,\s*80,\s*80\s*\]")),
    ("web/css/panels/ward_heat.css", ("--data-ally", "--data-enemy"),
     (r"#80b8ff", r"#ff8080")),
    ("web/js/panels/map_state.js", ("--data-ally", "--data-enemy"),
     (r"(?:myRGB|enemyRGB)\s*=.*\[\s*\d", r"(?:myColor|enemyColor)\s*=.*#[0-9A-Fa-f]{6}",
      r"getComputedStyle\(\s*document\.documentElement")),
    ("web/js/panels/threat_donut.js",
     ("--data-dmg-physical", "--data-dmg-magic", "--data-dmg-true", "--data-dmg-onhit"),
     (r'"#ff5050"', r'"#5070ff"', r'"#eeeeee"', r'"#ffaa00"', r'setAttribute\(\s*"stroke",\s*_PALETTE')),
    ("web/css/panels/pgr_winprob.css", ("--data-ally", "--data-enemy"),
     (r"\.pwp-(?:area-)?(?:ally|enemy)(?:::before)?\s*\{[^}]*--signal-",)),
)


def check_sites(texts: dict[str, str]) -> list[str]:
    probs = []
    if not texts:
        probs.append("no consumer site enumerated (empty enumeration)")
    for rel, must, must_not in SITES:
        text = texts.get(rel)
        if text is None:
            probs.append(f"{rel}: missing")
            continue
        body = _strip(text) if rel.endswith(".css") else text
        for tok in must:
            if tok not in body:
                probs.append(f"{rel}: does not read {tok}")
        for pat in must_not:
            if re.search(pat, body):
                probs.append(f"{rel}: still matches {pat!r}")
        if "documentElement.appendChild" in body:
            probs.append(f"{rel}: mounts on documentElement (RM-139: body-scoped tokens unreachable)")
    return probs


# ------------------------------------------------------------------- corpus
def _corpus():
    tokens = _read(TOKENS)
    themes = _read(THEMES_CSS)
    overlay = _read(OVERLAY_CSS)
    base = _read(BASE_CSS)
    return tokens, themes, overlay, base


def _web_texts() -> dict[str, str]:
    out = {}
    for p in sorted(WEB.rglob("*")):
        if p.suffix in {".css", ".js", ".mjs", ".html"} and p.is_file():
            out[p.relative_to(ROOT).as_posix()] = p.read_text(encoding="utf-8", errors="replace")
    return out


# -------------------------------------------------------------------- tests
def test_manifest_declared_in_base_root_as_parts():
    tokens, *_ = _corpus()
    assert check_manifest(tokens) == []


def test_theme_enumeration_matches_theme_js():
    _t, themes, _o, _b = _corpus()
    in_css = set(theme_blocks(themes))
    in_js = set(theme_js_names(_read(THEME_JS))) - {"hextech"}  # hextech = attribute-less base
    assert in_js, "THEMES list not found in theme.js (empty enumeration)"
    assert in_css == in_js, f"themes.css blocks {sorted(in_css)} != theme.js {sorted(in_js)}"


def test_every_token_resolves_in_every_scope():
    sc = scopes(*_corpus())
    assert len(sc) >= 12, f"expected 6 themes + 6 overlay layers, got {len(sc)}"
    assert check_resolution(sc) == []


def test_contrast_floor_on_every_canvas():
    probs, worst = check_contrast(scopes(*_corpus()))
    assert probs == []
    assert set(worst) == set(MANIFEST)


def test_team_encoding_never_overloads_good_bad():
    assert check_team(scopes(*_corpus())) == []


def test_overlay_repoint_obeys_palette_law():
    _t, _th, overlay, _b = _corpus()
    assert check_overlay(overlay) == []


def test_no_orphans_anywhere_under_web():
    web = _web_texts()
    css = {k: v for k, v in web.items() if k.endswith(".css")}
    assert css, "no css enumerated"
    assert check_orphans(css, web) == []


def test_reserved_ratchet():
    used = consumed_tokens(_web_texts())
    assert used, "no --data-* consumer found (empty enumeration)"
    for name in MANIFEST:
        if name in RESERVED:
            assert name not in used, f"{name} now has a consumer - remove it from RESERVED"
            assert RESERVED[name].strip(), f"{name} RESERVED without a reason"
        else:
            assert name in used, f"{name} has no consumer and is not RESERVED"


def test_panel_sites_read_the_tier():
    texts = {rel: _read(ROOT / rel) for rel, _m, _n in SITES}
    assert check_sites(texts) == []


# --------------------------------------------------------- positive controls
def test_positive_control_missing_declaration():
    tokens, *_ = _corpus()
    anchor = re.search(r"\n\s*--data-xp\s*:[^;]+;", tokens)
    assert anchor, "anchor --data-xp not found - the plant cannot apply"
    planted = tokens[:anchor.start()] + tokens[anchor.end():]
    assert any("--data-xp" in p for p in check_manifest(planted))


def test_positive_control_empty_base_is_red():
    assert check_manifest("") != []


def test_positive_control_unresolved_in_a_theme():
    tokens, themes, overlay, base = _corpus()
    anchor = ':root[data-theme="arcane"] {'
    assert anchor in themes
    planted = themes.replace(anchor, anchor + "\n  --data-ally: var(--no-such-part);", 1)
    probs = check_resolution(scopes(tokens, planted, overlay, base))
    assert any("arcane" in p and "--data-ally" in p for p in probs)


def test_positive_control_team_reuses_status():
    tokens, themes, overlay, base = _corpus()
    anchor = re.search(r"--data-enemy\s*:[^;]+;", tokens)
    assert anchor
    planted = tokens[:anchor.start()] + "--data-enemy: var(--prim-red);" + tokens[anchor.end():]
    probs = check_team(scopes(planted, themes, overlay, base))
    assert any("routes through status token --prim-red" in p for p in probs)
    assert any("dE from --prim-red" in p for p in probs)


def test_positive_control_low_contrast():
    tokens, themes, overlay, base = _corpus()
    anchor = re.search(r"--data-ally\s*:[^;]+;", tokens)
    assert anchor
    planted = tokens[:anchor.start()] + "--data-ally: 30, 30, 40;" + tokens[anchor.end():]
    probs, _w = check_contrast(scopes(planted, themes, overlay, base))
    assert any("--data-ally" in p for p in probs)


def test_positive_control_orphan_consumer_and_declaration():
    probs = check_orphans({"x.css": ":root { --data-bogus: 1, 2, 3; }"},
                          {"y.js": 'el.style.color = "rgb(var(--data-bogus))"; // the --data-dmg-* family'})
    assert len(probs) == 2


def test_positive_control_overlay_literal():
    planted = 'body[data-shell="overlay"] { --data-dmg-magic: 1, 2, 3; }'
    probs = check_overlay(planted)
    assert any("palette law" in p for p in probs)
    assert any("--data-dmg-physical" in p for p in probs)


def test_positive_control_site_regression():
    rel = "web/js/panels/spike_curve.js"
    text = _read(ROOT / rel)
    planted = text.replace("--data-ally", "--x-ally") + '\nconst _ALLY_COLOR2 = "#5096ff";\n'
    probs = check_sites({**{r: _read(ROOT / r) for r, _m, _n in SITES}, rel: planted})
    assert any(rel in p and "--data-ally" in p for p in probs)
    assert any(rel in p and "#5096ff" in p for p in probs)
