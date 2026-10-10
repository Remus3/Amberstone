"""Headless full-tree repo review driver (MAIN ORDER 2026-10-08 2246 section 8).

Operator order S7, relayed by MAIN: ONE headless driver through the kit spawn
path reviews 100 percent of the files on disk in this repo - tracked, untracked
and ignored alike - for folder hierarchy, memory recall, dated files, pins and
leaves, worktrees, scratch, orphans, stale files, the outside-repo sidecar
consolidation and the .md set, plus inferred topics. Sections 2, 3, 5 and 6 of
the same note are KNOWN findings: the prompt lists them and the reviewer cites
them instead of re-deriving them.

Every reviewer run is READ-ONLY and goes through RC's one door into the fleet
kit, `ops/loop/fleet_route.spawn` (FLEET-COMMON item 10): sonnet (writes_code
False), kind "build", a non-empty note label `repo-review-<batch>`, the usage
row written by the kit. Read-only is the CLI's own `--permission-mode dontAsk`
with only Read / Grep / Glob allowed and every writer, shell, agent and web
tool denied. A route or kit refusal halts the WHOLE driver (fail closed, no
fallback, never another spawn path) with status "blocked" and the refusal code.

Universe (the order's "count on disk"): every regular file under the repo root,
walked on the filesystem, except the root `.git/` directory; a linked worktree
registered by `git worktree list` that sits inside the root is ONE unit (it is
another checkout of this repository, reviewed under the worktrees topic). Git's
own index decides tracked (ADR-015: the index first), git's ignore rules decide
ignored; the rest is untracked. The snapshot is frozen at `enumerate` time;
`delta` re-measures and batches whatever appeared since, so the reviewed count
can be reconciled to a fresh on-disk count at compile time.

Bulk classes (caches, vendored node_modules, the DDragon asset mirror, the
meta_build mirror, responder exports, the embedded Python, the channel inbox,
nested worktrees) are reviewed BY CLASS: the prompt carries the whole class's
measured facts (count, bytes, dates, extension and folder histograms, computed
orphans) plus a deterministic sample, and the verdict covers every file of the
class. Every other file is listed ROW BY ROW with its metadata.

Files (all gitignored; written atomically):
  ops/runtime/repo_review/manifest.jsonl        frozen snapshot, one row per unit
  ops/runtime/repo_review/batches.json          the batch plan
  ops/runtime/repo_review/prompts/<bid>.txt     the exact prompt each run got
  ops/runtime/repo_review/raw/<bid>.out.txt     each run's raw result text
  ops/runtime/repo_review/findings/<bid>.json   parsed findings + run meta
  ops/runtime/repo_review/summary.json          compile output
  ops/loop/control/progress/repo-review.json    item-12 progress + checklist
  logs/repo_review.log                          driver log
Halt switch: ops/loop/control/REPO_REVIEW_STOP (checked before every spawn).

Usage:
  python ops/loop/repo_review.py enumerate
  python ops/loop/repo_review.py run [--parallel N] [--max-runs N] [--only B01,B02] [--dry-run]
  python ops/loop/repo_review.py delta
  python ops/loop/repo_review.py compile
Exit: 0 done, 1 failed batches remain, 2 halted (stop file / run cap), 3 refused.
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASK = "repo-review"
CALLER = "repo_review"
KIND = "build"
STAGE = ROOT / "ops" / "runtime" / "repo_review"
MANIFEST = STAGE / "manifest.jsonl"
BATCHES = STAGE / "batches.json"
PROMPTS = STAGE / "prompts"
RAW = STAGE / "raw"
FINDINGS = STAGE / "findings"
SUMMARY = STAGE / "summary.json"
STOP_FILE = ROOT / "ops" / "loop" / "control" / "REPO_REVIEW_STOP"
LOG = ROOT / "logs" / "repo_review.log"

RUN_TIMEOUT_S = 2700
DEFAULT_PARALLEL = 4
DEFAULT_MAX_RUNS = 70  # the driver's own ceiling, under the kit's 120 / 24 h
RETRIES = 1  # one re-run of a batch whose answer was missing or malformed
BATCH_WEIGHT_CAP = 150.0
SAMPLE_N = 60
READ_ONLY_EXTRA = (
    "--permission-mode", "dontAsk",
    "--allowedTools", "Read,Grep,Glob",
    "--disallowedTools",
    "Edit,Write,MultiEdit,NotebookEdit,Bash,PowerShell,Agent,Task,WebFetch,WebSearch",
)
CODE_EXT = frozenset({
    ".py", ".md", ".ps1", ".psm1", ".psd1", ".bat", ".cmd", ".sh", ".js", ".mjs",
    ".cjs", ".ts", ".tsx", ".jsx", ".css", ".html", ".htm", ".yml", ".yaml",
    ".toml", ".ini", ".cfg", ".txt", ".ahk", ".rst", ".svg", ".spec", "",
})
TEXT_EXT = CODE_EXT | {".json", ".jsonl", ".csv", ".xml", ".lock"}
REF_SCAN_MAX_BYTES = 512 * 1024
_TOKEN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-]*")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

# Core docs pulled out of their folders into ONE batch with the .md-set focus.
MD_CORE = (
    "CLAUDE.md", "README.md", "ROADMAP.md", "BACKLOG.md", "WAKEUP_NOTES.md",
    "RC-NEXT-SESSION.txt", "RC_WORK_TRACKER.md", "docs/ARCHITECTURE.md",
    "docs/API.md", "docs/AGENTS.md", "docs/OPERATIONS.md", "docs/LEDGER.md",
    "docs/history_notes.md", "docs/claude-md-history.md", "docs/DAEMON_SLAYER.md",
    "docs/ROADMAP_HISTORY.md", "docs/adr/README.md", "docs/LIVE_GAME_GATED_SYNC.md",
    "docs/ORCHESTRATION_PLAN.md", "docs/CHANNEL.md",
)

# (class id, title, reviewer note). Membership is decided by `classify`.
CLASSES = (
    ("worktrees", "Linked worktrees nested inside the repo root (one unit each)",
     "Each unit is another checkout of this repository. Judge: still needed, stale, "
     "locked, belongs under the sidecar folder, safe to remove (list, never do)."),
    ("pycache", "Python bytecode caches (__pycache__ / *.pyc)",
     "Regenerable. Judge: gitignored correctly, orphan bytecode whose source is gone, "
     "caches inside places that should hold none."),
    ("toolcache", "Tool caches (.ruff_cache / .pytest_cache)",
     "Regenerable. Judge: ignored, location, size."),
    ("node_modules", "Vendored npm dependencies (node_modules)",
     "Third-party install output. Judge: lockfile tracked, ignored, licence-gate "
     "relevance, whether the install belongs in the tree at all."),
    ("ddragon-web", "DDragon asset mirror under web/data/ddragon",
     "Riot static data mirror. Judge: versions kept vs needed, prune candidates by "
     "version, consumer of each version, size."),
    ("meta-build", "data/meta_build mirror (DDragon detail JSON + html)",
     "Judge: versions kept vs needed, consumer, prune or archive candidates."),
    ("responder-export", "ops/runtime/responder_export snapshots",
     "Copies of repo files exported for the inbox responder. Judge: retention, "
     "whether old exports can be pruned (Recycle Bin, consumer first), sidecar move."),
    ("python-embed", "Embedded Python distribution (python-embed)",
     "Third-party runtime. Judge: consumer, version, belongs in tree or sidecar."),
    ("inbox", "Channel inbox moon_sync_inbox (notes and kit bundles)",
     "Gitignored channel notes. Judge: dated notes and old kit bundles that can be "
     "archived (never deleted without a consumer check), stray files, pyc inside "
     "bundles. Never quote a note body; name files only."),
)
CLASS_IDS = tuple(c[0] for c in CLASSES)

KNOWN_FINDINGS = (
    ("KF-P1", "push CI runs the full dual suite on every push"),
    ("KF-P2", "pushes per slice, not per session"),
    ("KF-P3", "local full suite serial; run -n 8"),
    ("KF-P4", "test rules contradict (tiers vs always-full)"),
    ("KF-P5", "headless build slices monolithic and all-opus"),
    ("KF-P6", "headless_usage.jsonl stopped 2026-10-04, no kind"),
    ("KF-P7", "sub-agents use Bash for reads"),
    ("KF-P8", "ci.yml nightly runs on workflow_dispatch too"),
    ("KF-P9", "bootstrap reads ~178 KB before work; /done adds 34.6 KB"),
    ("KF-P10", "RC_FULL_SUITE=1 makes the PostToolUse hook run a full suite"),
    ("KF-P11", "126 progress files, some 'running' long past 2x ETA"),
    ("KF-P12", "one ANSWER per ORDER hit the 6/day cap; junk cls values"),
    ("KF-R1", "class private LAN IPv4 in tracked files"),
    ("KF-R2", "class user-profile path / account username in tracked files"),
    ("KF-R3", "the pre-rename project name in tracked files"),
    ("KF-R4", "42 root files (bat launchers, top-level py, atlas.html) clutter the root"),
    ("KF-R5", "README hand-off bullet is a history note"),
    ("KF-R6", "README 'deterministic engine' claim repeated"),
    ("KF-R7", "README status dated 2026-10-03"),
    ("KF-R8", "README topics: process topics vs product topics"),
    ("KF-S1", "lane worktree base pointed at the old drive-root folder"),
    ("KF-S2", "record lines naming the pre-rewrite bundles' old location"),
    ("KF-A1", "atlas.html is hand-authored data, stale; derive or retire"),
    ("KF-A2", "atlas motion freezes on reduced-motion; no pause control"),
    ("KF-A3", "atlas fonts under the 14 px floor"),
    ("KF-A4", "atlas region titles faint and small"),
    ("KF-A5", "atlas zoom performance"),
    ("KF-A6", "atlas carries the machine host name"),
    ("KF-A7", "atlas embeds base64 snapshots"),
    ("KF-A8", "atlas light theme should use kit tokens.css"),
    ("KF-A9", "atlas drag pans / zoom cap"),
)

TOPICS = ("H", "M", "D", "P", "W", "S", "O", "T", "X", "MD")
SEVERITIES = ("high", "med", "low", "info")
PROPOSED = ("FILE", "NA")

_log_lock = threading.Lock()
_state_lock = threading.Lock()


# ---------------------------------------------------------------- io helpers

def _say(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}"
    with _log_lock:
        try:
            LOG.parent.mkdir(parents=True, exist_ok=True)
            with LOG.open("a", encoding="ascii", errors="replace", newline="\n") as fh:
                fh.write(line + "\n")
        except OSError:
            pass
        if sys.stdout is not None:
            try:
                sys.stdout.write(msg + "\n")
                sys.stdout.flush()
            except (OSError, ValueError):
                pass


def _atomic_write(path: Path, text: str) -> None:
    """UTF-8 with LF kept verbatim, through core/polled_json (RM-258): a
    per-WRITE scratch name, the bounded WinError 5 retry and no stranded
    scratch on failure. The hand-rolled tmp + Path.replace this replaced had
    no retry and reused one pid.tid scratch name for every write a thread made
    (tests/test_atomic_write_guard_rm258_rm261.py; behaviour pinned by
    tests/test_loop_control_sibling_writers_lane8_cycle48.py)."""
    _atomic_write_bytes(Path(path), text.encode("utf-8"))


_import_lock = threading.Lock()


def _load_by_path(name: str, path: Path):
    """Load a sibling module by file path ONCE. Locked: worker threads that
    raced here used to see a half-executed module in sys.modules (measured
    2026-10-09: AttributeError on RouteRefused in 4 of the first 8 batches)."""
    with _import_lock:
        mod = sys.modules.get(name)
        if mod is not None:
            return mod
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop(name, None)
            raise
        return mod


# core/polled_json.py holds the repo's atomic-write contract (RM-258). Plain
# import first so a repo-root process (the test suite) shares one module
# object; run as `python ops/loop/repo_review.py`, sys.path[0] is ops/loop and
# the repo root is on no path entry, so the fallback binds it by absolute path
# under the same name the other ops/loop writers use.
try:
    from core.polled_json import atomic_write_bytes as _atomic_write_bytes
except ModuleNotFoundError:
    _atomic_write_bytes = _load_by_path(
        "rc_core_polled_json", ROOT / "core" / "polled_json.py").atomic_write_bytes


def _fleet_route():
    """RC's one door into the kit (FLEET-COMMON 10), loaded by file path."""
    return _load_by_path("rc_ops_loop_fleet_route", ROOT / "ops" / "loop" / "fleet_route.py")


