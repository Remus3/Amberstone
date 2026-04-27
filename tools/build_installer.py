"""
tools/build_installer.py
Riot Commander -- Installer staging builder.
Phase 5 Step 3.

Produces a guided-setup installer artifact from the validated portable archive.
This is the FIRST installer/distribution step above the portable ZIP.
It does NOT use NSIS/MSIX/Inno (not yet in scope).

What it produces:
  dist/installer_staging/
    setup.bat              -- guided first-run setup launcher
    RiotCommander-portable-<date>.zip  -- the validated portable archive (copied)
    INSTALL_README.md      -- operator-facing install guide
    INSTALL_MANIFEST.json  -- machine-readable installer metadata

The operator receives the installer_staging/ folder (or a ZIP of it).
They run setup.bat which:
  1. Extracts the portable archive to a chosen location
  2. Calls install.bat for first-time setup (API key, package verify)
  3. Confirms readiness via bootstrap_env_check.py

Usage (from project root):
    python tools/build_installer.py
    python tools/build_installer.py --output dist/installer_staging
    python tools/build_installer.py --dry-run

Or via wrapper:
    tools\\build_installer.cmd

Exit codes:
    0   Installer staging produced successfully
    1   Build failed
    2   Dry-run: would succeed (no output written)
"""
import argparse
import datetime
import json
import shutil
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
_DIST_DIR = _PROJECT_ROOT / "dist"
_DEFAULT_OUTPUT = _DIST_DIR / "installer_staging"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _info(msg): print(f"  INFO    {msg}")
def _ok(msg):   print(f"  OK      {msg}")
def _warn(msg): print(f"  WARN    {msg}")
def _err(msg):  print(f"  ERROR   {msg}", file=sys.stderr)


