"""The /sync-all-md README contract and README.md must describe the same page.

MEASURED 2026-10-18. `tools/sync-all-md.md` section 4 still carried the s207
README contract - an 8-section skeleton (title > What it does > How it works >
Daemon Slayer > Where it runs > Project status > More > License), exactly one
6-row table and "no install steps" - while README.md had grown to 13 sections,
three tables and a Quickstart. MAIN's GH-HYGIENE ORDER (2026-10-18 12:15)
requires the "How this repo is built" heading to stay and verifies the install
steps, so running /sync-all-md as written would have stripped exactly what that
ORDER kept. Nothing compared the two, so the skill and the page drifted apart.

The contract now lists the README skeleton as a fenced block in section 4, and
this file parses that block and README.md's real headings and fails on any
difference, in either direction. Edit both in one commit or neither.

Each parser is anchored (a parser that silently finds nothing cannot pass).
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SKILL = _REPO / "tools" / "sync-all-md.md"
_README = _REPO / "README.md"

_SKELETON_INTRO = "README skeleton - its `#` / `##` headings, in order."
_TABLE_SEP = re.compile(r"^\|(\s*:?-{3,}:?\s*\|)+\s*$")
_CONTENTS_ROW = re.compile(r"^\|\s*\[([^\]]+)\]\(#([^)]+)\)\s*\|")


def _text(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def _section4(skill: str) -> str:
    start = skill.index("\n### 4. README pass")
    end = skill.index("\n### 5. ", start)
    return skill[start:end]


def _unfenced_lines(text: str) -> list[str]:
    """Lines outside ``` fences (README code blocks are not headings)."""
    out, fenced = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):  # list-indented fences count
            fenced = not fenced
            continue
        if not fenced:
            out.append(line)
    return out


def _contract_skeleton() -> list[str]:
    sec = _section4(_text(_SKILL))
    after = sec[sec.index(_SKELETON_INTRO):]
    open_at = after.index("```text\n") + len("```text\n")
    close_at = after.index("\n```", open_at)
    return [ln for ln in after[open_at:close_at].split("\n") if ln.strip()]


def _readme_headings() -> list[str]:
    return [ln.rstrip() for ln in _unfenced_lines(_text(_README))
            if re.match(r"^#{1,2} ", ln)]


def _github_anchor(heading: str) -> str:
    slug = heading.strip().lower()
    slug = re.sub(r"[^\w\- ]", "", slug)
    return slug.replace(" ", "-")


def _readme_section(name: str) -> str:
    text = _text(_README)
    start = text.index(f"\n## {name}\n")
    nxt = text.find("\n## ", start + 1)
    return text[start:nxt if nxt != -1 else len(text)]


def test_the_contract_skeleton_parses():
    skeleton = _contract_skeleton()
    assert len(skeleton) >= 8, f"parsed only {len(skeleton)} skeleton lines"
    assert all(re.match(r"^#{1,2} \S", ln) for ln in skeleton), skeleton
    assert skeleton[0].startswith("# "), "the skeleton starts with the title"


def test_readme_headings_match_the_contract_skeleton_in_order():
    skeleton, actual = _contract_skeleton(), _readme_headings()
    assert len(actual) >= 8, f"parsed only {len(actual)} README headings"
    assert actual == skeleton, (
        "README.md headings and the tools/sync-all-md.md section 4 skeleton "
        "differ. A section change needs an ORDER and then BOTH files change in "
        f"one commit.\n contract: {skeleton}\n README:   {actual}"
    )


def test_the_contents_table_lists_every_section_in_order():
    sections = [h[3:] for h in _readme_headings() if h.startswith("## ")]
    after_contents = sections[sections.index("Contents") + 1:]
    rows = [m.groups() for m in map(_CONTENTS_ROW.match,
                                    _readme_section("Contents").split("\n")) if m]
    assert len(rows) >= 5, f"parsed only {len(rows)} Contents rows"
    assert [r[0] for r in rows] == after_contents, (rows, after_contents)
    bad = [(t, a) for t, a in rows if a != _github_anchor(t)]
    assert not bad, f"Contents anchors that do not resolve: {bad}"


def test_readme_table_count_matches_the_contract():
    m = re.search(r"Exactly \*\*(\d+)\*\* tables", _section4(_text(_SKILL)))
    assert m, "section 4 no longer states 'Exactly **N** tables'"
    seps = [ln for ln in _unfenced_lines(_text(_README)) if _TABLE_SEP.match(ln)]
    assert len(seps) == int(m.group(1)), (
        f"README.md has {len(seps)} tables; the contract allows {m.group(1)}"
    )


def test_the_contract_keeps_the_gh_hygiene_requirements():
    sec = _section4(_text(_SKILL))
    for needle in ("GH-HYGIENE", "2026-10-18", "## Quickstart",
                   "## How this repo is built", "Install steps live ONLY in",
                   "**No session changelog, no `sNNN` ids, no commit SHAs"):
        assert needle in sec, needle


def test_the_retired_s207_skeleton_is_not_reasserted():
    sec = _section4(_text(_SKILL))
    for stale in ("8-section skeleton", "no install steps,",
                  "Exactly **one** table", "Where it runs > Project status"):
        assert stale not in sec, f"retired s207 rule back in section 4: {stale!r}"


def test_quickstart_names_only_files_that_exist_at_head():
    # Drop the fenced clone block first: its triple backticks would pair the
    # inline spans after it the wrong way round.
    quick = "\n".join(_unfenced_lines(_readme_section("Quickstart")))
    spans = re.findall(r"`([^`]+)`", quick)
    paths = [p for s in spans for p in
             re.findall(r"[\w.-]+(?:/[\w.-]+)*\.(?:bat|txt|ps1|py|md)\b", s)]
    assert len(paths) >= 4, f"parsed only {paths}"
    # splitlines + strip: a Windows checkout may carry .gitignore as CRLF.
    gitignore = [ln.strip() for ln in _text(_REPO / ".gitignore").splitlines()]
    missing = []
    for p in paths:
        if p.startswith("API-Key-"):
            # Per-user key files: gitignored by design, never at HEAD.
            if p not in gitignore:
                missing.append(f"{p} (key file not gitignored)")
        elif not (_REPO / p).is_file():
            missing.append(p)
    assert not missing, f"README Quickstart names missing files: {missing}"
