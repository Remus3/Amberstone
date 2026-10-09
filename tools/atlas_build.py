"""Generate the data regions of ``atlas.html`` from the repository itself.

Why this exists
---------------
atlas.html used to carry its whole dataset as hand-typed JS literals: a CATS
map, a NODES array, an EDG string, a DUST string and a HUD block. Nothing
re-derived them, so the page drifted. MAIN measured it on 2026-10-08: 591 of
926 modules missing, 14 entries for deleted files, and a HUD commit count weeks
stale. This script replaces every one of those literals with data derived from
the repository, the same way ``tools/gen_archmap.py`` owns the module map in
docs/ARCHITECTURE.md.

What is derived, and from where
-------------------------------
* files - every TRACKED source module (CODE_EXTS) outside test trees,
  enumerated from the git index through ``tests/_repo_walk`` (ADR-015). The
  index is the authority; ``EXCLUDED_DIRS`` is the backstop.
* nodes - one per directory that holds modules. A directory with SPLIT_AT or
  more modules is split into ``dir/<prefix>_*`` families of GROUP_MIN or more
  files sharing a leading name token; the rest stay on the directory node.
* categories - first-match path-prefix rules (CATEGORIES below). Each is drawn
  in a fleet-kit chart token from ops/fleet_kit/tokens.css, so the page has no
  palette of its own.
* edges - real structure only: Python ``import`` statements (parsed with ast)
  and relative JS ``import`` / ``require`` specifiers, folded to node pairs and
  capped at EDGE_TOP per node, plus the directory containment tree (weight 0).
* descriptions - the first sentence of each module docstring, else its
  ``# arch:`` role, else its leading comment. ASCII-folded, then drive paths,
  home directories and non-loopback IPv4 addresses are redacted, because the
  page is served publicly.
* HUD - ENGINE_VERSION, the DS patch, the counts above, and a build stamp:
  the HEAD short sha, its commit date and the commit count at that sha.
* snapshots - the dashboard frames under atlas/snapshots/, labelled from
  atlas/snapshots/index.json. The page links them; it no longer inlines them.
* fonts - every inlined @font-face face is carried as WOFF 1.0 and audited
  with the standard library: a face that presents a Reserved Font Name it
  declares must rebuild to a pinned unmodified upstream file (SIL OFL-1.1
  condition 3), and the comment beside the faces (region ``fontnotice``)
  quotes each face's own copyright line and licence URL. See the fonts
  section below.

Determinism
-----------
The output is a pure function of the tracked file list, the file contents and
the stamp. No wall clock, no filesystem order, no randomness. ``--check``
re-renders with the stamp already in the page, so a new commit does not by
itself make the page stale; adding, removing or renaming a module, changing an
import or a docstring, or bumping ENGINE_VERSION does.

Usage
-----
    python tools/atlas_build.py            # rewrite atlas.html in place (atomic)
    python tools/atlas_build.py --check    # exit 1 if atlas.html is stale
"""
from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import html
import importlib.util
import json
import posixpath
import re
import struct
import subprocess
import sys
import unicodedata
import zlib
from collections import Counter, defaultdict
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, NamedTuple

REPO_ROOT = Path(__file__).resolve().parent.parent
ATLAS_NAME = "atlas.html"
SNAPSHOT_DIR = "atlas/snapshots"
SNAPSHOT_INDEX = SNAPSHOT_DIR + "/index.json"
GENERATOR = "tools/atlas_build.py"
SCHEMA = 1

CODE_EXTS = (".py", ".js", ".mjs", ".cjs", ".ps1")
SPLIT_AT = 24        # a directory with this many modules is split into families
GROUP_MIN = 4        # a family needs this many files to become its own node
EDGE_TOP = 3         # import edges kept per node (strongest first)
DESC_MAX = 140       # characters kept from a description
MIN_REPO_MODULES = 100  # the real repo below this means the walk collapsed

# (key, display name, fleet-kit token, path prefixes). First match wins; the
# last row's empty prefix catches everything else (ops/, app/, root files).
CATEGORIES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("engine", "DS Engine", "--fk-chart-1", ("agents/daemon_slayer/",)),
    ("core", "Core", "--fk-chart-2", ("core/", "lib/", "modules/", "oss/")),
    ("coaching", "Coaching", "--fk-chart-3", (
        "coaches/", "coach_integration/", "modes/", "tft/", "game_reader/",
        "lcu/", "vision_server/")),
    ("dashboard", "Dashboard", "--fk-chart-4", ("dashboard/", "web/", "mc/")),
    ("shell", "Desktop shell", "--fk-chart-5", ("rc-shell/", "lane-widget/")),
    ("agents", "Agents", "--fk-chart-6", ("agents/",)),
    ("tools", "Tools", "--fk-chart-7", ("tools/", "scripts/", "docs/")),
    ("ops", "App and ops", "--fk-chart-8", ("",)),
)

ROOT_NODE = "(root)"

_TEST_DIRS = frozenset({"tests", "test", "__tests__"})
_TEST_FILE = re.compile(
    r"(^test_.*\.py$|_test\.py$|^conftest\.py$|\.(test|spec)\.[cm]?js$)")


class BuildError(RuntimeError):
    """The build refuses rather than emit a page it cannot stand behind."""


# --------------------------------------------------------------------------
# repo enumeration (ADR-015: tests/_repo_walk is the one walker)
# --------------------------------------------------------------------------

_WALK: ModuleType | None = None


