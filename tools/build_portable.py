"""tools/build_portable.py - the Amberstone portable bundle builder (PKG-4).

docs/PACKAGING_PLAN.md MUST-FIX M6 measured the previous builder producing a
bundle that could not start: a hand-kept inclusion list that named files no
longer in the tree and omitted web_dashboard.py, app/, dashboard/, web/ and
agents/. This rewrite never keeps an inclusion list:

* INCLUSION = the git INDEX (`git ls-files`) minus an explicit, reasoned
  exclusion list (dev-only trees, operator-only and boot-start scripts,
  secrets and per-host state). Gitignored files are never in the index, so
  keys, certs, logs and data caches cannot ride along; the secret rules apply
  even to a force-added file. A failed or empty `git ls-files` refuses the
  build (no disk-walk fallback). Every tracked .gitignore ships (PKG-2).
* NEVER AT BOOT: besides the named installers, every included text file is
  scanned for task / boot signatures (schtasks, *-ScheduledTask cmdlets,
  -AtStartup / -AtLogOn, the Run registry keys, Startup-folder writes, login
  items); any hit not allow-listed file-by-file with a reason in
  BOOT_SCAN_ALLOW fails the build (plan intent 3).
* CLEAN SOURCE: files are copied from the working tree, so an included file
  that differs from HEAD refuses the build unless `--allow-dirty` (recorded).
* IMPORT CLOSURE: every repo module reachable by static import (plus
  importlib.import_module / __import__ calls on a literal or a module-level
  string constant) from the processes the backend runs (CLOSURE_ENTRIES) and
  from the coaches core/coach_registry.py loads by name must be inside the
  bundle, or the build fails.
* NO LFS POINTER: a tracked LFS file whose working copy is still the pointer
  refuses the build (plan S14: the laning coach would fail soft to live
  Haiku); `--skip-lfs-pointers` omits them instead and records which.
* RUNTIME: python-embed/ is built from the pinned python.org zip and the
  hashed lock by tools/build_python_embed.py (plan section 3.5), with the
  opencv ffmpeg DLL strip and the certifi inclusion as explicit, recorded
  steps (M10). `--python-embed DIR` reuses a prebuilt runtime only after it
  verifies against this tree's lock; `--no-embed` stages the backend alone.
* VERIFY: the finished folder is re-checked (no key file, no ops/runtime/,
  no excluded path, no LFS pointer, no boot signature) before success;
  tools/package_portable.py runs the same check before zipping.

The staged folder is the bundle root; its BUILD_MANIFEST.json (repo-relative
paths only) records version, commit, per-file sha256, exclusions and closure.

Usage (from the repo root):
    python tools/build_portable.py                    (embedded runtime, 3.14 host)
    python tools/build_portable.py --output dist/portable_staging
    python tools/build_portable.py --python-embed dist/python-embed
    python tools/build_portable.py --no-embed --skip-lfs-pointers --dry-run

Exit codes: 0 built, 1 refused or failed, 2 dry-run would succeed.
"""
from __future__ import annotations

import argparse
import ast
import datetime
import hashlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tools import build_python_embed as embed_mod  # noqa: E402

# Every process the backend runs: the plan's PKG-4 six, plus the DS launcher
# (core/daemon_slayer_client.py _spawn_child) and the supervisor that owns
# main.py, both spawned by path, so their closures must ship too.
CLOSURE_ENTRIES = (
    # arch: phase 2.4 (2026-05-09) - vision server entrypoint shim (real code in vision_server/)
    "moon_vision_server.py",
    "main.py",
    "web_dashboard.py",
    "tools/lcu_agent.py",
    "tools/liveclient_relay.py",
    "tools/hotkey_listener.py",
    "tools/start_daemon_slayer.py",
    "ops/rc_supervisor.py",
)

BUNDLE_NAME = "Amberstone"
BUILD_TOOL = "tools/build_portable.py"
MANIFEST_NAME = "BUILD_MANIFEST.json"
README_NAME = "PREREQUISITES.md"
EMBED_DIR_NAME = "python-embed"
DEFAULT_OUTPUT = _PROJECT_ROOT / "dist" / "portable_staging"
# Written by the build / package step at the bundle root, never from the index.
GENERATED_FILES = frozenset({MANIFEST_NAME, README_NAME, "PACKAGE_MANIFEST.json"})

LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1"
_LFS_POINTER_MAX = 1024

# --------------------------------------------------------------------------- #
# Exclusion rules. Order matters only for which reason is reported.
# --------------------------------------------------------------------------- #
R_SECRET = "secret or per-install credential"
R_HOST = "per-host config (gitignored by design)"
R_RUNTIME = "runtime state, logs or build output"
R_DEV = "dev-only"
R_TEST = "dev-only: test code"
R_SCRATCH = "dev-only: scratch or archive"
R_BOOT = "boot-start, scheduled-task or shortcut installer (plan intent 3, S8)"
R_KILL = "operator-only: kills by image name (plan S7)"
R_TASKS = ("operator-only: drives the RC-* scheduled tasks the launcher replaces "
           "(plan section 5)")
R_PHASE3 = ("dev profile only: Phase 3 supervisor + agents (PKG-1 services.json); it "
            "imports ops/loop/fleet_route.py, which is dev-only")
R_BUILD = "dev-only: build-time packaging tool"

