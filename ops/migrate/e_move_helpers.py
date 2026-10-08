"""Helpers for the RC C: -> E: move driven by ops/migrate/e_move.ps1.

The PowerShell driver owns tasks, processes, robocopy and junctions. This module
owns every edit that must be BYTE-EXACT or touches JSON too large for PS 5.1's
ConvertTo-Json: path-literal rewrites, git worktree link files, untracked config
files, and the Claude Code ``.claude.json`` project keys.

Pure functions (pinned by tests/test_e_move_helpers.py):
  PathRewriter(mappings).rewrite(text)   every spelling of a path literal
  rewrite_bytes(raw, rewriter)           byte-preserving file-content rewrite
  config_candidate(rel)                  RepointInternal (c) file filter
  clone_project_keys(data, mappings)     .claude.json "projects" key clone

CLI subcommands print ONE ASCII JSON document on stdout:
  rewrite-text, scan-reparse, repoint-gitdirs, repoint-configs,
  clone-project-keys, strays (read-only report of destination-only files)
Every subcommand that could write honours --dry-run, which writes NOTHING.
"""
from __future__ import annotations

import argparse
import codecs
import copy
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.polled_json import atomic_write_bytes  # noqa: E402

CREATE_NO_WINDOW = 0x08000000
_NO_WINDOW = CREATE_NO_WINDOW if os.name == "nt" else 0

# A literal only counts when it is not glued to a longer name on either side:
# "C:\Riot Commander.pre-E-move-20261008" and "XC:\Riot Commander" must not match.
_LEFT = r"(?<![A-Za-z0-9_])"
_RIGHT = r"(?![A-Za-z0-9_.\-])"
FORMS = ("json", "bs", "fwd", "msys")

FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_REPARSE_POINT = 0x400


@dataclass(frozen=True)
class DrivePath:
    """A drive-absolute Windows path split into drive letter + components."""

    drive: str
    parts: tuple

    @classmethod
    def parse(cls, path: str) -> DrivePath:
        m = re.match(r"^([A-Za-z]):[\\/]+(.*)$", path.strip())
        if not m:
            raise ValueError(f"not a drive-absolute path: {path!r}")
        parts = tuple(p for p in re.split(r"[\\/]+", m.group(2)) if p)
        if not parts:
            raise ValueError(f"refusing a bare drive root: {path!r}")
        return cls(m.group(1), parts)

    def render(self, form: str, lower_drive: bool) -> str:
        d = self.drive.lower() if lower_drive else self.drive.upper()
        if form == "json":
            return d + ":" + "\\\\" + "\\\\".join(self.parts)
        if form == "bs":
            return d + ":" + "\\" + "\\".join(self.parts)
        if form == "fwd":
            return d + ":/" + "/".join(self.parts)
        if form == "msys":
            return "/" + d + "/" + "/".join(self.parts)
        raise ValueError(f"unknown form {form!r}")

    def norm(self) -> str:
        return (self.drive + ":/" + "/".join(self.parts)).casefold()


def _form_regex(p: DrivePath, form: str, idx: int) -> str:
    esc = [re.escape(x) for x in p.parts]
    d = f"(?P<d{idx}>{re.escape(p.drive)})"
    if form == "json":
        return _LEFT + d + r":\\\\" + r"\\\\".join(esc)
    if form == "bs":
        return _LEFT + d + r":\\" + r"\\".join(esc)
    if form == "fwd":
        return _LEFT + d + ":/" + "/".join(esc)
    return "/" + d + "/" + "/".join(esc)


