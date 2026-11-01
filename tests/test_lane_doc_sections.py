"""FLEET-3b: the lane doc section map and the usage reader."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import lane_doc_sections as lds  # noqa: E402
import lane_usage_median as lum  # noqa: E402

REFERENCE = Path(__file__).resolve().parents[1] / "docs" / "LANE_PROMPT_REFERENCE.md"


@pytest.mark.parametrize("lane", sorted(lds.MAP))
def test_map_matches_the_real_doc(lane):
    _pre, sections = lds.split_doc(lds.doc_path(lane).read_text(encoding="utf-8"))
    must = set(lds.MAP[lane]["must"])
    on_demand = set(lds.MAP[lane]["on_demand"])
    assert sections, "an empty split would pass every other check"
    assert not must & on_demand
    assert must | on_demand == set(sections), "every section is classified, none invented"


@pytest.mark.parametrize("lane", sorted(lds.MAP))
def test_must_read_prints_must_sections_and_only_the_index_of_the_rest(lane):
    text = lds.must_read(lane)
    _pre, sections = lds.split_doc(lds.doc_path(lane).read_text(encoding="utf-8"))
    for num in lds.MAP[lane]["must"]:
        assert sections[num] in text
    for num in lds.MAP[lane]["on_demand"]:
        assert sections[num] not in text
        assert f"section {num}:" in text
    for banner in lds.BANNERS:
        assert banner not in text


def test_closed_and_gate_sections_stay_required():
    """The sections carrying a do-not-redo set or a hard gate are never on-demand."""
    required = {
        "ds": "CLOSED set", "gated": "HARD GATE", "queue": "Row fences", "repo": "FROZEN FILES",
        "research": "Closed negatives", "true-audit": "NON-NEGOTIABLE", "uiux": "5-phase",
    }
    for lane, phrase in required.items():
        assert phrase in lds.must_read(lane), lane


def test_unclassified_section_prints_in_full(tmp_path):
    doc = tmp_path / "tools" / "headless-ds.md"
    doc.parent.mkdir()
    body = "".join(f"### {n}. Title {n}\nbody {n}\n" for n in
                   list(lds.MAP["ds"]["must"]) + list(lds.MAP["ds"]["on_demand"]))
    doc.write_text(body + "### 99. A new section\nnew floor text\n", encoding="utf-8", newline="\n")
    text = lds.must_read("ds", root=tmp_path)
    assert "new floor text" in text
    assert "body 3\n" not in text


def test_missing_named_section_refuses(tmp_path):
    doc = tmp_path / "tools" / "headless-ds.md"
    doc.parent.mkdir()
    doc.write_text("### 1. Only one\nbody\n", encoding="utf-8", newline="\n")
    with pytest.raises(lds.MapError):
        lds.must_read("ds", root=tmp_path)


def test_preamble_keeps_mandate_and_drops_banners_and_frontmatter():
    pre = ("---\ndescription: x\n---\n\n> **SUBAGENT-FIRST (a).** one\n> 1. two\n\n"
           "> **DISPATCH (b).** three\n\n> **RACE GUARDS (c).** four\n\n"
           "> **OTHER.** kept quote\n\nYou are lane 6.\n")
    out = lds.strip_preamble(pre)
    assert "You are lane 6." in out and "kept quote" in out
    assert "description" not in out and "SUBAGENT-FIRST" not in out
    assert "DISPATCH" not in out and "RACE GUARDS" not in out


def test_cli_prints_a_section_and_refuses_an_absent_one():
    tool = str(Path(lds.__file__))
    good = subprocess.run([sys.executable, tool, "ds", "--section", "9"],
                          capture_output=True, text=True, check=False)
    assert good.returncode == 0 and "The wrap" in good.stdout
    bad = subprocess.run([sys.executable, tool, "ds", "--section", "777"],
                         capture_output=True, text=True, check=False)
    assert bad.returncode == 2 and "whole lane doc" in bad.stderr


def test_usage_reader_window_and_medians(tmp_path):
    usage = tmp_path / "u.jsonl"
    rows = [
        {"ts": "2026-10-31T23:00:00-06:00", "note": "lane-s144-ds", "cache_creation": 999, "num_turns": 9},
        {"ts": "2026-11-01T01:00:00-06:00", "note": "lane-s144-ds", "cache_creation": 100, "num_turns": 1},
        {"ts": "2026-11-01T02:00:00-06:00", "note": "lane-s144-repo", "cache_creation": 300, "num_turns": 3},
        {"ts": "2026-11-01T03:00:00-06:00", "note": "other", "cache_creation": 500, "num_turns": 5},
        {"ts": "2026-11-02T03:00:00-06:00", "note": "lane-s144-ds", "cache_creation": 888, "num_turns": 8},
    ]
    usage.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8")
    out = lum.report(lum.load_rows(usage, "2026-11-01", "2026-11-01"))
    assert out["all_runs"]["n"] == 3
    assert out["all_runs"]["median_cache_creation"] == 300
    assert out["lane_runs"]["median_cache_creation"] == 200
    assert out["lane_runs"]["total_cache_creation"] == 400
    assert out["per_lane"]["lane-s144-ds"]["n"] == 1


def test_reference_doc_is_ascii_lf_and_has_no_real_ids():
    raw = REFERENCE.read_bytes()
    assert raw.isascii() and b"\r" not in raw
    text = raw.decode("ascii")
    assert not re.search(r"\b[A-Za-z]:[\\/]", text), "no drive-letter path"
    assert not re.search(r"\b(?:NA1|EUW1|KR)_\d{6,}\b", text), "no real match id"
    assert not re.search(r"\b\d{10,}\b", text), "no bare game id"
