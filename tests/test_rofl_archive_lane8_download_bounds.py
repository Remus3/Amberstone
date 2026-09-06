"""LANE 8 (Headless-True-Audit): core/rofl_archive.py download-path bounds.

Four weaknesses, each with its own red test. All four are reachable through
`download_replays`, which nine non-test callers use (tools/rofl_archiver.py,
tools/replay_roster_pull.py, tools/rofl_tracked_backfill.py and
lcu/lcu_postgame_collector.py among them).

W1 - `_http_get_bytes` ended in a bare `resp.read()`, so a pre-signed S3 body
     was read into memory with no ceiling. Filed as RM-371 by lane 10 and left
     unfixed there because that lane ships one row per cycle.

W2 - `_maybe_gunzip` ended in `gzip.decompress(body)` with no output bound, and
     `download_replays` called it BEFORE the `_ROFL_MAGIC` validation. So the
     gzip expansion ratio (~1000x) was applied to unvalidated bytes: the archive
     decided whether the payload was a replay only after fully expanding it.
     RM-371 cited the transfer read alone and did not reach this.

W3 - the three writers finished with a bare `tmp.replace(target)`. On Windows
     `os.replace` raises PermissionError (WinError 5) while any reader holds the
     destination open. Filed as RM-310.

W4 - those writers derived the scratch name from the destination alone
     (`target.with_suffix(target.suffix + ".tmp")`), so two callers writing one
     `index.json` shared a single `index.json.tmp`. This is the same defect
     core/polled_json.py fixed for itself in lane 8 cycle 24 (`_scratch_path`,
     per-writer pid + random suffix) and never propagated here.

W3 and W4 are fixed by delegating to core/polled_json.py rather than re-rolling
the pattern, so the retry and the per-writer naming stay single-sourced.
"""

from __future__ import annotations

import gzip
import os
import pathlib

import pytest

import core.rofl_archive as ra


_URL = (
    "https://lol-prod-us-west-2-match-history-replay.s3.us-west-2.amazonaws.com"
    "/NA1/5595187452.rofl"
    "?response-content-disposition=attachment%3B%20filename%3D%22NA1_5595187452.rofl%22"
    "&X-Amz-Date=20260719T120000Z&X-Amz-Expires=3600&X-Amz-Signature=deadbeef"
)
_URL2 = _URL.replace("5595187452", "5595187453")

# _URL carries a fixed signature time; the download path must be exercised
# inside the signed window or it silently drifts into the expiry branch.
_SIGNED_AT = 1784462400
_FRESH = _SIGNED_AT + 60

_REAL = b"RIOT\x02\x00" + b"\x00" * 64


class _Fetcher:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        return self.payloads[ra.match_id_from_replay_url(url)]


class _EndlessResponse:
    """A body that never ends - the shape an unbounded `read()` cannot survive.

    `read()` with no argument returns far more than any ceiling; `read(n)`
    honours n, so a bounded reader terminates and an unbounded one does not.
    """

    def __init__(self, cap_probe: int):
        self._cap_probe = cap_probe

    def read(self, n=None):
        if n is None:
            return b"\0" * (self._cap_probe * 4)
        return b"\0" * n

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# ---------------------------------------------------------------------------
# W1 - the transfer read is bounded
# ---------------------------------------------------------------------------

def test_http_get_bytes_refuses_a_body_past_the_ceiling(monkeypatch):
    """A pre-signed URL that streams forever must raise, not fill memory."""
    monkeypatch.setattr(
        ra.urllib.request, "urlopen", lambda url, timeout=None: _EndlessResponse(2048)
    )
    with pytest.raises(ra.ReplayTooLarge):
        ra._http_get_bytes(_URL, max_bytes=2048)


def test_http_get_bytes_still_returns_a_body_inside_the_ceiling(monkeypatch):
    """The bound must not break the ordinary 10-13 MB replay."""

    class _Ok:
        def __init__(self):
            self._body = _REAL

        def read(self, n=None):
            body, self._body = self._body, b""
            return body if n is None else body[:n]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(ra.urllib.request, "urlopen", lambda url, timeout=None: _Ok())
    assert ra._http_get_bytes(_URL, max_bytes=len(_REAL) + 1) == _REAL


# ---------------------------------------------------------------------------
# W2 - decompression is bounded, and bounded BEFORE validation decides
# ---------------------------------------------------------------------------