def _kit():
    return _load_by_path("rc_fleet_kit_fleet_headless",
                         ROOT / "ops" / "fleet_kit" / "fleet_headless.py")


def _git_bytes(*args: str, cwd: Path | None = None) -> bytes:
    proc = subprocess.run(["git", *args], cwd=str(cwd or ROOT), capture_output=True,
                          timeout=900, creationflags=_NO_WINDOW)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])} failed rc={proc.returncode}")
    return proc.stdout


def _git_z(*args: str, cwd: Path | None = None) -> list[str]:
    raw = _git_bytes(*args, cwd=cwd).decode("utf-8", "replace")
    return [p for p in raw.split("\0") if p]


# ---------------------------------------------------------------- universe

def linked_worktrees(root: Path = ROOT) -> list[dict]:
    """Linked worktrees from `git worktree list --porcelain` (main excluded)."""
    text = _git_bytes("worktree", "list", "--porcelain", cwd=root).decode("utf-8", "replace")
    out, cur = [], {}
    for line in text.splitlines() + [""]:
        if not line.strip():
            if cur:
                out.append(cur)
            cur = {}
            continue
        key, _, val = line.partition(" ")
        cur[key] = val if val else True
    rootn = os.path.normcase(str(Path(root).resolve()))
    return [w for w in out if os.path.normcase(str(Path(w.get("worktree", "")).resolve())) != rootn]


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def walk_disk(root: Path, prune_rel: set[str]) -> list[str]:
    """Every regular file under root as a posix relative path, never entering the
    root `.git/` or a pruned (linked worktree) directory."""
    found = []
    for d, dirs, files in os.walk(root):
        rel_d = os.path.relpath(d, root).replace("\\", "/")
        rel_d = "" if rel_d == "." else rel_d
        keep = []
        for name in dirs:
            child = f"{rel_d}/{name}" if rel_d else name
            if (not rel_d and name == ".git") or child in prune_rel:
                continue
            keep.append(name)
        dirs[:] = keep
        for name in files:
            found.append(f"{rel_d}/{name}" if rel_d else name)
    return found


