"""
tools/package_portable.py
Riot Commander -- Redistributable portable archive builder.
Phase 4 Step 4.

Produces a redistributable ZIP archive from the staged portable bundle
built by tools/build_portable.py.

The ZIP expands into a single top-level folder:
  RiotCommander-portable/
    start.bat
    install.bat
    main.py
    ...

Usage (from project root):
    python tools/package_portable.py
    python tools/package_portable.py --rebuild-staging   (force fresh staged build)
    python tools/package_portable.py --output dist/      (override output dir)
    python tools/package_portable.py --version 1.0.0     (override version string)
    python tools/package_portable.py --dry-run           (validate only)

Or via wrapper:
    tools\\package_portable.cmd

Output:
    dist/RiotCommander-portable-<YYYYMMDD>.zip   (default)

The archive is built from dist/portable_staging/ (the staged bundle), NOT
from the live source tree.  This ensures build_portable.py's exclusion rules
remain authoritative.

Exit codes:
    0   Archive produced successfully
    1   Build failed (missing staged bundle, zip error, etc.)
    2   Dry-run: would succeed (no output written)
"""
import argparse
import datetime
import json
import subprocess
import sys
import zipfile
from pathlib import Path

_PROJECT_ROOT    = Path(__file__).parent.parent
_STAGED_DIR      = _PROJECT_ROOT / "dist" / "portable_staging"
_DEFAULT_OUT_DIR = _PROJECT_ROOT / "dist"
_ZIP_ROOT_NAME   = "RiotCommander-portable"   # top-level folder inside the ZIP


# -- Helpers -------------------------------------------------------------------

def _info(msg: str) -> None:
    print(f"  INFO    {msg}")

def _ok(msg: str) -> None:
    print(f"  OK      {msg}")

def _err(msg: str) -> None:
    print(f"  ERROR   {msg}", file=sys.stderr)


def _run_build(rebuild: bool, python_exe: str) -> bool:
    """
    Ensure the staged bundle exists.  If rebuild=True or the staged dir
    is absent/stale, run build_portable.py to regenerate it.
    Returns True on success.
    """
    build_script = _PROJECT_ROOT / "tools" / "build_portable.py"
    if not build_script.exists():
        _err(f"Build script not found: {build_script}")
        return False

    if not rebuild and _STAGED_DIR.exists() and (_STAGED_DIR / "BUILD_MANIFEST.json").exists():
        _info(f"Staged bundle already exists at {_STAGED_DIR} -- skipping rebuild")
        _info("Use --rebuild-staging to force a fresh build")
        return True

    _info("Running build_portable.py ...")
    result = subprocess.run(
        [python_exe, str(build_script)],
        cwd=str(_PROJECT_ROOT),
        capture_output=False,   # let output stream to console
    )
    if result.returncode != 0:
        _err(f"build_portable.py failed with exit code {result.returncode}")
        return False
    return True


def _read_staged_manifest() -> dict:
    """Load BUILD_MANIFEST.json from the staged bundle.  Returns {} on failure."""
    p = _STAGED_DIR / "BUILD_MANIFEST.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _archive_name(version: str) -> str:
    """Return the archive filename, e.g. RiotCommander-portable-20260413.zip"""
    return f"{_ZIP_ROOT_NAME}-{version}.zip"


# -- Package -------------------------------------------------------------------