_SECRET_NAME_RES = (
    re.compile(r"^api-key-.*\.txt$"),
    re.compile(r"^\.env(\..*)?$"),
    re.compile(r"token\.txt$"),
)
_SECRET_NAME_OK = {".env.example"}
_SECRET_SUFFIXES = (".pem", ".key", ".pfx", ".p12", ".crt", ".cer")

_HOST_CONFIG = frozenset({
    "ops/local_hosts.json",
    "ops/moon_sync_repos.json",
    "ops/local_paths.json",
    "ops/lane_worktrees.json",
    "config/coach_settings.json",
    "config/rank_tier_source.json",
    "config/operator_identity.json",
    "config/push_notify.json",
    "config/external_sources.json",
})

_RUNTIME_PREFIXES = ("ops/runtime/", "ops/tls/", "logs/", "dist/", "build/")
_RUNTIME_SUFFIXES = (".log", ".jsonl", ".pyc", ".pyo", ".tmp")

# Shipped on purpose, root and nested alike, ahead of the dev-only rules: the
# PKG-2 updater builds its IgnoreRules from the INSTALL's own ignore files and
# refuses every update when the root one is missing (ops/launcher/updater.py
# IgnoreRules.for_install), so a bundle without them could never be updated.
# Shipping every tracked one makes the install's ignore decisions equal the
# repo's. They hold ignore patterns only (no secret, host or machine path).
# An update payload never carries one (the updater denies the name), so the
# rules stay the installed bundle's own. .gitattributes stays dev-only.
IGNORE_FILE_NAME = ".gitignore"

_DEV_PREFIXES = (
    ("tests/", R_TEST),
    ("docs/", R_DEV + ": documentation"),
    ("ops/loop/", R_DEV + ": headless loop"),
    ("ops/fleet_kit/", R_DEV + ": fleet kit"),
    ("ops/audit/", R_DEV + ": audit artifacts"),
    ("ops/migrate/", R_DEV + ": one-off migration scripts"),
    (".github/", R_DEV + ": CI"),
    (".githooks/", R_DEV + ": git hooks (a packaged install has no git)"),
    (".claude/", R_DEV + ": agent settings"),
    ("lane-widget/", R_DEV + ": Mission Control lane widget"),
    ("mc/", R_DEV + ": Mission Control control plane"),
    ("oss/", R_DEV + ": standalone OSS package, not imported at runtime"),
    ("moon_sync_inbox/", R_DEV + ": cross-repo channel inbox"),
    ("memory/", R_DEV + ": agent memory"),
)

# Root-level files of tools/ that are documentation or agent prompts (31 at
# PKG-4; the /agent/ deploy route that served two of them is Legion-only).
_TOOLS_DOC_RE = re.compile(r"^tools/[^/]+\.md$")

_BUILD_FILES = frozenset({
    "tools/build_portable.py", "tools/build_portable.cmd",
    "tools/build_python_embed.py",
    "tools/package_portable.py", "tools/package_portable.cmd",
    "tools/build_installer.py", "tools/build_installer.cmd",
    "tools/run_packaged_smoke.py", "tools/run_packaged_smoke.cmd",
})

# Not the app: tools no launcher service runs. Several carry a task-install
# recipe in their docstring, which the boot-signature scan below would flag.
_NOT_THE_APP = {
    "tools/rc_facts.py": R_DEV + ": agent session hook",
    "tools/replay_chain_watch.py": (R_DEV + ": replay-chain scheduled tool (the replay "
                                    "tasks are not the app, plan section 5)"),
    "tools/ds_matchdb_mcp_server.py": (R_DEV + ": Claude MCP server (its docstring "
                                       "registers an AtLogOn task)"),
    "tools/start_ds_matchdb_mcp.py": R_DEV + ": Claude MCP server launcher",
    "tools/keybind_listener.py": ("retired agent, not a launcher service (its docstring "
                                  "registers an AtLogOn task)"),
    "tools/screen_agent.py": ("retired agent, not a launcher service (its docstring "
                              "registers AtLogOn tasks)"),
    # mc/routes.py splices these two tables into Mission Control :8895; :8888
    # serves neither (dashboard/_errors.py header), and both import_module
    # the dev-only ops/loop package.
    "dashboard/routes_loop_control.py": R_DEV + ": Mission Control route table (mc/ only)",
    "dashboard/routes_loop_status.py": R_DEV + ": Mission Control route table (mc/ only)",
}

_PHASE3_RE = re.compile(
    r"^agents/(?:supervisor\.py|_supervisor_[^/]+\.py|_minimap_bbox\.py"
    r"|agent\d+_[^/]+/|state/)")

_DEV_FILES = frozenset({
    "CLAUDE.md", "WAKEUP_NOTES.md", "ROADMAP.md", "BACKLOG.md",
    "RC-NEXT-SESSION.txt", "atlas.html", "mission_control.py",
    "conftest.py", "pytest.ini", "mypy.ini", "ruff.toml", "requirements.in",
    ".gitattributes", ".nojekyll", "ops/status_board.json",
    "ops/claude_settings.example.json", "ops/lane_worktrees.example.json",
    "ops/moon_sync_repos.example.json", "scripts/start_claude.ps1",
    "scripts/bootstrap_dev.ps1", "scripts/bootstrap_dev.cmd",
    "scripts/install_hooks.py",
})