def test_maybe_gunzip_stops_at_the_ceiling_instead_of_expanding_a_bomb():
    """5 MB of zeros compresses to a few KB. Under a 1 KB ceiling the expansion
    must be abandoned, not completed and then discarded."""
    bomb = gzip.compress(b"\0" * (5 * 1024 * 1024))
    assert len(bomb) < 64 * 1024, "precondition: the bomb is small on the wire"

    assert ra._maybe_gunzip(bomb, max_bytes=1024) == b""


def test_maybe_gunzip_still_expands_an_ordinary_gzipped_replay():
    """MEASURED 2026-07-19: live bodies arrive gzip-framed. The ceiling must not
    regress the case the gunzip exists for."""
    assert ra._maybe_gunzip(gzip.compress(_REAL), max_bytes=1024 * 1024) == _REAL


def test_download_rejects_an_oversize_body_and_keeps_sweeping(tmp_path, monkeypatch):
    """The injected transport bypasses `_http_get_bytes` entirely, so the size
    bound has to hold inside `download_replays` as well.

    Pre-fix this wrote the oversize payload to disk, because it carried valid
    container magic and nothing measured its length. The second URL proves the
    rejection is per-item and does not abort the sweep - the failure mode this
    file was already fixed for twice (LEDGER 1176, 1311).
    """
    monkeypatch.setattr(ra, "MAX_REPLAY_BYTES", 1024)
    oversize = _REAL + b"\0" * 4096
    fetch = _Fetcher({"NA1_5595187452": oversize, "NA1_5595187453": _REAL})

    res = ra.download_replays([_URL, _URL2], tmp_path, fetcher=fetch, now=_FRESH)

    assert res.failed == ["NA1_5595187452"]
    assert res.downloaded == ["NA1_5595187453"]
    assert not (tmp_path / "NA1_5595187452.rofl").exists()
    assert (tmp_path / "NA1_5595187453.rofl").read_bytes() == _REAL


def test_download_stops_a_bomb_that_would_otherwise_pass_the_magic_check(
    tmp_path, monkeypatch
):
    """The bomb carries VALID container magic, so the is-this-a-replay guard
    would accept it once expanded. Only the size ceiling stops it.

    This discriminating shape was forced by mutation testing. The first version
    of this test used a bomb of plain zeros, which the magic check rejects on
    its own - so it stayed green with the ceiling removed and guarded nothing.
    A bomb that survives validation is also the realistic one: an attacker who
    can serve a body can prepend six bytes.
    """
    monkeypatch.setattr(ra, "MAX_REPLAY_BYTES", 64 * 1024)
    bomb = gzip.compress(_REAL + b"\0" * (5 * 1024 * 1024))
    assert len(bomb) < 64 * 1024, "precondition: the bomb is small on the wire"
    fetch = _Fetcher({"NA1_5595187452": bomb, "NA1_5595187453": _REAL})

    res = ra.download_replays([_URL, _URL2], tmp_path, fetcher=fetch, now=_FRESH)

    assert res.failed == ["NA1_5595187452"]
    assert res.downloaded == ["NA1_5595187453"]
    assert list(tmp_path.glob("*.rofl")) == [tmp_path / "NA1_5595187453.rofl"]


# ---------------------------------------------------------------------------
# W5 - the bounded rewrite must not accept what gzip.decompress rejected
#
# Found by the lane 8 verifier, NOT by the first eight guards. Swapping
# gzip.decompress for zlib.decompressobj traded one silent failure for another:
# gzip.decompress raises EOFError on a truncated body, decompressobj returns the
# partial bytes with no exception at all. A truncated replay still carries the
# RIOT prefix, so it passed validation, was written under its final name, and
# was recorded in an index that is idempotent on match id - so the re-pull
# skipped it forever. That is the exact failure _atomic_write_bytes's docstring
# forbids, reintroduced one layer above it.
# ---------------------------------------------------------------------------

