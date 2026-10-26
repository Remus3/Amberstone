"""tools/package_portable.py - zip the staged Amberstone bundle (PKG-4).

Packs the folder tools/build_portable.py staged (default
dist/portable_staging/) into ONE redistributable archive:

    dist/Amberstone-portable-<version>.zip
      Amberstone-portable/
        start.bat, main.py, ..., python-embed/, BUILD_MANIFEST.json,
        PACKAGE_MANIFEST.json

plus `<archive>.sha256` beside it. The archive is built from the staged
folder, never from the live tree, so build_portable.py's exclusion rules stay
the authority - and they are re-checked here (build_portable.verify_bundle)
before a single byte is zipped: a staged folder holding a key file,
ops/runtime/, a boot-start installer or an LFS pointer is refused. A staged
folder from the retired pre-PKG-4 builder (no "bundle" in its manifest) is
refused too.

Usage (from the repo root):
    python tools/package_portable.py
    python tools/package_portable.py --rebuild-staging
    python tools/package_portable.py --version 1.0.0 --output dist/
    python tools/package_portable.py --dry-run

Exit codes: 0 archive produced, 1 refused or failed, 2 dry-run would succeed.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Callable, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tools import build_portable as bp  # noqa: E402

STAGED_DIR = bp.DEFAULT_OUTPUT
DEFAULT_OUT_DIR = _PROJECT_ROOT / "dist"
ZIP_ROOT_NAME = f"{bp.BUNDLE_NAME}-portable"   # top-level folder inside the zip
PACKAGE_MANIFEST = "PACKAGE_MANIFEST.json"


def archive_name(version: str) -> str:
    """e.g. Amberstone-portable-20261026.zip"""
    return f"{ZIP_ROOT_NAME}-{version}.zip"


def _err(msg: str) -> None:
    print(f"  ERROR   {msg}", file=sys.stderr)


def _rebuild(staged_dir: Path, python_exe: str, runner: Optional[Callable]) -> bool:
    cmd = [python_exe, str(_PROJECT_ROOT / "tools" / "build_portable.py"),
           "--output", str(staged_dir)]
    rc = runner(cmd) if runner else subprocess.run(cmd, cwd=str(_PROJECT_ROOT)).returncode
    if rc != 0:
        _err(f"build_portable.py failed with exit code {rc}")
        return False
    return True


def read_build_manifest(staged_dir: Path) -> Optional[dict]:
    try:
        doc = json.loads((Path(staged_dir) / bp.MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if doc.get("build_tool") != bp.BUILD_TOOL or doc.get("bundle") != bp.BUNDLE_NAME:
        return None
    return doc


def package(out_dir: Path = DEFAULT_OUT_DIR, version: Optional[str] = None,
            staged_dir: Path = STAGED_DIR, rebuild: bool = False, dry: bool = False,
            python_exe: Optional[str] = None,
            build_runner: Optional[Callable] = None) -> int:
    """Produce the archive. Returns 0 / 1 / 2 (see module docstring)."""
    out_dir, staged_dir = Path(out_dir), Path(staged_dir)
    version = version or datetime.date.today().strftime("%Y%m%d")
    name = archive_name(version)
    print(f"{bp.BUNDLE_NAME} package: {name} from {staged_dir.name}/")

    if rebuild and not dry:
        if not _rebuild(staged_dir, python_exe or sys.executable, build_runner):
            return 1
    manifest = read_build_manifest(staged_dir)
    if manifest is None:
        _err(f"{staged_dir.name}/ holds no {bp.BUNDLE_NAME} build "
             "(run tools/build_portable.py, or pass --rebuild-staging)")
        return 1
    problems = bp.verify_bundle(staged_dir)
    if problems:
        _err("staged bundle refused: " + "; ".join(problems[:20]))
        return 1
    files = sorted(p for p in staged_dir.rglob("*") if p.is_file())
    if dry:
        print(f"Dry-run: {len(files)} files would be zipped into {name}. Nothing written.")
        return 2

    pkg_manifest = {
        "package_tool": "tools/package_portable.py",
        "packaged_utc": datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        "archive": name,
        "version": version,
        "zip_root_folder": ZIP_ROOT_NAME,
        "bundle_version": manifest.get("version"),
        "source_commit": manifest.get("source_commit"),
        "python": manifest.get("python", {}).get("mode"),
        "file_count": len(files),
        "first_run": ["Unzip anywhere you can write to",
                      "Optional: put an Anthropic key in API-Key-Claude.txt",
                      "Run start.bat (nothing is registered to start at boot)"],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / name
    tmp = out_dir / (name + ".tmp")
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6) as zf:
            for src in files:
                zf.write(src, f"{ZIP_ROOT_NAME}/{src.relative_to(staged_dir).as_posix()}")
            zf.writestr(f"{ZIP_ROOT_NAME}/{PACKAGE_MANIFEST}",
                        json.dumps(pkg_manifest, indent=2, sort_keys=True) + "\n")
        tmp.replace(archive)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        _err(f"zip failed: {exc}")
        return 1
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    side = out_dir / (name + ".sha256")
    side.write_text(f"{digest}  {name}\n", encoding="ascii", newline="\n")
    print(f"Packaged {name}: {len(files)} files, "
          f"{archive.stat().st_size / (1024 * 1024):.1f} MB, sha256 {digest}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=f"Zip the staged {bp.BUNDLE_NAME} bundle.")
    p.add_argument("--output", "-o", default=str(DEFAULT_OUT_DIR))
    p.add_argument("--staged", default=str(STAGED_DIR),
                   help="staged bundle folder (default dist/portable_staging)")
    p.add_argument("--version", "-v", default=None, help="archive version (default YYYYMMDD)")
    p.add_argument("--rebuild-staging", action="store_true",
                   help="run tools/build_portable.py into the staged folder first")
    p.add_argument("--dry-run", "-n", action="store_true")
    args = p.parse_args(argv)
    return package(out_dir=Path(args.output), version=args.version,
                   staged_dir=Path(args.staged), rebuild=args.rebuild_staging,
                   dry=args.dry_run, python_exe=sys.executable)


if __name__ == "__main__":
    sys.exit(main())