def classify(path: str, status: str) -> str | None:
    """The bulk class id of a unit, or None for a row-by-row file."""
    if status == "W":
        return "worktrees"
    parts = path.split("/")
    if "__pycache__" in parts or path.endswith((".pyc", ".pyo")):
        return "pycache"
    if ".ruff_cache" in parts or ".pytest_cache" in parts:
        return "toolcache"
    if "node_modules" in parts:
        return "node_modules"
    if path.startswith("web/data/ddragon/"):
        return "ddragon-web"
    if path.startswith("data/meta_build/"):
        return "meta-build"
    if path.startswith("ops/runtime/responder_export/"):
        return "responder-export"
    if path.startswith("python-embed/"):
        return "python-embed"
    if path.startswith("moon_sync_inbox/"):
        return "inbox"
    return None


def last_commit_dates(root: Path = ROOT) -> dict[str, str]:
    """path -> date (YYYY-MM-DD) of the newest commit touching it, one log pass."""
    raw = _git_bytes("log", "--format=%x01%cs", "--name-only", "-z", cwd=root)
    dates: dict[str, str] = {}
    current = ""
    for chunk in raw.decode("utf-8", "replace").split("\0"):
        for piece in chunk.split("\n"):
            piece = piece.strip()
            if not piece:
                continue
            if piece.startswith("\x01"):
                current = piece[1:]
                continue
            dates.setdefault(piece, current)
    return dates


def ref_counts(root: Path, tracked: list[str], names: dict[str, set[str]]) -> dict[str, int]:
    """For each wanted path, how many OTHER tracked text files mention its basename
    (or its module stem). `names` maps path -> the token set that counts as a
    mention. A hint for the reviewer, never a verdict."""
    wanted: dict[str, set[str]] = collections.defaultdict(set)
    for path, toks in names.items():
        for t in toks:
            wanted[t].add(path)
    hits: dict[str, set[str]] = collections.defaultdict(set)
    for rel in tracked:
        if Path(rel).suffix.lower() not in TEXT_EXT:
            continue
        p = root / rel
        try:
            if p.stat().st_size > REF_SCAN_MAX_BYTES:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        toks = set()
        for m in _TOKEN.findall(text):
            toks.add(m)
            if "." in m:
                toks.update(x for x in m.split(".") if x)
        for t in toks & wanted.keys():
            for target in wanted[t]:
                if target != rel:
                    hits[target].add(rel)
    return {path: len(hits.get(path, ())) for path in names}


def mention_tokens(path: str) -> set[str]:
    name = path.rstrip("/").rsplit("/", 1)[-1]
    toks = {name, name.lstrip(".")} - {""}
    stem, dot, ext = name.rpartition(".")
    if dot and stem and len(stem) >= 4 and ("." + ext.lower()) in {".py", ".ps1", ".js", ".md", ".bat"}:
        toks.add(stem)
    return toks


