"""tools/build_installer.py - scripted-extract installer staging (PKG-4).

Wraps the newest dist/Amberstone-portable-*.zip (tools/package_portable.py)
in a guided setup folder:

    dist/installer_staging/
      setup.bat                         guided extract + first-run check
      Amberstone-portable-<ver>.zip     the verified portable archive
      INSTALL_README.md                 operator-facing guide
      INSTALL_MANIFEST.json             machine-readable metadata

This is NOT the NSIS shell installer: that is electron-builder's job
(rc-shell/electron-builder.yml, PACKAGING_PLAN PKG-6). setup.bat only
extracts and checks; it creates no Start-menu entry, no Run key, no
scheduled task and no logon hook (plan intent 3: never start at boot).

Usage (from the repo root):
    python tools/build_installer.py
    python tools/build_installer.py --archive dist/Amberstone-portable-1.0.0.zip
    python tools/build_installer.py --dry-run

Exit codes: 0 staged, 1 failed, 2 dry-run would succeed.
"""
from __future__ import annotations

import argparse
import datetime
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Callable, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tools import build_portable as bp  # noqa: E402
from tools import package_portable as pp  # noqa: E402

DIST_DIR = _PROJECT_ROOT / "dist"
DEFAULT_OUTPUT = DIST_DIR / "installer_staging"
ARCHIVE_GLOB = f"{pp.ZIP_ROOT_NAME}-*.zip"
DEFAULT_INSTALL_DIR = "%LOCALAPPDATA%\\" + bp.BUNDLE_NAME


def _err(msg: str) -> None:
    print(f"  ERROR   {msg}", file=sys.stderr)