def _find_archive() -> Path | None:
    """Find the most recent validated portable ZIP in dist/."""
    candidates = sorted(
        _DIST_DIR.glob("RiotCommander-portable-*.zip"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _build_archive() -> Path | None:
    """Run package_portable.py to produce/refresh the archive."""
    pkg = _PROJECT_ROOT / "tools" / "package_portable.py"
    if not pkg.exists():
        _err(f"package_portable.py not found: {pkg}")
        return None
    r = subprocess.run([sys.executable, str(pkg)], cwd=str(_PROJECT_ROOT))
    if r.returncode not in (0, 2):
        _err(f"package_portable.py failed: exit {r.returncode}")
        return None
    return _find_archive()


# ── setup.bat content ─────────────────────────────────────────────────────────

def _setup_bat(archive_name: str) -> str:
    return f"""\
@echo off
setlocal enabledelayedexpansion
title Riot Commander -- Setup
color 0A

echo.
echo  ====================================================
echo    RIOT COMMANDER -- GUIDED SETUP
echo  ====================================================
echo.
echo  This will:
echo    1. Extract the portable bundle to a folder you choose
echo    2. Run first-time setup (verify packages, create dirs)
echo    3. Check readiness
echo.

:: Step 1 -- choose install location
set DEFAULT_DEST=%USERPROFILE%\\RiotCommander
set /p DEST_INPUT=Install location (press Enter for default [%DEFAULT_DEST%]): 
if "%DEST_INPUT%"=="" (
    set INSTALL_DIR=%DEFAULT_DEST%
) else (
    set INSTALL_DIR=%DEST_INPUT%
)

echo.
echo  Installing to: %INSTALL_DIR%
echo.

:: Confirm
set /p CONFIRM=Proceed? (Y/N): 
if /i not "%CONFIRM%"=="Y" (
    echo  Setup cancelled.
    pause
    exit /b 1
)

:: Step 2 -- extract archive
echo.
echo  [1/3] Extracting portable bundle...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%" 2>nul

:: Use PowerShell to extract the ZIP
powershell -NoProfile -Command ^
  "Expand-Archive -Path '%~dp0{archive_name}' -DestinationPath '%INSTALL_DIR%' -Force"

if %errorlevel% neq 0 (
    echo  [FAIL] Extraction failed.
    pause
    exit /b 1
)

:: The ZIP expands into RiotCommander-portable\; find it
set APP_DIR=%INSTALL_DIR%\\RiotCommander-portable
if not exist "%APP_DIR%" (
    echo  [FAIL] Expected folder not found: %APP_DIR%
    pause
    exit /b 1
)
echo  [OK]   Extracted to: %APP_DIR%

:: Step 3 -- run install.bat
echo.
echo  [2/3] Running first-time setup...
call "%APP_DIR%\\install.bat"
if %errorlevel% neq 0 (
    echo  [WARN] Setup completed with warnings. Check above for details.
)

:: Step 4 -- readiness check
echo.
echo  [3/3] Checking readiness...
set EMBED_PY=%APP_DIR%\\python-embed\\python.exe
if exist "%EMBED_PY%" (
    "%EMBED_PY%" "%APP_DIR%\\tools\\bootstrap_env_check.py"
) else (
    python "%APP_DIR%\\tools\\bootstrap_env_check.py" 2>nul ^
    || echo  [WARN] Could not run readiness check (python not on PATH)
)

echo.
echo  ====================================================
echo    SETUP COMPLETE
echo  ====================================================
echo.
echo  To launch Riot Commander:
echo    %APP_DIR%\\start.bat
echo.
echo  To re-run setup:
echo    %APP_DIR%\\install.bat
echo.
pause
exit /b 0
"""


# ── Build ─────────────────────────────────────────────────────────────────────

def build(output_dir: Path, dry: bool, archive_override: Path | None) -> int:
    print("=" * 64)
    print("Riot Commander -- build_installer.py")
    print(f"Output   : {output_dir}")
    print(f"Dry-run  : {dry}")
    print("=" * 64)

    # ── Locate archive ────────────────────────────────────────────────────────
    print("\n[Step 1: Locate validated portable archive]")
    if archive_override:
        archive = archive_override
        if not archive.exists():
            _err(f"Specified archive not found: {archive}")
            return 1
        _ok(f"Using specified archive: {archive.name}")
    else:
        archive = _find_archive()
        if not archive:
            _info("No existing archive found -- building now...")
            archive = _build_archive()
            if not archive:
                _err("Archive build failed")
                return 1
            _ok(f"Archive built: {archive.name}")
        else:
            _ok(f"Using existing archive: {archive.name}")
    _info(f"Archive size: {archive.stat().st_size / (1024*1024):.1f} MB")

    # ── Create output dir ─────────────────────────────────────────────────────
    print("\n[Step 2: Prepare installer staging directory]")
    if not dry:
        if output_dir.exists():
            shutil.rmtree(str(output_dir))
        output_dir.mkdir(parents=True, exist_ok=True)

    # ── Copy archive ──────────────────────────────────────────────────────────
    print("\n[Step 3: Copy portable archive]")
    dest_archive = output_dir / archive.name
    if not dry:
        shutil.copy2(str(archive), str(dest_archive))
    _ok(f"Archive copied: {archive.name}")

    # ── Write setup.bat ───────────────────────────────────────────────────────
    print("\n[Step 4: Write setup.bat]")
    setup_content = _setup_bat(archive.name)
    if not dry:
        (output_dir / "setup.bat").write_text(setup_content, encoding="utf-8")
    _ok("setup.bat written")

    # ── Write INSTALL_README.md ───────────────────────────────────────────────
    print("\n[Step 5: Write INSTALL_README.md]")
    readme = f"""\
# INSTALL_README.md
# Riot Commander -- Installer Guide
# Strategy: scripted-extract installer (Phase 5 Step 3)
# Archive: {archive.name}
# Generated: {datetime.datetime.now(datetime.timezone.utc).isoformat()}

## What Is In This Folder

  {archive.name}   -- validated portable bundle (Option B, embedded Python)
  setup.bat        -- guided setup launcher (extract + first-run setup)
  INSTALL_README.md -- this file
  INSTALL_MANIFEST.json -- machine-readable installer metadata

## How to Install

  1. Run setup.bat
     - You will be prompted for an install location
     - Default: %USERPROFILE%\\RiotCommander
     - setup.bat extracts the archive, runs install.bat, and checks readiness

  2. When prompted by install.bat:
     - Edit API-Key-Claude.txt with your Anthropic API key (starts with sk-ant-)
     - Get your key at: https://console.anthropic.com/keys

  3. After setup completes, launch via:
     <install-location>\\RiotCommander-portable\\start.bat

## What Is Included

  - Embedded Python 3.11 runtime (python-embed/) -- no system Python required
  - anthropic SDK + Pillow pre-installed in embedded runtime
  - All source packages (core/, coaches/, tft/, ui/, lcu/, modes/, ops/)
  - Operator tooling (bootstrap_env_check.py, dev_cli.py)

## What Is NOT Included

  - API-Key-Claude.txt (you must supply this)
  - Runtime coaching artifacts (generated at runtime)
  - Dev-only harness tools (smoke, perf, preflight)

## Prerequisites

  Windows 10/11 (64-bit)
  No Python installation required for normal launch (embedded runtime included)
  System Python still required for frozen ops/watchdog scripts (if used)

## Troubleshooting

  Re-run readiness check at any time:
    <install-dir>\\RiotCommander-portable\\python-embed\\python.exe ^
    <install-dir>\\RiotCommander-portable\\tools\\bootstrap_env_check.py

  Re-run first-time setup:
    <install-dir>\\RiotCommander-portable\\install.bat

## What This Installer Does NOT Do (yet)

  - No Start Menu shortcut creation
  - No Windows registry entries
  - No Add/Remove Programs entry
  - No auto-update
  - No code signing
  These are candidates for Phase 5 Step 4+.
"""
    if not dry:
        (output_dir / "INSTALL_README.md").write_text(readme, encoding="utf-8")
    _ok("INSTALL_README.md written")

    # ── Write INSTALL_MANIFEST.json ───────────────────────────────────────────
    print("\n[Step 6: Write INSTALL_MANIFEST.json]")
    manifest = {
        "installer_tool":       "tools/build_installer.py",
        "installer_timestamp":  datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "installer_type":       "scripted-extract",
        "installer_version":    "phase5_step3",
        "portable_archive":     archive.name,
        "archive_size_mb":      round(archive.stat().st_size / (1024*1024), 1),
        "strategy":             "Option B -- embedded Python runtime",
        "setup_script":         "setup.bat",
        "default_install_location": "%USERPROFILE%\\RiotCommander",
        "zip_root_folder":      "RiotCommander-portable",
        "embedded_runtime":     "python-embed/  (Python 3.11.9)",
        "launch_chain":         "start.bat -> python-embed\\pythonw.exe main.py",
        "prerequisites": {
            "os":               "Windows 10/11 64-bit",
            "python_system":    "not required for app launch (embedded included)",
            "python_ops_stack": "advisory -- frozen ops/.ps1 scripts call python by PATH name",
            "api_key":          "required -- operator must supply API-Key-Claude.txt",
        },
        "not_yet_implemented": [
            "Start Menu shortcut",
            "Windows registry entry",
            "Add/Remove Programs entry",
            "Code signing",
            "Auto-update",
            "Full NSIS/MSIX/Inno installer",
        ],
        "dry_run": dry,
    }
    if not dry:
        (output_dir / "INSTALL_MANIFEST.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
    _ok(f"INSTALL_MANIFEST.json written")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 64)
    if dry:
        print("Dry-run complete: would succeed. No output written.")
        return 2
    size_mb = sum(f.stat().st_size for f in output_dir.rglob("*") if f.is_file()) / (1024*1024)
    print(f"Installer staging complete: {output_dir}")
    print(f"  {len(list(output_dir.iterdir()))} files  ({size_mb:.1f} MB total)")
    print(f"  Run setup.bat to install")
    return 0


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(
        description="Build installer staging directory for Riot Commander."
    )
    p.add_argument("--output", "-o", default=str(_DEFAULT_OUTPUT))
    p.add_argument("--archive", "-a", default=None,
                   help="Path to portable archive (default: latest in dist/)")
    p.add_argument("--dry-run", "-n", action="store_true")
    args = p.parse_args()
    return build(
        Path(args.output),
        dry=args.dry_run,
        archive_override=Path(args.archive) if args.archive else None,
    )


if __name__ == "__main__":
    sys.exit(main())
