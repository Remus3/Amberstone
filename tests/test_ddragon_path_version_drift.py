"""Guard: no live JS hardcodes a versioned DDragon mirror PATH.

Regression for the deep-audit P1 mirror prune (item 396): active_match.js
pinned /data/ddragon/16.10.1/img/map/*.png, which silently froze the map
pane onto a stale patch dir and made every old mirror dir load-bearing.
Asset URLs must derive the patch from the hydrated ITEMS/CHAMPS index
(items_index.js) so the mirror can be pruned to the current patch.

Bare version literals used as pre-hydration FALLBACKS (e.g.
``(ITEMS && ITEMS.version) || "16.10.1"``) are fine: ITEMS.version is
always truthy, the fallback is unreachable, and a wrong guess only
404s into the existing onerror CDN chain. Only PATH literals are banned.
"""
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_JS_ROOT = _REPO_ROOT / "web" / "js"

_VERSIONED_DDRAGON_PATH = re.compile(r"/data/ddragon/\d+\.\d+\.\d+")


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
