"""
tools/run_packaged_smoke.py
Amberstone -- packaged artifact smoke / integration harness (PKG-4).

Validates a real Amberstone-portable-<version>.zip (tools/package_portable.py)
by:
  1. building or reusing the archive,
  2. unpacking it into a temp directory (cleaned up after),
  3. running deterministic checks against the unpacked artifact:
     [A] structure (required files and trees, one top-level folder),
     [B] exclusions (tools/build_portable.verify_bundle on the unpacked
         folder: no key file, no ops/runtime/, nothing an exclusion rule
         names, no LFS pointer, no boot / scheduled-task signature),
     [C1] manifests, [C2] bootstrap_env_check under the embedded runtime,
     [D] launch chain (start.bat -> python-embed\\pythonw.exe, the ._pth
         puts the bundle root on sys.path),
     [E] operator docs,
     [F] the backend's packages import under the embedded runtime.

No live Riot API, Anthropic API or League client. Network only if the
archive has to be built (the embedded runtime download and the lock).

Usage (from project root):
    python tools/run_packaged_smoke.py
    python tools/run_packaged_smoke.py --rebuild          (force a fresh archive)
    python tools/run_packaged_smoke.py --archive <path>   (use a specific archive)
    python tools/run_packaged_smoke.py --keep-temp        (keep the temp dir)

Exit codes:
    0   All checks passed
    1   One or more checks failed
    2   Harness setup failure (archive not found, cannot extract, etc.)
"""
import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tools import build_portable as bp  # noqa: E402
from tools import package_portable as pp  # noqa: E402

_DIST_DIR = _PROJECT_ROOT / "dist"
ARCHIVE_GLOB = f"{pp.ZIP_ROOT_NAME}-*.zip"

# What a startable bundle must carry. A test keeps every path here clear of
# build_portable's exclusion rules (the old list required the excluded
# scripts/restart_clean.bat and ops/rc_league_watcher.ps1).
REQUIRED_FILES = (
    ("start.bat", "launch script: start.bat"),
    ("install.bat", "setup script: install.bat"),
    ("main.py", "entrypoint: main.py"),
    ("web_dashboard.py", "dashboard: web_dashboard.py"),
    ("moon_vision_server.py", "vision server: moon_vision_server.py"),
    ("requirements.txt", "hashed lock: requirements.txt"),
    ("PREREQUISITES.md", "operator doc: PREREQUISITES.md"),
    (bp.MANIFEST_NAME, "build manifest: " + bp.MANIFEST_NAME),
    (pp.PACKAGE_MANIFEST, "package manifest: " + pp.PACKAGE_MANIFEST),
    ("python-embed/python.exe", "embedded runtime: python-embed/python.exe"),
    ("python-embed/pythonw.exe", "embedded runtime: python-embed/pythonw.exe"),
    ("python-embed/EMBED_STAMP.json", "embedded runtime stamp"),
    ("ops/rc_supervisor.py", "frozen supervisor: ops/rc_supervisor.py"),
    ("tools/bootstrap_env_check.py", "operator tool: bootstrap_env_check.py"),
)
REQUIRED_TREES = ("app/", "core/", "coaches/", "dashboard/", "web/", "agents/daemon_slayer/",
                  "ops/", "config/", "data/")
IMPORT_SMOKE = ("import cv2, numpy, PIL, anthropic, pydantic, websockets, psutil; "
                "import app, dashboard.server, vision_server, agents.daemon_slayer.server, "
                "web_dashboard; print('IMPORTS-OK')")

_PASS = "  PASS  "
_FAIL = "  FAIL  "
_INFO = "  INFO  "
_WARN = "  WARN  "

_failures: list = []
_passes: list = []


# -- Helpers -------------------------------------------------------------------

def reset() -> None:
    _failures.clear()
    _passes.clear()


def failures() -> list:
    return list(_failures)


def _ok(label: str, detail: str = "") -> None:
    suffix = f"  -- {detail}" if detail else ""
    print(f"{_PASS}{label}{suffix}")
    _passes.append(label)


def _fail(label: str, detail: str = "") -> None:
    suffix = f"  -- {detail}" if detail else ""
    print(f"{_FAIL}{label}{suffix}")
    _failures.append(label)