def build_manifest(root: Path = ROOT) -> dict:
    """The frozen universe: rows + the reconciliation numbers."""
    root = Path(root)
    tracked = _git_z("ls-files", "-z", cwd=root)
    ignored = set(_git_z("ls-files", "-z", "--others", "--ignored", "--exclude-standard", cwd=root))
    untracked = set(_git_z("ls-files", "-z", "--others", "--exclude-standard", cwd=root))
    ignored_dirs = tuple(p for p in ignored if p.endswith("/"))
    wts = []
    rootr = root.resolve()
    for w in linked_worktrees(root):
        wp = Path(w["worktree"]).resolve()
        try:
            rel = wp.relative_to(rootr).as_posix()
        except ValueError:
            continue  # outside the root: the outside-repo inventory, not a unit here
        wts.append((rel, w))
    prune = {rel for rel, _ in wts}
    try:  # the review's own staging dir is its output, not its subject
        prune.add(Path(STAGE).resolve().relative_to(rootr).as_posix())
    except ValueError:
        pass
    disk = walk_disk(root, prune)
    tracked_set = set(tracked)
    rows = []
    leftovers = []
    for rel in disk:
        if rel in tracked_set:
            st = "T"
        elif rel in ignored or any(rel.startswith(d) for d in ignored_dirs if rel[:1] == d[:1]):
            st = "I"
        elif rel in untracked:
            st = "U"
        else:
            st = "?"
            leftovers.append(rel)
        rows.append({"p": rel, "st": st})
    if leftovers:
        # `git check-ignore` answers the few files git never listed itself.
        proc = subprocess.run(["git", "check-ignore", "--no-index", "--stdin", "-z"],
                              cwd=str(root), input="\0".join(leftovers).encode("utf-8"),
                              capture_output=True, timeout=300, creationflags=_NO_WINDOW)
        ign = {p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p}
        for r in rows:
            if r["st"] == "?":
                r["st"] = "I" if r["p"] in ign else "U"
    dates = last_commit_dates(root)
    for r in rows:
        try:
            s = (root / r["p"]).stat()
            r["sz"] = s.st_size
            r["mt"] = time.strftime("%Y-%m-%d", time.localtime(s.st_mtime))
        except OSError:
            r["sz"], r["mt"] = None, ""
        r["lc"] = dates.get(r["p"], "") if r["st"] == "T" else ""
        r["cls"] = classify(r["p"], r["st"])
    for rel, w in wts:
        rows.append({"p": rel + "/", "st": "W", "sz": None, "mt": "", "lc": "",
                     "cls": "worktrees", "branch": str(w.get("branch", "")),
                     "head": str(w.get("HEAD", ""))[:12], "locked": bool(w.get("locked"))})
    per_file = {r["p"]: mention_tokens(r["p"]) for r in rows if r["cls"] is None}
    refs = ref_counts(root, tracked, per_file)
    for r in rows:
        r["refs"] = refs.get(r["p"]) if r["cls"] is None else None
    rows.sort(key=lambda r: r["p"])
    missing = sorted(tracked_set - set(disk))
    return {
        "rows": rows,
        "counts": {
            "disk_units": len(rows),
            "disk_files": len(disk),
            "worktree_units": len(wts),
            "tracked_index": len(tracked),
            "tracked_on_disk": sum(1 for r in rows if r["st"] == "T"),
            "tracked_missing_on_disk": len(missing),
            "ignored": sum(1 for r in rows if r["st"] == "I"),
            "untracked": sum(1 for r in rows if r["st"] == "U"),
            "git_ignored_entries": len(ignored),
            "git_untracked_entries": len(untracked),
        },
        "tracked_missing": missing[:200],
    }


# ---------------------------------------------------------------- batches

def weight(path: str) -> float:
    return 1.0 if Path(path).suffix.lower() in CODE_EXT else 0.35


def _group_key(path: str, big_tops: set[str]) -> str:
    parts = path.split("/")
    if len(parts) == 1:
        return "<root>"
    if parts[0] in big_tops and len(parts) > 2:
        return "/".join(parts[:2])
    return parts[0]


def plan_batches(rows: list[dict], cap: float = BATCH_WEIGHT_CAP) -> list[dict]:
    """Class batches first (one per present class), then the MD-core batch, then
    row-by-row batches packed folder by folder up to `cap` weight. Every row lands
    in exactly one batch."""
    batches: list[dict] = []
    by_cls: dict[str, list[str]] = collections.defaultdict(list)
    md_core: list[str] = []
    rest: list[str] = []
    core = set(MD_CORE)
    for r in rows:
        if r["cls"]:
            by_cls[r["cls"]].append(r["p"])
        elif r["p"] in core:
            md_core.append(r["p"])
        else:
            rest.append(r["p"])
    n = 0
    for cid, title, _note in CLASSES:
        if by_cls.get(cid):
            n += 1
            batches.append({"id": f"C{n:02d}", "kind": "class", "cls": cid, "title": title,
                            "paths": sorted(by_cls[cid])})
    if md_core:
        batches.append({"id": "MD01", "kind": "mdcore",
                        "title": "Core .md set, hand-off and memory recall",
                        "paths": sorted(md_core)})
    top_weight: dict[str, float] = collections.Counter()
    for p in rest:
        top_weight[p.split("/")[0] if "/" in p else "<root>"] += weight(p)
    big = {t for t, w in top_weight.items() if w > cap}
    groups: dict[str, list[str]] = collections.defaultdict(list)
    for p in sorted(rest):
        groups[_group_key(p, big)].append(p)
    cur: list[str] = []
    cur_w = 0.0
    cur_groups: list[str] = []
    k = 0

    def flush():
        nonlocal cur, cur_w, cur_groups, k
        if cur:
            k += 1
            batches.append({"id": f"B{k:02d}", "kind": "files",
                            "title": ", ".join(cur_groups[:6]) + (" ..." if len(cur_groups) > 6 else ""),
                            "paths": cur})
        cur, cur_w, cur_groups = [], 0.0, []

    for g in sorted(groups):
        items = groups[g]
        gw = sum(weight(p) for p in items)
        if cur and cur_w + gw > cap:
            flush()
        if gw <= cap:
            cur.extend(items)
            cur_w += gw
            cur_groups.append(g)
            continue
        for p in items:  # a group larger than the cap is chunked
            w = weight(p)
            if cur and cur_w + w > cap:
                flush()
            if not cur_groups or cur_groups[-1] != g:
                cur_groups.append(g)
            cur.append(p)
            cur_w += w
    flush()
    return batches


# ---------------------------------------------------------------- prompts