class PathRewriter:
    """Rewrite every spelling of each source root to the matching destination.

    Spellings: ``C:\\X`` (bs), ``C:/X`` (fwd), ``C:\\\\X`` (json-escaped) and
    ``/c/X`` (msys). Matching is case-insensitive; the drive letter keeps the
    case it had, the rest takes the destination's canonical spelling. One
    combined regex, so a destination can never be re-matched by a later pair.
    """

    def __init__(self, mappings):
        pairs = [(DrivePath.parse(s), DrivePath.parse(d)) for s, d in mappings]
        # Longest source first so a nested root wins over its parent.
        pairs.sort(key=lambda sd: len(sd[0].parts), reverse=True)
        self.pairs = pairs
        self._index = []
        alts = []
        for pi, (src, _dst) in enumerate(pairs):
            for form in FORMS:
                idx = len(self._index)
                self._index.append((pi, form))
                alts.append(f"(?P<a{idx}>{_form_regex(src, form, idx)})")
        self.regex = re.compile("(?:" + "|".join(alts) + ")" + _RIGHT, re.IGNORECASE)

    def _replacement(self, m: re.Match) -> str:
        for idx in range(len(self._index)):
            if m.group(f"a{idx}") is not None:
                pi, form = self._index[idx]
                drive_text = m.group(f"d{idx}")
                return self.pairs[pi][1].render(form, lower_drive=drive_text.islower())
        return m.group(0)

    def rewrite(self, text: str):
        """Return (new_text, match_count). Count includes identity rewrites."""
        count = 0

        def repl(m):
            nonlocal count
            count += 1
            return self._replacement(m)

        return self.regex.sub(repl, text), count

    def matches(self, text: str) -> bool:
        return bool(text) and self.regex.search(text) is not None

    def dst_roots(self):
        return [d for _s, d in self.pairs]


def rewrite_bytes(raw: bytes, rw: PathRewriter):
    """Rewrite path literals in file bytes without disturbing anything else.

    UTF-16 files (BOM) are decoded and re-encoded with the same BOM. Anything
    else with a NUL byte is binary and left alone. Everything else goes through
    latin-1, a 1:1 byte<->char map, so line endings, a UTF-8 BOM and non-ASCII
    bytes survive untouched (the patterns are pure ASCII and can never match
    inside a UTF-8 multibyte sequence). Returns (new_raw, count, kind).
    """
    for bom, codec in ((codecs.BOM_UTF16_LE, "utf-16-le"), (codecs.BOM_UTF16_BE, "utf-16-be")):
        if raw.startswith(bom):
            try:
                text = raw[len(bom):].decode(codec)
            except UnicodeDecodeError:
                return raw, 0, "binary"
            new, n = rw.rewrite(text)
            return (bom + new.encode(codec)) if n else raw, n, codec
    if b"\x00" in raw:
        return raw, 0, "binary"
    new, n = rw.rewrite(raw.decode("latin-1"))
    return (new.encode("latin-1") if n else raw), n, "bytes"


def _backup(path: Path, backup: Path | None) -> str | None:
    """Copy ``path`` to ``backup`` once; the FIRST backup is the pristine one."""
    if backup is None:
        return None
    if not backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup)
    return str(backup)


def rewrite_file(path: Path, rw: PathRewriter, dry_run: bool, backup: Path | None = None,
                 max_bytes: int = 32 * 1024 * 1024) -> dict:
    rec = {"path": str(path), "count": 0, "kind": "", "changed": False}
    try:
        size = path.stat().st_size
        if size > max_bytes:
            rec["kind"] = "too-large"
            return rec
        raw = path.read_bytes()
    except OSError as exc:
        rec["error"] = f"read: {exc}"
        return rec
    new, n, kind = rewrite_bytes(raw, rw)
    rec["count"], rec["kind"] = n, kind
    if n and new != raw:
        rec["changed"] = True
        if not dry_run:
            try:
                rec["backup"] = _backup(path, backup)
                atomic_write_bytes(path, new)
            except OSError as exc:
                rec["error"] = f"write: {exc}"
    return rec


# --------------------------------------------------------------------------
# RepointInternal (b): git worktree link files
# --------------------------------------------------------------------------

def _under(path_norm: str, root_norm: str) -> bool:
    return path_norm == root_norm or path_norm.startswith(root_norm.rstrip("/") + "/")


def _norm(p: str) -> str:
    p = p.strip()
    if p.startswith("\\\\?\\"):
        p = p[4:]
    return p.replace("\\", "/").rstrip("/").casefold()


def gitdir_link_files(repo: Path, wt_root: Path | None):
    """[(kind, path)] for every worktree link file under the repo and wt root."""
    out = []
    admin = repo / ".git" / "worktrees"
    if admin.is_dir():
        for d in sorted(admin.iterdir()):
            f = d / "gitdir"
            if f.is_file():
                out.append(("admin", f))
    for base in (repo / ".claude" / "worktrees", wt_root):
        if base is None or not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            f = d / ".git"
            if d.is_dir() and f.is_file():
                out.append(("pointer", f))
    return out


