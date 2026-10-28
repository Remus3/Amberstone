"""RM-258 residual: tools/ladder_role_scout.py writes its role file through
core.polled_json.

The scout is a background bulk ingest (~50 Riot calls a minute, its own
docstring), named as a busy ingest by tools/replay_chain_watch.py (the
15-minute RC-ReplayChainWatch task), tools/timeline_ingest.py and
tools/build_rank_baselines.py, and its output `data/ladder_role_mains.json` is
the `--source ladder` input tools/timeline_ingest.py reads. It wrote a
destination-derived `<out>.tmp` scratch with Path.write_text (CRLF on Windows)
and swapped it in with a bare Path.replace: no fsync, no WinError 5 retry
while a reader holds the target open, one scratch name for every concurrent
run, and a refused rename left the scratch file behind.

The write now goes through `polled_json.atomic_write_text` (per-writer scratch
name, fsync, bounded retry, scratch removed on failure) with the same
serialized string, so the document is unchanged and the bytes are LF only. A
rename that fails for good still raises: the run did not produce its file.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import polled_json  # noqa: E402
from core import riot_api as RA  # noqa: E402
from core import riot_retry  # noqa: E402
from tools import ladder_role_scout as lrs  # noqa: E402

_MATCH = {"info": {"participants": [
    {"puuid": "P1", "teamPosition": "TOP", "riotIdGameName": "Synth\u00e9",
     "riotIdTagline": "NA1"}]}}


def _call(endpoint, url, rate_limit_timeout_s=5.0):
    RA._record_outcome("ok")
    if endpoint == "league_v4":
        return {"entries": [{"puuid": "P1", "leaguePoints": 900}]}
    return ["M1"]


def _get_match(*_a, **_k):
    RA._record_outcome("ok")
    return _MATCH


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(riot_retry, "_sleep", lambda _s: None)
    monkeypatch.setattr(lrs, "_pace", lambda: None)
    monkeypatch.setattr(lrs.time, "time", lambda: 1793170000.0)
    monkeypatch.setattr(RA, "_call", _call)
    monkeypatch.setattr(RA, "get_match", _get_match)


def _run(out: Path) -> int:
    with redirect_stdout(io.StringIO()):
        return lrs.main(["--out", str(out), "--min-share", "0.5"])


def _spy_replace(monkeypatch):
    seen = []
    real = polled_json._replace_with_retry

    def spy(src, dst):
        seen.append((Path(src), Path(dst)))
        real(src, dst)

    monkeypatch.setattr(polled_json, "_replace_with_retry", spy)
    return seen


def test_the_role_file_is_renamed_through_polled_json(tmp_path, monkeypatch,
                                                      offline):
    seen = _spy_replace(monkeypatch)
    out = tmp_path / "ladder_role_mains.json"
    assert _run(out) == 0
    assert len(seen) == 1, seen
    src, dst = seen[0]
    assert dst == out
    # Per-writer scratch (pid + token) beside the target, never `<name>.tmp`.
    assert src.parent == out.parent
    assert re.fullmatch(
        re.escape(f"{out.name}.{os.getpid()}.") + r"[0-9a-f]{8}\.tmp",
        src.name), src.name
    raw = out.read_bytes()
    assert b"\r" not in raw
    blob = json.loads(raw.decode("utf-8"))
    # Same document and layout the old writer serialized: indent=2, ASCII
    # escapes (json.dumps default), no trailing newline.
    assert raw == json.dumps(blob, indent=2).encode("utf-8")
    assert b"\\u00e9" in raw
    assert [r["riot_id"] for r in blob["roles"]["TOP"]] == ["Synth\u00e9#NA1"]
    assert [p.name for p in out.parent.iterdir()] == [out.name]


def test_a_refused_rename_raises_and_leaves_no_scratch(tmp_path, monkeypatch,
                                                      offline):
    out = tmp_path / "ladder_role_mains.json"
    out.write_bytes(b'{"keep": true}')

    def refused(src, dst):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(polled_json, "_replace_with_retry", refused)
    with pytest.raises(PermissionError):
        _run(out)
    # The previous role file survives intact and no scratch is left behind.
    assert out.read_bytes() == b'{"keep": true}'
    assert [p.name for p in tmp_path.iterdir()] == [out.name]
