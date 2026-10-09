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

    --leak-sweep [REV]        every file tracked at REV (default HEAD) against
                              the LEAK classes only; prints counts by class,
                              exempt test/fixture hits counted apart. The
                              acceptance measure for MAIN 2246 ORDER section 3.

`--all` is an AUDIT, not a gate: the baseline is keyed by blob, so a later
version of a file that still carries a reviewed fixture is a new blob and
reports again until it is reviewed and added. The GATE is `--pre-push`.

LEAK CLASSES (MAIN 2246 ORDER sections 3-4; `credential_patterns.scan_leaks`).
`--pre-push` also halts on an ADDED line carrying private-LAN IPv4, a tailnet
address or DNS name, a Windows-generated host name, or a literal value from
this host's identity: the gitignored `ops/local_hosts.json` (read from the
main checkout when the push runs in a linked worktree) plus the live computer
name. User-profile and checkout paths are ADVISORY: reported, never a halt.
Test code and fixtures are exempt by path (`credential_patterns.is_leak_exempt`).
No new hook wiring: `.githooks/pre-push` already runs `--pre-push`.

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
import os
import socket
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import credential_patterns as cp  # noqa: E402
from tools.sibling_name_sweep import main_working_tree, resolve_push_range  # noqa: E402

BASELINE = ROOT / "tools" / "credential_history_baseline.json"
LOCAL_HOSTS_RELATIVE = Path("ops") / "local_hosts.json"
# The identity keys of ops/local_hosts.example.json. `_doc` and any key not
# listed here are never read as values.
_LOCAL_HOST_KEYS = ("tailnet_name", "tailnet_fqdn", "tailnet_ipv4", "lan_ipv4",
                    "lan_subnet", "cert_sans")
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


def _local_hosts_path(root: Path) -> Path:
    """The gitignored per-host config; a linked worktree reads the main tree's."""
    local = root / LOCAL_HOSTS_RELATIVE
    if local.exists():
        return local
    main = main_working_tree(root)
    if main is not None and (main / LOCAL_HOSTS_RELATIVE).exists():
        return main / LOCAL_HOSTS_RELATIVE
    return local


