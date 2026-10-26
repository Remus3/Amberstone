"""RM-928 (c): the TFT-HUD spec's code citations point at the code they name.

docs/TFT_PROGRAM.md section 10 (the live HUD reader spec, s136 T16) is the
acceptance text for the TFT-HUD-00..12 slices, so a citation there that lands on
the wrong lines sends a builder to the wrong code. Measured 2026-10-26:

  - 10.3 item 2 cited `tft/tft_state_reader.py:241-251` for the 2.0 s OCR sleep;
    those lines are the class attribute and `__init__`, the sleep is in
    `TftStateReader._ocr_loop`.
  - 10.3 item 4 cited `dashboard/_state_builder.py` lines that moved when the
    RM-924 lobby pre-flip added lines above them.
  - 10.1 cited three `docs/LEDGER.md:<line>` locations. The LEDGER is
    newest-first, so every new entry moves every line below it; all three had
    drifted onto other entries or a blank line. A LEDGER entry is cited by its
    entry NUMBER, which never moves.

Each check reads the cited lines and asserts they hold the code the sentence
describes. When one of these files is edited above a cited line this test goes
red on purpose: the fix is the citation in docs/TFT_PROGRAM.md, not this test.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "TFT_PROGRAM.md"


def _section_10() -> str:
    text = DOC.read_text(encoding="utf-8")
    start = text.index("\n## 10. ")
    nxt = text.find("\n## ", start + 1)
    return text[start:] if nxt == -1 else text[start:nxt]


def _item(section: str, begin: str, end: str) -> str:
    i = section.index(begin)
    j = section.index(end, i)
    return section[i:j]


def _lines(rel: str, first: int, last: int) -> str:
    src = (ROOT / rel).read_text(encoding="utf-8").splitlines()
    assert 1 <= first <= last <= len(src), f"{rel}:{first}-{last} is out of range"
    return "\n".join(src[first - 1:last])


def _cites(item: str, rel: str) -> list[tuple[int, int]]:
    """Every `rel:a[-b]` citation in `item`, plus bare `:a[-b]` ones that follow it."""
    out: list[tuple[int, int]] = []
    pat = re.compile(r"`(?:([A-Za-z0-9_./-]+):|:)(\d+)(?:-(\d+))?`")
    current = None
    for m in pat.finditer(item):
        if m.group(1):
            current = m.group(1)
        if current == rel:
            a = int(m.group(2))
            out.append((a, int(m.group(3) or a)))
    return out


def _ocr_sleep_line() -> tuple[int, float]:
    """(line, seconds) of the time.sleep call inside TftStateReader._ocr_loop."""
    tree = ast.parse((ROOT / "tft" / "tft_state_reader.py").read_text(encoding="utf-8"))
    for cls in ast.walk(tree):
        if isinstance(cls, ast.ClassDef) and cls.name == "TftStateReader":
            for fn in cls.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == "_ocr_loop":
                    for node in ast.walk(fn):
                        if (isinstance(node, ast.Call)
                                and isinstance(node.func, ast.Attribute)
                                and node.func.attr == "sleep"
                                and node.args
                                and isinstance(node.args[0], ast.Constant)):
                            return node.lineno, float(node.args[0].value)
    raise AssertionError("TftStateReader._ocr_loop has no time.sleep(<constant>) call")


def test_ocr_thread_cite_lands_on_the_ocr_loop_sleep():
    item = _item(_section_10(), "**OCR thread.**", "**Worker poll.**")
    line, seconds = _ocr_sleep_line()
    stated = re.search(r"sleeps (\d+(?:\.\d+)?) s", item)
    assert stated and float(stated.group(1)) == seconds, (
        f"10.3 item 2 states the OCR sleep as {stated and stated.group(1)} s; "
        f"_ocr_loop sleeps {seconds} s")
    assert "_ocr_loop" in item, "10.3 item 2 should name TftStateReader._ocr_loop"
    cites = _cites(item, "tft/tft_state_reader.py")
    assert cites, "10.3 item 2 cites no tft/tft_state_reader.py line"
    assert any(a <= line <= b for a, b in cites), (
        f"10.3 item 2 cites tft/tft_state_reader.py {cites}; the _ocr_loop sleep is "
        f"at :{line} - fix the citation in docs/TFT_PROGRAM.md")


def test_bottleneck_cites_land_on_the_coach_file_read_and_the_hp_fill():
    item = _item(_section_10(), "**The bottleneck.**", "**State cadence.**")
    cites = _cites(item, "dashboard/_state_builder.py")
    assert len(cites) == 3, f"10.3 item 4 should cite 3 _state_builder.py locations: {cites}"
    (a1, b1), (a2, b2), (a3, b3) = cites
    read = _lines("dashboard/_state_builder.py", a1, b1)
    assert "coach_file = MODE_TO_FILE.get(" in read and "read_json(coach_file)" in read, (
        f"dashboard/_state_builder.py:{a1}-{b1} is not the coach-file read:\n{read}")
    fill = _lines("dashboard/_state_builder.py", a2, b2)
    assert "_TFT_STANDALONE_COACH_FILL = (" in fill, (
        f"dashboard/_state_builder.py:{a2} is not the EoG fill table:\n{fill}")
    loop = _lines("dashboard/_state_builder.py", a3, b3)
    assert "for src, dst in _TFT_STANDALONE_COACH_FILL" in loop, (
        f"dashboard/_state_builder.py:{a3} is not the blanks-only fill loop:\n{loop}")


def test_section_10_cites_ledger_entries_by_number_not_by_line():
    hits = re.findall(r"docs/LEDGER\.md:\d+", _section_10())
    assert not hits, (
        f"section 10 cites LEDGER lines {hits}; the LEDGER is newest-first, so a line "
        "citation drifts with every new entry - cite the entry number instead")


def test_ledger_entries_named_in_section_10_exist():
    """The three entries the 10.1 history names (R120, R125, R220) carry those labels."""
    ledger = (ROOT / "docs" / "LEDGER.md").read_text(encoding="utf-8")
    section = _section_10()
    for entry, label in (("894", "R120"), ("899", "R125"), ("1099", "R220")):
        assert f"LEDGER entry {entry}" in section, f"section 10 should cite LEDGER entry {entry}"
        m = re.search(rf"^{entry}\. DONE .*$", ledger, re.M)
        assert m and label in m.group(0), f"LEDGER entry {entry} is not the {label} entry"
