"""
tests/test_motion_reduce_sweep_oq4.py

OQ4 (QA45, operator-queue 2026-07-01) - quiet-by-default motion sweep of the
infinite CSS animation loops, respecting prefers-reduced-motion.

Classification result (5 parallel analysts + adversarial verify, 2026-07-01):
ALL 10 infinite-loop sites carry a LIVE signal (loading shimmer, buy-cue,
queue-searching heartbeat, zone-danger alarm, critical-HP alarm, advisory
attention) - none is pure ambient decoration. So the correct sweep per the
tokens.css RC2 D2 doctrine ("REPLACE the signal, do not kill it") is:

  - DEFAULT rendering unchanged (motion-tolerant users keep every loop);
  - EVERY loop gains a same-file @media (prefers-reduced-motion: reduce)
    static-replace: animation: none !important plus a static hold (ring /
    color / opacity) that preserves the meaning.

The pre-existing input_activity.css:473 global wildcard (0.01ms duration,
iteration-count 1) already HALTS all animation under reduce but silently
drops the signals - exactly the anti-pattern the tokens.css:169 comment
calls out. The per-site holds locked here layer the signal back on top.

Invariants:
  A. drift guard - any web/css file declaring an `infinite` animation must
     carry a prefers-reduced-motion block (future loops cannot ship uncovered);
  B. per-site - each known selector is covered by a same-file reduce block
     containing `animation: none !important`;
  C. the reduce blocks are pure 7-bit ASCII;
  D. the 7 default loops still exist (the sweep did NOT trim default
     rendering - that would drop live signals; re-litigate via operator).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS_DIR = ROOT / "web" / "css"

REDUCE_AT = "@media (prefers-reduced-motion: reduce)"

# Every infinite-loop site and the selector its reduce block must cover.
# (panels/primitives.css .rc-skel was in the original 10 but the whole
# dormant rc-skel mechanism was removed 2026-07-01 - see
# tests/test_rc_skel_removed.py. The header row-2 removal 2026-07-04 then
# retired the .hp.hp-critical HP-bar alarm with its element, and the
# 2026-07-05 E11 lobby restructure (dead-code purge, commit c6670b19)
# retired the .lobby-status.searching queue heartbeat with its element -
# leaving 7 live-signal loops.)
SITES = {
    "panels/item_build.css": [
        ".item-tile.next-up .item-icon",
        ".item-tile.next-up.can-afford .item-icon",
    ],
    "panels/map_state.css": [
        'body[data-zone="deep"] .panel-right-now',
        ".zone-pill.zone-deep",
    ],
    "panels/header.css": [
        ".lq-find.is-searching",
        ".zone-pill.zone-enemy",
        ".advisory-badge.pulse",
    ],
}

_INFINITE = re.compile(r"animation:[^;{}]*\binfinite\b", re.IGNORECASE)


def _reduce_blocks(css: str) -> str:
    """Concatenate the body text of every prefers-reduced-motion block."""
    out = []
    i = 0
    while True:
        i = css.find(REDUCE_AT, i)
        if i < 0:
            break
        j = css.find("{", i)
        depth, k = 1, j + 1
        while depth and k < len(css):
            if css[k] == "{":
                depth += 1
            elif css[k] == "}":
                depth -= 1
            k += 1
        out.append(css[j + 1 : k - 1])
        i = k
    return "\n".join(out)


def _all_css_files():
    return sorted(CSS_DIR.rglob("*.css"))


# --------------------------------------------------------------------- A
def test_every_infinite_loop_file_has_reduce_block():
    """Drift guard: an infinite animation may not ship without same-file
    prefers-reduced-motion coverage."""
    offenders = []
    for p in _all_css_files():
        css = p.read_text(encoding="utf-8", errors="replace")
        if _INFINITE.search(css) and REDUCE_AT not in css:
            offenders.append(str(p.relative_to(ROOT)))
    assert not offenders, (
        f"infinite animation without a prefers-reduced-motion block: {offenders}"
    )


# --------------------------------------------------------------------- B
def test_each_known_site_static_replaced():
    """Each classified selector gets animation: none !important inside a
    same-file reduce block (the RC2 D2 static-replace)."""
    missing = []
    for rel, selectors in SITES.items():
        css = (CSS_DIR / rel).read_text(encoding="utf-8", errors="replace")
        blocks = _reduce_blocks(css)
        for sel in selectors:
            pat = re.compile(
                re.escape(sel) + r"\s*{[^}]*animation:\s*none\s*!important",
                re.DOTALL,
            )
            if not pat.search(blocks):
                missing.append(f"{rel} :: {sel}")
    assert not missing, (
        "selector(s) not static-replaced under prefers-reduced-motion: "
        f"{missing}"
    )


# --------------------------------------------------------------------- C
def test_reduce_blocks_are_ascii():
    for rel in SITES:
        css = (CSS_DIR / rel).read_text(encoding="utf-8", errors="replace")
        blocks = _reduce_blocks(css)
        bad = sorted({c for c in blocks if ord(c) > 0x7F})
        assert not bad, f"{rel}: non-ASCII in reduce block(s): {bad!r}"


# --------------------------------------------------------------------- D
def test_default_loops_unchanged():
    """The sweep must NOT trim default rendering - the live-signal loops
    survive for motion-tolerant users (operator can re-litigate). 7 since
    the dormant rc-skel loop (2026-07-01), the .hp.hp-critical HP-bar alarm
    (2026-07-04 header row-2 removal), and the .lobby-status.searching lobby
    heartbeat (2026-07-05 E11 dead-code purge) were retired with their
    mechanisms."""
    count = 0
    for rel in SITES:
        css = (CSS_DIR / rel).read_text(encoding="utf-8", errors="replace")
        count += len(_INFINITE.findall(css))
    assert count == 7, (
        f"expected the 7 classified default loops to survive, found {count}"
    )