def _info(msg: str) -> None:
    print(f"{_INFO}{msg}")


def _warn(msg: str) -> None:
    print(f"{_WARN}{msg}")


def find_archive(dist_dir: Path = _DIST_DIR) -> Optional[Path]:
    """The most recent Amberstone-portable-*.zip in `dist_dir`."""
    candidates = sorted(Path(dist_dir).glob(ARCHIVE_GLOB),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _build_archive() -> Optional[Path]:
    """Run package_portable.py --rebuild-staging to produce a fresh archive."""
    result = subprocess.run(
        [sys.executable, str(_PROJECT_ROOT / "tools" / "package_portable.py"),
         "--rebuild-staging"],
        cwd=str(_PROJECT_ROOT),
    )
    if result.returncode != 0:
        print(f"  ERROR  package_portable.py exited {result.returncode}", file=sys.stderr)
        return None
    return find_archive()


# -- Check suites --------------------------------------------------------------

def check_archive_structure(entries: set) -> str:
    """A) Archive structure. Returns the top-level folder ('' if broken)."""
    print("\n[A] Archive Structure")
    top_levels = {e.split("/")[0] for e in entries if e}
    if top_levels != {pp.ZIP_ROOT_NAME}:
        _fail("single top-level folder", f"want {pp.ZIP_ROOT_NAME}/, found {sorted(top_levels)}")
        return ""
    tl = pp.ZIP_ROOT_NAME
    _ok("single top-level folder", tl)
    for rel, label in REQUIRED_FILES:
        if f"{tl}/{rel}" in entries:
            _ok(label, rel)
        else:
            _fail(label, f"missing: {rel}")
    for tree in REQUIRED_TREES:
        if any(e.startswith(f"{tl}/{tree}") for e in entries):
            _ok(f"source tree: {tree}")
        else:
            _fail(f"source tree: {tree}", "no entries found")
    return tl


def check_exclusions(bundle_root: Path, zip_path: Path) -> None:
    """B) Exclusion policy, judged by the builder's own verify_bundle."""
    print("\n[B] Exclusion Policy")
    problems = bp.verify_bundle(bundle_root)
    if problems:
        for line in problems[:20]:
            _fail("excluded content in archive", line)
    else:
        _ok("verify_bundle clean (no key file, ops/runtime, excluded path, "
            "LFS pointer or boot signature)")
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    if size_mb >= 10:
        _ok("archive size consistent with an embedded runtime", f"{size_mb:.1f} MB")
    else:
        _warn(f"archive size {size_mb:.1f} MB is unexpectedly small -- no runtime?")


def check_manifests(bundle_root: Path) -> dict:
    """C1) Manifest contents."""
    print("\n[C1] Manifest Contents")
    docs = {}
    for name in (bp.MANIFEST_NAME, pp.PACKAGE_MANIFEST):
        try:
            docs[name] = json.loads((bundle_root / name).read_text(encoding="utf-8"))
            _ok(f"{name} parseable")
        except (OSError, ValueError) as exc:
            _fail(f"{name} unreadable", str(exc))
            docs[name] = {}
    build_m = docs[bp.MANIFEST_NAME]
    if build_m.get("bundle") == bp.BUNDLE_NAME and build_m.get("build_tool") == bp.BUILD_TOOL:
        _ok("BUILD_MANIFEST names the Amberstone builder")
    else:
        _fail("BUILD_MANIFEST is not an Amberstone build", str(build_m.get("bundle")))
    py = build_m.get("python") or {}
    if py.get("mode") in ("build", "dir") and (py.get("cpython") or {}).get("version"):
        _ok("embedded runtime recorded", py["cpython"]["version"])
    else:
        _fail("no embedded runtime recorded", str(py.get("mode")))
    if docs[pp.PACKAGE_MANIFEST].get("zip_root_folder") == pp.ZIP_ROOT_NAME:
        _ok("PACKAGE_MANIFEST zip root", pp.ZIP_ROOT_NAME)
    else:
        _fail("PACKAGE_MANIFEST zip root wrong",
              str(docs[pp.PACKAGE_MANIFEST].get("zip_root_folder")))
    return docs


def check_launch_chain(bundle_root: Path) -> None:
    """D) start.bat launches the embedded runtime, which can import the root."""
    print("\n[D] Launch Chain")
    sb = bundle_root / "start.bat"
    content = sb.read_text(encoding="utf-8", errors="replace") if sb.exists() else ""
    if "python-embed\\pythonw.exe" in content:
        _ok("start.bat launches python-embed\\pythonw.exe")
    else:
        _fail("start.bat does not launch python-embed\\pythonw.exe")
    pths = sorted((bundle_root / "python-embed").glob("python3*._pth"))
    lines = pths[0].read_text(encoding="utf-8").splitlines() if pths else []
    if ".." in lines and "import site" in lines:
        _ok("._pth puts the bundle root and site-packages on sys.path", pths[0].name)
    else:
        _fail("._pth would not import the bundle root", pths[0].name if pths else "missing")


# Folders tools/bootstrap_env_check.py expects that a fresh bundle does not
# carry: the app creates them on first start (ops/runtime/ must never ship).
RUNTIME_CREATED_DIRS = ("audit/", "logs/", "ops/runtime/")
_ISSUE_PATH = re.compile(
    r"[\w.-]+(?:/[\w.-]+)*(?:\.(?:bat|ps1|py|md|vbs|xml|json|txt)\b|/)")


def _tolerated_issue(issue: str) -> Optional[str]:
    """Why a bootstrap_env_check ISSUE is expected in a bundle, else None:
    the missing key, a path the builder excludes on purpose, or a folder the
    app creates on first start."""
    if "API-Key-Claude" in issue:
        return "no key ships"
    paths = _ISSUE_PATH.findall(issue)
    why = []
    for p in paths:
        reason = bp.exclusion_reason(p + "x" if p.endswith("/") else p)
        if reason:
            why.append(f"{p} excluded on purpose ({reason})")
        elif p in RUNTIME_CREATED_DIRS:
            why.append(f"{p} is created on first start")
        else:
            return None
    return "; ".join(why) if why else None


def check_bootstrap_from_unpacked(bundle_root: Path) -> None:
    """C2) Run bootstrap_env_check.py under the embedded runtime."""
    print("\n[C2] Bootstrap Readiness from Unpacked Artifact")
    bec = bundle_root / "tools" / "bootstrap_env_check.py"
    embed_py = bundle_root / "python-embed" / "python.exe"
    if not bec.exists() or not embed_py.exists():
        _fail("bootstrap check cannot run", "bootstrap_env_check.py or python.exe missing")
        return
    try:
        result = subprocess.run([str(embed_py), str(bec)], cwd=str(bundle_root),
                                capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        _fail("bootstrap check could not run", str(exc))
        return
    output = result.stdout + result.stderr
    for needle, label in (
            ("PASS  python-embed/python.exe present", "embedded python.exe reported PASS"),
            ("PASS  python-embed/pythonw.exe present", "embedded pythonw.exe reported PASS"),
            ("PASS  embedded runtime: anthropic + Pillow importable",
             "packages importable per bootstrap")):
        (_ok if needle in output else _fail)(label)
    issues = [ln.strip() for ln in output.splitlines() if "ISSUE:" in ln]
    unexpected = []
    for issue in issues:
        why = _tolerated_issue(issue)
        if why:
            _info(f"expected bootstrap issue ({why}): {issue}")
        else:
            unexpected.append(issue)
    if unexpected:
        _fail("unexpected issues from bootstrap", str(unexpected))
    else:
        _ok(f"bootstrap issues all expected ({len(issues)})")
    _info(f"bootstrap exit code: {result.returncode}")


def check_operator_docs(bundle_root: Path) -> None:
    """E) Operator first-run docs."""
    print("\n[E] Operator Docs")
    prereq = bundle_root / "PREREQUISITES.md"
    if not prereq.exists():
        _fail("PREREQUISITES.md missing from unpacked artifact")
        return
    content = prereq.read_text(encoding="utf-8", errors="replace")
    _ok("PREREQUISITES.md present")
    for needle, label in (("embedded", "describes the embedded runtime"),
                          ("start.bat", "describes how to launch"),
                          ("not included", "lists what is intentionally not included"),
                          ("at boot", "states nothing starts at boot")):
        if needle.lower() in content.lower():
            _ok(f"PREREQUISITES.md {label}")
        else:
            _fail(f"PREREQUISITES.md missing: {label}")


def check_imports_from_unpacked(bundle_root: Path) -> None:
    """F) The backend imports under the embedded runtime. A throwaway vision
    token stands in for the per-install one PKG-1 provisions on first run
    (core/vision_token.py raises at import without one)."""
    print("\n[F] Backend Imports Under the Embedded Runtime")
    embed_py = bundle_root / "python-embed" / "python.exe"
    if not embed_py.exists():
        _fail("import smoke cannot run", "python-embed/python.exe missing")
        return
    env = dict(os.environ)
    env["RC_VISION_TOKEN"] = secrets.token_hex(16)
    try:
        result = subprocess.run([str(embed_py), "-c", IMPORT_SMOKE], cwd=str(bundle_root),
                                capture_output=True, text=True, timeout=180, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        _fail("import smoke could not run", str(exc))
        return
    if result.returncode == 0 and "IMPORTS-OK" in result.stdout:
        _ok("third-party + backend packages import from the bundle")
    else:
        tail = (result.stderr or result.stdout).strip().splitlines()[-1:] or ["no output"]
        _fail("backend import failed under the embedded runtime", tail[0])


# -- Main runner ---------------------------------------------------------------

def run(archive_path: Path, keep_temp: bool = False) -> int:
    reset()
    print("=" * 64)
    print("Amberstone -- Packaged Artifact Smoke / Integration Check")
    print(f"Archive : {archive_path.name}")
    print(f"Size    : {archive_path.stat().st_size / (1024 * 1024):.1f} MB")
    print("=" * 64)

    tmp = Path(tempfile.mkdtemp(prefix="amberstone_pkg_smoke_"))
    try:
        with zipfile.ZipFile(str(archive_path), "r") as zf:
            entries = set(zf.namelist())
            zf.extractall(str(tmp))
        _ok("archive extracted successfully", f"{len(entries)} entries")
    except (OSError, zipfile.BadZipFile) as exc:
        print(f"  ERROR  extraction failed: {exc}", file=sys.stderr)
        if not keep_temp:
            shutil.rmtree(str(tmp), ignore_errors=True)
        return 2

    tl = check_archive_structure(entries)
    if tl:
        bundle_root = tmp / tl
        check_exclusions(bundle_root, archive_path)
        check_manifests(bundle_root)
        check_launch_chain(bundle_root)
        check_operator_docs(bundle_root)
        check_bootstrap_from_unpacked(bundle_root)
        check_imports_from_unpacked(bundle_root)

    if not keep_temp:
        shutil.rmtree(str(tmp), ignore_errors=True)
        _info("Temp dir cleaned up")
    else:
        _info(f"Temp dir kept: {tmp}")

    print("\n" + "=" * 64)
    total = len(_passes) + len(_failures)
    if not _failures:
        print(f"Packaged smoke: ALL PASS  ({len(_passes)}/{total} checks)")
        return 0
    print(f"Packaged smoke: {len(_failures)} FAILURE(s) / {len(_passes)} PASS / {total} total")
    for f in _failures:
        print(f"  FAIL: {f}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Packaged artifact smoke/integration harness for Amberstone.")
    parser.add_argument("--archive", "-a", default=None,
                        help="the packaged zip to test (default: newest in dist/)")
    parser.add_argument("--rebuild", action="store_true",
                        help="force a fresh package build before running checks")
    parser.add_argument("--keep-temp", action="store_true",
                        help="keep the temp extraction directory for inspection")
    args = parser.parse_args()

    if args.archive:
        archive = Path(args.archive)
        if not archive.exists():
            print(f"  ERROR  specified archive not found: {archive.name}", file=sys.stderr)
            return 2
    elif args.rebuild:
        _info("Building fresh archive...")
        archive = _build_archive()
        if not archive:
            print("  ERROR  archive build failed", file=sys.stderr)
            return 2
    else:
        archive = find_archive()
        if not archive:
            _info("No existing archive found -- building now...")
            archive = _build_archive()
            if not archive:
                print("  ERROR  no archive available and build failed", file=sys.stderr)
                return 2
        else:
            _info(f"Using existing archive: {archive.name}")

    return run(archive, keep_temp=args.keep_temp)


if __name__ == "__main__":
    sys.exit(main())
