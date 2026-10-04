# arch: credential-shape scan over git HISTORY (blobs), pre-push + full | section=tools | frozen=no
"""Credential-shape scan over git OBJECTS, not the working tree (RM-492).

`tools/credential_patterns.py` was wired only as a Claude PostToolUse hook, so
it saw the file an agent just wrote and nothing else: absent in a fresh clone,
absent under `--no-verify`, and blind to every blob already in history - on a
PUBLIC repository. This tool runs the same patterns over blob CONTENT read
straight from the object store:

    --pre-push REMOTE [URL]   refs on stdin (git's pre-push format); scans the
                              lines the push ADDS (every commit, `-p -U0`).
                              Wired in `.githooks/pre-push`, which a fresh
                              clone gets from `python scripts/install_hooks.py`.
                              No baseline: new content is never pre-accepted;
                              a genuine fixture line carries the PRAGMA.
    --all                     every blob reachable from any ref, against the
                              reviewed baseline. The one-off / CI-shaped
                              audit. Prints a measured runtime (2026-10-04:
                              55848 blobs, 52365 scanned, 2974 over the 1 MB
                              ALL_MAX_BLOB_BYTES cap, 405 s).

`--all` is an AUDIT, not a gate: the baseline is keyed by blob, so a later
version of a file that still carries a reviewed fixture is a new blob and
reports again until it is reviewed and added. The GATE is `--pre-push`.

VALUES ARE NEVER EMITTED (the `credential_patterns` contract): a finding is
blob path + line + pattern class + arm. A known, reviewed historical hit is
accepted by listing its BLOB SHA and class in
`tools/credential_history_baseline.json` - a sha, never a value - so the
baseline cannot itself leak anything.

Exit codes match the sibling-name sweep: 0 clean, 2 HALT (findings), 3 FAULT
(the scan could not run - never a clean verdict).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import credential_patterns as cp  # noqa: E402
from tools.sibling_name_sweep import resolve_push_range  # noqa: E402

BASELINE = ROOT / "tools" / "credential_history_baseline.json"
EXIT_CLEAN, EXIT_HALT, EXIT_FAULT = 0, 2, 3
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# Blobs over the cap are skipped and COUNTED in the report, never silently
# dropped. A push scans few blobs, so it uses the write-time hook's own 8 MB
# budget. The full-history audit cannot: measured 2026-10-04, RC's object
# store holds 57197 blobs / 13.6 GB, of which 3269 blobs over 1 MB carry
# 10.5 GB - versioned generated data (DS tables, scenario JSON), not files a
# credential is typed into. At 8 MB the --all pass ran >25 min CPU-bound; at
# 1 MB it scans every source/config blob ever committed.
PUSH_MAX_BLOB_BYTES = cp.MAX_SCAN_BYTES
ALL_MAX_BLOB_BYTES = 1_000_000
# Paths whose blobs are not text a secret is written into. Git-LFS pointers
# are tiny text and ARE scanned; the payload never enters this object store.
_SKIP_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".woff",
                  ".woff2", ".ttf", ".otf", ".zip", ".gz", ".7z", ".pdf",
                  ".exe", ".dll", ".pyd", ".db", ".sqlite", ".rofl", ".mp4",
                  ".wav", ".mp3", ".onnx", ".bin", ".pkl", ".npz")


class GitFault(RuntimeError):
    pass


def _git(args: Sequence[str], stdin: bytes | None = None, root: Path = ROOT) -> bytes:
    try:
        proc = subprocess.run(["git", *args], cwd=root, input=stdin,
                              capture_output=True, creationflags=_NO_WINDOW)
    except OSError as exc:
        raise GitFault(f"git {args[0]}: {exc}") from exc
    if proc.returncode != 0:
        raise GitFault(f"git {args[0]} exited {proc.returncode}: "
                       f"{proc.stderr.decode('utf-8', 'replace')[:300]}")
    return proc.stdout


def list_blobs(rev_args: Sequence[str], root: Path = ROOT,
               sizes: dict[str, int] | None = None) -> dict[str, str]:
    """{blob_sha: first path seen} for every blob reachable from rev_args.

    When ``sizes`` is given it is filled with {blob_sha: size in bytes}, so an
    over-cap blob can be skipped without streaming it through the pipe.
    """
    out = _git(["rev-list", "--objects", *rev_args], root=root)
    candidates: dict[str, str] = {}
    for line in out.decode("utf-8", "replace").splitlines():
        sha, _, path = line.partition(" ")
        if path and sha not in candidates:
            candidates[sha] = path
    if not candidates:
        return {}
    check = _git(["cat-file",
                  "--batch-check=%(objectname) %(objecttype) %(objectsize)"],
                 stdin=("\n".join(candidates) + "\n").encode(), root=root)
    blobs = {}
    for line in check.decode().splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1] == "blob":
            blobs[parts[0]] = candidates[parts[0]]
            if sizes is not None:
                sizes[parts[0]] = int(parts[2])
    return blobs


def _read_blobs(shas: Sequence[str], root: Path = ROOT,
                max_bytes: int = PUSH_MAX_BLOB_BYTES) -> Iterable[tuple[str, bytes | None]]:
    """Stream (sha, content) via one `cat-file --batch`; None when skipped."""
    if not shas:
        return
    proc = subprocess.Popen(["git", "cat-file", "--batch"], cwd=root,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)
    assert proc.stdin and proc.stdout
    stdin = proc.stdin

    def _feed() -> None:
        # One feeder thread instead of a write/flush/read round trip per
        # blob: the per-blob handshake measured >10 min over RC's history.
        try:
            stdin.write(("\n".join(shas) + "\n").encode())
            stdin.close()
        except OSError:
            pass

    feeder = threading.Thread(target=_feed, daemon=True)
    feeder.start()
    try:
        for sha in shas:
            header = proc.stdout.readline().decode().split()
            if len(header) < 3 or header[1] == "missing":
                raise GitFault(f"cat-file could not read {sha}")
            size = int(header[2])
            data = proc.stdout.read(size)
            proc.stdout.read(1)  # trailing LF
            yield sha, (None if size > max_bytes else data)
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=30)
        feeder.join(timeout=5)


def load_baseline(path: Path = BASELINE) -> set[tuple[str, str]]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8")).get("accepted", [])
    except FileNotFoundError:
        return set()
    return {(r["blob"], r["class"]) for r in rows}


def scan_blobs(blobs: dict[str, str], baseline: set[tuple[str, str]],
               root: Path = ROOT, max_bytes: int = PUSH_MAX_BLOB_BYTES,
               sizes: dict[str, int] | None = None,
               ) -> tuple[list[tuple[str, str, cp.Finding]], dict]:
    """Return (findings as (blob, path, Finding), stats). Never a value."""
    stats = {"blobs": len(blobs), "scanned": 0, "skipped_binary": 0,
             "skipped_large": 0, "baselined": 0, "cap": max_bytes}
    todo = []
    for sha, path in blobs.items():
        if path.lower().endswith(_SKIP_SUFFIXES):
            stats["skipped_binary"] += 1
        elif sizes is not None and sizes.get(sha, 0) > max_bytes:
            stats["skipped_large"] += 1
        else:
            todo.append(sha)
    hits = []
    for sha, data in _read_blobs(todo, root=root, max_bytes=max_bytes):
        if data is None:
            stats["skipped_large"] += 1
            continue
        if b"\0" in data[:8192]:
            stats["skipped_binary"] += 1
            continue
        stats["scanned"] += 1
        for f in cp.scan_text(data.decode("utf-8", "replace")):
            if (sha, f.pattern_class) in baseline:
                stats["baselined"] += 1
                continue
            hits.append((sha, blobs[sha], f))
    return hits, stats


def _report(hits, stats, elapsed: float) -> None:
    for sha, path, f in hits:
        print(f"  {path}:{f.line_no}  blob={sha[:12]} class={f.pattern_class} "
              f"arm={f.arm}", file=sys.stderr)
    print(f"[credential-history] {len(hits)} finding(s); {stats['scanned']} "
          f"blob(s) scanned of {stats['blobs']} ({stats['skipped_binary']} "
          f"binary, {stats['skipped_large']} over {stats['cap']} bytes, "
          f"{stats['baselined']} baselined) in {elapsed:.1f}s",
          file=sys.stderr)


def run(rev_args_list: Sequence[Sequence[str]], root: Path = ROOT,
        baseline_path: Path = BASELINE,
        max_bytes: int = PUSH_MAX_BLOB_BYTES) -> int:
    t0 = time.monotonic()
    try:
        blobs: dict[str, str] = {}
        sizes: dict[str, int] = {}
        for rev_args in rev_args_list:
            for sha, path in list_blobs(rev_args, root=root, sizes=sizes).items():
                blobs.setdefault(sha, path)
        hits, stats = scan_blobs(blobs, load_baseline(baseline_path), root=root,
                                 max_bytes=max_bytes, sizes=sizes)
    except (GitFault, OSError, ValueError, KeyError) as exc:
        print(f"[credential-history] FAULT - scan did not run: {exc}. This is "
              "not a clean verdict.", file=sys.stderr)
        return EXIT_FAULT
    _report(hits, stats, time.monotonic() - t0)
    if hits:
        print("[credential-history] HALT - credential-shaped content in the "
              "objects above. Remove it from history, or if it is a reviewed "
              "fixture add its blob sha + class to "
              "tools/credential_history_baseline.json.", file=sys.stderr)
        return EXIT_HALT
    return EXIT_CLEAN


def _have(sha: str, root: Path = ROOT) -> bool:
    try:
        _git(["cat-file", "-e", sha + "^{commit}"], root=root)
        return True
    except GitFault:
        return False


def added_lines(rev_args: Sequence[str], root: Path = ROOT) -> dict[tuple[str, str], list[str]]:
    """{(commit, path): [added line, ...]} for every commit in the range.

    Pre-push scans what the push ADDS, not whole blobs: a blob-level scan would
    re-flag every reviewed fixture each time an unrelated line in its file
    changed, and a gate that halts on old content gets bypassed. A secret
    introduced by the push is, by definition, on an added line.
    """
    out = _git(["log", "--no-merges", "--format=%x01%H", "-p", "--unified=0",
                "--no-color", "--no-ext-diff", "--no-renames", *rev_args],
               root=root)
    found: dict[tuple[str, str], list[str]] = {}
    commit, path = "", ""
    for raw in out.decode("utf-8", "replace").split("\n"):
        if raw.startswith("\x01"):
            commit, path = raw[1:].strip(), ""
        elif raw.startswith("+++ "):
            target = raw[4:]
            path = target[2:] if target.startswith("b/") else ""
        elif raw.startswith("+") and path and not raw.startswith("+++"):
            if path.lower().endswith(_SKIP_SUFFIXES):
                continue
            found.setdefault((commit, path), []).append(raw[1:].rstrip("\r"))
    return found


def run_push(rev_args_list: Sequence[Sequence[str]], root: Path = ROOT) -> int:
    t0 = time.monotonic()
    hits = []
    lines_scanned = 0
    try:
        seen: set[tuple[str, str]] = set()
        for rev_args in rev_args_list:
            for key, lines in added_lines(rev_args, root=root).items():
                if key in seen:
                    continue
                seen.add(key)
                lines_scanned += len(lines)
                text = "\n".join(lines)[:PUSH_MAX_BLOB_BYTES]
                for f in cp.scan_text(text):
                    hits.append((key[0], key[1], f))
    except (GitFault, OSError, ValueError) as exc:
        print(f"[credential-history] FAULT - push scan did not run: {exc}. "
              "This is not a clean verdict.", file=sys.stderr)
        return EXIT_FAULT
    for commit, path, f in hits:
        print(f"  {path}  commit={commit[:12]} added-line#{f.line_no} "
              f"class={f.pattern_class} arm={f.arm}", file=sys.stderr)
    print(f"[credential-history] push: {len(hits)} finding(s) over "
          f"{lines_scanned} added line(s) in {len(seen)} file-commit(s), "
          f"{time.monotonic() - t0:.1f}s", file=sys.stderr)
    if hits:
        print("[credential-history] HALT - the push ADDS credential-shaped "
              "content. Remove it, or mark a genuine fixture line with "
              f"`{cp.PRAGMA}`.", file=sys.stderr)
        return EXIT_HALT
    return EXIT_CLEAN


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true",
                   help="scan every blob reachable from any ref")
    g.add_argument("--pre-push", nargs="*", metavar="ARG",
                   help="remote name (and url); refs read from stdin")
    ns = ap.parse_args(argv)
    if ns.all:
        return run([["--all"]], max_bytes=ALL_MAX_BLOB_BYTES)
    remote = (ns.pre_push or ["origin"])[0]
    ranges = []
    for line in sys.stdin.read().splitlines():
        spec = resolve_push_range(line, remote, have=_have) if line.strip() else None
        if spec is not None:
            ranges.append(spec.args)
    if not ranges:
        return EXIT_CLEAN
    return run_push(ranges)


if __name__ == "__main__":
    sys.exit(main())