def package(
    out_dir: Path,
    version: str,
    rebuild: bool,
    dry: bool,
    python_exe: str,
) -> int:
    """
    Produce the redistributable archive.  Returns 0 on success, 1 on failure.
    """
    print("=" * 64)
    print("Riot Commander -- package_portable.py")
    print(f"Staged bundle : {_STAGED_DIR}")
    print(f"Output dir    : {out_dir}")
    print(f"Archive name  : {_archive_name(version)}")
    print(f"ZIP root      : {_ZIP_ROOT_NAME}/")
    print(f"Dry-run       : {dry}")
    print("=" * 64)

    # -- Step 1: ensure staged bundle ------------------------------------------
    print("\n[Step 1: Staged bundle]")
    if not dry:
        ok = _run_build(rebuild, python_exe)
        if not ok:
            return 1

    if not dry and not (_STAGED_DIR / "BUILD_MANIFEST.json").exists():
        _err(f"Staged bundle missing or incomplete: {_STAGED_DIR}")
        _err("Run: python tools/build_portable.py  first")
        return 1

    staged_manifest = _read_staged_manifest()
    staged_strategy = staged_manifest.get("strategy", "Option A -- prerequisite Python, portable project bundle")
    _ok(f"Staged bundle ready  ({_STAGED_DIR})")
    if staged_manifest:
        _info(f"Staged strategy: {staged_manifest.get('strategy', 'unknown')}")
        _info(f"Staged timestamp: {staged_manifest.get('build_timestamp', 'unknown')}")

    # -- Step 2: collect files -------------------------------------------------
    print("\n[Step 2: Collect staged files]")
    if not dry:
        all_files = list(_STAGED_DIR.rglob("*"))
        file_list = [f for f in all_files if f.is_file()]
        _ok(f"Found {len(file_list)} files in staged bundle")
    else:
        file_list = []
        _info("Dry-run: skipping file enumeration")

    # -- Step 3: validate no forbidden files crept in -------------------------
    print("\n[Step 3: Exclusion guard]")
    forbidden_checks = [
        ("API-Key-Claude.txt",      "secret key"),
        (".git",                    "source control"),
    ]
    violations = []
    if not dry:
        # Check only the top-level name of each entry (exact match).
        # Using a substring/parts-membership check would false-positive on
        # .gitkeep files whose name contains the string ".git".
        staged_top = {f.relative_to(_STAGED_DIR).parts[0] for f in file_list}
        for name, label in forbidden_checks:
            if name in staged_top:
                violations.append(f"{name} ({label})")
                _err(f"Forbidden item found in staged bundle: {name}")
            else:
                _ok(f"{name} not present  ({label} correctly excluded)")

        # Verify ops/runtime has only .gitkeep
        rt_files = [
            f for f in file_list
            if len(f.relative_to(_STAGED_DIR).parts) >= 2
            and f.relative_to(_STAGED_DIR).parts[0] == "ops"
            and f.relative_to(_STAGED_DIR).parts[1] == "runtime"
        ]
        rt_non_placeholder = [f for f in rt_files if f.name != ".gitkeep"]
        if rt_non_placeholder:
            for f in rt_non_placeholder:
                violations.append(f"ops/runtime/{f.name} (live runtime artifact)")
                _err(f"Live runtime artifact in staged bundle: {f.name}")
        else:
            _ok("ops/runtime/ contains only placeholder (.gitkeep or empty)")

    if violations:
        _err(f"Cannot package: {len(violations)} exclusion violation(s). Re-run build_portable.py.")
        return 1

    # -- Step 4: produce archive -----------------------------------------------
    print("\n[Step 4: Build ZIP archive]")
    archive_path = out_dir / _archive_name(version)

    if not dry:
        out_dir.mkdir(parents=True, exist_ok=True)
        archive_path.unlink(missing_ok=True)

        with zipfile.ZipFile(
            str(archive_path), "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as zf:
            for src_file in sorted(file_list):
                rel = src_file.relative_to(_STAGED_DIR)
                # Place every file under the root folder inside the ZIP
                arcname = f"{_ZIP_ROOT_NAME}/{rel}"
                zf.write(str(src_file), arcname)

        zip_size_kb = round(archive_path.stat().st_size / 1024, 1)
        _ok(f"Archive created: {archive_path}")
        _ok(f"Archive size: {zip_size_kb} KB  ({len(file_list)} files)")

    # -- Step 5: write PACKAGE_MANIFEST.json inside the archive ---------------
    print("\n[Step 5: Package manifest]")
    now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    pkg_manifest = {
        "package_tool":         "tools/package_portable.py",
        "package_timestamp":    now_utc,
        "archive_filename":     _archive_name(version),
        "version":              version,
        "zip_root_folder":      _ZIP_ROOT_NAME,
        "staged_bundle_path":   str(_STAGED_DIR),
        "strategy":             staged_strategy,
        "strategy_doc":         "tools/PYTHON_BUNDLING_STRATEGY.md",
        "staged_build_timestamp": staged_manifest.get("build_timestamp", "unknown"),
        "prerequisites": (
            {
                "python_embed": "included -- python-embed/ in archive (Python 3.11)",
                "pythonw_embed": "included -- python-embed/pythonw.exe for GUI launch",
                "api_key": "API-Key-Claude.txt must be created by operator (not bundled)",
                "ops_ps1_path_python": "PATH python advisory for frozen ops/.ps1 scripts only",
            } if staged_strategy.startswith("Option B") else {
                "python": "3.9+ installed and python on PATH",
                "pythonw": "on PATH (same installation -- required for GUI launch)",
                "pip": "accessible via python -m pip (required for install.bat)",
                "internet": "required for initial install.bat pip install step",
                "api_key": "API-Key-Claude.txt must be created by operator (not bundled)",
            }
        ),
        "first_run_steps": (
            [
                "1. Unzip to any folder",
                "2. Run install.bat (verifies embedded packages, creates runtime dirs)",
                "3. Edit API-Key-Claude.txt with your Anthropic API key (sk-ant-...)",
                "4. Run start.bat to launch (uses embedded python-embed/pythonw.exe)",
            ] if staged_strategy.startswith("Option B") else [
                "1. Unzip to any folder",
                "2. Install Python 3.9+ and ensure it is on PATH",
                "3. Run install.bat (installs Python packages and creates runtime dirs)",
                "4. Edit API-Key-Claude.txt with your Anthropic API key (sk-ant-...)",
                "5. Run start.bat to launch",
            ]
        ),
        "launch_chain": (
            "start.bat -> python-embed/pythonw.exe main.py  (fallback: PATH pythonw.exe)"
            if staged_strategy.startswith("Option B")
            else "start.bat -> PATH pythonw.exe main.py"
        ),
        "not_included": (
            [
                "API-Key-Claude.txt (secret -- supply your own)",
                "Python interpreter NOT required for launch (python-embed/ included)",
                "Python packages PRE-INSTALLED in python-embed/Lib/site-packages/",
                "Live coaching artifacts (generated at runtime)",
                "Dev-only harness tools (run_phase2_smoke.py, preflight, etc.)",
                "Audit/proof bundles",
            ] if staged_strategy.startswith("Option B") else [
                "API-Key-Claude.txt (secret -- supply your own)",
                "Python interpreter (install separately)",
                "Python packages (run install.bat)",
                "Live coaching artifacts (generated at runtime)",
                "Dev-only harness tools (run_phase2_smoke.py, preflight, etc.)",
                "Audit/proof bundles",
            ]
        ),
        "excluded_ops_runtime": "ops/runtime/ contains only placeholder; live artifacts excluded",
    }

    if not dry:
        # Append PACKAGE_MANIFEST.json into the ZIP
        with zipfile.ZipFile(str(archive_path), "a", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                f"{_ZIP_ROOT_NAME}/PACKAGE_MANIFEST.json",
                json.dumps(pkg_manifest, indent=2),
            )
        _ok("PACKAGE_MANIFEST.json written into archive")

    # -- Summary ---------------------------------------------------------------
    print("\n" + "=" * 64)
    if dry:
        print("Dry-run complete: would succeed. No output written.")
        return 2

    print(f"Package complete: {archive_path}")
    print(f"  ZIP root: {_ZIP_ROOT_NAME}/")
    print("  Unzip to any folder, then run install.bat and start.bat.")
    return 0


# -- Entry point ---------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Package the Riot Commander staged bundle into a redistributable ZIP."
    )
    parser.add_argument(
        "--output", "-o",
        default=str(_DEFAULT_OUT_DIR),
        help=f"Output directory for the ZIP (default: {_DEFAULT_OUT_DIR})",
    )
    parser.add_argument(
        "--version", "-v",
        default=datetime.date.today().strftime("%Y%m%d"),
        help="Version string for archive name (default: YYYYMMDD)",
    )
    parser.add_argument(
        "--rebuild-staging",
        action="store_true",
        help="Force a fresh staged bundle build before packaging",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Validate and report without writing any output",
    )
    args = parser.parse_args()

    return package(
        out_dir=Path(args.output),
        version=args.version,
        rebuild=args.rebuild_staging,
        dry=args.dry_run,
        python_exe=sys.executable,
    )


if __name__ == "__main__":
    sys.exit(main())