def _human(n: int | None) -> str:
    if n is None:
        return "-"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024.0
    return str(n)


def _sample(paths: list[str], n: int = SAMPLE_N) -> list[str]:
    if len(paths) <= n:
        return list(paths)
    step = len(paths) / float(n)
    return [paths[int(i * step)] for i in range(n)]


def class_facts(cid: str, rows: list[dict], root: Path = ROOT) -> list[str]:
    """Measured facts for one bulk class (lines of text for the prompt)."""
    paths = sorted(r["p"] for r in rows)
    sizes = [r.get("sz") or 0 for r in rows]
    dates = sorted(r.get("mt") or "" for r in rows if r.get("mt"))
    st = collections.Counter(r["st"] for r in rows)
    ext = collections.Counter(Path(p.rstrip("/")).suffix.lower() or "<none>" for p in paths)
    folders = collections.Counter("/".join(p.split("/")[:3]) for p in paths)
    lines = [f"units: {len(rows)} (status {dict(st)}), bytes {_human(sum(sizes))}",
             f"mtime range: {dates[0] if dates else '-'} .. {dates[-1] if dates else '-'}",
             "extensions: " + ", ".join(f"{e}={c}" for e, c in ext.most_common(12)),
             "top folders: " + ", ".join(f"{f}={c}" for f, c in folders.most_common(15))]
    if cid == "pycache":
        orphans = []
        for p in paths:
            parts = p.split("/")
            if "__pycache__" not in parts or not p.endswith(".pyc"):
                continue
            i = parts.index("__pycache__")
            src_name = parts[-1].split(".")[0] + ".py"
            src = "/".join(parts[:i] + [src_name])
            if not (root / src).exists():
                orphans.append(p)
        lines.append(f"computed: {len(orphans)} orphan .pyc whose source .py is gone; "
                     f"sample: {', '.join(_sample(orphans, 25))}")
    elif cid == "worktrees":
        for r in rows:
            lines.append(f"worktree {r['p']} branch={r.get('branch', '')} head={r.get('head', '')} "
                         f"locked={r.get('locked')}")
    elif cid == "node_modules":
        pkgs = {"/".join(p.split("/")[:p.split("/").index("node_modules") + 2]) for p in paths}
        lines.append(f"computed: {len(pkgs)} package folders directly under node_modules")
    elif cid == "responder-export":
        exports = collections.Counter(p.split("/")[3] for p in paths if len(p.split("/")) > 3)
        lines.append(f"computed: {len(exports)} export folders: "
                     + ", ".join(f"{e}={c}" for e, c in sorted(exports.items())[:40]))
    elif cid in ("ddragon-web", "meta-build"):
        depth = 4 if cid == "ddragon-web" else 4
        vers = collections.Counter("/".join(p.split("/")[:depth]) for p in paths)
        lines.append("computed versions: " + ", ".join(f"{v}={c}" for v, c in sorted(vers.items())))
    elif cid == "inbox":
        tops = collections.Counter("/".join(p.split("/")[:2]) for p in paths)
        lines.append(f"computed: {len(tops)} top-level inbox entries (full list follows)")
        lines.extend(f"  {t} ({c} file{'s' if c != 1 else ''})" for t, c in sorted(tops.items()))
    return lines


_RULES = """\
You are a READ-ONLY reviewer in RC's headless full-tree repo review (MAIN ORDER
2026-10-08 2246 section 8, operator order S7). Repo root: the current working
directory. Batch {bid} of {total}: {title}.

RULES FOR THIS RUN
- Read-only. Use only Read, Grep and Glob. Every writer, shell, agent and web
  tool is denied; do not try them. The CLAUDE.md sub-agent-first rule, session
  checklist and /done ritual bind interactive sessions, NOT this run: do not
  print a checklist, do not dispatch.
- Your FINAL message is ONE JSON object and nothing else (no prose, no code
  fence), schema below. ASCII only.
- Never write a machine name, account or user name, email, IP address, token,
  key, or a sibling repository name or path into the output. Name a leak by
  CLASS and file:line only. Channel codes (MAIN, SS, ...) are fine. Write a
  user-profile path as %USERPROFILE%\\...
- Never quote a channel note body; name files only.

REVIEW TOPICS (order section 8): H folder hierarchy and organisation;
M memory recall (memory files, hand-off, what a fresh session must read);
D dated files that can move to an archive or be pruned (Recycle Bin only; name
the consumer you checked); P pins and leaves; W worktrees; S scratch;
O orphans; T stale files; X files living outside the repo / consolidation into
ONE sidecar folder <sidecar-root>\\RC (LIST moves, never do them; write the
root as <sidecar-root>, never a drive letter); MD refactor /
clean / audit of the .md set (CLAUDE.md outside its pinned FLEET-COMMON block);
I:<topic> any topic you infer on the way (mark it inferred).

KNOWN FINDINGS (sections 2, 3, 5, 6 of the order). Do NOT re-derive them. If a
file in your batch is one of them, set "proposed" to "KNOWN:<id>":
{known}

METHOD
- Account for EVERY unit in your batch. A unit not named in a finding counts
  as reviewed-clean, so look before you let one pass.
- Use the metadata: st (T tracked / I ignored / U untracked / W worktree),
  size, mtime date, lc (date of the newest commit touching it), refs (how many
  OTHER tracked text files mention its name or module stem - a HINT; 0 means
  orphan candidate: confirm with Grep before calling anything an orphan).
- Open the head of every file whose path, size, date or refs hint a problem,
  and of every .md / config / script whose role you cannot tell from its path.
- Prefer FEW, well-grouped findings: one finding may name many paths.
- "proposed": FILE (needs a fix: give a testable acceptance), NA (recorded, no
  action needed), or KNOWN:<id>. "gated": none | irreversible | operator |
  out-of-tree | frozen (frozen files per CLAUDE.md need operator approval).

OUTPUT SCHEMA (exactly these keys)
{{"batch": "{bid}", "manifest_count": <int: units you were given>,
 "reviewed_clean_count": <int: units named in no finding>,
 "folders": [{{"folder": "<path>", "verdict": "<one line>"}}],
 "findings": [{{"sev": "high|med|low|info", "topic": "H|M|D|P|W|S|O|T|X|MD|I:<name>",
   "paths": ["<rel/path or rel/path:line>"], "finding": "<one or two sentences>",
   "action": "<proposed fix, one sentence>", "verify": "<what you read or grepped>",
   "proposed": "FILE|NA|KNOWN:<id>", "gated": "none|irreversible|operator|out-of-tree|frozen",
   "acceptance": "<testable acceptance, FILE only, else empty>"}}]}}
"""