_BOOT_FILES = frozenset({
    "ops/install_startup.bat",
    "ops/autostart_on_login.bat",
    "ops/rc_league_watcher.ps1",
    "ops/rc_watcher_launch.vbs",
    "ops/phase3_install.ps1",
    "ops/phase3_install_periodic_audit.ps1",
})
_BOOT_RES = (
    re.compile(r"^ops/RC-[^/]*\.xml$"),
    re.compile(r"^ops/install_RC_[^/]*\.ps1$"),
    re.compile(r"^tools/install_[^/]*\.ps1$"),
    re.compile(r"^tools/[^/]*_install\.ps1$"),
)
_TASK_DRIVER_RE = re.compile(r"^tools/legion_[^/]*\.ps1$")
# PKG-7: the operator's one-time cutover (unregisters / re-imports RC-* tasks).
_TASK_DRIVER_FILES = frozenset({"tools/launcher_cutover.ps1"})

_KILL_FILES = frozenset({
    "ops/launch_new_system.bat",
    "scripts/restart.bat",
    "scripts/kill.bat",
    "scripts/restart_clean.bat",
})

_TEST_SEGMENTS = frozenset({"tests", "test"})
_SCRATCH_SEGMENTS = frozenset({"scratch", "_scratch", ".scratch", "tmp", "_tmp",
                               "_archive", "__pycache__"})
_SCRATCH_SUFFIXES = (".bak", ".orig", ".rej")


def exclusion_reason(rel: str) -> Optional[str]:
    """Why `rel` (a repo-relative forward-slash path) never ships, else None."""
    rel = rel.replace("\\", "/").lstrip("/")
    parts = rel.split("/")
    name = parts[-1]
    low = name.lower()
    if low not in _SECRET_NAME_OK and (
            any(r.search(low) for r in _SECRET_NAME_RES) or low.endswith(_SECRET_SUFFIXES)):
        return R_SECRET
    if rel in _HOST_CONFIG:
        return R_HOST
    if rel.startswith(_RUNTIME_PREFIXES) or low.endswith(_RUNTIME_SUFFIXES):
        return R_RUNTIME
    if name == IGNORE_FILE_NAME:
        return None
    for prefix, reason in _DEV_PREFIXES:
        if rel.startswith(prefix):
            return reason
    if any(seg in _TEST_SEGMENTS for seg in parts[:-1]) or (
            low.startswith("test_") and low.endswith(".py")) or low == "conftest.py":
        return R_TEST
    if any(seg in _SCRATCH_SEGMENTS for seg in parts[:-1]) or low.endswith(_SCRATCH_SUFFIXES):
        return R_SCRATCH
    if rel in _DEV_FILES or _TOOLS_DOC_RE.match(rel):
        return R_DEV
    if rel in _BUILD_FILES:
        return R_BUILD
    if rel in _NOT_THE_APP:
        return _NOT_THE_APP[rel]
    if _PHASE3_RE.match(rel):
        return R_PHASE3
    if rel in _BOOT_FILES or any(r.match(rel) for r in _BOOT_RES):
        return R_BOOT
    if _TASK_DRIVER_RE.match(rel) or rel in _TASK_DRIVER_FILES:
        return R_TASKS
    if rel in _KILL_FILES:
        return R_KILL
    return None


# --------------------------------------------------------------------------- #
# Boot-signature content scan (plan intent 3: never start at boot)
# --------------------------------------------------------------------------- #
# The exclusion rules above name the installers known at PKG-4; this scan
# catches the next one. Every included text file (NUL-free head, at most
# BOOT_SCAN_MAX_BYTES - a boot installer is never a multi-MB data table) is
# matched against these signatures, and ANY hit the allow-list below does not
# name, file by file and signature by signature, fails the build.
BOOT_SIGNATURES = (
    ("schtasks", re.compile(r"\bschtasks(?:\.exe)?\b", re.I)),
    ("schtasks /Create", re.compile(r"\bschtasks(?:\.exe)?\b.{0,160}?/create\b",
                                    re.I | re.S)),
    ("Register-ScheduledTask", re.compile(r"\bRegister-ScheduledTask\b", re.I)),
    ("New-ScheduledTaskTrigger", re.compile(r"\bNew-ScheduledTaskTrigger\b", re.I)),
    ("ScheduledTask cmdlet", re.compile(
        r"\b(?:Register|Unregister|New|Set|Enable|Disable|Start|Stop|Get)"
        r"-ScheduledTask\w*", re.I)),
    ("-AtStartup", re.compile(r"-AtStartup\b", re.I)),
    ("-AtLogOn", re.compile(r"-AtLogOn\b", re.I)),
    ("Run registry key", re.compile(r"CurrentVersion\\{1,2}Run(?:Once)?\b", re.I)),
    ("Startup folder", re.compile(
        r"Programs(?:\\{1,2}|/)Startup\b|shell:(?:common\s?)?startup\b"
        r"|GetFolderPath\(\s*['\"]?(?:Common)?Startup|SpecialFolder\]::(?:Common)?Startup"
        r"|CSIDL_(?:COMMON_)?STARTUP|FOLDERID_(?:Common)?Startup", re.I)),
    ("login item", re.compile(r"\bsetLoginItemSettings\b|\bopenAtLogin\b")),
    ("Task Scheduler COM", re.compile(r"\bSchedule\.Service\b", re.I)),
)
BOOT_SCAN_MAX_BYTES = 2 * 1024 * 1024
# Cheap literal prefilter: every signature contains one of these (lower-cased),
# so a file holding none of them cannot match and skips the regex pass.
_BOOT_ANCHORS = ("schtasks", "scheduledtask", "-atstartup", "-atlogon",
                 "currentversion", "startup", "loginitem", "openatlogin",
                 "schedule.service")

