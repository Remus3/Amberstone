"""
tools/build_portable.py
Riot Commander -- Portable staging bundle builder.
Phase 4 Step 3 / Phase 5 Step 1.

Builds a staged portable bundle according to the strategy documented in
tools/PYTHON_BUNDLING_STRATEGY.md and tools/DISTRIBUTION_LAYOUT.md.

Current strategy: Option B (embedded Python 3.11 runtime) when python-embed/
is present at the project root. Falls back to Option A (prerequisite Python)
if python-embed/ is absent. Strategy is detected at build time and recorded
in BUILD_MANIFEST.json and PREREQUISITES.md.

The staged output is a self-contained folder ready for packaging.

Usage (from project root):
    python tools/build_portable.py
    python tools/build_portable.py --output dist/portable_staging
    python tools/build_portable.py --dry-run

Or via wrapper:
    tools\\build_portable.cmd

Output:
    dist/portable_staging/    (default; override with --output)

Exit codes:
    0   Staged output produced successfully
    1   Build failed (missing required source, copy error, etc.)
    2   Dry-run mode: would succeed (no output written)
"""
import argparse
import datetime
import json
import shutil
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
_DEFAULT_OUTPUT = _PROJECT_ROOT / "dist" / "portable_staging"

# ── Inclusion rules ───────────────────────────────────────────────────────────
#
# Strategy: portable staging bundle (current baseline: Option B when python-embed/ present, Option A fallback otherwise)
#   - All Python source packages
#   - All launch/setup scripts
#   - All config files (no secrets)
#   - All frozen ops files
#   - Operator tooling docs and launch docs
#   - Runtime directory placeholders (empty, with .gitkeep)
#
# Excluded:
#   - API-Key-Claude.txt  (secret -- user must supply)
#   - audit/              (proof bundles: dev-only, not deployed)
#   - logs/               (transient runtime logs)
#   - __pycache__/        (bytecode cache: recreated at runtime)
#   - *.pyc / *.pyo       (bytecode: recreated at runtime)
#   - .git/               (source control: not for distribution)
#   - dist/               (the output itself: prevent self-copy)
#   - *.tmp               (transient temp files)
#   - data/*.json         (runtime coaching artifacts: generated at runtime)
#   - ops/runtime/        (supervisor/heartbeat artifacts: ACTIVELY EXCLUDED -- placeholder only)

# Top-level Python source files to include
_ROOT_PY_FILES = [
    "main.py",
    "app.py",
    "overlay.py",
    "item_advisor.py",
    "performance_tracker.py",
    "composition_advisor.py",
    "champion_profiles.py",
    "role_profiles.py",
    "coaching_timestamps.py",
    # arch: phase 2.4 (2026-05-09) — vision server entrypoint shim (real code in vision_server/)
    # Listed here because RC-VisionServer scheduled task and dashboard/server.py
    # spawn this file by path.
    "moon_vision_server.py",
]

# Top-level launcher / setup scripts
_ROOT_BAT_FILES = [
    "start.bat",
    "restart_clean.bat",
    "install.bat",
    "restart.bat",
    "kill.bat",
    "start_debug.bat",
    "run_watchdog.bat",
    "requirements.txt",
]

# Source packages to copy entirely (excluding __pycache__)
_SOURCE_PACKAGES = [
    "core",
    "coaches",
    "coach_integration",
    "game_reader",
    "vision_server",
    "tft",
    "ui",
    "lcu",
    "modes",
    "ops",     # includes frozen Phase 0 files
]

# Embedded Python runtime directory (Option B)
# Included when present; contains python.exe, pythonw.exe, Lib/site-packages/
_EMBED_PYTHON_DIR = "python-embed"

# Config files to include (no secrets)
_CONFIG_INCLUDES = [
    "config/feature_flags.json",
    "config/coach_settings.json",
    "config/FEATURE_POLICY.md",
    "config/CONFIG_AUTHORITY.md",
    "config/settings.json",
    "config/self_monitor_profile.json",
    "config/rc_config.json",    # also at ops/ -- include both if present
]

