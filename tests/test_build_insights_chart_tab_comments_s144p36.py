"""
tests/test_build_insights_chart_tab_comments_s144p36.py
RM-1187: the Build Insights comments count and name the chart tabs that
the code really dispatches.

web/index.html carries nine data-bi-tab buttons. Four are the WPA tables
(`_TABLE_KEYS` in web/js/panels/build_insights.js) and five are chart
panels that `_renderActive` dispatches to their own modules (duration,
snowball, flow, opscore, bench). The comments had not kept up with the
Snowball tab and the other chart panels:

- the comment above `_syncControls` said "the four chart tabs (duration /
  flow / opscore / bench)", leaving out snowball;
- the comment above `_renderActive` said only the Game Length tab is a
  chart panel and "every other tab flows through the shared table engine",
  but five tabs skip the table engine;
- the min_n debounce comment in `_wireControlsOnce` said "invalidate both
  caches", but it clears four table caches;
- the R30 review test docstring said the Min-N control "HIDES on the four
  chart tabs".

The tab sets are measured from the source, never restated, so a new tab
turns this red until its comments are updated. This is a static read: no
browser and no mock server.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BI_JS = ROOT / "web" / "js" / "panels" / "build_insights.js"
INDEX = ROOT / "web" / "index.html"
R30 = ROOT / "tests" / "snapshot_panels" / "test_build_insights_review_r30.py"

_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "both": 2,
}
_COUNT_RE = re.compile(
    r"\b(" + "|".join(_NUM) + r")\s+(WPA\s+tables|chart\s+tabs|"
    r"chart\s+panels|(?:table\s+)?caches)\b",
    re.IGNORECASE,
)


def _src():
    return BI_JS.read_text(encoding="utf-8")


def _html_tabs():
    keys = re.findall(r'data-bi-tab="([a-z]+)"', INDEX.read_text(encoding="utf-8"))
    assert keys, "no data-bi-tab buttons found in web/index.html"
    return keys


def _table_keys():
    m = re.search(r"const _TABLE_KEYS = \[([^\]]*)\];", _src())
    assert m, "_TABLE_KEYS not found in build_insights.js"
    keys = re.findall(r"'([a-z]+)'", m.group(1))
    assert keys, "_TABLE_KEYS is empty"
    return keys


def _chart_keys():
    m = re.search(r"function _renderActive\(\) \{(.*?)\n\}", _src(), re.S)
    assert m, "_renderActive not found in build_insights.js"
    keys = re.findall(r"_ST\.active === '([a-z]+)'", m.group(1))
    assert keys, "_renderActive dispatches no chart tab"
    return keys


def _comment_above(func):
    lines = _src().splitlines()
    idx = next(
        (i for i, ln in enumerate(lines) if ln.startswith(f"function {func}(")),
        None,
    )
    assert idx is not None, f"function {func} not found in build_insights.js"
    block = []
    i = idx - 1
    while i >= 0 and lines[i].lstrip().startswith("//"):
        block.insert(0, lines[i])
        i -= 1
    assert block, f"no comment block directly above {func}"
    return "\n".join(block)


def _counts(text):
    out = []
    for m in _COUNT_RE.finditer(text):
        noun = re.sub(r"\s+", " ", m.group(2).lower())
        out.append((_NUM[m.group(1).lower()], noun, m.group(0)))
    return out


def test_tab_sets_partition_the_html_tabs():
    html, table, chart = _html_tabs(), _table_keys(), _chart_keys()
    assert len(html) == len(set(html)), f"duplicate data-bi-tab: {html}"
    assert not set(table) & set(chart), (table, chart)
    assert set(table) | set(chart) == set(html), (
        f"html tabs {sorted(html)} != table {sorted(table)} + chart "
        f"{sorted(chart)}"
    )


def test_sync_controls_comment_names_every_chart_tab():
    text = _comment_above("_syncControls")
    missing = [k for k in _chart_keys() if not re.search(rf"\b{k}\b", text)]
    assert not missing, f"_syncControls comment omits chart tab(s) {missing}"


def test_render_active_comment_names_every_chart_tab():
    text = _comment_above("_renderActive")
    missing = [k for k in _chart_keys() if not re.search(rf"\b{k}\b", text)]
    assert not missing, f"_renderActive comment omits chart tab(s) {missing}"
    assert "every other tab" not in text, (
        "_renderActive comment says every non-duration tab uses the table "
        "engine; five chart tabs skip it"
    )


def test_count_words_match_the_measured_sets():
    want = {
        "wpa tables": len(_table_keys()),
        "caches": len(_table_keys()),
        "table caches": len(_table_keys()),
        "chart tabs": len(_chart_keys()),
        "chart panels": len(_chart_keys()),
    }
    bad = []
    seen = set()
    for path in (BI_JS, R30):
        for n, noun, phrase in _counts(path.read_text(encoding="utf-8")):
            seen.add(noun)
            expect = want[noun]
            if n != expect:
                bad.append(f"{path.name}: {phrase!r} (measured {expect})")
    assert not bad, "stale count word(s): " + "; ".join(bad)
    # Anchor: an empty scan would pass vacuously.
    assert {"wpa tables", "chart tabs", "table caches"} <= seen, seen


def test_this_file_is_ascii_lf():
    raw = Path(__file__).read_bytes()
    assert all(b < 0x80 for b in raw), "non-ASCII byte in this guard"
    assert b"\r" not in raw, "CR byte in this guard"