# rel -> (signatures it may carry, why it still ships). Kept tight: a new
# signature in an allow-listed file is still a failure.
BOOT_SCAN_ALLOW = {
    "core/daemon_slayer_client.py": (
        frozenset({"schtasks"}),
        "DsWatchdog runs / queries an EXISTING RC-DaemonSlayer task and falls back "
        "to a direct child where none is registered (plan S9); it creates no task"),
    "core/port_handoff.py": (
        frozenset({"schtasks"}),
        "docstring measurement note about `schtasks /End` + `/Run`; runs nothing"),
    "dashboard/routes_loop_monitor.py": (
        frozenset({"schtasks"}),
        "a command-name token in the loop monitor's classifier list; runs nothing"),
    "ops/rc_supervisor.py": (
        frozenset({"schtasks"}),
        "FROZEN supervisor: `schtasks /Run RC-Phase3-Supervisor` of an existing task, "
        "breaker-bounded (plan S9); it creates no task"),
    "tools/liveclient_relay.py": (
        frozenset({"schtasks", "schtasks /Create"}),
        "module docstring records the legacy ONLOGON task; the agent creates none "
        "(the launcher runs it, plan section 3.1)"),
}


def _scan_text(path: Path, skipped: Optional[list] = None, rel: str = "") -> Optional[str]:
    try:
        if path.stat().st_size > BOOT_SCAN_MAX_BYTES:
            if skipped is not None:
                skipped.append(rel)
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def boot_signature_hits(root: Path, rels: Iterable[str],
                        skipped: Optional[list] = None) -> dict:
    """rel -> sorted signature names found in that file. Files over the size
    cap are appended to `skipped` (recorded in the manifest), never hidden."""
    hits = {}
    for rel in rels:
        text = _scan_text(Path(root) / rel, skipped, rel)
        if text is None:
            continue
        low = text.lower()
        if not any(a in low for a in _BOOT_ANCHORS):
            continue
        found = sorted(name for name, rx in BOOT_SIGNATURES if rx.search(text))
        if found:
            hits[rel] = found
    return hits


def boot_violations(hits: dict, allow: Optional[dict] = None) -> list:
    """'rel: signatures' for every hit the allow-list does not cover."""
    allow = BOOT_SCAN_ALLOW if allow is None else allow
    out = []
    for rel, names in sorted(hits.items()):
        allowed = allow.get(rel, (frozenset(), ""))[0]
        extra = [n for n in names if n not in allowed]
        if extra:
            out.append(f"{rel}: {', '.join(extra)}")
    return out


# --------------------------------------------------------------------------- #
# Git index
# --------------------------------------------------------------------------- #
class BundleError(RuntimeError):
    """A refused bundle build."""


def _default_git_runner(cmd: list, cwd: Path) -> tuple:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, timeout=120,
                              creationflags=flags)
    except (OSError, subprocess.SubprocessError):
        return 127, b""
    return proc.returncode, proc.stdout


def git_index_files(root: Path, *, git_runner: Optional[Callable] = None) -> list:
    """Every path in the git index of `root`; raises BundleError on any failure."""
    rc, out = (git_runner or _default_git_runner)(["git", "ls-files", "-z"], Path(root))
    if rc != 0:
        raise BundleError(f"git ls-files failed (exit {rc}); refusing to guess the file set")
    files = sorted({p for p in out.decode("utf-8", errors="strict").split("\0") if p})
    if not files:
        raise BundleError("git ls-files returned an empty index; refusing to build")
    return files


def _git_text(root: Path, args: list, git_runner: Optional[Callable]) -> Optional[str]:
    rc, out = (git_runner or _default_git_runner)(["git", *args], Path(root))
    if rc != 0:
        return None
    return out.decode("utf-8", errors="replace").strip()