def _repo_walk() -> ModuleType:
    global _WALK
    if _WALK is None:
        path = REPO_ROOT / "tests" / "_repo_walk.py"
        spec = importlib.util.spec_from_file_location("_atlas_repo_walk", path)
        if spec is None or spec.loader is None:
            raise BuildError(f"cannot load {path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _WALK = mod
    return _WALK


def is_test_path(rel: str) -> bool:
    parts = rel.split("/")
    if any(p in _TEST_DIRS for p in parts[:-1]):
        return True
    return bool(_TEST_FILE.search(parts[-1]))


def collect_modules(root: Path, min_modules: int = 0) -> list[str]:
    """Sorted forward-slash paths of every tracked, non-test source module."""
    walk = _repo_walk()
    base = Path(root).resolve()
    tracked = walk.tracked_relpaths(str(base))
    if tracked is None:
        raise BuildError(
            f"git index unreadable under {base.name}; the atlas maps tracked "
            "files only and will not guess from the disk")
    out = []
    for rel in tracked:
        if walk.is_excluded(rel) or not rel.endswith(CODE_EXTS):
            continue
        if is_test_path(rel) or not (base / rel).is_file():
            continue
        out.append(rel)
    out.sort()
    if len(out) < min_modules:
        raise BuildError(
            f"only {len(out)} modules found (floor {min_modules}); an empty map "
            "and a clean repo look the same, so the walk is treated as broken")
    return out


# --------------------------------------------------------------------------
# text: ASCII fold, redaction, one-sentence summaries
# --------------------------------------------------------------------------

_FOLD = {
    0x2014: " - ", 0x2013: "-", 0x2012: "-", 0x2010: "-", 0x2011: "-",
    0x2212: "-", 0x2018: "'", 0x2019: "'", 0x201A: "'", 0x201C: '"',
    0x201D: '"', 0x2026: "...", 0x2192: "->", 0x2190: "<-", 0x2194: "<->",
    0x21D2: "=>", 0x00D7: "x", 0x2264: "<=", 0x2265: ">=", 0x2260: "!=",
    0x2248: "~", 0x00A0: " ", 0x2022: "-", 0x00B7: "-", 0x2032: "'",
    0x00B0: " deg", 0x2713: "ok", 0x2714: "ok", 0x2717: "x", 0x2718: "x",
}
_DRIVE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s'\"`)<>]*")
_UNC = re.compile(r"\\\\[^\s'\"`)<>]+")
_HOMEDIR = re.compile(r"(?<![\w.])/(?:Users|home)/[^\s'\"`)<>]*")
_IPV4 = re.compile(r"(?<![\d.])\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?![\d.])")
_LOOPBACK = frozenset({"127.0.0.1", "0.0.0.0"})
_BOM = chr(0xFEFF)
_SENTENCE_END = re.compile(r"(?<=[a-z0-9)\]'\"`][.!?])\s")
_NOT_AN_END = ("e.g.", "i.e.", "vs.", "etc.", "approx.", "cf.")


def ascii_fold(text: str) -> str:
    text = text.translate(_FOLD)
    text = unicodedata.normalize("NFKD", text)
    return text.encode("ascii", "ignore").decode("ascii")


def redact(text: str) -> str:
    text = _DRIVE.sub("<path>", text)
    text = _UNC.sub("<path>", text)
    text = _HOMEDIR.sub("<path>", text)
    return _IPV4.sub(
        lambda m: m.group(0) if m.group(0) in _LOOPBACK else "<ip>", text)


def summarize(text: str | None) -> str:
    """First sentence of the first paragraph, ASCII-only, redacted, bounded."""
    if not text:
        return ""
    text = ascii_fold(text).strip()
    para = re.split(r"\n\s*\n", text, maxsplit=1)[0]
    para = " ".join(para.split())
    para = para.replace("``", "").replace("**", "")
    para = redact(para)
    for m in _SENTENCE_END.finditer(para):
        if m.start() > DESC_MAX:
            break
        if para[: m.start()].endswith(_NOT_AN_END):
            continue
        para = para[: m.start()]
        break
    if len(para) > DESC_MAX:
        cut = para.rfind(" ", 0, DESC_MAX - 3)
        para = para[: cut if cut > 40 else DESC_MAX - 3].rstrip(" ,;:-") + "..."
    return para


# --------------------------------------------------------------------------
# per-file facts: description + outgoing dependencies
# --------------------------------------------------------------------------

_ARCH = re.compile(r"^#\s*arch:\s*([^|]+?)\s*(?:\|.*)?$")
_PY_SKIP = re.compile(
    r"^#\s*(!|-\*-|coding[:=]|noqa|type:|pylint|ruff|mypy|fmt:|SPDX|"
    r"Copyright|arch:|flake8|pragma)", re.I)
_JS_SKIP = re.compile(
    r"^(eslint|global |jshint|@ts-|prettier|istanbul|#!|use strict)", re.I)
_JS_SPEC = re.compile(
    r"""(?:\bfrom\s*|\bimport\s*\(?\s*|\brequire\s*\(\s*)['"](\.{1,2}/[^'"]+)['"]""")


def _read(root: Path, rel: str) -> str:
    # LF-normalised and BOM-stripped, so a CRLF checkout builds the same page.
    raw = (root / rel).read_bytes()
    text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
    return text.lstrip(_BOM)


def _py_leading_comment(src: str) -> str:
    lines = []
    for i, line in enumerate(src.split("\n")[:12]):
        s = line.strip()
        if not s:
            if lines:
                break
            continue
        if not s.startswith("#"):
            break
        m = _ARCH.match(s)
        if m and i < 8 and not m.group(1).startswith("phase "):
            return m.group(1)
        if _PY_SKIP.match(s):
            continue
        lines.append(s.lstrip("#").strip())
    return " ".join(lines)


def py_description(src: str, tree: ast.Module | None) -> str:
    doc = ast.get_docstring(tree, clean=True) if tree is not None else None
    if doc and doc.strip():
        return summarize(doc)
    return summarize(_py_leading_comment(src))


def _comment_body(src: str) -> str:
    s = src.lstrip()
    if s.startswith("#!"):
        s = s.split("\n", 1)[1].lstrip() if "\n" in s else ""
    lines: list[str] = []
    if s.startswith("/*"):
        end = s.find("*/")
        body = s[2:end if end >= 0 else len(s)]
        for line in body.split("\n"):
            lines.append(line.strip().lstrip("*").strip())
    else:
        for line in s.split("\n"):
            t = line.strip()
            if not t.startswith("//"):
                break
            lines.append(t[2:].strip())
    kept = []
    for t in lines:
        if _JS_SKIP.match(t):
            continue
        if t.startswith("@"):
            tag, _, rest = t.partition(" ")
            if tag in ("@file", "@fileoverview", "@module", "@description"):
                t = rest
            else:
                continue
        kept.append(t)
    return "\n".join(kept)


def js_description(src: str) -> str:
    return summarize(_comment_body(src))


def ps1_description(src: str) -> str:
    s = src.lstrip(_BOM).lstrip()
    if s.startswith("<#"):
        end = s.find("#>")
        body = s[2:end if end >= 0 else len(s)]
        m = re.search(r"^\s*\.SYNOPSIS\s*\n(.*?)(?=^\s*\.[A-Z]+\s*$|\Z)",
                      body, re.S | re.M)
        if m:
            return summarize(m.group(1))
        body = re.sub(r"^\s*\.[A-Z]+.*$", "", body, flags=re.M)
        return summarize(body)
    lines = []
    for line in s.split("\n"):
        t = line.strip()
        if not t.startswith("#"):
            break
        if t.lower().startswith("#requires"):
            continue
        lines.append(t.lstrip("#").strip())
    return summarize(" ".join(lines))


def _py_package(rel: str) -> list[str]:
    parts = rel[:-3].split("/")
    if parts[-1] == "__init__":
        return parts[:-1]
    return parts[:-1]


def py_module_names(rel: str) -> list[str]:
    parts = rel[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    names = [".".join(parts)] if parts else []
    if "src" in parts[:-1]:
        i = parts.index("src")
        if parts[i + 1:]:
            names.append(".".join(parts[i + 1:]))
    return names


def py_import_targets(tree: ast.Module, rel: str) -> list[tuple[str, tuple[str, ...]]]:
    pkg = _py_package(rel)
    out: list[tuple[str, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append((alias.name, ()))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                drop = node.level - 1
                if drop > len(pkg):
                    continue
                base = pkg[: len(pkg) - drop]
                mod = ".".join(base + ([node.module] if node.module else []))
            else:
                mod = node.module or ""
            if mod or node.level:
                out.append((mod, tuple(a.name for a in node.names)))
    return out


def resolve_py(targets: Iterable[tuple[str, tuple[str, ...]]], rel: str,
               by_name: dict[str, str]) -> set[str]:
    here = "/".join(rel.split("/")[:-1]).replace("/", ".")
    found: set[str] = set()

    def lookup(name: str) -> str | None:
        if not name:
            return None
        hit = by_name.get(name)
        if hit is None and here:
            # scripts run with their own directory on sys.path
            hit = by_name.get(here + "." + name)
        return hit

    for mod, names in targets:
        hits = [lookup(mod + "." + n if mod else n) for n in names if n != "*"]
        hits = [h for h in hits if h]
        if not hits:
            parts = mod.split(".") if mod else []
            while parts:
                h = lookup(".".join(parts))
                if h:
                    hits = [h]
                    break
                parts.pop()
        found.update(hits)
    found.discard(rel)
    return found


def resolve_js(src: str, rel: str, modules: set[str]) -> set[str]:
    here = posixpath.dirname(rel)
    found: set[str] = set()
    for spec in _JS_SPEC.findall(src):
        spec = spec.split("?", 1)[0].split("#", 1)[0]
        base = posixpath.normpath(posixpath.join(here, spec))
        for cand in (base, base + ".js", base + ".mjs", base + ".cjs",
                     base + "/index.js"):
            if cand in modules:
                found.add(cand)
                break
    found.discard(rel)
    return found


def strip_self_name(desc: str, rel: str) -> str:
    """Drop a leading self-reference ("core/x.py - ...", "core.x: ...")."""
    names = {rel, posixpath.basename(rel)}
    if rel.endswith(".py"):
        names.update(py_module_names(rel))
    for name in sorted(names, key=len, reverse=True):
        if desc.startswith(name):
            rest = desc[len(name):]
            if not rest or rest[0] in " :-,(":
                rest = rest.lstrip(" :-,")
                if rest.startswith("("):
                    break
                return rest[:1].upper() + rest[1:] if rest else ""
    return desc


def scan_files(root: Path, modules: list[str]) -> tuple[dict[str, str], dict[str, set[str]], dict[str, int]]:
    """Return (description, dependencies, LF line count) per module."""
    module_set = set(modules)
    by_name: dict[str, str] = {}
    for rel in modules:
        if rel.endswith(".py"):
            for name in py_module_names(rel):
                by_name.setdefault(name, rel)
    descs: dict[str, str] = {}
    deps: dict[str, set[str]] = {}
    lines: dict[str, int] = {}
    for rel in modules:
        src = _read(root, rel)
        lines[rel] = src.count("\n") + (0 if src.endswith("\n") or not src else 1)
        if rel.endswith(".py"):
            try:
                tree: ast.Module | None = ast.parse(src)
            except (SyntaxError, ValueError):
                tree = None
            descs[rel] = py_description(src, tree)
            deps[rel] = (resolve_py(py_import_targets(tree, rel), rel, by_name)
                         if tree is not None else set())
        elif rel.endswith(".ps1"):
            descs[rel] = ps1_description(src)
            deps[rel] = set()
        else:
            descs[rel] = js_description(src)
            deps[rel] = resolve_js(src, rel, module_set)
        descs[rel] = strip_self_name(descs[rel], rel)
    return descs, deps, lines


# --------------------------------------------------------------------------
# structure: nodes, categories, edges
# --------------------------------------------------------------------------

def category_of(path: str) -> str:
    probe = path if path.endswith("/") or path == "" else path + "/"
    for key, _name, _token, prefixes in CATEGORIES:
        if any(probe.startswith(p) for p in prefixes):
            return key
    return CATEGORIES[-1][0]


def _family_token(name: str) -> str:
    stem = name.rsplit(".", 1)[0].lstrip("_")
    return re.split(r"[_\-.]", stem, maxsplit=1)[0].lower()


def assign_nodes(modules: list[str]) -> dict[str, str]:
    """Map each module to its node id (``dir/``, ``dir/<token>_*`` or root)."""
    by_dir: dict[str, list[str]] = defaultdict(list)
    for rel in modules:
        by_dir[posixpath.dirname(rel)].append(rel)
    node_of: dict[str, str] = {}
    for d in sorted(by_dir):
        files = by_dir[d]
        dir_id = d + "/" if d else ROOT_NODE
        families: dict[str, str] = {}
        if len(files) >= SPLIT_AT:
            counts = Counter(_family_token(posixpath.basename(f)) for f in files)
            for tok, n in counts.items():
                if n >= GROUP_MIN and tok:
                    families[tok] = (d + "/" if d else "") + tok + "_*"
        for f in files:
            node_of[f] = families.get(_family_token(posixpath.basename(f)), dir_id)
    return node_of


def _node_dir(node_id: str) -> str:
    if node_id == ROOT_NODE:
        return ""
    if node_id.endswith("_*"):
        return posixpath.dirname(node_id)
    return node_id.rstrip("/")


def _weight(n_files: int) -> int:
    return 1 if n_files < 5 else (2 if n_files < 20 else 3)


def _dir_desc(d: str, files: list[str], descs: dict[str, str],
              lines: dict[str, int]) -> str:
    # Only tracked inputs: a package docstring, never an on-disk README that
    # may be untracked on one machine and absent on the next.
    init = (d + "/" if d else "") + "__init__.py"
    pkg = descs.get(init, "")
    largest = sorted(files, key=lambda f: (-lines[f], f))[:3]
    names = ", ".join(posixpath.basename(f) for f in largest)
    head = f"{len(files)} source file{'s' if len(files) != 1 else ''}"
    tail = f" Largest: {names}." if names else ""
    if pkg:
        return f"{pkg.rstrip('.')}. {head}.{tail}"
    return f"{head} in {d + '/' if d else 'the repository root'}.{tail}"


def build_structure(root: Path, modules: list[str]) -> dict[str, Any]:
    descs, deps, lines = scan_files(root, modules)
    node_of = assign_nodes(modules)
    members: dict[str, list[str]] = defaultdict(list)
    for rel in modules:
        members[node_of[rel]].append(rel)

    cat_order = {c[0]: i for i, c in enumerate(CATEGORIES)}
    node_ids = sorted(members, key=lambda n: (cat_order[category_of(_node_dir(n))], n))
    index = {nid: i for i, nid in enumerate(node_ids)}

    nodes = []
    for nid in node_ids:
        files = members[nid]
        d = _node_dir(nid)
        if nid.endswith("_*"):
            tok = nid.rsplit("/", 1)[-1][:-2]
            largest = sorted(files, key=lambda f: (-lines[f], f))[:3]
            names = ", ".join(posixpath.basename(f) for f in largest)
            desc = (f"{len(files)} modules named {tok}_* in {d}/. Largest: {names}.")
        else:
            desc = _dir_desc(d, files, descs, lines)
        nodes.append({
            "id": nid,
            "label": nid,
            "cat": category_of(d),
            "w": _weight(len(files)),
            "files": len(files),
            "desc": desc,
        })

    # import edges, folded to node pairs
    pair_w: Counter[tuple[int, int]] = Counter()
    for rel in modules:
        a = index[node_of[rel]]
        for dst in deps[rel]:
            b = index[node_of[dst]]
            if a != b:
                pair_w[(min(a, b), max(a, b))] += 1
    incident: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for (a, b), w in pair_w.items():
        incident[a].append((w, b))
        incident[b].append((w, a))
    keep: set[tuple[int, int]] = set()
    for a, lst in incident.items():
        for w, b in sorted(lst, key=lambda t: (-t[0], node_ids[t[1]]))[:EDGE_TOP]:
            keep.add((min(a, b), max(a, b)))
    edges = [[a, b, pair_w[(a, b)]] for a, b in sorted(keep)]

    # containment tree: each node hangs off its nearest ancestor directory
    # node. Top-level directories get no parent - hanging them all off the
    # root node would draw a star that says nothing.
    dir_nodes = {_node_dir(n): index[n] for n in node_ids if not n.endswith("_*")}
    tree: set[tuple[int, int]] = set()
    for nid in node_ids:
        me = index[nid]
        d = _node_dir(nid)
        if nid.endswith("_*"):
            probe = d
        elif d:
            probe = posixpath.dirname(d)
        else:
            continue
        while probe:
            parent = dir_nodes.get(probe)
            if parent is not None and parent != me:
                pair = (min(parent, me), max(parent, me))
                if pair not in keep:
                    tree.add(pair)
                break
            probe = posixpath.dirname(probe)
    edges += [[a, b, 0] for a, b in sorted(tree)]
    edges.sort()

    files_out = [[rel, index[node_of[rel]], descs[rel]] for rel in modules]
    return {"nodes": nodes, "files": files_out, "edges": edges}


# --------------------------------------------------------------------------
# facts, stamp, snapshots
# --------------------------------------------------------------------------

def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(root), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=120)
    if proc.returncode != 0:
        raise BuildError(f"git {' '.join(args)} failed: {proc.stderr.strip()[:200]}")
    return proc.stdout.strip()


def read_stamp(root: Path) -> dict[str, Any]:
    return {
        "commit": _git(root, "rev-parse", "--short=9", "HEAD"),
        "date": _git(root, "log", "-1", "--format=%cs", "HEAD"),
        "commits": int(_git(root, "rev-list", "--count", "HEAD")),
    }


def read_facts(root: Path) -> dict[str, str | None]:
    engine = patch = None
    init = root / "agents" / "daemon_slayer" / "__init__.py"
    if init.is_file():
        m = re.search(r'^ENGINE_VERSION\s*=\s*"([^"]+)"',
                      init.read_text(encoding="utf-8"), re.M)
        engine = m.group(1) if m else None
    cur = root / "data" / "daemon_slayer" / "current.txt"
    if cur.is_file():
        patch = cur.read_text(encoding="utf-8").strip() or None
    return {"engine": engine, "patch": patch}


def read_snapshots(root: Path) -> list[dict[str, str]]:
    snap_dir = root / SNAPSHOT_DIR
    if not snap_dir.is_dir():
        return []
    labels: dict[str, str] = {}
    index = root / SNAPSHOT_INDEX
    order: list[str] = []
    if index.is_file():
        for row in json.loads(index.read_text(encoding="utf-8")):
            labels[row["file"]] = ascii_fold(row["label"])
            order.append(row["file"])
    present = sorted(p.name for p in snap_dir.iterdir()
                     if p.suffix.lower() in (".webp", ".png", ".jpg", ".jpeg"))
    missing = [f for f in order if f not in present]
    if missing:
        raise BuildError(f"{SNAPSHOT_INDEX} names missing files: {missing}")
    names = order + [f for f in present if f not in labels]
    out = []
    for name in names:
        label = labels.get(name) or re.sub(r"^\d+[-_]", "", name.rsplit(".", 1)[0]).replace("-", " ").title()
        out.append({"label": label, "src": SNAPSHOT_DIR + "/" + name})
    return out


# --------------------------------------------------------------------------
# fonts: the inlined @font-face faces (SIL Open Font License 1.1)
# --------------------------------------------------------------------------
#
# The page inlines its web fonts as data: URIs. Every face is carried as WOFF
# 1.0 (zlib per table), the one compressed font container the standard
# library can open, so this build and its tests read each face's name table
# without fontTools or brotli. A WOFF2 face is refused, never guessed at.
#
# A face already in WOFF form is validated and passed through byte for byte,
# so a re-run is identical whatever zlib the interpreter links. A raw
# TrueType / OpenType face is wrapped once, "WOFF compression only" in the
# sense of OFL FAQ 2.2.1: table data, table checksums and the physical table
# order are kept, and there is no WOFF metadata or private block, so
# ``to_sfnt`` rebuilds the original font file byte for byte.
#
# Reserved Font Names (OFL condition 3): a face whose family or PostScript
# names carry an RFN its own name table declares is accepted only when the
# sfnt it rebuilds to is a pinned, unmodified upstream file
# (UNMODIFIED_RFN_FONTS). A subset or any other Modified Version that kept an
# RFN is refused. Adjudicated 2026-10-09 (slice W-L): embed the unmodified
# upstream Orbitron rather than rename the Google subset.

_SFNT_FLAVORS = (0x00010000, 0x4F54544F, 0x74727565)  # TrueType, 'OTTO', 'true'
_WOFF_SIG = 0x774F4646   # 'wOFF'
_WOFF2_SIG = 0x774F4632  # 'wOF2'
_WOFF_HEADER = struct.Struct(">LLLHHLHHLLLLL")  # 44 bytes
_WOFF_ENTRY = struct.Struct(">4sLLLL")          # 20 bytes per table
_SFNT_ENTRY = struct.Struct(">4sLLL")           # 16 bytes per table
FONT_MIME = "font/woff"
FONT_FORMAT = "woff"

# sha256 of the rebuilt sfnt -> where that exact file is published upstream.
UNMODIFIED_RFN_FONTS: dict[str, str] = {
    "f42db2dd16e642258e35782916eceb1dcdbea06fb958d77ad71dc5963587e8fd":
        "Orbitron[wght].ttf v2.001, 38576 bytes, google/fonts "
        "ofl/orbitron at abf71245949027c279caff7c2cb988c97e7d0b11",
}


class Sfnt(NamedTuple):
    """An OpenType font: flavor word, tables, directory checksums, data order.

    A NamedTuple, not a dataclass: the tests load this file by path without
    registering it in sys.modules, which a dataclass with postponed
    annotations cannot survive."""
    flavor: int
    tables: dict[str, bytes]
    checksums: dict[str, int]
    order: tuple[str, ...]


def _pad4(n: int) -> int:
    return (n + 3) & ~3


def table_checksum(data: bytes, tag: str = "") -> int:
    """OpenType table checksum; ``head`` is summed with checkSumAdjustment zeroed."""
    if tag == "head" and len(data) >= 12:
        data = data[:8] + b"\0\0\0\0" + data[12:]
    data += b"\0" * (_pad4(len(data)) - len(data))
    return sum(struct.unpack(f">{len(data) // 4}L", data)) & 0xFFFFFFFF


def _read_sfnt(data: bytes) -> Sfnt:
    flavor, num = struct.unpack_from(">LH", data)
    if len(data) < 12 + _SFNT_ENTRY.size * num:
        raise BuildError("sfnt table directory is truncated")
    tables: dict[str, bytes] = {}
    sums: dict[str, int] = {}
    offsets: dict[str, int] = {}
    for i in range(num):
        tag_b, csum, off, length = _SFNT_ENTRY.unpack_from(data, 12 + _SFNT_ENTRY.size * i)
        tag = tag_b.decode("latin-1")
        if off + length > len(data):
            raise BuildError(f"sfnt table {tag!r} runs past the end of the font")
        tables[tag] = data[off:off + length]
        sums[tag] = csum
        offsets[tag] = off
    return Sfnt(flavor, tables, sums, tuple(sorted(tables, key=lambda t: (offsets[t], t))))


def to_sfnt(font: Sfnt) -> bytes:
    """The TrueType / OpenType file a WOFF decoder rebuilds from ``font``."""
    n = len(font.tables)
    power = 1 << (n.bit_length() - 1) if n else 0
    search = power * 16
    header = struct.pack(">LHHHH", font.flavor, n, search,
                         power.bit_length() - 1 if n else 0, n * 16 - search)
    offset = 12 + _SFNT_ENTRY.size * n
    where: dict[str, int] = {}
    body: list[bytes] = []
    for tag in font.order:
        data = font.tables[tag]
        where[tag] = offset
        body.append(data + b"\0" * (_pad4(len(data)) - len(data)))
        offset += _pad4(len(data))
    entries = [_SFNT_ENTRY.pack(tag.encode("latin-1"), font.checksums[tag], where[tag],
                                len(font.tables[tag])) for tag in sorted(font.tables)]
    return header + b"".join(entries) + b"".join(body)


def _read_woff(data: bytes) -> Sfnt:
    if len(data) < _WOFF_HEADER.size:
        raise BuildError("WOFF header is truncated")
    (_sig, flavor, length, num, reserved, total_sfnt, _major, _minor,
     meta_off, meta_len, meta_orig, priv_off, priv_len) = _WOFF_HEADER.unpack_from(data)
    if length != len(data):
        raise BuildError("WOFF length field does not match the data")
    if reserved:
        raise BuildError("WOFF reserved field is not zero")
    if meta_off or meta_len or meta_orig or priv_off or priv_len:
        raise BuildError("WOFF metadata and private blocks are not carried by this page")
    if len(data) < _WOFF_HEADER.size + _WOFF_ENTRY.size * num:
        raise BuildError("WOFF table directory is truncated")
    tables: dict[str, bytes] = {}
    sums: dict[str, int] = {}
    offsets: dict[str, int] = {}
    expect_total = 12 + 16 * num
    for i in range(num):
        tag_b, off, comp, orig, csum = _WOFF_ENTRY.unpack_from(
            data, _WOFF_HEADER.size + _WOFF_ENTRY.size * i)
        tag = tag_b.decode("latin-1")
        if off % 4 or off + comp > len(data) or comp > orig:
            raise BuildError(f"WOFF table {tag!r} has a bad offset or length")
        blob = data[off:off + comp]
        if comp < orig:
            try:
                blob = zlib.decompress(blob)
            except zlib.error as exc:
                raise BuildError(f"WOFF table {tag!r} does not inflate: {exc}") from exc
        if len(blob) != orig:
            raise BuildError(f"WOFF table {tag!r} inflates to the wrong length")
        if csum not in (table_checksum(blob, tag), table_checksum(blob)):
            raise BuildError(f"WOFF table {tag!r} fails its checksum")
        tables[tag] = blob
        sums[tag] = csum
        offsets[tag] = off
        expect_total += _pad4(orig)
    if total_sfnt != expect_total:
        raise BuildError("WOFF totalSfntSize does not match its tables")
    return Sfnt(flavor, tables, sums, tuple(sorted(tables, key=lambda t: (offsets[t], t))))


def read_font(data: bytes) -> Sfnt:
    """Open a raw TrueType / OpenType font or a WOFF 1.0 wrapper; refuse WOFF2."""
    if len(data) < 12:
        raise BuildError("font data is truncated")
    sig = struct.unpack_from(">L", data)[0]
    if sig == _WOFF_SIG:
        return _read_woff(data)
    if sig in _SFNT_FLAVORS:
        return _read_sfnt(data)
    if sig == _WOFF2_SIG:
        raise BuildError(
            "a WOFF2 face cannot be audited by the standard library; inline it as "
            "TTF (fontTools: f = TTFont(path); f.flavor = None; f.save(out)) and re-run")
    raise BuildError(f"unknown font signature 0x{sig:08x}")


def encode_woff(font: Sfnt) -> bytes:
    """WOFF 1.0 of ``font``: directory in tag order, data in the font's own
    physical order, original checksums, zlib per table where it is smaller,
    no metadata or private block."""
    n = len(font.tables)
    head = font.tables.get("head", b"")
    major, minor = struct.unpack_from(">HH", head, 4) if len(head) >= 8 else (0, 0)
    offset = _WOFF_HEADER.size + _WOFF_ENTRY.size * n
    total_sfnt = 12 + 16 * n
    where: dict[str, tuple[int, int]] = {}
    blobs: list[bytes] = []
    for tag in font.order:
        raw = font.tables[tag]
        packed = zlib.compress(raw, 9)
        blob = packed if len(packed) < len(raw) else raw
        where[tag] = (offset, len(blob))
        blob += b"\0" * (_pad4(len(blob)) - len(blob))
        blobs.append(blob)
        offset += len(blob)
        total_sfnt += _pad4(len(raw))
    entries = [_WOFF_ENTRY.pack(tag.encode("latin-1"), where[tag][0], where[tag][1],
                                len(font.tables[tag]), font.checksums[tag])
               for tag in sorted(font.tables)]
    header = _WOFF_HEADER.pack(_WOFF_SIG, font.flavor, offset, n, 0, total_sfnt,
                               major, minor, 0, 0, 0, 0, 0)
    return header + b"".join(entries) + b"".join(blobs)


def sfnt_sha256(font: Sfnt) -> str:
    return hashlib.sha256(to_sfnt(font)).hexdigest()


def name_records(font: Sfnt) -> list[tuple[int, int, int, int, str]]:
    """(platform, encoding, language, nameID, text) for every name record."""
    data = font.tables.get("name")
    if not data or len(data) < 6:
        return []
    _fmt, count, str_off = struct.unpack_from(">HHH", data)
    out = []
    for i in range(count):
        if 6 + 12 * (i + 1) > len(data):
            raise BuildError("name table record array is truncated")
        pid, eid, lid, nid, length, off = struct.unpack_from(">6H", data, 6 + 12 * i)
        raw = data[str_off + off:str_off + off + length]
        codec = "utf-16-be" if pid in (0, 3) else "latin-1"
        out.append((pid, eid, lid, nid, raw.decode(codec, errors="replace")))
    return out


def name_text(font: Sfnt, name_id: int) -> str:
    """The Windows English (else first) string for ``name_id``; "" if absent."""
    recs = [r for r in name_records(font) if r[3] == name_id]
    recs.sort(key=lambda r: (r[0] != 3, r[2] != 0x409, r[:3]))
    return recs[0][4] if recs else ""


# nameIDs that present the font to a user or a font menu: family (1), unique
# id (3), full name (4), PostScript name (6), typographic family and
# subfamily (16, 17), compatible full (18), WWS family and subfamily (21, 22),
# variations PostScript prefix (25). fvar instance PostScript names are added
# per font.
FAMILY_NAME_IDS = frozenset({1, 3, 4, 6, 16, 17, 18, 21, 22, 25})
# Curly quotes are built with chr() to keep this source 7-bit ASCII.
_LQ, _RQ, _LSQ, _RSQ = chr(0x201C), chr(0x201D), chr(0x2018), chr(0x2019)
_QUOTED = re.compile(
    rf"\"([^\"]+)\"|'([^']+)'|{_LQ}([^{_RQ}]+){_RQ}|{_LSQ}([^{_RSQ}]+){_RSQ}")
_QUOTE_CHARS = "\"'" + _LQ + _RQ + _LSQ + _RSQ
_RFN_CLAUSE = re.compile(
    r"Reserved\s+Font\s+Names?\s*:?\s*"
    rf"((?:(?:{_QUOTED.pattern})(?:\s*(?:,|and|&)\s*)?)+|[^.,;{_QUOTE_CHARS}]+)", re.I)

# RFNs known from the upstream OFL.txt headers of the fonts this page has
# carried. A face is checked against these as well as against what its own
# name table declares, so a copy whose RFN clause was edited out of nameID 0
# is still caught.
KNOWN_RFNS: tuple[str, ...] = ("Orbitron",)


def _fvar_ps_name_ids(font: Sfnt) -> set[int]:
    data = font.tables.get("fvar")
    if not data or len(data) < 16:
        return set()
    (_maj, _min, axes_off, _res, axis_count, axis_size,
     inst_count, inst_size) = struct.unpack_from(">8H", data)
    if inst_size < 6 + 4 * axis_count:
        return set()
    base = axes_off + axis_count * axis_size
    out = set()
    for i in range(inst_count):
        at = base + i * inst_size + 4 + 4 * axis_count
        if at + 2 > len(data):
            raise BuildError("fvar instance array is truncated")
        ps_id = struct.unpack_from(">H", data, at)[0]
        if ps_id != 0xFFFF:
            out.add(ps_id)
    return out


def declared_rfns(font: Sfnt) -> list[str]:
    """Reserved Font Names declared in the copyright (0) or licence (13) strings."""
    found: list[str] = []
    for _p, _e, _l, nid, text in name_records(font):
        if nid not in (0, 13):
            continue
        for m in _RFN_CLAUSE.finditer(text):
            clause = m.group(1)
            quoted = [next(g for g in q.groups() if g) for q in _QUOTED.finditer(clause)]
            for name in quoted or [clause]:
                name = name.strip().strip(_QUOTE_CHARS).strip()
                if name and name not in found:
                    found.append(name)
    return found


def family_names(font: Sfnt) -> list[tuple[int, str]]:
    """Sorted distinct (nameID, text) pairs that name the family to a user."""
    ids = FAMILY_NAME_IDS | _fvar_ps_name_ids(font)
    return sorted({(r[3], r[4]) for r in name_records(font) if r[3] in ids})


def rfn_family_hits(font: Sfnt) -> list[tuple[int, str, str]]:
    """(nameID, text, RFN) for every family name that carries an RFN the
    face declares or one listed in KNOWN_RFNS."""
    hits = []
    rfns = declared_rfns(font)
    rfns += [r for r in KNOWN_RFNS if r not in rfns]
    for rfn in rfns:
        forms = {rfn.lower(), rfn.replace(" ", "").lower()}
        for nid, text in family_names(font):
            if any(f in text.lower() for f in forms):
                hits.append((nid, text, rfn))
    return hits


_FONT_FACE = re.compile(r"@font-face\s*\{[^{}]*\}")
_FACE_SRC = re.compile(
    r"url\(data:([\w.+/-]+);base64,([A-Za-z0-9+/=]+)\)(?:\s*format\(['\"]?[\w-]+['\"]?\))?")
_FACE_FAMILY = re.compile(r"font-family\s*:\s*(['\"]?)([^;'\"]+?)\1\s*;")
_FACE_WEIGHT = re.compile(r"font-weight\s*:\s*([^;]+?)\s*;")


def _b64decode(text: str) -> bytes:
    try:
        return base64.b64decode(text, validate=True)
    except ValueError as exc:
        raise BuildError(f"an @font-face data: URI is not valid base64: {exc}") from exc


def embedded_faces(page: str) -> list[dict[str, Any]]:
    """Every @font-face with a data: source: CSS family, weight, mime, bytes."""
    out = []
    for block in _FONT_FACE.findall(page):
        src = _FACE_SRC.search(block)
        if src is None:
            continue
        fam = _FACE_FAMILY.search(block)
        weight = _FACE_WEIGHT.search(block)
        out.append({
            "family": fam.group(2).strip() if fam else "",
            "weight": weight.group(1) if weight else "",
            "mime": src.group(1),
            "data": _b64decode(src.group(2)),
        })
    return out


def check_reserved_names(font: Sfnt, label: str) -> None:
    """Refuse a Modified Version that still presents a declared RFN."""
    hits = rfn_family_hits(font)
    if hits and sfnt_sha256(font) not in UNMODIFIED_RFN_FONTS:
        nid, text, rfn = hits[0]
        raise BuildError(
            f"{label}: name {nid} {text!r} carries the Reserved Font Name {rfn!r} "
            "but the face is not a pinned unmodified upstream file "
            "(UNMODIFIED_RFN_FONTS); OFL-1.1 condition 3 forbids an RFN on a "
            "Modified Version - embed the unmodified file or rename the family")


def render_fonts(page: str) -> str:
    """Carry every inlined face as WOFF 1.0 and enforce the RFN rule."""
    def fix(m: re.Match[str]) -> str:
        block = m.group(0)
        src = _FACE_SRC.search(block)
        if src is None:
            return block
        fam = _FACE_FAMILY.search(block)
        weight = _FACE_WEIGHT.search(block)
        label = (f"@font-face {fam.group(2).strip() if fam else '?'} "
                 f"{weight.group(1) if weight else '?'}")
        data = _b64decode(src.group(2))
        font = read_font(data)
        if struct.unpack_from(">L", data)[0] != _WOFF_SIG:
            data = encode_woff(font)
        check_reserved_names(font, label)
        url = (f"url(data:{FONT_MIME};base64,{base64.b64encode(data).decode('ascii')})"
               f" format('{FONT_FORMAT}')")
        return block[:src.start()] + url + block[src.end():]
    return _FONT_FACE.sub(fix, page)


def _comment_safe(text: str) -> str:
    # Copyright lines are quoted as the font states them: ASCII-folded for the
    # page's 7-bit rule, never redacted, and unable to close the comment.
    return ascii_fold(text).replace("*/", "* /").strip()


def render_font_notice(page: str) -> str:
    """The CSS comment that travels with the faces: per family, what the
    face is, its copyright line(s) read from its own name table (nameID 0),
    and its licence, so a copy of the page on its own still carries them."""
    families: dict[str, dict[str, Any]] = {}
    for face in embedded_faces(page):
        font = read_font(face["data"])
        row = families.setdefault(face["family"], {
            "weights": [], "copyright": [], "urls": [], "kinds": []})
        if face["weight"] not in row["weights"]:
            row["weights"].append(face["weight"])
        for key, value in (("copyright", name_text(font, 0)),
                           ("urls", name_text(font, 14))):
            if value and _comment_safe(value) not in row[key]:
                row[key].append(_comment_safe(value))
        sha = sfnt_sha256(font)
        if sha in UNMODIFIED_RFN_FONTS:
            kind = ("unmodified upstream file, WOFF 1.0 wrapper only: "
                    + UNMODIFIED_RFN_FONTS[sha])
        elif declared_rfns(font):
            kind = "Modified Version, renamed away from its Reserved Font Name"
        else:
            kind = "Modified Version (subset); declares no Reserved Font Name"
        if kind not in row["kinds"]:
            row["kinds"].append(kind)
    if not families:
        return ""
    lines = [
        "/* Inlined fonts. Each is under the SIL Open Font License, Version 1.1",
        "   (SPDX OFL-1.1), not the Apache License of this page. Full licence",
        "   text: LICENSES/OFL-1.1.txt in the repository beside this page.",
    ]
    for family, row in families.items():
        weights = ", ".join(w.replace(" ", "-") for w in row["weights"] if w)
        lines.append(f"   {_comment_safe(family)}"
                     + (f" (weights {weights})" if weights else "") + ":")
        lines += [f"     {k}." if not k.endswith(".") else f"     {k}" for k in row["kinds"]]
        lines += [f"     {c}" for c in row["copyright"]]
        lines += [f"     Licence URL in the font: {u}" for u in row["urls"]]
    lines[-1] += " */"
    return "\n".join(lines)


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def _j(obj: Any) -> str:
    text = json.dumps(obj, ensure_ascii=True, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def build_model(root: Path, stamp: dict[str, Any] | None = None,
                min_modules: int = 0) -> dict[str, Any]:
    root = Path(root).resolve()
    modules = collect_modules(root, min_modules=min_modules)
    structure = build_structure(root, modules)
    return {
        "schema": SCHEMA,
        "generator": GENERATOR,
        "stamp": stamp if stamp is not None else read_stamp(root),
        "facts": read_facts(root),
        "categories": [{"key": k, "name": n, "token": t} for k, n, t, _p in CATEGORIES],
        "nodes": structure["nodes"],
        "files": structure["files"],
        "edges": structure["edges"],
        "snapshots": read_snapshots(root),
    }


def render_data(model: dict[str, Any]) -> str:
    out = ["window.ATLAS_DATA={"]
    for key in ("schema", "generator", "stamp", "facts"):
        out.append(f'"{key}":{_j(model[key])},')
    for key in ("categories", "nodes", "files", "edges", "snapshots"):
        rows = model[key]
        out.append(f'"{key}":[')
        for i, row in enumerate(rows):
            out.append(_j(row) + ("," if i < len(rows) - 1 else ""))
        out.append("]" + ("," if key != "snapshots" else ""))
    out.append("};")
    return "\n".join(out)


def parse_data(page: str) -> dict[str, Any]:
    """Inverse of render_data for a page: the embedded model."""
    body = _region(page, "data", js=True)
    body = body.strip()
    prefix = "window.ATLAS_DATA="
    if not body.startswith(prefix) or not body.endswith(";"):
        raise BuildError("data region is not a window.ATLAS_DATA assignment")
    return json.loads(body[len(prefix):-1])


def _counts(model: dict[str, Any]) -> dict[str, int]:
    edges = model["edges"]
    return {
        "nodes": len(model["nodes"]),
        "files": len(model["files"]),
        "cats": len(model["categories"]),
        "imports": sum(1 for e in edges if e[2] > 0),
        "tree": sum(1 for e in edges if e[2] == 0),
    }


def render_text(model: dict[str, Any]) -> dict[str, str]:
    c = _counts(model)
    st = model["stamp"]
    facts = model["facts"]
    engine = facts.get("engine") or "n/a"
    patch = facts.get("patch") or "n/a"
    e = html.escape
    summary = (
        f"ATLAS is an interactive map of the Amberstone repository, generated "
        f"from the git index: {c['nodes']} components in {c['cats']} categories, "
        f"with all {c['files']} tracked source files drawn as dust around the "
        f"component they belong to, and {c['imports']} import links between "
        f"components. Built at commit {st['commit']} ({st['date']}).")
    lede = (
        f"The Amberstone repository drawn as one map: {c['nodes']} components in "
        f"{c['cats']} categories, with all {c['files']} tracked source files "
        f"orbiting as dust. Generated from the git index at commit "
        f"{st['commit']}. Drag to pan, scroll to zoom, click to explore.")
    noscript = (
        f"<strong>This map needs JavaScript.</strong> It is one interactive "
        f"canvas. In text: ATLAS draws the Amberstone repository as "
        f"{c['nodes']} components - directories and module families - in "
        f"{c['cats']} categories, with all {c['files']} tracked source files as "
        f"dust around the component each one belongs to. It is generated from "
        f"the git index by {GENERATOR}; this copy was built at commit "
        f"{st['commit']} ({st['date']}).")
    tip_engine = (f"Daemon Slayer is the local build-math engine: ENGINE_VERSION "
                  f"{engine} on League patch {patch}, read from the repository "
                  f"when this page was generated.")
    tip_nodes = ("Components: one per directory that holds source files, with "
                 "large directories split into module families.")
    tip_files = ("Every tracked source file (.py .js .mjs .cjs .ps1) outside the "
                 "test trees, drawn as a dust star around its component.")
    tip_commits = (f"Commit count of the branch at {st['commit']}, the commit "
                   f"this page was generated from.")
    hud = "\n".join([
        f'<div class="hud-title">repo stats at build, {e(st["date"])}</div>',
        f'<div class="hud-tip" style="pointer-events:auto" title="{e(tip_commits)}">commits: {st["commits"]}</div>',
        f'<div>commit: {e(st["commit"])}</div>',
        f'<div class="hud-tip" style="pointer-events:auto" title="{e(tip_engine)}">engine: DS {e(engine)} / patch {e(patch)}</div>',
        f'<div class="hud-tip" style="pointer-events:auto" title="{e(tip_nodes)}">nodes: {c["nodes"]}</div>',
        f'<div class="hud-tip" style="pointer-events:auto" title="{e(tip_files)}">files: {c["files"]}</div>',
        f'<div>links: {c["imports"]} imports + {c["tree"]} tree</div>',
        f'<div>built by: {e(GENERATOR)}</div>',
    ])
    return {
        "lede": e(lede),
        "summary": e(summary),
        "fallback": e(summary + " Your browser cannot draw a canvas, so the map "
                      "itself is unavailable."),
        "noscript": noscript,
        "hud": hud,
    }


_HTML_REGIONS = ("lede", "noscript", "summary", "fallback", "hud")


def _region_re(name: str, js: bool) -> re.Pattern[str]:
    n = re.escape(name)
    if js:
        return re.compile(rf"(/\*atlas:gen:{n}\*/)(.*?)(/\*/atlas:gen:{n}\*/)", re.S)
    return re.compile(rf"(<!--atlas:gen:{n}-->)(.*?)(<!--/atlas:gen:{n}-->)", re.S)


def _region(page: str, name: str, js: bool = False) -> str:
    hits = _region_re(name, js).findall(page)
    if len(hits) != 1:
        raise BuildError(f"expected exactly one atlas:gen:{name} region, found {len(hits)}")
    return hits[0][1]


def render_page(template: str, model: dict[str, Any]) -> str:
    text = render_text(model)
    page = template
    for name in _HTML_REGIONS:
        _region(page, name)  # exactly-one check
        page = _region_re(name, False).sub(
            lambda m, v=text[name]: m.group(1) + v + m.group(3), page)
    _region(page, "data", js=True)
    data = "\n" + render_data(model) + "\n"
    page = _region_re("data", True).sub(lambda m: m.group(1) + data + m.group(3), page)
    page = render_fonts(page)
    if embedded_faces(page) or _region_re("fontnotice", True).search(page):
        _region(page, "fontnotice", js=True)  # exactly-one check
        notice = "\n" + render_font_notice(page) + "\n"
        page = _region_re("fontnotice", True).sub(
            lambda m: m.group(1) + notice + m.group(3), page)
    return page


def build_page(root: Path, template: str | None = None,
               stamp: dict[str, Any] | None = None, min_modules: int = 0) -> str:
    root = Path(root).resolve()
    if template is None:
        template = (root / ATLAS_NAME).read_text(encoding="utf-8")
    model = build_model(root, stamp=stamp, min_modules=min_modules)
    page = render_page(template, model)
    try:
        page.encode("ascii")
    except UnicodeEncodeError as exc:
        raise BuildError(f"generated page is not 7-bit ASCII: {exc}") from exc
    return page


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="ascii", newline="\n") as fh:
        fh.write(text)
    tmp.replace(path)


STALE_MESSAGE = "atlas.html is stale. Run: python tools/atlas_build.py"


def check_page(root: Path, min_modules: int = MIN_REPO_MODULES) -> tuple[int, str]:
    """The ``--check`` verdict as data: (0, "") fresh, (1, why) stale, (2, why) unbuildable.

    Re-renders with the stamp already in the page, so only a change to what the
    page maps (a module added, removed or renamed, an import, a docstring,
    ENGINE_VERSION) makes it stale - a new commit alone does not.
    tools/drift_guard.py calls this in process; ``main`` prints its message.
    """
    target = Path(root).resolve() / ATLAS_NAME
    try:
        current = target.read_text(encoding="utf-8")
    except OSError as exc:
        return 2, f"atlas_build: cannot read {ATLAS_NAME}: {exc.__class__.__name__}"
    try:
        stamp = parse_data(current)["stamp"]
    except (BuildError, ValueError, KeyError):
        stamp = None
    try:
        page = build_page(root, template=current, stamp=stamp, min_modules=min_modules)
    except BuildError as exc:
        return 2, f"atlas_build: {exc}"
    return (0, "") if page == current else (1, STALE_MESSAGE)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if atlas.html differs from a fresh build")
    ap.add_argument("--root", default=str(REPO_ROOT), help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    if args.check:
        code, message = check_page(root)
        if message:
            print(message, file=sys.stderr)
        return code
    target = root / ATLAS_NAME
    current = target.read_text(encoding="utf-8")
    try:
        page = build_page(root, template=current, stamp=None,
                          min_modules=MIN_REPO_MODULES)
    except BuildError as exc:
        print(f"atlas_build: {exc}", file=sys.stderr)
        return 2
    if page != current:
        _write_atomic(target, page)
    model = parse_data(page)
    c = _counts(model)
    print(f"atlas.html: {c['nodes']} nodes, {c['files']} files, "
          f"{c['imports']} import links, {c['tree']} tree links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
