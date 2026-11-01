"""Print the parts of a lane doc (tools/headless-<lane>.md) a lane worker must read.

The rotating lane directive used to inline the whole lane doc. Most of each doc is
the sections a lane directive overrides (push, CI, dual suite, wrap, banner) plus
the three standing banners every doc repeats. This prints:
  - the doc's own preamble, minus those three banners and the frontmatter
  - every section in MUST, and every numbered section the map does not know
  - a one-line index of the ON_DEMAND sections, each with its read trigger

An unclassified section prints in full, so a section added to a doc is read rather
than lost. A named section missing from a doc exits 2: the worker then reads the
whole doc. Nothing here deletes or edits a lane doc; every section stays reachable.

Usage:
  python tools/lane_doc_sections.py <lane>                 the pre-flight read
  python tools/lane_doc_sections.py <lane> --section <n>   one on-demand section
Long form: docs/LANE_PROMPT_REFERENCE.md.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEADING = re.compile(r"(?m)^#{2,3} (\d+)\.[^\n]*$")
BANNERS = ("> **SUBAGENT-FIRST", "> **DISPATCH", "> **RACE GUARDS")
SUPERSEDED = "superseded by the directive; read only if the directive is silent"

MAP: dict[str, dict] = {
    "ds": {
        "must": ("1", "2", "4", "6", "10"),
        "on_demand": {
            "3": "before believing a registry-count or ASCII-hygiene test failure",
            "5": "when a spec or finding involves a default-flip",
            "7": "when writing a Tier-2 / ENGINE_VERSION spec",
            "8": "when writing a DS restart MERGER FOLLOW-UP (a lane never restarts DS)",
            "9": SUPERSEDED,
            "11": SUPERSEDED,
        },
    },
    "gated": {
        "must": ("0", "1", "2", "3", "4", "7"),
        "on_demand": {
            "5": "when classifying a change's tier",
            "6": "before committing an edit to docs/LIVE_GAME_GATED_SYNC.md",
        },
    },
    "queue": {
        "must": ("1", "2", "4", "6", "12", "13"),
        "on_demand": {
            "3": "only when rows 1-7 of the directive are all closed, taken or blocked",
            "5": SUPERSEDED + " (a lane never mints an id)",
            "7": SUPERSEDED,
            "8": SUPERSEDED,
            "9": SUPERSEDED,
            "10": SUPERSEDED,
            "11": SUPERSEDED,
            "14": SUPERSEDED,
        },
    },
    "repo": {
        "must": ("1", "3", "5", "6", "8", "9", "11"),
        "on_demand": {
            "2": "before reading any area outside the worktree (writing there is suspended)",
            "4": "if a row names ops/loop/slots.py or ops/loop/winmutex.py (never edit them)",
            "7": "before any rename, move or module split",
            "10": SUPERSEDED + " (the guards in its step 2 are in the lane section)",
            "12": SUPERSEDED,
        },
    },
    "research": {
        "must": ("1", "2", "3", "4", "5", "6", "7", "9"),
        "on_demand": {"8": SUPERSEDED, "10": SUPERSEDED},
    },
    "true-audit": {
        "must": ("1", "2", "3", "4", "5", "6", "7", "8", "10"),
        "on_demand": {
            "9": SUPERSEDED + " (its backfill step is in the lane section)",
            "11": SUPERSEDED,
        },
    },
    "uiux": {
        "must": ("1", "2", "3", "4", "5", "6", "7", "9"),
        "on_demand": {
            "8": SUPERSEDED + " (its QA-doc step is in the lane section)",
            "10": SUPERSEDED,
        },
    },
}


class MapError(Exception):
    """The map names a doc or section that is not there."""


def doc_path(lane: str, root: Path = ROOT) -> Path:
    return root / "tools" / f"headless-{lane}.md"


def split_doc(text: str) -> tuple[str, dict[str, str]]:
    """Return (preamble, {section number: heading + body}). Numbered headings only."""
    text = text.replace("\r\n", "\n")
    marks = list(HEADING.finditer(text))
    pre = text[: marks[0].start()] if marks else text
    sections = {}
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        sections[mark.group(1)] = text[mark.start():end].rstrip() + "\n"
    return pre, sections


def strip_preamble(pre: str) -> str:
    """Drop the frontmatter and the three standing banners; keep everything else."""
    if pre.startswith("---\n"):
        end = pre.find("\n---\n", 4)
        if end != -1:
            pre = pre[end + 5:]
    keep = [p for p in re.split(r"\n\s*\n", pre)
            if p.strip() and not p.lstrip().startswith(BANNERS)]
    return "\n\n".join(p.strip("\n") for p in keep) + "\n"


def must_read(lane: str, root: Path = ROOT) -> str:
    cfg = MAP[lane]
    path = doc_path(lane, root)
    if not path.is_file():
        raise MapError(f"lane doc missing: {path.name}")
    pre, sections = split_doc(path.read_text(encoding="utf-8"))
    known = set(cfg["must"]) | set(cfg["on_demand"])
    missing = sorted(known - set(sections))
    if missing:
        raise MapError(f"{path.name}: map names absent section(s) {missing}")
    out = [f"LANE DOC {path.name}, required parts. Your directive wins wherever they differ.\n",
           strip_preamble(pre)]
    for num, body in sections.items():
        if num not in cfg["on_demand"]:  # MUST, or unclassified: read it
            out.append(body)
    index = [f"  section {num}: {why}" for num, why in cfg["on_demand"].items()]
    out.append(f"ON-DEMAND (python tools/lane_doc_sections.py {lane} --section <n>):\n"
               + "\n".join(index) + "\n")
    return "\n".join(out)


def one_section(lane: str, num: str, root: Path = ROOT) -> str:
    path = doc_path(lane, root)
    if not path.is_file():
        raise MapError(f"lane doc missing: {path.name}")
    _pre, sections = split_doc(path.read_text(encoding="utf-8"))
    if num not in sections:
        raise MapError(f"{path.name}: no section {num}")
    return sections[num]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("lane", choices=sorted(MAP))
    ap.add_argument("--section", help="print this one section")
    args = ap.parse_args(argv)
    try:
        text = one_section(args.lane, args.section) if args.section else must_read(args.lane)
    except MapError as exc:
        print(f"lane_doc_sections: {exc}. Read the whole lane doc instead.", file=sys.stderr)
        return 2
    sys.stdout.buffer.write(text.encode("ascii", "replace"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