def _link_target(kind: str, text: str) -> str:
    line = text.strip().splitlines()[0].strip() if text.strip() else ""
    if kind == "pointer":
        if line.lower().startswith("gitdir:"):
            return line[len("gitdir:"):].strip()
        return ""
    return line


def repoint_gitdirs(repo: Path, wt_root: Path | None, rw: PathRewriter, dry_run: bool,
                    backup_root: Path | None) -> dict:
    dst_norms = [d.norm() for d in rw.dst_roots()]
    rewritten, unchanged, errors = [], 0, []
    internal, external, dangling = [], [], []
    for kind, f in gitdir_link_files(repo, wt_root):
        backup = None
        if backup_root is not None:
            try:
                rel = f.relative_to(repo)
                backup = backup_root / "gitlinks" / rel
            except ValueError:
                backup = backup_root / "gitlinks" / "_wt" / f.parent.name / f.name
        rec = rewrite_file(f, rw, dry_run, backup)
        if rec.get("error"):
            errors.append(rec)
        if rec["count"]:
            rewritten.append({"path": rec["path"], "count": rec["count"]})
        else:
            unchanged += 1
        try:
            text = f.read_bytes().decode("latin-1")
        except OSError:
            continue
        if dry_run:
            text, _n = rw.rewrite(text)
        target = _link_target(kind, text)
        if not target:
            continue
        if kind == "admin":
            wt_path = target[:-len("/.git")] if target.replace("\\", "/").endswith("/.git") else target
            norm = _norm(wt_path)
            row = {"admin": str(f.parent), "worktree": wt_path, "exists": os.path.isdir(wt_path)}
            if any(_under(norm, r) for r in dst_norms):
                internal.append(row)
            else:
                external.append(row)
        elif not os.path.isdir(target):
            dangling.append({"pointer": str(f), "gitdir": target})
    return {
        "files": len(rewritten) + unchanged,
        "rewritten": rewritten,
        "unchanged": unchanged,
        "internal_worktrees": internal,
        "external_worktrees": external,
        "dangling_pointers": dangling,
        "errors": errors,
    }


# --------------------------------------------------------------------------
# RepointInternal (c): untracked / ignored config files
# --------------------------------------------------------------------------

CONFIG_EXTS = frozenset({".json", ".ps1", ".bat", ".cmd", ".vbs", ".ini", ".cfg",
                         ".toml", ".yaml", ".yml", ".xml", ".txt"})
# ops/runtime/responder_export/ is a byte projection of origin/main that the inbox
# responder runs in (tools/inbox_responder_export.py, PUBLIC-PROJECTION PRINCIPLE):
# rewriting it would make its bytes differ from origin/main. ops/migrate/ holds this
# tool, whose Src defaults must never be rewritten to Dst.
ANCHORED_EXCLUDES = ("logs/", "data/", "docs/_archive/", "moon_sync_inbox/",
                     ".claude/worktrees/", "ops/runtime/e_move_backup/", "ops/migrate/",
                     "ops/runtime/responder_export/")
EXACT_EXCLUDES = frozenset({"ops/runtime/e_move_state.json"})
COMPONENT_EXCLUDES = frozenset({"node_modules", ".venv", "__pycache__", ".git"})
NAME_EXCLUDE_GLOBS = ("*.jsonl", "*.log*")


def config_candidate(rel: str):
    """(is_candidate, reason) for a repo-relative path. Case-insensitive."""
    low = rel.replace("\\", "/").lower()
    for pre in ANCHORED_EXCLUDES:
        if low.startswith(pre):
            return False, "excluded:" + pre
    if low in EXACT_EXCLUDES:
        return False, "excluded:state"
    parts = low.split("/")
    if any(p in COMPONENT_EXCLUDES for p in parts[:-1]):
        return False, "excluded:component"
    name = parts[-1]
    for g in NAME_EXCLUDE_GLOBS:
        if fnmatch.fnmatchcase(name, g):
            return False, "excluded:" + g
    if os.path.splitext(name)[1] not in CONFIG_EXTS:
        return False, "extension"
    return True, ""


