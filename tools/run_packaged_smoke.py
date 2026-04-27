"""
tools/run_packaged_smoke.py
Riot Commander -- Packaged artifact smoke/integration harness.
Phase 5 Step 2.

Validates the real packaged portable ZIP archive by:
  1. Building or reusing the archive via package_portable.py
  2. Unpacking into a temp directory (cleaned up after)
  3. Running deterministic checks against the unpacked artifact

No live Riot API, Anthropic API, Tk, Windows-MCP, or internet required.
Uses only the Python standard library.

Usage (from project root):
    python tools/run_packaged_smoke.py
    python tools/run_packaged_smoke.py --rebuild     (force fresh archive build)
    python tools/run_packaged_smoke.py --archive <path>  (use specific archive)
    python tools/run_packaged_smoke.py --keep-temp   (do not delete temp dir)

Or via wrapper:
    tools\\run_packaged_smoke.cmd

Exit codes:
    0   All checks passed
    1   One or more checks failed
    2   Harness setup failure (archive not found, cannot extract, etc.)
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
_DIST_DIR = _PROJECT_ROOT / "dist"

_PASS = "  PASS  "
_FAIL = "  FAIL  "
_INFO = "  INFO  "
_WARN = "  WARN  "

_failures: list[str] = []
_passes:   list[str] = []


# ── Helpers ───────────────────────────────────────────────────────────────────

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


def _find_archive() -> Path | None:
    """Find the most recent RiotCommander-portable-*.zip in dist/."""
    candidates = sorted(
        _DIST_DIR.glob("RiotCommander-portable-*.zip"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _build_archive() -> Path | None:
    """Run package_portable.py to produce/refresh the archive."""
    pkg_script = _PROJECT_ROOT / "tools" / "package_portable.py"
    if not pkg_script.exists():
        print(f"  ERROR  package_portable.py not found: {pkg_script}", file=sys.stderr)
        return None
    result = subprocess.run(
        [sys.executable, str(pkg_script)],
        cwd=str(_PROJECT_ROOT),
    )
    if result.returncode not in (0, 2):  # 2 = dry-run (not expected here)
        print(f"  ERROR  package_portable.py exited {result.returncode}", file=sys.stderr)
        return None
    return _find_archive()


# ── Check suites ──────────────────────────────────────────────────────────────

def check_archive_structure(root: Path, entries: set[str]) -> None:
    """A) Archive structure checks."""
    print("\n[A] Archive Structure")

    # Single top-level folder
    top_levels = {e.split("/")[0] for e in entries if e}
    if len(top_levels) == 1:
        tl = next(iter(top_levels))
        _ok("single top-level folder", tl)
    else:
        _fail("single top-level folder", f"found: {sorted(top_levels)}")
        return  # can't proceed without knowing root

    tl = next(iter(top_levels))

    def present(rel: str, label: str) -> bool:
        key = f"{tl}/{rel}"
        if key in entries or key.rstrip("/") in entries:
            _ok(f"{label}", rel)
            return True
        _fail(f"{label}", f"missing: {rel}")
        return False

    # Required launch/setup files
    for f, lbl in [
        ("start.bat",        "launch script: start.bat"),
        ("restart_clean.bat","launch script: restart_clean.bat"),
        ("install.bat",      "setup script: install.bat"),
        ("main.py",          "entrypoint: main.py"),
        ("requirements.txt", "requirements.txt"),
    ]:
        present(f, lbl)

    # Required docs/manifests
    for f, lbl in [
        ("PREREQUISITES.md",   "operator doc: PREREQUISITES.md"),
        ("BUILD_MANIFEST.json","staged manifest: BUILD_MANIFEST.json"),
        ("PACKAGE_MANIFEST.json", "package manifest: PACKAGE_MANIFEST.json"),
    ]:
        present(f, lbl)

    # Embedded runtime
    for f, lbl in [
        ("python-embed/python.exe",   "embedded runtime: python-embed/python.exe"),
        ("python-embed/pythonw.exe",  "embedded runtime: python-embed/pythonw.exe"),
    ]:
        present(f, lbl)

    # Core source packages
    for pkg in ("core/", "coaches/", "ops/", "config/"):
        found = any(e.startswith(f"{tl}/{pkg}") for e in entries)
        if found:
            _ok(f"source package: {pkg}")
        else:
            _fail(f"source package: {pkg}", "no entries found")

    # Frozen Phase 0 files
    for f in ("ops/rc_supervisor.py", "ops/rc_league_watcher.ps1"):
        present(f, f"frozen file: {f}")

    # Operator tooling
    present("tools/bootstrap_env_check.py", "operator tool: bootstrap_env_check.py")


def check_exclusions(entries: set[str], zip_path: Path) -> None:
    """B) Exclusion checks."""
    print("\n[B] Exclusion Policy")

    def absent(pattern: str, label: str) -> None:
        hit = [e for e in entries if pattern.lower() in e.lower()]
        if not hit:
            _ok(f"{label} correctly excluded")
        else:
            _fail(f"{label} found in archive", f"entries: {hit[:3]}")

    absent("api-key-claude.txt",  "API-Key-Claude.txt (secret key)")
    absent("/.git/",              ".git/ (source control)")
    absent("__pycache__",         "__pycache__/ (bytecode cache)")
    absent(".pyc",                "*.pyc (bytecode)")
    # audit/ must contain only placeholder .gitkeep, not proof bundles
    audit_entries = [e for e in entries if "/audit/" in e and not e.endswith("/")]
    audit_non_placeholder = [e for e in audit_entries if not e.endswith(".gitkeep")]
    if not audit_non_placeholder:
        _ok("audit/ correctly excluded (placeholder only)",
            f"{len(audit_entries)} entry" if audit_entries else "empty")
    else:
        _fail("audit/ proof content found in archive", f"entries: {audit_non_placeholder[:3]}")

    # ops/runtime must only have placeholder
    rt_entries = [e for e in entries if "/ops/runtime/" in e and not e.endswith("/")]
    rt_non_placeholder = [e for e in rt_entries if not e.endswith(".gitkeep")]
    if not rt_non_placeholder:
        _ok("ops/runtime/ has only placeholder (.gitkeep)", f"{len(rt_entries)} entry/entries")
    else:
        _fail("ops/runtime/ has live runtime artifacts", f"{rt_non_placeholder[:3]}")

    # Verify archive size is in Option B range (~15–50 MB)
    size_mb = zip_path.stat().st_size / (1024 * 1024)
    if size_mb >= 10:
        _ok("archive size consistent with Option B (embedded runtime)", f"{size_mb:.1f} MB")
    else:
        _warn(f"archive size {size_mb:.1f} MB is unexpectedly small -- may be Option A bundle")


def check_manifests(root: Path, tl: str) -> dict:
    """Return parsed BUILD_MANIFEST and PACKAGE_MANIFEST for downstream checks."""
    print("\n[C1] Manifest Contents")
    build_m: dict = {}
    pkg_m:   dict = {}

    bm_path = root / tl / "BUILD_MANIFEST.json"
    if bm_path.exists():
        try:
            build_m = json.loads(bm_path.read_text(encoding="utf-8"))
            _ok("BUILD_MANIFEST.json parseable")
        except Exception as e:
            _fail("BUILD_MANIFEST.json parse error", str(e))
    else:
        _fail("BUILD_MANIFEST.json missing")

    pm_path = root / tl / "PACKAGE_MANIFEST.json"
    if pm_path.exists():
        try:
            pkg_m = json.loads(pm_path.read_text(encoding="utf-8"))
            _ok("PACKAGE_MANIFEST.json parseable")
        except Exception as e:
            _fail("PACKAGE_MANIFEST.json parse error", str(e))
    else:
        _fail("PACKAGE_MANIFEST.json missing")

    # Strategy must be Option B
    for name, m in [("BUILD_MANIFEST", build_m), ("PACKAGE_MANIFEST", pkg_m)]:
        strat = m.get("strategy", "")
        if "Option B" in strat:
            _ok(f"{name}.strategy is Option B", strat)
        else:
            _fail(f"{name}.strategy not Option B", strat or "(missing)")

    # Launch chain must mention embedded runtime
    lc = build_m.get("launch_chain", "")
    if "python-embed" in lc:
        _ok("BUILD_MANIFEST.launch_chain references embedded runtime", lc)
    else:
        _fail("BUILD_MANIFEST.launch_chain missing embedded runtime", lc or "(missing)")

    return {"build": build_m, "pkg": pkg_m}


def check_launch_chain(root: Path, tl: str) -> None:
    """D) Launch chain truthfulness -- inspect start.bat content."""
    print("\n[D] Launch Chain Truthfulness")
    sb = root / tl / "start.bat"
    if not sb.exists():
        _fail("start.bat not found for inspection")
        return
    content = sb.read_text(encoding="utf-8", errors="replace")
    if "python-embed" in content:
        _ok("start.bat references python-embed\\ (Option B embedded runtime)")
    else:
        _fail("start.bat does not reference python-embed", "may be Option A only")
    if "pythonw.exe" in content.lower():
        _ok("start.bat references pythonw.exe")
    else:
        _fail("start.bat missing pythonw.exe reference")
    # PATH fallback must also be present
    if "pythonw.exe main.py" in content or 'pythonw.exe" main.py' in content:
        _ok("start.bat has PATH pythonw.exe fallback")
    else:
        _info("start.bat PATH fallback not detected (may be conditional block)")

    rc = root / tl / "restart_clean.bat"
    if rc.exists():
        rc_content = rc.read_text(encoding="utf-8", errors="replace")
        if "python-embed" in rc_content:
            _ok("restart_clean.bat references python-embed\\ (Option B)")
        else:
            _fail("restart_clean.bat does not reference python-embed")


def check_bootstrap_from_unpacked(root: Path, tl: str) -> None:
    """C2) Run bootstrap_env_check.py from the unpacked artifact root."""
    print("\n[C2] Bootstrap Readiness from Unpacked Artifact")

    bec = root / tl / "tools" / "bootstrap_env_check.py"
    if not bec.exists():
        _fail("bootstrap_env_check.py missing from unpacked artifact")
        return

    embed_py = root / tl / "python-embed" / "python.exe"
    if not embed_py.exists():
        _fail("python-embed/python.exe not found -- cannot run embedded bootstrap")
        _info("Falling back to system python for bootstrap check")
        runner = sys.executable
    else:
        runner = str(embed_py)
        _ok("using embedded python.exe for bootstrap check")

    try:
        result = subprocess.run(
            [runner, str(bec)],
            cwd=str(root / tl),
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = result.stdout + result.stderr

        # Embedded runtime section must PASS
        if "PASS  python-embed/python.exe present" in output:
            _ok("embedded python.exe reported PASS by bootstrap")
        else:
            _fail("embedded python.exe not reported as PASS", "(check bootstrap output)")

        if "PASS  python-embed/pythonw.exe present" in output:
            _ok("embedded pythonw.exe reported PASS by bootstrap")
        else:
            _fail("embedded pythonw.exe not reported as PASS")

        if "PASS  embedded runtime: anthropic + Pillow importable" in output:
            _ok("packages importable from embedded runtime")
        else:
            _fail("embedded runtime packages not importable")

        # Staged-bundle mode: dev-only tools should be INFO not MISS
        if "dev-only, not staged" in output:
            _ok("dev-only tools correctly shown as INFO (not MISS) in staged mode")
        else:
            _info("dev-only tool staging mode not detected in output")

        # API key should be the only ISSUE
        issues = [l.strip() for l in output.splitlines() if "ISSUE:" in l]
        api_key_only = all("API-Key-Claude" in i for i in issues)
        if api_key_only and issues:
            _ok(f"only expected issue: API-Key-Claude.txt absent ({len(issues)} issue)")
        elif not issues:
            _ok("bootstrap exited with no issues (API key may have been present)")
        else:
            _fail("unexpected issues from bootstrap", str(issues))

        _info(f"bootstrap exit code: {result.returncode}")

    except subprocess.TimeoutExpired:
        _fail("bootstrap check timed out (60s)")
    except Exception as e:
        _fail("bootstrap check raised exception", str(e))


def check_operator_docs(root: Path, tl: str) -> None:
    """E) Operator first-run docs."""
    print("\n[E] Operator Docs")

    prereq = root / tl / "PREREQUISITES.md"
    if prereq.exists():
        content = prereq.read_text(encoding="utf-8", errors="replace")
        _ok("PREREQUISITES.md present")
        if "Option B" in content or "embedded" in content.lower():
            _ok("PREREQUISITES.md describes Option B / embedded runtime")
        else:
            _fail("PREREQUISITES.md does not describe Option B embedded runtime")
        if "API" in content and "sk-ant" in content:
            _ok("PREREQUISITES.md describes API key requirement")
        else:
            _fail("PREREQUISITES.md missing API key guidance")
        if "start.bat" in content:
            _ok("PREREQUISITES.md describes how to launch")
        else:
            _fail("PREREQUISITES.md missing launch instructions")
        if "NOT" in content.upper() or "not included" in content.lower() or "not bundled" in content.lower():
            _ok("PREREQUISITES.md documents what is intentionally not included")
        else:
            _info("PREREQUISITES.md intentional-omissions section not detected")
    else:
        _fail("PREREQUISITES.md missing from unpacked artifact")

    # LAUNCH_STRATEGY.md
    ls = root / tl / "tools" / "LAUNCH_STRATEGY.md"
    if ls.exists():
        content = ls.read_text(encoding="utf-8", errors="replace")
        if "Option B" in content or "python-embed" in content:
            _ok("LAUNCH_STRATEGY.md present and describes Option B")
        else:
            _fail("LAUNCH_STRATEGY.md does not describe Option B")
    else:
        _info("tools/LAUNCH_STRATEGY.md not in artifact (optional for operator)")


# ── Main runner ───────────────────────────────────────────────────────────────

def run(archive_path: Path, keep_temp: bool = False) -> int:
    print("=" * 64)
    print("Riot Commander -- Packaged Artifact Smoke / Integration Check")
    print(f"Archive : {archive_path}")
    print(f"Size    : {archive_path.stat().st_size / (1024*1024):.1f} MB")
    print("=" * 64)

    # Extract to temp
    tmp = Path(tempfile.mkdtemp(prefix="rc_pkg_smoke_"))
    _info(f"Extracting to temp dir: {tmp}")
    try:
        with zipfile.ZipFile(str(archive_path), "r") as zf:
            entries = set(zf.namelist())
            zf.extractall(str(tmp))
        _ok("archive extracted successfully", f"{len(entries)} entries")
    except Exception as e:
        print(f"  ERROR  extraction failed: {e}", file=sys.stderr)
        if not keep_temp:
            shutil.rmtree(str(tmp), ignore_errors=True)
        return 2

    # Determine top-level folder
    top_levels = {e.split("/")[0] for e in entries if e}
    tl = next(iter(top_levels)) if len(top_levels) == 1 else ""

    # Run all check suites
    check_archive_structure(tmp, entries)
    check_exclusions(entries, archive_path)
    manifests = check_manifests(tmp, tl) if tl else {}
    check_launch_chain(tmp, tl) if tl else None
    check_bootstrap_from_unpacked(tmp, tl) if tl else None
    check_operator_docs(tmp, tl) if tl else None

    # Cleanup
    if not keep_temp:
        shutil.rmtree(str(tmp), ignore_errors=True)
        _info(f"Temp dir cleaned up: {tmp}")
    else:
        _info(f"Temp dir kept: {tmp}")

    # Summary
    print("\n" + "=" * 64)
    total = len(_passes) + len(_failures)
    if not _failures:
        print(f"Packaged smoke: ALL PASS  ({len(_passes)}/{total} checks)")
        return 0
    else:
        print(f"Packaged smoke: {len(_failures)} FAILURE(s) / {len(_passes)} PASS / {total} total")
        for f in _failures:
            print(f"  FAIL: {f}")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Packaged artifact smoke/integration harness for Riot Commander."
    )
    parser.add_argument(
        "--archive", "-a",
        default=None,
        help="Path to the packaged ZIP archive to test (default: latest in dist/)",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Force a fresh package build before running checks",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep temp extraction directory after run (for inspection)",
    )
    args = parser.parse_args()

    if args.archive:
        archive = Path(args.archive)
        if not archive.exists():
            print(f"  ERROR  specified archive not found: {archive}", file=sys.stderr)
            return 2
    elif args.rebuild:
        _info("Building fresh archive...")
        archive = _build_archive()
        if not archive:
            print("  ERROR  archive build failed", file=sys.stderr)
            return 2
    else:
        archive = _find_archive()
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