# Operator docs to include
_DOC_FILES = [
    "tools/LAUNCH_STRATEGY.md",
    "tools/DEV_WORKFLOW.md",
    "tools/DISTRIBUTION_LAYOUT.md",
    "tools/PYTHON_BUNDLING_STRATEGY.md",
    "tools/bootstrap_env_check.py",
    "tools/bootstrap_env_check.cmd",
    "tools/dev_cli.py",
    "tools/dev_cli.cmd",
]

# Runtime directories to create as empty placeholders
_RUNTIME_DIRS = [
    "data",
    "logs",
    "audit",
    "ops/runtime",
]

# Explicit exclusion: these must never appear in staged output
_NEVER_INCLUDE = {
    "API-Key-Claude.txt",   # secret
    ".git",
    "__pycache__",
    "dist",
    "build",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _info(msg: str) -> None:
    print(f"  INFO    {msg}")

def _ok(msg: str) -> None:
    print(f"  OK      {msg}")

def _warn(msg: str) -> None:
    print(f"  WARN    {msg}")

def _err(msg: str) -> None:
    print(f"  ERROR   {msg}", file=sys.stderr)


def _copy_file(src: Path, dst: Path, dry: bool) -> bool:
    """Copy src to dst, creating parent dirs. Returns True on success."""
    if not src.exists():
        return False
    if not dry:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))
    return True


def _copy_package(src_dir: Path, dst_dir: Path, dry: bool) -> int:
    """
    Recursively copy a source package directory, skipping excluded paths.
    Returns number of files copied.
    """
    count = 0
    if not src_dir.exists():
        _warn(f"package not found, skipping: {src_dir.name}/")
        return 0
    for src_file in src_dir.rglob("*"):
        # Skip excluded directories/files
        parts = src_file.parts
        if any(excl in parts for excl in _NEVER_INCLUDE):
            continue
        if src_file.suffix in (".pyc", ".pyo", ".tmp"):
            continue
        if not src_file.is_file():
            continue
        # Explicitly skip ops/runtime contents -- these are live runtime artifacts,
        # not source files.  The placeholder is created separately by _write_gitkeep.
        try:
            rel = src_file.relative_to(_PROJECT_ROOT)
            rel_parts = rel.parts
            if len(rel_parts) >= 2 and rel_parts[0] == "ops" and rel_parts[1] == "runtime":
                continue
        except ValueError:
            pass
        rel = src_file.relative_to(_PROJECT_ROOT)
        dst_file = dst_dir / rel
        if not dry:
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src_file), str(dst_file))
        count += 1
    return count


def _write_gitkeep(path: Path, dry: bool) -> None:
    """Create an empty .gitkeep in a runtime placeholder directory."""
    if not dry:
        path.mkdir(parents=True, exist_ok=True)
        gk = path / ".gitkeep"
        if not gk.exists():
            gk.write_text(
                "# This directory is created by the build step as a placeholder.\n"
                "# It will be populated at runtime.\n",
                encoding="utf-8",
            )


# ── Build ─────────────────────────────────────────────────────────────────────