def _git(repo: Path, *args: str) -> bytes:
    cmd = ["git", "-c", f"safe.directory={repo.as_posix()}", "-C", str(repo), *args]
    proc = subprocess.run(cmd, capture_output=True, check=False, creationflags=_NO_WINDOW)
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {proc.stderr.decode('utf-8', 'replace').strip()}")
    return proc.stdout


def untracked_files(repo: Path):
    """Union of `ls-files --others` with and without --ignored --exclude-standard."""
    seen = set()
    for extra in ((), ("--ignored", "--exclude-standard")):
        out = _git(repo, "ls-files", "-z", "--others", *extra)
        for item in out.split(b"\0"):
            if item:
                seen.add(item.decode("utf-8", "surrogateescape"))
    return sorted(seen)


def repoint_configs(repo: Path, rw: PathRewriter, dry_run: bool, backup_root: Path | None) -> dict:
    listed = untracked_files(repo)
    candidates, matched, errors, skipped = 0, [], [], {}
    for rel in listed:
        ok, why = config_candidate(rel)
        if not ok:
            skipped[why] = skipped.get(why, 0) + 1
            continue
        f = repo / rel
        if not f.is_file():
            continue
        candidates += 1
        backup = (backup_root / rel) if backup_root is not None else None
        rec = rewrite_file(f, rw, dry_run, backup)
        if rec.get("error"):
            errors.append({"path": rel, "error": rec["error"]})
        if rec["count"]:
            matched.append({"path": rel, "count": rec["count"], "kind": rec["kind"]})
    return {"listed": len(listed), "candidates": candidates, "matched": matched,
            "skipped": skipped, "errors": errors}


# --------------------------------------------------------------------------
# Cutover (iii): Claude Code .claude.json project keys
# --------------------------------------------------------------------------

def _norm_key(k: str) -> str:
    return k.replace("\\", "/").rstrip("/").casefold()


def _rewrite_obj(obj, rw: PathRewriter):
    if isinstance(obj, str):
        return rw.rewrite(obj)[0]
    if isinstance(obj, list):
        return [_rewrite_obj(x, rw) for x in obj]
    if isinstance(obj, dict):
        return {k: _rewrite_obj(v, rw) for k, v in obj.items()}
    return obj


def clone_project_keys(data: dict, mappings) -> list:
    """Clone each "projects" key naming a source ROOT to its destination key.

    Never removes or overwrites anything: a destination key that already exists
    is left as-is. The exact-case spelling of a source is cloned first, so a
    lower-case duplicate key does not win the destination slot. String values
    inside the clone have every source literal rewritten.
    """
    projects = data.get("projects")
    if not isinstance(projects, dict):
        return []
    rw = PathRewriter(mappings)
    srcs = {_norm_key(s): s for s, _d in mappings}
    cands = [k for k in projects if _norm_key(k) in srcs]

    def rank(k: str) -> int:
        canonical = srcs[_norm_key(k)].replace("\\", "/").rstrip("/")
        return 0 if k.replace("\\", "/").rstrip("/") == canonical else 1

    cands.sort(key=rank)
    actions = []
    for k in cands:
        new_k, _n = rw.rewrite(k)
        if new_k == k:
            actions.append({"from": k, "to": new_k, "action": "unchanged"})
        elif new_k in projects:
            actions.append({"from": k, "to": new_k, "action": "exists"})
        else:
            projects[new_k] = _rewrite_obj(copy.deepcopy(projects[k]), rw)
            actions.append({"from": k, "to": new_k, "action": "cloned"})
    return actions


def _serialize_like(data, text: str) -> str:
    out = json.dumps(data, indent=2, ensure_ascii=False)
    return out + "\n" if text.endswith("\n") else out


