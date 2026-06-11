"""Guard: no live JS hardcodes a versioned DDragon mirror PATH.

Regression for the deep-audit P1 mirror prune (item 396): active_match.js
pinned /data/ddragon/16.10.1/img/map/*.png, which silently froze the map
pane onto a stale patch dir and made every old mirror dir load-bearing.
Asset URLs must derive the patch from the hydrated ITEMS/CHAMPS index
(items_index.js) so the mirror can be pruned to the current patch.

Bare version literals used as pre-hydration FALLBACKS (e.g.
``(ITEMS && ITEMS.version) || "16.10.1"``) are unreachable (ITEMS.version
is always truthy post-hydration) and a wrong guess only 404s into the
existing onerror CDN chain - but scattered copies drift (16.10.1 vs
16.12.1 mixed across panels). Deep-audit P2: they are centralized into
the single shared ``DDRAGON_FALLBACK_VERSION`` constant in
web/js/lib/items_index.js; the second guard below bans any other quoted
semver literal in live JS.
"""
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_JS_ROOT = _REPO_ROOT / "web" / "js"

_VERSIONED_DDRAGON_PATH = re.compile(r"/data/ddragon/\d+\.\d+\.\d+")

# Quoted semver string literal anywhere in a JS line ("16.12.1" / '16.12.1').
_QUOTED_SEMVER = re.compile(r"""["']\d+\.\d+\.\d+["']""")
# The one allowed home: the shared constant definition in items_index.js.
_FALLBACK_HOME = _JS_ROOT / "lib" / "items_index.js"
_FALLBACK_DEF = re.compile(
    r"""^export const DDRAGON_FALLBACK_VERSION = ["']\d+\.\d+\.\d+["'];"""
)


def test_no_versioned_ddragon_path_literal_in_live_js():
    offenders = []
    for js in sorted(_JS_ROOT.rglob("*.js")):
        text = js.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if _VERSIONED_DDRAGON_PATH.search(line):
                offenders.append(f"{js.relative_to(_REPO_ROOT)}:{i}: {line.strip()[:100]}")
    assert not offenders, (
        "versioned /data/ddragon/<patch>/ path literal(s) in live JS - "
        "derive the patch from ITEMS/CHAMPS.version instead:\n" + "\n".join(offenders)
    )


def test_semver_fallback_literals_centralized_in_items_index():
    """Scattered ``|| "16.x.y"`` (and ternary / early-return) version
    fallback literals are banned in live JS. The ONLY allowed quoted
    semver literal is the single ``DDRAGON_FALLBACK_VERSION`` constant
    definition in web/js/lib/items_index.js; every consumer imports it."""
    offenders = []
    def_lines = 0
    for js in sorted(_JS_ROOT.rglob("*.js")):
        text = js.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if not _QUOTED_SEMVER.search(line):
                continue
            if js == _FALLBACK_HOME and _FALLBACK_DEF.match(line.strip()):
                def_lines += 1
                continue
            offenders.append(f"{js.relative_to(_REPO_ROOT)}:{i}: {line.strip()[:100]}")
    assert def_lines == 1, (
        "expected exactly one DDRAGON_FALLBACK_VERSION definition line in "
        f"web/js/lib/items_index.js, found {def_lines}"
    )
    assert not offenders, (
        "quoted semver version literal(s) in live JS outside the shared "
        "DDRAGON_FALLBACK_VERSION constant (web/js/lib/items_index.js) - "
        "import the constant instead:\n" + "\n".join(offenders)
    )