def build(output_dir: Path, dry: bool = False) -> int:
    """
    Produce the staged portable bundle. Returns 0 on success, 1 on failure.
    """
    # Detect strategy before printing banner (truthful output)
    _embed_src_check = _PROJECT_ROOT / _EMBED_PYTHON_DIR
    _pre_strategy = (
        "Option B -- embedded Python runtime"
        if _embed_src_check.exists()
        else "Option A -- prerequisite Python on PATH (no embedded runtime)"
    )
    print("=" * 64)
    print("Riot Commander -- build_portable.py")
    print(f"Strategy : {_pre_strategy}")
    print(f"Output   : {output_dir}")
    print(f"Dry-run  : {dry}")
    print("=" * 64)

    # Validate source root
    if not (_PROJECT_ROOT / "main.py").exists():
        _err(f"Project root not found or missing main.py: {_PROJECT_ROOT}")
        return 1

    # Safety: refuse to stage into the project root itself
    try:
        output_dir.resolve().relative_to(_PROJECT_ROOT.resolve())
        # output_dir is inside project root -- that's fine (dist/ is excluded)
    except ValueError:
        pass  # output_dir is outside project root -- also fine

    if output_dir.resolve() == _PROJECT_ROOT.resolve():
        _err("Output dir cannot be the project root")
        return 1

    # Wipe and recreate output dir
    if not dry:
        if output_dir.exists():
            shutil.rmtree(str(output_dir))
        output_dir.mkdir(parents=True, exist_ok=True)

    included_files: list[str] = []
    errors: list[str] = []

    # ── Root .py files ────────────────────────────────────────────────────────
    strategy_label = "Option A -- prerequisite Python on PATH (no embedded runtime)"  # updated below
    print("\n[Root Python files]")
    for name in _ROOT_PY_FILES:
        src = _PROJECT_ROOT / name
        if src.exists():
            ok = _copy_file(src, output_dir / name, dry)
            if ok:
                _ok(name)
                included_files.append(name)
            else:
                _warn(f"copy failed: {name}")
        else:
            _info(f"optional, not found: {name}")

    # ── Root launcher / setup files ───────────────────────────────────────────
    print("\n[Launchers and setup]")
    for name in _ROOT_BAT_FILES:
        src = _PROJECT_ROOT / name
        if src.exists():
            ok = _copy_file(src, output_dir / name, dry)
            if ok:
                _ok(name)
                included_files.append(name)
        else:
            _info(f"optional, not found: {name}")

    # ── Source packages ───────────────────────────────────────────────────────
    # ── Embedded Python runtime (Option B) ─────────────────────────────────
    print("\n[Embedded Python runtime (Option B)]")
    embed_src = _PROJECT_ROOT / _EMBED_PYTHON_DIR
    if embed_src.exists():
        n = _copy_package(embed_src, output_dir, dry)
        _ok(f"{_EMBED_PYTHON_DIR}/  ({n} files)  -- Option B embedded runtime")
        included_files.append(f"{_EMBED_PYTHON_DIR}/")
        strategy_label = "Option B -- embedded Python runtime"
    else:
        _warn(f"{_EMBED_PYTHON_DIR}/ not found -- staging as Option A (PATH Python required)")
        strategy_label = "Option A -- prerequisite Python on PATH (no embedded runtime)"

    # ── Source packages ───────────────────────────────────────────────────
    print("\n[Source packages]")
    for pkg in _SOURCE_PACKAGES:
        src_dir = _PROJECT_ROOT / pkg
        n = _copy_package(src_dir, output_dir, dry)
        if n > 0:
            _ok(f"{pkg}/  ({n} files)")
            included_files.append(f"{pkg}/")
        elif src_dir.exists():
            _warn(f"{pkg}/  (0 files copied -- check exclusion rules)")
        else:
            _info(f"{pkg}/  (not found, skipping)")

    # ── Config files ──────────────────────────────────────────────────────────
    print("\n[Config files]")
    for rel in _CONFIG_INCLUDES:
        src = _PROJECT_ROOT / rel
        if src.exists():
            ok = _copy_file(src, output_dir / rel, dry)
            if ok:
                _ok(rel)
                included_files.append(rel)
        else:
            _info(f"optional, not found: {rel}")

    # ops/rc_config.json lives in ops/ which is already covered by _SOURCE_PACKAGES
    # but also sometimes at config/ -- handled above.

    # ── Operator docs and tooling ─────────────────────────────────────────────
    print("\n[Operator docs and tooling]")
    for rel in _DOC_FILES:
        src = _PROJECT_ROOT / rel
        if src.exists():
            ok = _copy_file(src, output_dir / rel, dry)
            if ok:
                _ok(rel)
                included_files.append(rel)
        else:
            _info(f"optional, not found: {rel}")

    # ── Secret exclusion verification ─────────────────────────────────────────
    print("\n[Exclusion verification]")
    secret = output_dir / "API-Key-Claude.txt"
    audit_dir = output_dir / "audit"
    git_dir = output_dir / ".git"
    for path, label in [(secret, "API-Key-Claude.txt"), (audit_dir, "audit/"), (git_dir, ".git/")]:
        if not dry and path.exists():
            _err(f"EXCLUDED item found in output -- removing: {label}")
            if path.is_dir():
                shutil.rmtree(str(path))
            else:
                path.unlink()
            errors.append(f"had to remove excluded item: {label}")
        else:
            _ok(f"{label} correctly excluded")

    # ── Runtime directory placeholders ────────────────────────────────────────
    # Run AFTER exclusion verification so placeholders are never wiped.
    print("\n[Runtime directory placeholders]")
    for rel in _RUNTIME_DIRS:
        p = output_dir / rel
        _write_gitkeep(p, dry)
        _ok(f"{rel}/  (placeholder)")
        included_files.append(f"{rel}/")

    # ── Prerequisite note file ────────────────────────────────────────────────
    print("\n[PREREQUISITES.md]")
    prereq_content_b = """\
# PREREQUISITES.md
# Riot Commander -- Portable Bundle Prerequisites
# Strategy: Option B (embedded Python runtime)
# Generated by: tools/build_portable.py

## Python Runtime

  This bundle includes an embedded Python 3.11 runtime (python-embed/).
  You do NOT need to install Python separately for normal application launch.

## Required Before First Launch

  1. Run install.bat (first time only)
     - Verifies packages in embedded runtime
     - Creates runtime directories (data/, logs/, config/)
     - Validates API key format

  2. Edit API-Key-Claude.txt with your Anthropic API key
     - The key must start with sk-ant-
     - Get your key at: https://console.anthropic.com/keys

## After Setup Is Complete

  Launch:       start.bat  (uses embedded python-embed\\pythonw.exe)
  Clean start:  restart_clean.bat
  Diagnostics:  python-embed\\python.exe tools\\bootstrap_env_check.py
  Operator CLI: python-embed\\python.exe tools\\dev_cli.py status

## What Is NOT Included in This Bundle

  - API-Key-Claude.txt (supply your own key)
  - Python packages are PRE-INSTALLED in python-embed/ Lib/site-packages/
  - Runtime coaching artifacts (generated at runtime)
  - Audit/proof bundles (dev-only)

## Note on Ops Supervisor Stack

  The background watchdog scripts (ops/*.ps1) call python by PATH name.
  For the ops supervisor stack to work, system Python must be on PATH.
  Normal application launch (start.bat) does NOT require system Python.

## Python Bundling Status

  Current strategy: Option B -- embedded Python 3.11 runtime included.
  See tools/PYTHON_BUNDLING_STRATEGY.md for details.
"""
    prereq_content_a = """\
# PREREQUISITES.md
# Riot Commander -- Portable Bundle Prerequisites
# Strategy: Option A (prerequisite Python)
# Generated by: tools/build_portable.py

## Required Before Running

  1. Python 3.9 or newer installed
     - Download: https://python.org/downloads
     - During install: check "Add Python to PATH"
     - Verify: python --version

  2. Run install.bat (first time only)
     - Installs required Python packages (anthropic, Pillow)
     - Creates runtime directories (data/, logs/, config/)
     - Validates API key format

  3. Edit API-Key-Claude.txt with your Anthropic API key
     - The key must start with sk-ant-
     - Get your key at: https://console.anthropic.com/keys

## After Prerequisites Are Met

  Launch:       start.bat
  Clean start:  restart_clean.bat
  Diagnostics:  python tools/bootstrap_env_check.py
  Operator CLI: python tools/dev_cli.py status

## What Is NOT Included in This Bundle

  - API-Key-Claude.txt (supply your own key)
  - Python interpreter (install separately)
  - Python packages (run install.bat)
  - Runtime coaching artifacts (generated at runtime)
  - Audit/proof bundles (dev-only)

## Python Bundling Status

  Current strategy: Option A -- prerequisite Python install.
  See tools/PYTHON_BUNDLING_STRATEGY.md for details.
"""
    prereq_content = prereq_content_b if strategy_label.startswith("Option B") else prereq_content_a
    prereq_path = output_dir / "PREREQUISITES.md"
    if not dry:
        prereq_path.write_text(prereq_content, encoding="utf-8")
    _ok("PREREQUISITES.md written")
    included_files.append("PREREQUISITES.md")

    # ── Build manifest ────────────────────────────────────────────────────────
    print("\n[BUILD_MANIFEST.json]")
    manifest = {
        "build_tool":       "tools/build_portable.py",
        "build_timestamp":  datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "strategy":         strategy_label,
        "strategy_doc":     "tools/PYTHON_BUNDLING_STRATEGY.md",
        "layout_doc":       "tools/DISTRIBUTION_LAYOUT.md",
        "output_path":      str(output_dir),
        "project_root":     str(_PROJECT_ROOT),
        "dry_run":          dry,
        "included_toplevel": sorted(set(
            p.split("/")[0] for p in included_files
        )),
        "included_files_count": len(included_files),
        "excluded_categories": [
            "API-Key-Claude.txt  (secret -- user must supply)",
            "audit/              (proof bundles: dev-only, not deployed)",
            "logs/               (transient runtime logs: generated at runtime)",
            "__pycache__/        (bytecode cache: recreated at runtime)",
            ".git/               (source control: not for distribution)",
            "dist/               (build output: prevents self-copy)",
            "*.pyc / *.pyo       (bytecode: recreated at runtime)",
            "*.tmp               (transient temp files)",
            "data/*.json         (coaching artifacts: generated at runtime)",
            "ops/runtime/        (supervisor artifacts: generated at runtime)",
        ],
        "runtime_dirs_created": _RUNTIME_DIRS,
        "prerequisites": (
            {
                "python_embed": "included -- python-embed/ in bundle (Python 3.11)",
                "pythonw_embed": "included -- python-embed/pythonw.exe used for launch",
                "api_key": "API-Key-Claude.txt must be supplied by operator",
                "ops_ps1_path_python": "PATH python advisory for frozen ops/.ps1 scripts",
            } if strategy_label.startswith("Option B") else {
                "python": "3.9+ on PATH",
                "pythonw": "on PATH (same installation as python)",
                "pip": "accessible via python -m pip",
                "internet": "required for initial install.bat pip step",
            }
        ),
        "launch_chain": (
            "start.bat -> python-embed/pythonw.exe main.py  (fallback: PATH pythonw.exe)"
            if strategy_label.startswith("Option B")
            else "start.bat -> PATH pythonw.exe main.py"
        ),
        "install_chain": (
            "install.bat -> verify embedded packages (install if missing)"
            if strategy_label.startswith("Option B")
            else "install.bat -> python -m pip install -r requirements.txt"
        ),
        "warnings_if_any": errors,
    }
    manifest_path = output_dir / "BUILD_MANIFEST.json"
    if not dry:
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _ok(f"BUILD_MANIFEST.json written  ({len(included_files)} files staged)")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 64)
    if errors:
        print(f"Build completed with {len(errors)} warning(s):")
        for e in errors:
            print(f"  WARN: {e}")
        return 0  # warnings don't fail the build

    if dry:
        print("Dry-run complete: would succeed. No output written.")
        return 2

    print(f"Build complete: {output_dir}")
    print(f"  {len(included_files)} files/dirs staged")
    print("  Run: python tools/bootstrap_env_check.py  (from staged root)")
    print("  Run: install.bat  (first time setup)")
    print("  Run: start.bat  (launch)")
    return 0


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a portable staging bundle for Riot Commander."
    )
    parser.add_argument(
        "--output", "-o",
        default=str(_DEFAULT_OUTPUT),
        help=f"Output directory (default: {_DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Validate and report without writing any output",
    )
    args = parser.parse_args()

    output_dir = Path(args.output)
    return build(output_dir, dry=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