def clone_keys_in_file(path: Path, mappings, backup_dir: Path | None, dry_run: bool,
                       attempts: int = 6) -> dict:
    rec = {"file": str(path), "actions": [], "written": False}
    if not path.is_file():
        rec["missing"] = True
        return rec
    for attempt in range(attempts):
        st = path.stat()
        raw = path.read_bytes()
        bom = raw.startswith(codecs.BOM_UTF8)
        text = raw[3:].decode("utf-8") if bom else raw.decode("utf-8")
        data = json.loads(text)
        rec["format_preserved"] = _serialize_like(data, text) == text
        actions = clone_project_keys(data, mappings)
        rec["actions"] = actions
        if dry_run or not any(a["action"] == "cloned" for a in actions):
            return rec
        body = (codecs.BOM_UTF8 if bom else b"") + _serialize_like(data, text).encode("utf-8")
        st2 = path.stat()
        if (st2.st_mtime_ns, st2.st_size) != (st.st_mtime_ns, st.st_size):
            time.sleep(0.5)
            continue
        if backup_dir is not None:
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            bpath = backup_dir / f"{path.parent.name}{path.name}.{stamp}.bak"
            bpath.write_bytes(raw)
            rec["backup"] = str(bpath)
        try:
            atomic_write_bytes(path, body)
        except OSError as exc:
            rec["last_error"] = str(exc)
            time.sleep(0.5)
            continue
        check = json.loads(path.read_bytes().decode("utf-8-sig"))
        want = [a["to"] for a in actions if a["action"] == "cloned"]
        rec["written"] = True
        rec["verified"] = all(k in check.get("projects", {}) for k in want)
        rec["attempt"] = attempt + 1
        return rec
    rec["error"] = "file kept changing under us (or stayed locked); nothing written"
    return rec


# --------------------------------------------------------------------------
# Preseed: reparse points (junctions / symlinks) inside the trees
# --------------------------------------------------------------------------

def _map_path(path: str, rw: PathRewriter):
    """Destination twin of ``path`` if it lies under a source root, else None."""
    n = _norm(path)
    for src, dst in rw.pairs:
        sn = src.norm()
        if _under(n, sn):
            tail = path.replace("\\", "/").rstrip("/")[len(sn):].lstrip("/")
            base = dst.render("bs", lower_drive=False)
            return base + ("\\" + tail.replace("/", "\\") if tail else "")
    return None


def scan_reparse(roots, rw: PathRewriter) -> dict:
    found, errors = [], []
    stats = {"dirs": 0, "files": 0, "bytes": 0}
    for root in roots:
        if not os.path.isdir(root):
            continue
        stack = [root]
        while stack:
            d = stack.pop()
            try:
                it = os.scandir(d)
            except OSError as exc:
                errors.append(f"{d}: {exc}")
                continue
            with it:
                for e in it:
                    try:
                        st = e.stat(follow_symlinks=False)
                    except OSError as exc:
                        errors.append(f"{e.path}: {exc}")
                        continue
                    attrs = getattr(st, "st_file_attributes", 0)
                    if attrs & FILE_ATTRIBUTE_REPARSE_POINT:
                        is_dir = bool(attrs & FILE_ATTRIBUTE_DIRECTORY)
                        if e.is_junction():
                            kind = "junction"
                        elif e.is_symlink():
                            kind = "symlink_dir" if is_dir else "symlink_file"
                        else:
                            kind = "other"
                        target = None
                        if kind != "other":
                            try:
                                target = os.readlink(e.path)
                                if target.startswith("\\\\?\\"):
                                    target = target[4:]
                                if not os.path.isabs(target):
                                    target = os.path.normpath(os.path.join(os.path.dirname(e.path), target))
                            except OSError as exc:
                                errors.append(f"{e.path}: readlink {exc}")
                        row = {"path": e.path, "kind": kind, "target": target}
                        dst_target = _map_path(target, rw) if target else None
                        if kind != "other" and dst_target:
                            row["dst_link"] = _map_path(e.path, rw)
                            row["dst_target"] = dst_target
                        else:
                            row["external"] = True
                        found.append(row)
                        continue
                    if e.is_dir(follow_symlinks=False):
                        stats["dirs"] += 1
                        stack.append(e.path)
                    else:
                        stats["files"] += 1
                        stats["bytes"] += st.st_size
    return {"reparse": found, "stats": stats, "errors": errors[:50], "error_count": len(errors)}


# --------------------------------------------------------------------------
# Cutover: strays (files on the destination that the source no longer has)
# --------------------------------------------------------------------------

# Destination-only by design: the mirrored .git and this tool's own files.
STRAY_SKIP = (".git", "ops/runtime/e_move_backup", "ops/runtime/e_move_state.json",
              "logs/e_move.log", "logs/e_move_robocopy.log")