def build_prompt(batch: dict, rows_by_path: dict[str, dict], total: int,
                 root: Path = ROOT) -> str:
    known = "\n".join(f"  {kid}: {text}" for kid, text in KNOWN_FINDINGS)
    head = _RULES.format(bid=batch["id"], total=total, title=batch["title"], known=known)
    rows = [rows_by_path[p] for p in batch["paths"]]
    if batch["kind"] == "class":
        note = next(n for c, _t, n in CLASSES if c == batch["cls"])
        facts = class_facts(batch["cls"], rows, root)
        body = [f"THIS BATCH IS ONE BULK CLASS: {batch['cls']} - {len(rows)} units.",
                f"Class note: {note}",
                "Review the class as a whole (location, ignore rules, retention, consumers,",
                "size, prune / archive / sidecar candidates) and Glob / Read the sample.",
                "Your verdict covers every unit of the class; manifest_count = "
                f"{len(rows)}.", "", "MEASURED FACTS:"]
        body += [f"- {line}" for line in facts]
        body += ["", f"DETERMINISTIC SAMPLE ({min(len(rows), SAMPLE_N)} paths):"]
        body += [f"  {p}" for p in _sample(sorted(batch["paths"]))]
        return head + "\n" + "\n".join(body) + "\n"
    body = []
    if batch["kind"] == "mdcore":
        body += ["THIS BATCH IS THE CORE .md SET. Focus: the .md refactor topic (roadmap,",
                 "backlog, CLAUDE.md outside the FLEET-COMMON block, architecture, api,",
                 "agents, ledgers, operations), memory recall (what a fresh session must",
                 "read; the bootstrap size), duplication and drift between these docs.",
                 "These files are large: read headings and sample sections, do not read",
                 "every line. The account memory index lives OUTSIDE the repo under",
                 "%USERPROFILE%\\.claude-acct2\\projects\\ (read-only, Glob it).", ""]
    body += [f"MANIFEST ({len(rows)} units). Columns: path | st | size | mtime | lc | refs"]
    for r in rows:
        refs = "-" if r.get("refs") is None else str(r["refs"])
        body.append(f"{r['p']} | {r['st']} | {_human(r.get('sz'))} | {r.get('mt') or '-'} | "
                    f"{r.get('lc') or '-'} | {refs}")
    return head + "\n" + "\n".join(body) + "\n"


# ---------------------------------------------------------------- results

def parse_answer(text: str | None, batch: dict) -> tuple[dict | None, str | None]:
    """The reviewer's JSON, validated. Returns (doc, None) or (None, reason)."""
    if not text or not text.strip():
        return None, "empty answer"
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        s = s[s.find("{"):] if "{" in s else s
    try:
        doc = json.loads(s)
    except ValueError:
        i, j = s.find("{"), s.rfind("}")
        if i < 0 or j <= i:
            return None, "no JSON object"
        try:
            doc = json.loads(s[i:j + 1])
        except ValueError:
            return None, "malformed JSON"
    if not isinstance(doc, dict):
        return None, "answer is not an object"
    if doc.get("batch") != batch["id"]:
        return None, f"batch id {doc.get('batch')!r} != {batch['id']}"
    want = len(batch["paths"])
    if doc.get("manifest_count") != want:
        return None, f"manifest_count {doc.get('manifest_count')!r} != {want}"
    findings = doc.get("findings")
    if not isinstance(findings, list):
        return None, "findings is not a list"
    clean = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        f = {k: f.get(k) for k in ("sev", "topic", "paths", "finding", "action", "verify",
                                   "proposed", "gated", "acceptance")}
        if f["sev"] not in SEVERITIES:
            f["sev"] = "info"
        if not isinstance(f["paths"], list):
            f["paths"] = [str(f["paths"])] if f["paths"] else []
        prop = str(f["proposed"] or "NA")
        if prop not in PROPOSED and not prop.startswith("KNOWN:"):
            prop = "FILE" if f.get("acceptance") else "NA"
        f["proposed"] = prop
        clean.append(f)
    doc["findings"] = clean
    if not isinstance(doc.get("folders"), list):
        doc["folders"] = []
    return doc, None


# ---------------------------------------------------------------- run

class Halt(Exception):
    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code
        self.reason = reason


def _result_path(bid: str) -> Path:
    return FINDINGS / f"{bid}.json"