def modified_tracked_files(root: Path, *, git_runner: Optional[Callable] = None) -> list:
    """Tracked paths whose working copy or index entry differs from HEAD
    (`git status --porcelain -z --untracked-files=no`). The bundle copies the
    working tree, so any of these makes it differ from `source_commit`.
    Raises BundleError when git cannot say."""
    rc, out = (git_runner or _default_git_runner)(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=no"], Path(root))
    if rc != 0:
        raise BundleError(f"git status failed (exit {rc}); cannot prove a clean source")
    tokens = out.decode("utf-8", errors="strict").split("\0")
    paths, i = [], 0
    while i < len(tokens):
        tok = tokens[i]
        i += 1
        if len(tok) < 4:
            continue
        xy, path = tok[:2], tok[3:]
        paths.append(path)
        if "R" in xy or "C" in xy:
            i += 1  # the rename / copy source follows as its own token
    return sorted(set(paths))


# --------------------------------------------------------------------------- #
# Plan
# --------------------------------------------------------------------------- #
def is_lfs_pointer(path: Path) -> bool:
    try:
        if path.stat().st_size > _LFS_POINTER_MAX:
            return False
        with open(path, "rb") as fh:
            return fh.read(len(LFS_POINTER_PREFIX)) == LFS_POINTER_PREFIX
    except OSError:
        return False


@dataclass
class BundlePlan:
    include: list = field(default_factory=list)
    excluded: dict = field(default_factory=dict)
    lfs_pointers: list = field(default_factory=list)
    missing_on_disk: list = field(default_factory=list)


def plan_bundle(root: Path, index_files: Iterable[str]) -> BundlePlan:
    root = Path(root)
    plan = BundlePlan()
    for rel in sorted(set(index_files)):
        reason = exclusion_reason(rel)
        if reason:
            plan.excluded.setdefault(reason, []).append(rel)
            continue
        path = root / rel
        if not path.is_file():
            plan.missing_on_disk.append(rel)
        elif is_lfs_pointer(path):
            plan.lfs_pointers.append(rel)
        else:
            plan.include.append(rel)
    return plan


# --------------------------------------------------------------------------- #
# Import closure
# --------------------------------------------------------------------------- #
@dataclass
class Closure:
    files: set = field(default_factory=set)
    script_dir_imports: list = field(default_factory=list)
    unparsable: list = field(default_factory=list)
    missing_entries: list = field(default_factory=list)
    dynamic_imports: list = field(default_factory=list)


_DYNAMIC_IMPORTERS = {"import_module", "__import__"}

# Modules loaded through a NON-literal import_module the AST walk cannot read:
# app/_game_lifecycle.py does importlib.import_module(mp) for each coach in
# core/coach_registry.py MODE_COACH_MAP. The map is parsed (never hand-copied),
# so a new coach becomes a closure root on its own.
COACH_REGISTRY = "core/coach_registry.py"
COACH_REGISTRY_MAP = "MODE_COACH_MAP"


def registry_roots(root: Path, universe: frozenset) -> list:
    """Repo files for every coach module the registry names (empty when the
    registry is not in the index, e.g. a test fixture repo)."""
    if COACH_REGISTRY not in universe:
        return []
    try:
        tree = ast.parse((Path(root) / COACH_REGISTRY).read_bytes(), filename=COACH_REGISTRY)
    except (OSError, SyntaxError, ValueError) as exc:
        raise BundleError(f"{COACH_REGISTRY} unreadable: {exc}") from exc
    mapping = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == COACH_REGISTRY_MAP for t in node.targets):
            try:
                mapping = ast.literal_eval(node.value)
            except ValueError as exc:
                raise BundleError(f"{COACH_REGISTRY_MAP} is not a literal: {exc}") from exc
    if not isinstance(mapping, dict) or not mapping:
        raise BundleError(f"{COACH_REGISTRY} has no literal {COACH_REGISTRY_MAP}")
    out = []
    for value in mapping.values():
        modname = value[0] if isinstance(value, (tuple, list)) and value else None
        if not isinstance(modname, str):
            raise BundleError(f"{COACH_REGISTRY_MAP} entry without a module name: {value!r}")
        hit = _resolve(modname, ("",), universe)
        if hit is None:
            raise BundleError(f"{COACH_REGISTRY_MAP} names {modname}, not in the index")
        out.extend(hit[1])  # the module plus every parent package __init__
    return sorted(set(out))


def closure_roots(root: Path, universe: frozenset) -> list:
    """CLOSURE_ENTRIES plus the registry-loaded coach modules (and the package
    __init__ files importing them executes)."""
    return list(CLOSURE_ENTRIES) + [r for r in registry_roots(root, universe)
                                    if r not in CLOSURE_ENTRIES]


def _resolve(dotted: str, bases: tuple, universe: frozenset) -> Optional[tuple]:
    parts = [p for p in dotted.split(".") if p]
    if not parts:
        return None
    for base in bases:
        prefix = f"{base}/" if base else ""
        stem = prefix + "/".join(parts)
        for cand in (stem + ".py", stem + "/__init__.py"):
            if cand in universe:
                found = [cand]
                for i in range(1, len(parts)):
                    init = prefix + "/".join(parts[:i]) + "/__init__.py"
                    if init in universe:
                        found.append(init)
                return base, found
    return None


def _package_of(rel: str) -> list:
    pp = PurePosixPath(rel)
    return list(pp.parent.parts) if pp.parent.parts != (".",) else []


def _module_str_constants(tree: ast.AST) -> dict:
    """Module-level `NAME = "literal"` bindings (the shape the dashboard's
    `importlib.import_module(_LANES_MODULE)` call sites use)."""
    consts = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and \
                isinstance(node.value.value, str):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    consts[t.id] = node.value.value
    return consts