def _is_reparse(st) -> bool:
    return bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)


def _count_files(root: str) -> int:
    n, stack = 0, [root]
    while stack:
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            for e in it:
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if e.is_dir(follow_symlinks=False) and not _is_reparse(st):
                    stack.append(e.path)
                else:
                    n += 1
    return n


def find_strays(src: Path, dst: Path, limit: int = 300, skip=STRAY_SKIP) -> dict:
    """Entries under ``dst`` with no counterpart under ``src``. Read-only.

    A missing directory is reported once (with its file count), never descended.
    Reparse points are never followed. Nothing is ever deleted.
    """
    out = {"src": str(src), "dst": str(dst), "count": 0, "files": 0, "sample": [], "errors": 0}
    if not src.is_dir() or not dst.is_dir():
        out["missing"] = True
        return out
    skips = {s.casefold() for s in skip}
    stack = [""]
    while stack:
        rel_dir = stack.pop()
        try:
            it = os.scandir(dst / rel_dir if rel_dir else dst)
        except OSError:
            out["errors"] += 1
            continue
        with it:
            for e in it:
                rel = f"{rel_dir}/{e.name}" if rel_dir else e.name
                if rel.casefold() in skips:
                    continue
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    out["errors"] += 1
                    continue
                is_dir = e.is_dir(follow_symlinks=False) and not _is_reparse(st)
                if os.path.lexists(src / rel):
                    if is_dir:
                        stack.append(rel)
                    continue
                nfiles = _count_files(e.path) if is_dir else 1
                out["count"] += 1
                out["files"] += nfiles
                if len(out["sample"]) < limit:
                    out["sample"].append({"rel": rel, "kind": "dir" if is_dir else "file", "files": nfiles})
    return out


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _emit(obj) -> int:
    sys.stdout.write(json.dumps(obj, ensure_ascii=True, sort_keys=False) + "\n")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_map(p):
        p.add_argument("--map", nargs=2, action="append", metavar=("SRC", "DST"), required=True)

    p = sub.add_parser("rewrite-text")
    add_map(p)
    p.add_argument("--text", required=True)

    p = sub.add_parser("scan-reparse")
    add_map(p)
    p.add_argument("--root", action="append", required=True)

    p = sub.add_parser("repoint-gitdirs")
    add_map(p)
    p.add_argument("--repo", required=True)
    p.add_argument("--wt-root")
    p.add_argument("--backup-root")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("repoint-configs")
    add_map(p)
    p.add_argument("--repo", required=True)
    p.add_argument("--backup-root")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("clone-project-keys")
    add_map(p)
    p.add_argument("--file", action="append", required=True)
    p.add_argument("--backup-dir")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("strays")
    p.add_argument("--pair", nargs=2, action="append", metavar=("SRC", "DST"), required=True)
    p.add_argument("--limit", type=int, default=300)

    a = ap.parse_args(argv)
    if a.cmd == "strays":
        return _emit({"pairs": [find_strays(Path(s), Path(d), a.limit) for s, d in a.pair]})
    mappings = [tuple(m) for m in a.map]
    rw = PathRewriter(mappings)
    if a.cmd == "rewrite-text":
        text, n = rw.rewrite(a.text)
        return _emit({"text": text, "count": n})
    if a.cmd == "scan-reparse":
        return _emit(scan_reparse(a.root, rw))
    if a.cmd == "repoint-gitdirs":
        wt = Path(a.wt_root) if a.wt_root else None
        backup = Path(a.backup_root) if a.backup_root else None
        return _emit(repoint_gitdirs(Path(a.repo), wt, rw, a.dry_run, backup))
    if a.cmd == "repoint-configs":
        backup = Path(a.backup_root) if a.backup_root else None
        return _emit(repoint_configs(Path(a.repo), rw, a.dry_run, backup))
    if a.cmd == "clone-project-keys":
        bdir = Path(a.backup_dir) if a.backup_dir else None
        res = []
        for f in a.file:
            try:
                res.append(clone_keys_in_file(Path(f), mappings, bdir, a.dry_run))
            except (OSError, ValueError) as exc:
                res.append({"file": f, "error": str(exc)})
        return _emit({"files": res})
    return 2


if __name__ == "__main__":
    sys.exit(main())