def local_leak_values(root: Path = ROOT, env: Mapping[str, str] | None = None,
                      hostname: str | None = None) -> tuple[str, ...]:
    """This host's literal identity values. NEVER printed by any caller.

    The identity keys of the gitignored ``ops/local_hosts.json`` plus the live
    computer name (``COMPUTERNAME`` and ``socket.gethostname()``; CLAUDE.md:
    never record it, probe it live). Placeholders, loopback and documentation
    addresses are dropped by ``credential_patterns.usable_leak_value``. An
    absent or malformed config contributes nothing; it is not a fault.
    """
    env = os.environ if env is None else env
    raw: list[str] = []
    try:
        doc = json.loads(_local_hosts_path(Path(root)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    if isinstance(doc, dict):
        for key in _LOCAL_HOST_KEYS:
            item = doc.get(key)
            raw.extend(i for i in (item if isinstance(item, list) else [item])
                       if isinstance(i, str))
    raw.append(env.get("COMPUTERNAME", "") or "")
    if hostname is None:
        try:
            hostname = socket.gethostname()
        except OSError:
            hostname = ""
    raw.append(hostname or "")
    out: list[str] = []
    seen: set[str] = set()
    for value in raw:
        value = value.strip()
        if cp.usable_leak_value(value) and value.lower() not in seen:
            seen.add(value.lower())
            out.append(value)
    return tuple(out)


def checkout_leak_paths(root: Path = ROOT) -> tuple[str, ...]:
    """Every spelling of this checkout's absolute path (and the main tree's)."""
    bases = [Path(root)]
    main = main_working_tree(Path(root))
    if main is not None:
        bases.append(main)
    out: list[str] = []
    for base in bases:
        try:
            resolved = str(base.resolve())
        except OSError:
            continue
        for variant in cp.checkout_path_variants(resolved):
            if variant not in out:
                out.append(variant)
    return tuple(out)


def _split_leaks(path: str, text: str, values: Sequence[str],
                 checkout_paths: Sequence[str]) -> tuple[list, list]:
    """(gate findings, advisory findings) for one path's text; [] when exempt."""
    if cp.is_leak_exempt(path):
        return [], []
    gate, advisory = [], []
    for f in cp.scan_leaks(text, tuple(values), tuple(checkout_paths)):
        (advisory if cp.is_advisory(f) else gate).append(f)
    return gate, advisory


def run_push(rev_args_list: Sequence[Sequence[str]], root: Path = ROOT,
             leak_values: Sequence[str] | None = None,
             checkout_paths: Sequence[str] | None = None) -> int:
    t0 = time.monotonic()
    hits = []
    leak_hits = []
    advisory = []
    lines_scanned = 0
    try:
        if leak_values is None:
            leak_values = local_leak_values(root)
        if checkout_paths is None:
            checkout_paths = checkout_leak_paths(root)
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
                gate, adv = _split_leaks(key[1], text, leak_values, checkout_paths)
                leak_hits.extend((key[0], key[1], f) for f in gate)
                advisory.extend((key[0], key[1], f) for f in adv)
    except (GitFault, OSError, ValueError) as exc:
        print(f"[credential-history] FAULT - push scan did not run: {exc}. "
              "This is not a clean verdict.", file=sys.stderr)
        return EXIT_FAULT
    for commit, path, f in hits + leak_hits:
        print(f"  {path}  commit={commit[:12]} added-line#{f.line_no} "
              f"class={f.pattern_class} arm={f.arm}", file=sys.stderr)
    for commit, path, f in advisory:
        print(f"  advisory {path}  commit={commit[:12]} added-line#{f.line_no} "
              f"class={f.pattern_class} arm={f.arm}", file=sys.stderr)
    print(f"[credential-history] push: {len(hits)} credential + {len(leak_hits)} "
          f"leak finding(s), {len(advisory)} advisory, over {lines_scanned} "
          f"added line(s) in {len(seen)} file-commit(s), "
          f"{time.monotonic() - t0:.1f}s", file=sys.stderr)
    if advisory:
        print("[leak-classes] advisory, not a halt: added lines carry a "
              "user-profile or checkout path. Prefer %USERPROFILE%, <repo> or "
              "<checkout> placeholders.", file=sys.stderr)
    if hits:
        print("[credential-history] HALT - the push ADDS credential-shaped "
              "content. Remove it, or mark a genuine fixture line with "
              f"`{cp.PRAGMA}`.", file=sys.stderr)
    if leak_hits:
        print("[leak-classes] HALT - the push ADDS network or machine identity "
              "(private LAN, tailnet, host name). Code reads host values from "
              "the gitignored ops/local_hosts.json; docs use an RFC 5737 "
              "address or a named placeholder. Test and fixture paths are "
              "exempt.", file=sys.stderr)
    if hits or leak_hits:
        return EXIT_HALT
    return EXIT_CLEAN


def tracked_blobs(rev: str, root: Path = ROOT) -> list[tuple[str, str, int]]:
    """(blob sha, path, size) for every file tracked at ``rev``."""
    out = _git(["ls-tree", "-r", "-l", "-z", "--full-tree", rev], root=root)
    rows = []
    for record in out.decode("utf-8", "replace").split("\0"):
        meta, _, path = record.partition("\t")
        parts = meta.split()
        if not path or len(parts) != 4 or parts[1] != "blob":
            continue
        rows.append((parts[2], path, int(parts[3]) if parts[3].isdigit() else 0))
    return rows


def sweep_leaks(rev: str = "HEAD", root: Path = ROOT,
                leak_values: Sequence[str] | None = None,
                checkout_paths: Sequence[str] | None = None,
                max_bytes: int = PUSH_MAX_BLOB_BYTES) -> tuple[list, list, dict]:
    """(hits, exempt_hits, stats) over every file tracked at ``rev``.

    hits / exempt_hits are (path, Finding) - never a value. A blob shared by
    several paths is read once and attributed to each path.
    """
    if leak_values is None:
        leak_values = local_leak_values(root)
    if checkout_paths is None:
        checkout_paths = checkout_leak_paths(root)
    rows = tracked_blobs(rev, root=root)
    stats = {"files": len(rows), "scanned": 0, "skipped_binary": 0,
             "skipped_large": 0, "exempt_files": 0, "cap": max_bytes}
    todo: dict[str, list[str]] = {}
    for sha, path, size in rows:
        if path.lower().endswith(_SKIP_SUFFIXES):
            stats["skipped_binary"] += 1
        elif size > max_bytes:
            stats["skipped_large"] += 1
        else:
            todo.setdefault(sha, []).append(path)
    hits: list = []
    exempt: list = []
    values, paths = tuple(leak_values), tuple(checkout_paths)
    for sha, data in _read_blobs(list(todo), root=root, max_bytes=max_bytes):
        if data is None:
            stats["skipped_large"] += len(todo[sha])
            continue
        if b"\0" in data[:8192]:
            stats["skipped_binary"] += len(todo[sha])
            continue
        findings = cp.scan_leaks(data.decode("utf-8", "replace"), values, paths)
        for path in todo[sha]:
            stats["scanned"] += 1
            is_exempt = cp.is_leak_exempt(path)
            stats["exempt_files"] += int(is_exempt)
            (exempt if is_exempt else hits).extend((path, f) for f in findings)
    return hits, exempt, stats


def run_leak_sweep(rev: str = "HEAD", root: Path = ROOT,
                   leak_values: Sequence[str] | None = None,
                   checkout_paths: Sequence[str] | None = None) -> int:
    t0 = time.monotonic()
    try:
        hits, exempt, stats = sweep_leaks(rev, root=root, leak_values=leak_values,
                                          checkout_paths=checkout_paths)
    except (GitFault, OSError, ValueError) as exc:
        print(f"[leak-sweep] FAULT - sweep did not run: {exc}. This is not a "
              "clean verdict.", file=sys.stderr)
        return EXIT_FAULT
    gate = [(p, f) for p, f in hits if not cp.is_advisory(f)]
    advisory = [(p, f) for p, f in hits if cp.is_advisory(f)]
    for path, f in gate:
        print(f"  {path}:{f.line_no}  class={f.pattern_class} arm={f.arm}",
              file=sys.stderr)

    def _by_class(rows) -> str:
        lines = Counter(f.pattern_class for _p, f in rows)
        files = Counter(cls for _p, cls in {(p, f.pattern_class) for p, f in rows})
        return ", ".join(f"{c}={lines[c]} line(s)/{files[c]} file(s)"
                         for c in sorted(lines)) or "none"

    print(f"[leak-sweep] {rev}: {len(gate)} gate hit(s) outside test/fixture "
          f"paths; {len(advisory)} advisory; {len(exempt)} in exempt test/"
          f"fixture paths. {stats['scanned']} file(s) scanned of "
          f"{stats['files']} ({stats['skipped_binary']} binary, "
          f"{stats['skipped_large']} over {stats['cap']} bytes, "
          f"{stats['exempt_files']} exempt) in {time.monotonic() - t0:.1f}s",
          file=sys.stderr)
    print(f"[leak-sweep]   gate: {_by_class(gate)}", file=sys.stderr)
    print(f"[leak-sweep]   advisory: {_by_class(advisory)}", file=sys.stderr)
    print(f"[leak-sweep]   exempt: {_by_class(exempt)}", file=sys.stderr)
    return EXIT_HALT if gate else EXIT_CLEAN


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true",
                   help="scan every blob reachable from any ref")
    g.add_argument("--pre-push", nargs="*", metavar="ARG",
                   help="remote name (and url); refs read from stdin")
    g.add_argument("--leak-sweep", nargs="?", const="HEAD", metavar="REV",
                   help="leak classes over every file tracked at REV (HEAD)")
    ns = ap.parse_args(argv)
    if ns.all:
        return run([["--all"]], max_bytes=ALL_MAX_BLOB_BYTES)
    if ns.leak_sweep is not None:
        return run_leak_sweep(ns.leak_sweep)
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