def _imports_of(tree: ast.AST, rel: str) -> list:
    """(dotted name, is_relative, is_dynamic) for every import the module
    could execute: import statements, plus import_module / __import__ calls
    whose first argument is a literal or a module-level string constant."""
    names = []
    pkg = _package_of(rel)
    consts = _module_str_constants(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend((a.name, False, False) for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                up = node.level - 1
                if up > len(pkg):
                    continue
                base = pkg[:len(pkg) - up] if up else list(pkg)
                mod = ".".join(base + ([node.module] if node.module else []))
                rel_flag = True
            else:
                mod = node.module or ""
                rel_flag = False
            if mod:
                names.append((mod, rel_flag, False))
            for a in node.names:
                if a.name != "*":
                    names.append((f"{mod}.{a.name}" if mod else a.name, rel_flag, False))
        elif isinstance(node, ast.Call) and node.args:
            f = node.func
            fname = f.attr if isinstance(f, ast.Attribute) else (
                f.id if isinstance(f, ast.Name) else "")
            if fname not in _DYNAMIC_IMPORTERS:
                continue
            arg = node.args[0]
            target = None
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                target = arg.value
            elif isinstance(arg, ast.Name) and arg.id in consts:
                target = consts[arg.id]
            if target and not target.startswith("."):
                names.append((target, False, True))
    return names


def import_closure(root: Path, entries: Iterable[str], universe: frozenset) -> Closure:
    """Repo files reachable by import from `entries`, resolved in `universe`.

    A script entry also searches its own folder (sys.path[0] for a script);
    a module found only there is listed in `script_dir_imports`, because the
    embedded runtime's ._pth puts no script folder on sys.path. Every
    resolved dynamic import is listed in `dynamic_imports`.
    """
    root = Path(root)
    out = Closure()
    for entry in entries:
        if entry not in universe:
            out.missing_entries.append(entry)
            continue
        entry_dir = str(PurePosixPath(entry).parent)
        bases = ("",) if entry_dir in ("", ".") else ("", entry_dir)
        queue = [entry]
        seen = set()
        while queue:
            rel = queue.pop()
            if rel in seen:
                continue
            seen.add(rel)
            out.files.add(rel)
            try:
                tree = ast.parse((root / rel).read_bytes(), filename=rel)
            except (OSError, SyntaxError, ValueError):
                out.unparsable.append(rel)
                continue
            for dotted, is_rel, is_dyn in _imports_of(tree, rel):
                hit = _resolve(dotted, ("",) if is_rel else bases, universe)
                if hit is None:
                    continue
                base, found = hit
                if base:
                    out.script_dir_imports.append(f"{rel}: {dotted} -> {found[0]}")
                if is_dyn:
                    out.dynamic_imports.append(f"{rel}: {dotted} -> {found[0]}")
                queue.extend(f for f in found if f not in seen)
    out.script_dir_imports = sorted(set(out.script_dir_imports))
    out.unparsable = sorted(set(out.unparsable))
    out.dynamic_imports = sorted(set(out.dynamic_imports))
    return out


# --------------------------------------------------------------------------- #
# Verify a finished bundle folder
# --------------------------------------------------------------------------- #
def verify_bundle(bundle_dir: Path) -> list:
    """Problems in a staged bundle (empty list = clean)."""
    bundle_dir = Path(bundle_dir)
    problems = []
    secret = bundle_dir / "API-Key-Claude.txt"
    if secret.exists():
        problems.append("API-Key-Claude.txt: " + R_SECRET)
    if (bundle_dir / "ops" / "runtime").exists():
        problems.append("ops/runtime/: " + R_RUNTIME)
    scan = []
    for path in sorted(bundle_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(bundle_dir).as_posix()
        if rel == "API-Key-Claude.txt":
            continue
        if rel.startswith(EMBED_DIR_NAME + "/"):
            # The runtime is third-party content checked by its own stamp
            # (certifi's cacert.pem is not a secret); only key files matter.
            if any(r.search(path.name.lower()) for r in _SECRET_NAME_RES[:1]):
                problems.append(f"{rel}: {R_SECRET}")
            continue
        reason = exclusion_reason(rel)
        if reason:
            problems.append(f"{rel}: {reason}")
        elif is_lfs_pointer(path):
            problems.append(f"{rel}: git-lfs pointer, not the real file")
        elif rel not in GENERATED_FILES:
            # The generated manifests list the signature names themselves.
            scan.append(rel)
    for line in boot_violations(boot_signature_hits(bundle_dir, scan)):
        problems.append(f"{line}: boot / scheduled-task signature not allow-listed")
    return problems


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #
def _sha256(path: Path) -> str:
    return embed_mod.sha256_file(path)


def _err(msg: str) -> None:
    print(f"  ERROR   {msg}", file=sys.stderr)


def _info(msg: str) -> None:
    print(f"  INFO    {msg}")


def check_output_dir(root: Path, out: Path, *, marker: str = MANIFEST_NAME,
                     marker_key: str = "build_tool",
                     marker_value: str = BUILD_TOOL) -> Optional[str]:
    """Why `out` may not be wiped and rebuilt (None = safe). Shared with
    tools/build_installer.py: never the repo root or a folder holding it;
    inside the repo only under an excluded tree (dist/); an existing non-empty
    folder only when it holds `marker` written by the same tool."""
    r, o = Path(root).resolve(), Path(out).resolve()
    if o == r:
        return "output dir cannot be the repo root"
    if o in r.parents:
        return "output dir cannot contain the repo root"
    if r in o.parents and exclusion_reason(o.relative_to(r).as_posix() + "/x") is None:
        return "output dir inside the repo must be under an excluded tree (e.g. dist/)"
    if o.exists():
        if not o.is_dir():
            return "output path exists and is not a folder"
        if any(o.iterdir()):
            try:
                man = json.loads((o / marker).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                man = {}
            if not isinstance(man, dict) or man.get(marker_key) != marker_value:
                return (f"output dir is not empty and holds no previous {marker_value} "
                        "output; refusing to delete it")
    return None


def _readme(version: str, python_line: str) -> str:
    return f"""# {BUNDLE_NAME} - portable bundle

Built by {BUILD_TOOL} (PKG-4). Version: {version}.
Python: {python_line}

## First run

1. Optional: put an Anthropic API key in API-Key-Claude.txt next to start.bat.
   Coaching panels need it; DS math and the deterministic coach do not.
   (start.bat still refuses to start without one - PACKAGING_PLAN S11.)
2. Run start.bat. Nothing is registered to start at boot or at logon.

## Not included, on purpose

- API keys (API-Key-Claude.txt, API-Key-Riot.txt), per-host config
  (ops/local_hosts.json), TLS certificates, logs and runtime state.
  ops/runtime/ and logs/ are created on first start.
- Developer tooling: tests, docs, the headless loop, the fleet kit, CI
  config, git hooks.
- Boot-start installers and scripts that kill python by image name.

## Licences

LICENSE (Apache-2.0) covers the source; NOTICE names the third-party data
under data/ that it does NOT cover. python-embed/LICENSE.txt and
python-embed/{embed_mod.STAMP_NAME} record the runtime's licences, including
the opencv ffmpeg DLL and certifi decisions.
"""


def build(root: Path = _PROJECT_ROOT, output_dir: Path = DEFAULT_OUTPUT, *,
          embed: str = "build", embed_dir: Optional[Path] = None,
          embed_pin: Optional[embed_mod.EmbedPin] = None,
          embed_options: Optional[embed_mod.EmbedOptions] = None,
          embed_cache: Optional[Path] = None, embed_zip: Optional[Path] = None,
          opener: Optional[Callable] = None, pip_runner: Optional[Callable] = None,
          host_version=None, skip_lfs_pointers: bool = False,
          version: Optional[str] = None, dry_run: bool = False,
          allow_dirty: bool = False, git_runner: Optional[Callable] = None) -> int:
    """Stage the bundle. Returns 0 built, 1 refused / failed, 2 dry-run ok."""
    root, out = Path(root), Path(output_dir)
    if embed not in ("build", "dir", "none"):
        _err(f"unknown embed mode {embed!r}")
        return 1
    pin = embed_pin or embed_mod.PINS[embed_mod.DEFAULT_VERSION]
    options = embed_options or embed_mod.EmbedOptions()
    version = version or datetime.date.today().strftime("%Y%m%d")
    print(f"{BUNDLE_NAME} bundle builder: version {version}, runtime mode {embed}")

    problem = check_output_dir(root, out)
    if problem:
        _err(problem)
        return 1
    try:
        index = git_index_files(root, git_runner=git_runner)
        universe = frozenset(index)
        plan = plan_bundle(root, index)
        roots = closure_roots(root, universe)
        modified = modified_tracked_files(root, git_runner=git_runner)
    except BundleError as exc:
        _err(str(exc))
        return 1
    if plan.missing_on_disk:
        _err(f"tracked but missing on disk: {plan.missing_on_disk[:20]}")
        return 1
    shipped = set(plan.include) | set(plan.lfs_pointers)
    dirty = sorted(p for p in modified if p in shipped)
    if dirty and not allow_dirty:
        _err("included files differ from HEAD (commit them, or pass --allow-dirty "
             f"to build the working tree anyway): {dirty[:20]}")
        return 1
    if plan.lfs_pointers and not skip_lfs_pointers:
        _err("git-lfs pointers instead of real files (run `git lfs pull`, or pass "
             f"--skip-lfs-pointers to omit them): {plan.lfs_pointers}")
        return 1
    scan_skipped: list = []
    boot_hits = boot_signature_hits(root, plan.include, scan_skipped)
    boot_bad = boot_violations(boot_hits)
    if boot_bad:
        _err("boot / scheduled-task signatures in files that would ship (exclude the "
             "file, or allow-list it in BOOT_SCAN_ALLOW with a reason): "
             + "; ".join(boot_bad))
        return 1
    closure = import_closure(root, roots, universe)
    if closure.missing_entries:
        _err(f"closure entry points not in the index: {closure.missing_entries}")
        return 1
    included = set(plan.include)
    violations = sorted(closure.files - included)
    if violations:
        _err("the import closure needs files the exclusion rules drop: "
             + ", ".join(f"{v} ({exclusion_reason(v) or 'lfs pointer'})" for v in violations))
        return 1
    _info(f"{len(plan.include)} files from the index, "
          f"{sum(len(v) for v in plan.excluded.values())} excluded, "
          f"closure {len(closure.files)} modules, boot scan {len(boot_hits)} "
          f"allow-listed hit(s)")

    lock = root / "requirements.txt"
    if embed == "dir":
        if embed_dir is None:
            _err("--python-embed needs a folder")
            return 1
        bad = embed_mod.verify_embed_dir(Path(embed_dir), requirements=lock, pin=pin,
                                         options=options)
        if bad:
            _err("prebuilt python-embed refused: " + "; ".join(bad))
            return 1
    elif embed == "build":
        try:
            embed_mod.check_host_python(pin, host_version)
        except embed_mod.EmbedError as exc:
            _err(str(exc))
            return 1

    if dry_run:
        print("Dry-run: the bundle would build. Nothing written.")
        return 2

    if out.exists():
        shutil.rmtree(out)  # a previous build of this tool, checked above
    out.mkdir(parents=True)

    files = {}
    for rel in plan.include:
        src, dst = root / rel, out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        files[rel] = _sha256(dst)

    stamp = None
    try:
        if embed == "build":
            stamp = embed_mod.build_embed(
                out / EMBED_DIR_NAME, requirements=lock, pin=pin, options=options,
                cache_dir=embed_cache, opener=opener, local_zip=embed_zip,
                runner=pip_runner, version_info=host_version)
        elif embed == "dir":
            shutil.copytree(Path(embed_dir), out / EMBED_DIR_NAME)
            stamp = embed_mod.read_stamp(out / EMBED_DIR_NAME)
    except (embed_mod.EmbedError, OSError) as exc:
        _err(f"embedded runtime failed: {exc}")
        return 1

    if stamp:
        python_line = (f"embedded CPython {stamp['cpython']['version']} in "
                       f"{EMBED_DIR_NAME}/, packages from the hashed requirements.txt")
        python_doc = {"mode": embed, "dir": EMBED_DIR_NAME, "cpython": stamp["cpython"],
                      "requirements_sha256": stamp["requirements_sha256"],
                      "package_count": len(stamp["packages"])}
        steps = {"opencv_ffmpeg_dll": stamp["opencv_ffmpeg"], "certifi": stamp["certifi"]}
        packages = stamp["packages"]
    else:
        python_line = ("NONE - this is the backend payload only and cannot start on "
                       "its own (build with the embedded runtime for a runnable bundle)")
        python_doc = {"mode": "none", "warning": python_line}
        steps = {"opencv_ffmpeg_dll": {"stripped": options.strip_opencv_ffmpeg,
                                       "licence": embed_mod.OPENCV_FFMPEG_LICENCE,
                                       "applies_to": "no runtime in this bundle"},
                 "certifi": {"included": options.include_certifi,
                             "licence": embed_mod.CERTIFI_LICENCE,
                             "applies_to": "no runtime in this bundle"}}
        packages = []
    steps["ruling"] = "M10 licence ruling is operator-gated (PKG-8) before any distribution"

    (out / README_NAME).write_text(_readme(version, python_line), encoding="utf-8",
                                   newline="\n")
    manifest = {
        "build_tool": BUILD_TOOL,
        "bundle": BUNDLE_NAME,
        "version": version,
        "built_utc": datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "source_commit": _git_text(root, ["rev-parse", "--verify", "-q", "HEAD"], git_runner),
        "source_tree_clean": not modified,
        "source_included_clean": not dirty,
        "allow_dirty": allow_dirty,
        "dirty_included": dirty,
        "file_count": len(files),
        "files": files,
        "excluded_counts": {k: len(v) for k, v in sorted(plan.excluded.items())},
        "excluded_named": {k: v for k, v in sorted(plan.excluded.items())
                           if k in (R_SECRET, R_HOST, R_BOOT, R_KILL, R_TASKS)},
        "lfs_pointers_skipped": plan.lfs_pointers,
        "boot_scan": {"signatures": [name for name, _ in BOOT_SIGNATURES],
                      "allow_listed": {k: v for k, v in sorted(boot_hits.items())},
                      "skipped_over_size_cap": scan_skipped},
        "closure": {"entries": roots, "module_count": len(closure.files),
                    "script_dir_imports": closure.script_dir_imports,
                    "dynamic_imports": closure.dynamic_imports,
                    "unparsable": closure.unparsable},
        "python": python_doc,
        "licence_steps": steps,
        "third_party": {
            "python_packages": packages,
            "tracked_data": ("data/ carries third-party game data NOT covered by the "
                             "Apache-2.0 licence - see NOTICE; redistribution is gated "
                             "(PACKAGING_PLAN section 6, OVERLAY_COMPLIANCE_PLAN N8)"),
        },
    }
    tmp = out / (MANIFEST_NAME + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8",
                   newline="\n")
    tmp.replace(out / MANIFEST_NAME)

    problems = verify_bundle(out)
    if problems:
        _err("post-build verification failed: " + "; ".join(problems[:20]))
        return 1
    print(f"Built {out.name}: {len(files)} files, runtime {python_doc['mode']}.")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=f"Stage the {BUNDLE_NAME} portable bundle.")
    p.add_argument("--output", "-o", default=str(DEFAULT_OUTPUT))
    p.add_argument("--version", default=None, help="bundle version (default YYYYMMDD)")
    p.add_argument("--dry-run", "-n", action="store_true")
    p.add_argument("--skip-lfs-pointers", action="store_true",
                   help="omit LFS files whose working copy is still the pointer")
    p.add_argument("--allow-dirty", action="store_true",
                   help="build even when included tracked files differ from HEAD "
                        "(recorded in the manifest)")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--python-embed", default=None, metavar="DIR",
                       help="reuse a prebuilt runtime (verified against this lock)")
    group.add_argument("--no-embed", action="store_true",
                       help="stage the backend only (cannot start on its own)")
    embed_mod.add_embed_arguments(p)
    args = p.parse_args(argv)
    mode = "none" if args.no_embed else ("dir" if args.python_embed else "build")
    return build(
        _PROJECT_ROOT, Path(args.output), embed=mode,
        embed_dir=Path(args.python_embed) if args.python_embed else None,
        embed_pin=embed_mod.PINS[args.python_version],
        embed_options=embed_mod.options_from_args(args),
        embed_cache=Path(args.embed_cache) if args.embed_cache else None,
        embed_zip=Path(args.embed_zip) if args.embed_zip else None,
        skip_lfs_pointers=args.skip_lfs_pointers, version=args.version,
        dry_run=args.dry_run, allow_dirty=args.allow_dirty)


if __name__ == "__main__":
    sys.exit(main())