def find_archive(dist_dir: Path = DIST_DIR) -> Optional[Path]:
    """The most recent Amberstone-portable-*.zip in `dist_dir`."""
    candidates = sorted(Path(dist_dir).glob(ARCHIVE_GLOB),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _build_archive(dist_dir: Path, runner: Optional[Callable]) -> Optional[Path]:
    cmd = [sys.executable, str(_PROJECT_ROOT / "tools" / "package_portable.py"),
           "--output", str(dist_dir)]
    rc = runner(cmd) if runner else subprocess.run(cmd, cwd=str(_PROJECT_ROOT)).returncode
    if rc != 0:
        _err(f"package_portable.py failed: exit {rc}")
        return None
    return find_archive(dist_dir)


def _bundle_manifest(archive: Path) -> dict:
    try:
        with zipfile.ZipFile(archive) as zf:
            return json.loads(zf.read(f"{pp.ZIP_ROOT_NAME}/{bp.MANIFEST_NAME}"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return {}


def setup_bat(archive_name: str) -> str:
    """The guided setup script. Paths reach PowerShell through environment
    variables, never spliced into the command text, so a folder name holding
    a quote cannot change the command."""
    root = pp.ZIP_ROOT_NAME
    return f"""@echo off
setlocal
title {bp.BUNDLE_NAME} - Setup

echo.
echo  {bp.BUNDLE_NAME} guided setup
echo  This extracts the portable bundle to a folder you choose and checks it.
echo  Nothing is registered to start at boot or at logon.
echo.

set "DEFAULT_DEST={DEFAULT_INSTALL_DIR}"
set "DEST_INPUT="
set /p "DEST_INPUT=Install location (Enter for %DEFAULT_DEST%): "
if "%DEST_INPUT%"=="" (set "INSTALL_DIR=%DEFAULT_DEST%") else (set "INSTALL_DIR=%DEST_INPUT%")

echo.
echo  Installing to: %INSTALL_DIR%
set "CONFIRM="
set /p "CONFIRM=Proceed? (Y/N): "
if /i not "%CONFIRM%"=="Y" (
    echo  Setup cancelled.
    pause
    exit /b 1
)

echo.
echo  [1/2] Extracting...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
set "AMB_ZIP=%~dp0{archive_name}"
set "AMB_DEST=%INSTALL_DIR%"
powershell -NoProfile -Command "Expand-Archive -LiteralPath $env:AMB_ZIP -DestinationPath $env:AMB_DEST -Force"
if errorlevel 1 (
    echo  [FAIL] Extraction failed.
    pause
    exit /b 1
)
set "APP_DIR=%INSTALL_DIR%\\{root}"
if not exist "%APP_DIR%\\start.bat" (
    echo  [FAIL] Expected folder not found: %APP_DIR%
    pause
    exit /b 1
)
echo  [OK]   Extracted to: %APP_DIR%

echo.
echo  [2/2] Checking readiness...
if exist "%APP_DIR%\\python-embed\\python.exe" (
    "%APP_DIR%\\python-embed\\python.exe" "%APP_DIR%\\tools\\bootstrap_env_check.py"
) else (
    echo  [WARN] No embedded runtime in this bundle - it cannot start on its own.
)

echo.
echo  Setup complete. Launch with:
echo    %APP_DIR%\\start.bat
echo.
pause
exit /b 0
"""


def _readme(archive_name: str, python_line: str) -> str:
    root = pp.ZIP_ROOT_NAME
    return f"""# {bp.BUNDLE_NAME} - install guide

Archive: {archive_name}
Runtime: {python_line}

## Install

1. Run setup.bat and pick a folder (default {DEFAULT_INSTALL_DIR}).
   It extracts the archive and runs the readiness check.
2. Optional: put an Anthropic API key in <folder>\\{root}\\API-Key-Claude.txt.
   (start.bat still refuses to start without one - PACKAGING_PLAN S11.)
3. Launch <folder>\\{root}\\start.bat.

## What this installer does not do

- No Start-menu shortcut, registry entry or Add/Remove Programs entry.
- Nothing starts at boot or at logon, ever (PACKAGING_PLAN intent 3).
- No code signing and no auto-update; the NSIS shell installer and its
  updater are built by electron-builder (PACKAGING_PLAN PKG-6).
"""


def build(output_dir: Path = DEFAULT_OUTPUT, dry: bool = False,
          archive_override: Optional[Path] = None, dist_dir: Path = DIST_DIR,
          build_runner: Optional[Callable] = None) -> int:
    output_dir, dist_dir = Path(output_dir), Path(dist_dir)
    if archive_override:
        archive = Path(archive_override)
        if not archive.is_file():
            _err(f"archive not found: {archive.name}")
            return 1
    else:
        archive = find_archive(dist_dir)
        if archive is None:
            if dry:
                print("Dry-run: no archive yet; package_portable.py would build one.")
                return 2
            archive = _build_archive(dist_dir, build_runner)
            if archive is None:
                return 1
    if not archive.name.startswith(pp.ZIP_ROOT_NAME + "-"):
        _err(f"not an {pp.ZIP_ROOT_NAME} archive: {archive.name}")
        return 1
    man = _bundle_manifest(archive)
    py = man.get("python") or {}
    cp = py.get("cpython") or {}
    python_line = (f"embedded CPython {cp.get('version')}" if cp.get("version")
                   else "no embedded runtime recorded in this archive")
    print(f"{bp.BUNDLE_NAME} installer staging from {archive.name}")
    if dry:
        print("Dry-run: would stage setup.bat, the archive and the manifests.")
        return 2

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    shutil.copy2(archive, output_dir / archive.name)
    (output_dir / "setup.bat").write_text(setup_bat(archive.name).replace("\n", "\r\n"),
                                          encoding="ascii", newline="")
    (output_dir / "INSTALL_README.md").write_text(_readme(archive.name, python_line),
                                                  encoding="utf-8", newline="\n")
    manifest = {
        "installer_tool": "tools/build_installer.py",
        "installer_utc": datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "installer_type": "scripted-extract",
        "portable_archive": archive.name,
        "archive_size_mb": round(archive.stat().st_size / (1024 * 1024), 1),
        "zip_root_folder": pp.ZIP_ROOT_NAME,
        "default_install_location": DEFAULT_INSTALL_DIR,
        "bundle_version": man.get("version"),
        "embedded_runtime": cp.get("version"),
        "starts_at_boot": False,
        "not_implemented": ["Start-menu shortcut", "Add/Remove Programs entry",
                            "code signing", "auto-update (electron-builder, PKG-6)"],
    }
    (output_dir / "INSTALL_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8",
        newline="\n")
    print(f"Installer staging complete: {output_dir.name}/ (run setup.bat)")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description=f"Stage the {bp.BUNDLE_NAME} scripted-extract installer.")
    p.add_argument("--output", "-o", default=str(DEFAULT_OUTPUT))
    p.add_argument("--archive", "-a", default=None,
                   help="portable archive (default: newest in dist/)")
    p.add_argument("--dry-run", "-n", action="store_true")
    args = p.parse_args(argv)
    return build(Path(args.output), dry=args.dry_run,
                 archive_override=Path(args.archive) if args.archive else None)


if __name__ == "__main__":
    sys.exit(main())
