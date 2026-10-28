"""RM-258 residual: the hz_shadow_arena_contamination rewrite goes through core.polled_json.

`flag_rows()` in tools/hz_shadow_arena_contamination.py rewrites the HZ-C1
shadow corpus (`--flag`; by default the live jsonl, in place) by streaming
into a destination-derived `<dst>.tmp` and swapping it in with a bare
os.replace: no fsync, no WinError 5 retry, one scratch name for every
concurrent run, and a scratch file left behind when the swap fails.

Each test flags synthetic rows in tmp_path, spies on
`core.polled_json.atomic_write_bytes`, then checks the exact on-disk bytes
(CRLF and torn appends kept) and that no scratch file is left beside the
corpus. The in-place case (source == corpus, the default `--flag` shape)
must read the whole source before the swap.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import hz_choice_shadow as hzs
from core import polled_json
from tools import hz_shadow_arena_contamination as hzc


def _row(band, spike, recall_label, mode="arena"):
    # Same shape as tests/test_hz_shadow_arena_contamination.py::_row.
    return {
        "ts": "2026-07-08T23:25:14.487798+00:00",
        "mode": mode, "my_champion": "Kai'Sa", "enemy": "Amumu",
        "band": band, "mana_state": "full", "cd_state": "all_up",
        "covered": True, "level": 3, "item_count": 2,
        "choices": [
            {"key": "A", "label": "Trade Amumu",
             "expected_outcome": "net swing +0.11; you remove 20% of Amumu, "
                                 "they remove 8% of you"},
            {"key": "B", "label": recall_label,
             "expected_outcome": f"buy Runaan's Hurricane (2500g) toward {spike}"},
        ],
    }


def _corpus_bytes() -> tuple[bytes, str, str]:
    keep = json.dumps(_row("L2", "component", "Back soon", mode="sr"))
    hit = json.dumps(_row("L2", "component", "Back soon"))
    torn = "\x00\x00\x00"
    raw = "\r\n".join([keep, hit, torn]) + "\r\n"
    return raw.encode("utf-8"), keep, hit


def _expected(keep: str, hit: str) -> bytes:
    row = json.loads(hit)
    row[hzs.PRECOMPUTE_SOURCE_KEY] = hzs.SR_COPY_TAG
    return (keep.encode() + b"\r\n" + json.dumps(row).encode() + b"\r\n"
            + b"\x00\x00\x00\r\n")


@pytest.fixture
def spy(monkeypatch):
    calls = []
    real = polled_json.atomic_write_bytes

    def _spy(path, data):
        calls.append((Path(path), data))
        real(path, data)

    monkeypatch.setattr(polled_json, "atomic_write_bytes", _spy)
    return calls


def _scratch(d: Path) -> list[str]:
    return sorted(p.name for p in d.iterdir() if p.name.endswith(".tmp"))


def test_flag_rows_routes_through_polled_json(tmp_path, spy):
    raw, keep, hit = _corpus_bytes()
    src = tmp_path / "src.jsonl"
    dst = tmp_path / "out" / "dst.jsonl"
    src.write_bytes(raw)

    result = hzc.flag_rows(src, dst)

    assert result["tagged"] == 1
    assert [p for p, _ in spy] == [dst]
    assert spy[0][1] == dst.read_bytes() == _expected(keep, hit)
    assert _scratch(dst.parent) == []


def test_flag_rows_in_place_reads_the_whole_source_first(tmp_path, spy):
    raw, keep, hit = _corpus_bytes()
    corpus = tmp_path / "shadow.jsonl"
    corpus.write_bytes(raw)
    backup = tmp_path / "bak" / "shadow.jsonl.bak"

    result = hzc.flag_rows(corpus, corpus, backup)

    assert result == {"tagged": 1, "already_tagged": 0, "untouched": 2,
                      "backup": str(backup)}
    assert backup.read_bytes() == raw
    assert corpus.read_bytes() == _expected(keep, hit)
    assert len(spy) == 1
    assert _scratch(tmp_path) == []


def test_refused_swap_keeps_the_prior_corpus_and_leaves_no_scratch(
        tmp_path, monkeypatch):
    raw, _keep, _hit = _corpus_bytes()
    src = tmp_path / "src.jsonl"
    dst = tmp_path / "dst.jsonl"
    src.write_bytes(raw)
    dst.write_bytes(b"prior\n")
    fired = []

    def _refuse(a, b):
        fired.append((a, b))
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(polled_json, "_replace_with_retry", _refuse)
    with pytest.raises(PermissionError):
        hzc.flag_rows(src, dst)
    assert len(fired) == 1
    assert dst.read_bytes() == b"prior\n"
    assert _scratch(tmp_path) == []


def test_tool_carries_no_hand_rolled_rename():
    text = Path(hzc.__file__).read_text(encoding="utf-8")
    assert "os.replace(" not in text
    assert 'suffix + ".tmp"' not in text