def test_maybe_gunzip_rejects_a_truncated_stream():
    """A cut-short gzip body must be discarded, not silently half-expanded."""
    payload = _REAL + b"\0" * 200000
    whole = gzip.compress(payload)
    truncated = whole[: len(whole) // 2]

    # Precondition: the truncated body is still a well-formed gzip HEADER, so
    # nothing upstream rejects it before the decompressor sees it.
    assert truncated.startswith(b"\x1f\x8b")

    assert ra._maybe_gunzip(truncated, max_bytes=1024 * 1024) == b""


def test_download_rejects_a_truncated_body_that_still_carries_valid_magic(
    tmp_path, monkeypatch
):
    """End to end: a truncated replay must never reach its final .rofl name.

    The index is idempotent on match id, so a truncated file written once is
    skipped by every later pull - the corruption is permanent, not transient.
    """
    monkeypatch.setattr(ra, "MAX_REPLAY_BYTES", 8 * 1024 * 1024)
    whole = gzip.compress(_REAL + b"\0" * 200000)
    truncated = whole[: len(whole) // 2]
    fetch = _Fetcher({"NA1_5595187452": truncated, "NA1_5595187453": _REAL})

    res = ra.download_replays([_URL, _URL2], tmp_path, fetcher=fetch, now=_FRESH)

    assert res.failed == ["NA1_5595187452"]
    assert res.downloaded == ["NA1_5595187453"]
    assert not (tmp_path / "NA1_5595187452.rofl").exists()


def test_maybe_gunzip_expands_every_member_of_a_multi_member_body():
    """gzip.decompress concatenates all members; one decompressobj stops after
    the first. Returning only member one would silently truncate a valid body.
    """
    two = gzip.compress(_REAL) + gzip.compress(b"TAILTAIL")
    assert ra._maybe_gunzip(two, max_bytes=1024 * 1024) == _REAL + b"TAILTAIL"


# ---------------------------------------------------------------------------
# W3 - a Windows reader holding the target no longer loses the write
# ---------------------------------------------------------------------------

def test_index_write_retries_a_windows_permission_error(tmp_path, monkeypatch):
    """WinError 5 on os.replace is routine on Windows when a reader has the
    destination open. A bare replace surfaces it as a lost write."""
    real_replace = os.replace
    state = {"failures": 2}

    def flaky(src, dst):
        if str(dst).endswith("index.json") and state["failures"] > 0:
            state["failures"] -= 1
            raise PermissionError(5, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky)

    fetch = _Fetcher({"NA1_5595187452": _REAL})
    res = ra.download_replays([_URL], tmp_path, fetcher=fetch, now=_FRESH)

    assert res.downloaded == ["NA1_5595187452"]
    assert state["failures"] == 0, "the retry path was never exercised"
    assert (tmp_path / "index.json").exists()


# ---------------------------------------------------------------------------
# W4 - the scratch name is per-writer, and stays single-sourced
# ---------------------------------------------------------------------------

def test_writers_never_use_the_shared_deterministic_scratch_name(
    tmp_path, monkeypatch
):
    """Two writers of one index.json must not share `index.json.tmp`.

    Structural guard, matching the one core/polled_json.py uses for the same
    defect: a contention test would be probabilistic, the naming property is
    not. Every scratch path observed during a real write must be unique to this
    writer rather than derived from the destination alone.

    The recorders go on via monkeypatch rather than by assignment. These are
    stdlib methods and the whole suite runs under `-n 8`, so a window where
    pathlib is globally patched is exactly the shape that produces a failure
    only under the full parallel suite; monkeypatch restores on every exit path
    including the ones a try/finally in the test body does not cover.
    """
    seen: list[str] = []
    real_write_bytes = pathlib.Path.write_bytes
    real_write_text = pathlib.Path.write_text

    def rec_bytes(self, data):
        seen.append(self.name)
        return real_write_bytes(self, data)

    def rec_text(self, data, *a, **kw):
        seen.append(self.name)
        return real_write_text(self, data, *a, **kw)

    monkeypatch.setattr(pathlib.Path, "write_bytes", rec_bytes)
    monkeypatch.setattr(pathlib.Path, "write_text", rec_text)

    fetch = _Fetcher({"NA1_5595187452": _REAL})
    ra.download_replays([_URL], tmp_path, fetcher=fetch, now=_FRESH)

    scratch = [n for n in seen if n.endswith(".tmp")]
    assert scratch, "precondition: the writers go through a scratch file"
    assert "index.json.tmp" not in scratch, (
        "index.json.tmp is derived from the destination alone, so every writer "
        "of that file opens the same scratch path - lane 8 cycle 24"
    )
    assert all(str(os.getpid()) in n for n in scratch), (
        f"scratch names must carry the writer pid: {scratch}"
    )