def batch_done(bid: str) -> bool:
    try:
        doc = json.loads(_result_path(bid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return doc.get("status") == "ok"


def _spawn(prompt: str, bid: str, timeout: float = RUN_TIMEOUT_S):
    """ONE read-only reviewer run through fleet_route (the kit). Raises Halt on a
    route or kit refusal: the driver fails closed, it never falls back."""
    fr = _fleet_route()
    try:
        line, proc = fr.spawn(prompt, caller=CALLER, note=f"repo-review-{bid}",
                              writes_code=False, bare=False, kind=KIND,
                              extra=list(READ_ONLY_EXTRA), prompt_on_stdin=True,
                              timeout=timeout, cwd=ROOT)
    except fr.RouteRefused as exc:
        raise Halt(getattr(exc, "code", None) or "refused", str(exc)) from None
    except subprocess.TimeoutExpired:
        return {"rc": None, "error": "timeout"}, None
    return line, proc


class Runner:
    def __init__(self, batches: list[dict], rows_by_path: dict[str, dict],
                 parallel: int = DEFAULT_PARALLEL, max_runs: int = DEFAULT_MAX_RUNS,
                 spawn=None, clock=time.time, root: Path = ROOT):
        self.batches = batches
        self.rows_by_path = rows_by_path
        self.parallel = max(1, int(parallel))
        self.max_runs = int(max_runs)
        self.spawn = spawn or _spawn
        self.clock = clock
        self.root = root
        self.runs = 0
        self.durations: list[float] = []
        self.halt: Halt | None = None
        self.started = clock()

    def pending(self) -> list[dict]:
        return [b for b in self.batches if not batch_done(b["id"])]

    def progress(self, step: str, status: str = "running", reason: str | None = None) -> None:
        total = len(self.batches)
        left = self.pending()
        done = total - len(left)
        avg = (sum(self.durations) / len(self.durations)) if self.durations else 600.0
        eta = int(avg * len(left) / self.parallel) if left else 0
        rows = [{"id": b["id"], "task": f"review {b['title']}"[:120],
                 "state": "pending", "eta_s": int(avg)} for b in left[:19]]
        if status == "running":
            rows.append({"id": "compile", "task": "compile findings and reconcile counts",
                         "state": "pending", "eta_s": None})
        try:
            _kit().write_progress(self.root, TASK, 100 * done / total if total else 100,
                                  step, eta, status, checklist=rows, reason=reason)
        except (OSError, ValueError) as exc:
            _say(f"progress write failed: {exc}")

    def _take_run(self) -> bool:
        with _state_lock:
            if self.halt is not None:
                return False
            if os.path.lexists(STOP_FILE):
                self.halt = Halt("stop-file", "REPO_REVIEW_STOP present")
                return False
            if self.runs >= self.max_runs:
                self.halt = Halt("run-cap", f"driver run cap {self.max_runs} reached")
                return False
            self.runs += 1
            return True

    def run_batch(self, batch: dict) -> str:
        bid = batch["id"]
        prompt = build_prompt(batch, self.rows_by_path, len(self.batches), self.root)
        _atomic_write(PROMPTS / f"{bid}.txt", prompt)
        reason = "not run"
        for attempt in range(1 + RETRIES):
            if not self._take_run():
                return "halted"
            t0 = self.clock()
            try:
                line, proc = self.spawn(prompt, bid)
            except Halt as h:
                with _state_lock:
                    self.halt = self.halt or h
                _say(f"{bid} REFUSED ({h.code}): {h.reason}")
                return "halted"
            dt = self.clock() - t0
            text = (line or {}).get("result")
            if text is None and proc is not None:
                text = getattr(proc, "stdout", None)
            _atomic_write(RAW / f"{bid}.a{attempt}.out.txt", text or "")
            doc, reason = parse_answer(text, batch)
            if (line or {}).get("error"):
                reason = f"run error {line.get('error')}" + (f"; {reason}" if reason else "")
                doc = None if line.get("error") == "timeout" else doc
            meta = {"batch": bid, "attempt": attempt, "duration_s": round(dt, 1),
                    "rc": (line or {}).get("rc"), "cost_usd": (line or {}).get("cost_usd"),
                    "model": (line or {}).get("model"), "units": len(batch["paths"]),
                    "kind": batch["kind"], "title": batch["title"]}
            if doc is not None:
                with _state_lock:
                    self.durations.append(dt)
                _atomic_write(_result_path(bid), json.dumps(
                    dict(meta, status="ok", answer=doc), indent=1, ensure_ascii=True))
                _say(f"{bid} ok in {dt:.0f}s: {len(doc['findings'])} findings")
                return "ok"
            _say(f"{bid} attempt {attempt} rejected: {reason}")
            _atomic_write(_result_path(bid), json.dumps(
                dict(meta, status="failed", reason=reason), indent=1, ensure_ascii=True))
        return "failed"

    def run(self, only: set[str] | None = None) -> int:
        todo = [b for b in self.pending() if not only or b["id"] in only]
        if self.spawn is _spawn:
            _fleet_route()  # load the door once, before any worker thread races for it
        _say(f"run: {len(todo)} batches to review, parallel {self.parallel}, cap {self.max_runs}")
        self.progress(f"starting: {len(todo)} batches pending")
        failed = 0
        with cf.ThreadPoolExecutor(max_workers=self.parallel) as pool:
            futs = {pool.submit(self.run_batch, b): b for b in todo}
            for fut in cf.as_completed(futs):
                b = futs[fut]
                try:
                    res = fut.result()
                except Exception as exc:  # noqa: BLE001 - one batch never kills the run
                    res = "failed"
                    _say(f"{b['id']} crashed: {exc.__class__.__name__}: {exc}")
                failed += res == "failed"
                self.progress(f"{b['id']} {res} ({len(self.batches) - len(self.pending())}"
                              f"/{len(self.batches)} batches, {self.runs} runs)")
        if self.halt is not None:
            status = "blocked" if self.halt.code not in ("stop-file", "run-cap") else "failed"
            self.progress(f"HALTED: {self.halt.code}", status=status, reason=self.halt.reason)
            _say(f"halted: {self.halt.code} {self.halt.reason}")
            return 3 if status == "blocked" else 2
        left = [b for b in self.pending() if not only or b["id"] in only]
        if left:
            self.progress(f"{len(left)} batches failed after retry", status="failed",
                          reason="failed batches remain")
            return 1
        if self.pending():
            self.progress(f"selected batches reviewed; {len(self.pending())} not selected remain")
            return 0
        self.progress("all batches reviewed; compile next", status="done")
        return 0


# ---------------------------------------------------------------- compile

def load_manifest() -> list[dict]:
    with MANIFEST.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_batches() -> list[dict]:
    return json.loads(BATCHES.read_text(encoding="utf-8"))["batches"]


def _stage_rel() -> str | None:
    try:
        return Path(STAGE).resolve().relative_to(Path(ROOT).resolve()).as_posix()
    except ValueError:
        return None


def compile_summary(rows: list[dict], batches: list[dict]) -> dict:
    """Coverage + findings. A row marked gone (deleted since it was measured) or
    excluded (the review's own staging output) is reported, not counted."""
    dropped = collections.Counter("gone" if r.get("gone") else "excluded"
                                  for r in rows if r.get("gone") or r.get("excluded"))
    rows = [r for r in rows if not r.get("gone") and not r.get("excluded")]
    reviewed: set[str] = set()
    findings = []
    batch_state = {}
    for b in batches:
        try:
            doc = json.loads(_result_path(b["id"]).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = {"status": "missing"}
        batch_state[b["id"]] = doc.get("status")
        if doc.get("status") != "ok":
            continue
        reviewed.update(b["paths"])
        for i, f in enumerate(doc["answer"]["findings"], 1):
            findings.append(dict(f, id=f"{b['id']}-{i:02d}", batch=b["id"]))
    tops = collections.defaultdict(lambda: {"units": 0, "reviewed": 0})
    for r in rows:
        top = r["p"].split("/")[0] if "/" in r["p"] else "<root files>"
        tops[top]["units"] += 1
        tops[top]["reviewed"] += r["p"] in reviewed
    return {"units": len(rows), "reviewed": len(reviewed & {r["p"] for r in rows}),
            "gone": dropped["gone"], "excluded": dropped["excluded"],
            "batches": batch_state, "tops": dict(sorted(tops.items())),
            "findings": findings,
            "severity": dict(collections.Counter(f["sev"] for f in findings)),
            "proposed": dict(collections.Counter(f["proposed"].split(":")[0] for f in findings))}


# ---------------------------------------------------------------- CLI

def cmd_enumerate() -> int:
    t0 = time.time()
    man = build_manifest(ROOT)
    rows = man["rows"]
    batches = plan_batches(rows)
    STAGE.mkdir(parents=True, exist_ok=True)
    _atomic_write(MANIFEST, "".join(json.dumps(r, ensure_ascii=True) + "\n" for r in rows))
    _atomic_write(BATCHES, json.dumps({"taken": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                       "counts": man["counts"],
                                       "tracked_missing": man["tracked_missing"],
                                       "batches": batches}, indent=1, ensure_ascii=True))
    c = man["counts"]
    _say(f"enumerate: {c['disk_units']} units ({c['tracked_on_disk']} tracked, {c['ignored']} "
         f"ignored, {c['untracked']} untracked, {c['worktree_units']} worktree units); "
         f"{len(batches)} batches; {time.time() - t0:.0f}s")
    return 0


def cmd_run(args) -> int:
    rows = load_manifest()
    batches = load_batches()
    only = set(args.only.split(",")) if args.only else None
    by_path = {r["p"]: r for r in rows}
    if args.dry_run:
        for b in batches:
            if only and b["id"] not in only:
                continue
            p = build_prompt(b, by_path, len(batches), ROOT)
            _say(f"{b['id']} {b['kind']} units={len(b['paths'])} prompt_chars={len(p)} {b['title']}")
        return 0
    return Runner(batches, by_path, parallel=args.parallel, max_runs=args.max_runs).run(only)


def cmd_delta() -> int:
    """Re-measure the disk; batch every unit that appeared since `enumerate`."""
    old = load_manifest()
    old_paths = {r["p"] for r in old}
    man = build_manifest(ROOT)
    now = {r["p"]: r for r in man["rows"]}
    new_rows = [r for r in man["rows"] if r["p"] not in old_paths]
    stage_rel = _stage_rel()
    gone = []
    for r in old:
        if r["p"] in now:
            r.pop("gone", None)
            if now[r["p"]]["st"] != r["st"]:
                r["st_now"] = now[r["p"]]["st"]
        elif stage_rel and r["p"].startswith(stage_rel + "/"):
            r["excluded"] = "review-output"
        else:
            r["gone"] = True
            gone.append(r["p"])
    data = json.loads(BATCHES.read_text(encoding="utf-8"))
    batches = data["batches"]
    n = sum(1 for b in batches if b["id"].startswith("D")) + 1
    added = []
    if new_rows:
        # the delta is reviewed row by row, packed like the main plan
        for b in plan_batches(new_rows, cap=BATCH_WEIGHT_CAP * 3):
            b["id"] = f"D{n:02d}"
            b["title"] = "delta since enumerate: " + b["title"]
            b["kind"] = "files" if b["kind"] != "class" else "class"
            n += 1
            added.append(b)
    for r in new_rows:
        r["delta"] = True
    _atomic_write(MANIFEST, "".join(json.dumps(r, ensure_ascii=True) + "\n"
                                    for r in sorted(old + new_rows, key=lambda r: r["p"])))
    data["batches"] = batches + added
    data.setdefault("deltas", []).append({
        "taken": time.strftime("%Y-%m-%dT%H:%M:%S"), "new": len(new_rows),
        "batches": [b["id"] for b in added], "gone": len(gone), "gone_sample": gone[:50],
        "counts_now": man["counts"]})
    _atomic_write(BATCHES, json.dumps(data, indent=1, ensure_ascii=True))
    _say(f"delta: {len(new_rows)} new units in {len(added)} batches; {len(gone)} gone; "
         f"disk now {man['counts']['disk_units']} units")
    return 0


def cmd_compile() -> int:
    summary = compile_summary(load_manifest(), load_batches())
    _atomic_write(SUMMARY, json.dumps(summary, indent=1, ensure_ascii=True))
    _say(f"compile: {summary['reviewed']}/{summary['units']} units reviewed; "
         f"{len(summary['findings'])} findings {summary['severity']} {summary['proposed']}")
    return 0 if summary["reviewed"] == summary["units"] else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="repo_review", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("enumerate")
    r = sub.add_parser("run")
    r.add_argument("--parallel", type=int, default=DEFAULT_PARALLEL)
    r.add_argument("--max-runs", type=int, default=DEFAULT_MAX_RUNS)
    r.add_argument("--only", default="")
    r.add_argument("--dry-run", action="store_true")
    sub.add_parser("delta")
    sub.add_parser("compile")
    args = ap.parse_args(argv)
    if args.cmd == "enumerate":
        return cmd_enumerate()
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "delta":
        return cmd_delta()
    return cmd_compile()


if __name__ == "__main__":
    raise SystemExit(main())
