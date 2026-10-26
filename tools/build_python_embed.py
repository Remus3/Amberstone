"""tools/build_python_embed.py - the embedded CPython runtime for the Amberstone
bundle (PKG-4, docs/PACKAGING_PLAN.md section 3.5).

Decision recorded in the plan: EMBEDDED. The bundle carries a CPython
embeddable distribution in `python-embed/`, with site-packages installed from
the HASHED lock (`requirements.txt`) at build time - never copied from a dev
interpreter (plan S12: the dev interpreter trails several pins).

Steps, each explicit and each recorded in python-embed/EMBED_STAMP.json:

1. fetch    The pinned python.org embeddable zip (PINS below). The SHA-256 is
            checked BEFORE the zip is used; a mismatch refuses and keeps
            nothing. A cached copy is reused only while its hash still
            matches; `--embed-zip` takes a local copy, verified the same way.
2. extract  Into the target folder (zip-slip refused).
3. paths    Rewrite python3XX._pth. A ._pth file puts the interpreter in
            safe_path mode (measured on the pinned 3.14.4 zip: sys.flags
            .safe_path True, the script's folder NOT on sys.path), so
            `pythonw main.py` could not `import app`. The rewrite adds
            `Lib\\site-packages`, `..` (the bundle root, which holds
            python-embed/) and `import site` (site-packages .pth files).
4. install  `pip install --require-hashes --only-binary=:all: --target
            Lib/site-packages -r requirements.txt` for the pinned runtime's
            platform and version, by a host interpreter of the SAME
            major.minor (the lock's environment markers are evaluated on the
            host, so a different host version could pick other pins).
5. M10 licence steps, both configurable, both recorded:
            - opencv ffmpeg DLL: `cv2/opencv_videoio_ffmpeg*.dll` is LGPL-2.1
              and RC never calls VideoCapture / VideoWriter, so it is STRIPPED
              by default (the plan's recommendation); `--keep-opencv-ffmpeg`
              keeps it.
            - certifi: MPL-2.0, shipped unmodified. INCLUDED by default - the
              plan names dropping it only as an option, pending the M10
              ruling, and lib/http/client.py prefers its CA bundle (it falls
              back to the system store when certifi is absent);
              `--drop-certifi` removes the package and its dist-info.
6. inventory Every installed distribution's declared licence (dist-info
            METADATA), copyleft families flagged. The generated notices file
            is PKG-8's job (tools/build_third_party_notices.py); this is the
            record of what the runtime actually carries.

Usage (from the repo root; the host interpreter must be 3.14):
    python tools/build_python_embed.py --target dist/python-embed
    python tools/build_python_embed.py --target dist/python-embed --embed-zip <zip>
    python tools/build_python_embed.py --verify dist/python-embed

Exit codes: 0 built / verified, 1 refused or failed.
"""
from __future__ import annotations

import argparse
import datetime
import email.parser
import hashlib
import json
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

STAMP_NAME = "EMBED_STAMP.json"
SITE_PACKAGES_REL = ("Lib", "site-packages")
EMBED_ZIP_MAX_BYTES = 64 * 1024 * 1024
_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class EmbedPin:
    """One pinned python.org embeddable distribution."""

    version: str
    url: str
    sha256: str
    platform: str = "win_amd64"

    @property
    def major_minor(self) -> tuple:
        major, minor = self.version.split(".")[:2]
        return int(major), int(minor)

    @property
    def tag(self) -> str:
        major, minor = self.major_minor
        return f"{major}{minor}"

    @property
    def pth_name(self) -> str:
        return f"python{self.tag}._pth"


# The hash is the one python.org publishes for this exact file in its Windows
# install-manager index (https://www.python.org/ftp/python/index-windows.json,
# entry id "pythonembed-3.14-64", sort-version 3.14.4), and a download of the
# URL on 2026-10-26 hashed to the same value. 3.14.4 is the canonical dev
# interpreter's version (measured 2026-10-26), per plan section 3.5.
PINS = {
    "3.14.4": EmbedPin(
        version="3.14.4",
        url="https://www.python.org/ftp/python/3.14.4/python-3.14.4-embeddable-amd64.zip",
        sha256="fa2e63e9f0607e34d8841cc8080641069b71d2bddb5a69fa30c24eb5599da9fe",
    ),
}
DEFAULT_VERSION = "3.14.4"

# What the CPython embeddable zip itself carries (its LICENSE.txt is the
# authority and ships inside python-embed/).
CPYTHON_LICENCE = ("PSF-2.0; bundled OpenSSL (Apache-2.0), libffi (MIT), "
                   "SQLite (public domain), expat (MIT), mpdecimal (BSD-2-Clause), "
                   "zstd (BSD-3-Clause), vcruntime140 (Microsoft VC++ "
                   "redistributable terms) - see python-embed/LICENSE.txt")

OPENCV_FFMPEG_GLOB = "opencv_videoio_ffmpeg*.dll"
OPENCV_FFMPEG_LICENCE = "LGPL-2.1 (FFmpeg build bundled in the opencv-python wheel)"
CERTIFI_LICENCE = "MPL-2.0 (shipped unmodified)"

_COPYLEFT = re.compile(r"\b(A?GPL|LGPL|MPL|EPL|EUPL|CDDL|OSL)\b|GNU |Mozilla Public",
                       re.IGNORECASE)


class EmbedError(RuntimeError):
    """A refused or failed embedded-runtime step."""


@dataclass
class EmbedOptions:
    """The two M10 licence steps. Defaults = the plan's recommendation."""

    strip_opencv_ffmpeg: bool = True
    include_certifi: bool = True


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(_CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def site_packages(target: Path) -> Path:
    return Path(target).joinpath(*SITE_PACKAGES_REL)


def check_host_python(pin: EmbedPin, version_info=None) -> None:
    """Refuse a host interpreter whose major.minor differs from the pin."""
    vi = tuple(version_info if version_info is not None else sys.version_info)[:2]
    if vi != pin.major_minor:
        raise EmbedError(
            f"host Python {vi[0]}.{vi[1]} cannot install the lock for the "
            f"embedded {pin.version}: the lock's environment markers are "
            f"evaluated on the host. Run this with a "
            f"{pin.major_minor[0]}.{pin.major_minor[1]} interpreter.")


# --------------------------------------------------------------------------- #
# 1. fetch
# --------------------------------------------------------------------------- #
def fetch_embed_zip(pin: EmbedPin, cache_dir: Path, *, opener: Optional[Callable] = None,
                    local_zip: Optional[Path] = None, timeout: float = 120.0) -> Path:
    """Return a path to the pinned embeddable zip, SHA-256 verified.

    `local_zip` is verified in place. Otherwise a cached copy in `cache_dir`
    is reused while its hash matches, else the pin's https URL is downloaded
    through `opener(url, timeout=...)` (default urllib.request.urlopen) to a
    temp file, verified, then moved into place. A mismatch keeps nothing.
    """
    if local_zip is not None:
        local_zip = Path(local_zip)
        if not local_zip.is_file():
            raise EmbedError(f"embed zip not found: {local_zip.name}")
        got = sha256_file(local_zip)
        if got != pin.sha256:
            raise EmbedError(f"embed zip {local_zip.name} sha256 {got} != pinned "
                             f"{pin.sha256} for Python {pin.version}")
        return local_zip
    if not pin.url.startswith("https://"):
        raise EmbedError(f"refusing a non-https embed URL: {pin.url}")
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / pin.url.rsplit("/", 1)[-1]
    if dest.is_file() and sha256_file(dest) == pin.sha256:
        return dest
    open_url = opener if opener is not None else urllib.request.urlopen
    tmp = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    size = 0
    try:
        with open_url(pin.url, timeout=timeout) as resp, open(tmp, "wb") as out:
            while True:
                block = resp.read(_CHUNK)
                if not block:
                    break
                size += len(block)
                if size > EMBED_ZIP_MAX_BYTES:
                    raise EmbedError(f"embed download exceeded {EMBED_ZIP_MAX_BYTES} bytes")
                h.update(block)
                out.write(block)
        if h.hexdigest() != pin.sha256:
            raise EmbedError(f"downloaded {dest.name} sha256 {h.hexdigest()} != "
                             f"pinned {pin.sha256}; refusing it")
        tmp.replace(dest)
    except EmbedError:
        tmp.unlink(missing_ok=True)
        raise
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise EmbedError(f"embed download failed: {exc}") from exc
    return dest


# --------------------------------------------------------------------------- #
# 2. extract, 3. paths
# --------------------------------------------------------------------------- #
def extract_embed(zip_path: Path, target: Path) -> None:
    """Extract every member under `target`, refusing any that escapes it."""
    target = Path(target)
    base = target.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            dest = (target / name).resolve()
            if dest != base and base not in dest.parents:
                raise EmbedError(f"zip member escapes the target: {name!r}")
        target.mkdir(parents=True, exist_ok=True)
        zf.extractall(target)


def configure_pth(target: Path, pin: EmbedPin) -> list:
    """Rewrite the ._pth so the bundle root and site-packages are importable."""
    pth = Path(target) / pin.pth_name
    if not pth.is_file():
        raise EmbedError(f"{pin.pth_name} missing from the embeddable zip")
    lines = [f"python{pin.tag}.zip", ".", "\\".join(SITE_PACKAGES_REL), "..",
             "", "# PKG-4: '..' is the Amberstone bundle root (python-embed/ sits in it).",
             "import site"]
    _atomic_write_text(pth, "\n".join(lines) + "\n")
    return lines


# --------------------------------------------------------------------------- #
# 4. install
# --------------------------------------------------------------------------- #
def pip_install_command(pin: EmbedPin, requirements: Path, target_site: Path,
                        python_exe: str) -> list:
    major, minor = pin.major_minor
    return [
        str(python_exe), "-I", "-m", "pip", "install",
        "--isolated", "--no-input", "--disable-pip-version-check",
        "--require-hashes", "--only-binary=:all:",
        "--platform", pin.platform,
        "--python-version", f"{major}.{minor}",
        "--implementation", "cp",
        "--abi", f"cp{pin.tag}",
        "--target", str(target_site),
        "-r", str(requirements),
    ]


def _default_runner(cmd: list) -> int:
    # A human runs this builder from a console and watches pip's output, so
    # no CREATE_NO_WINDOW here (tests/test_no_console_flash_scheduled_tools.py
    # scopes the flag to unattended spawners).
    return subprocess.run(cmd, check=False).returncode


def install_requirements(pin: EmbedPin, requirements: Path, target: Path, *,
                         runner: Optional[Callable] = None,
                         python_exe: Optional[str] = None) -> list:
    sp = site_packages(target)
    sp.mkdir(parents=True, exist_ok=True)
    cmd = pip_install_command(pin, requirements, sp, python_exe or sys.executable)
    rc = (runner or _default_runner)(cmd)
    if rc != 0:
        raise EmbedError(f"pip install of the hashed lock failed (exit {rc})")
    return cmd


# --------------------------------------------------------------------------- #
# 5. M10 licence steps, 6. inventory
# --------------------------------------------------------------------------- #
def _rel(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()


def strip_opencv_ffmpeg(sp: Path) -> list:
    removed = []
    for dll in sorted(Path(sp).rglob(OPENCV_FFMPEG_GLOB)):
        removed.append(_rel(dll, sp))
        dll.unlink()
    return removed


def drop_certifi(sp: Path) -> list:
    removed = []
    sp = Path(sp)
    for p in sorted([sp / "certifi", *sp.glob("certifi-*.dist-info")]):
        if p.is_dir():
            removed.append(_rel(p, sp) + "/")
            shutil.rmtree(p)
    return removed


def _declared_licence(meta) -> str:
    """PEP 639 License-Expression, else a short one-line License field, else
    the License classifiers. A multi-line License field is a pasted licence
    text (json5 0.15.0 carries a Debian-style copyright block whose first
    line names no licence at all), so the classifiers win over it."""
    expr = (meta.get("License-Expression") or "").strip()
    if expr:
        return expr
    lic = (meta.get("License") or "").strip()
    if lic and "\n" not in lic and len(lic) <= 64:
        return lic
    classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or []
                   if c.startswith("License ::")]
    if classifiers:
        return "; ".join(classifiers)
    return "SEE LICENSE TEXT IN DIST-INFO" if lic else "UNDECLARED"


def license_inventory(sp: Path) -> list:
    """name, version, declared licence and a copyleft flag per dist-info."""
    rows = []
    parser = email.parser.HeaderParser()
    for meta_path in sorted(Path(sp).glob("*.dist-info/METADATA")):
        try:
            meta = parser.parsestr(meta_path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        name = (meta.get("Name") or meta_path.parent.name.split("-")[0]).strip()
        licence = _declared_licence(meta)
        rows.append({"name": name, "version": (meta.get("Version") or "").strip(),
                     "licence": licence, "copyleft": bool(_COPYLEFT.search(licence))})
    return rows


# --------------------------------------------------------------------------- #
# The whole runtime
# --------------------------------------------------------------------------- #
def build_embed(target: Path, *, requirements: Path, pin: Optional[EmbedPin] = None,
                options: Optional[EmbedOptions] = None, cache_dir: Optional[Path] = None,
                opener: Optional[Callable] = None, local_zip: Optional[Path] = None,
                runner: Optional[Callable] = None, python_exe: Optional[str] = None,
                version_info=None, log: Callable = print) -> dict:
    """Build python-embed/ at `target` (must be absent or empty). Returns the stamp."""
    pin = pin or PINS[DEFAULT_VERSION]
    options = options or EmbedOptions()
    target = Path(target)
    requirements = Path(requirements)
    if not requirements.is_file():
        raise EmbedError(f"lock not found: {requirements.name}")
    if target.exists() and any(target.iterdir()):
        raise EmbedError(f"embed target is not empty: {target.name}")
    check_host_python(pin, version_info)
    cache = Path(cache_dir) if cache_dir else _PROJECT_ROOT / "dist" / "embed-cache"
    log(f"  embed: fetch Python {pin.version} ({pin.sha256[:12]}...)")
    zip_path = fetch_embed_zip(pin, cache, opener=opener, local_zip=local_zip)
    extract_embed(zip_path, target)
    pth_lines = configure_pth(target, pin)
    log("  embed: pip install --require-hashes -r requirements.txt")
    cmd = install_requirements(pin, requirements, target, runner=runner, python_exe=python_exe)
    sp = site_packages(target)
    removed_dll = strip_opencv_ffmpeg(sp) if options.strip_opencv_ffmpeg else []
    kept_dll = [] if options.strip_opencv_ffmpeg else [
        _rel(p, sp) for p in sorted(sp.rglob(OPENCV_FFMPEG_GLOB))]
    removed_certifi = [] if options.include_certifi else drop_certifi(sp)
    packages = license_inventory(sp)
    stamp = {
        "tool": "tools/build_python_embed.py",
        "built_utc": _utc_now(),
        "cpython": {"version": pin.version, "url": pin.url, "sha256": pin.sha256,
                    "licence": CPYTHON_LICENCE},
        "pth": pth_lines,
        "requirements_sha256": sha256_file(requirements),
        "pip_flags": [a for a in cmd[4:] if a.startswith("--")],
        "opencv_ffmpeg": {"stripped": options.strip_opencv_ffmpeg,
                          "removed": removed_dll, "kept": kept_dll,
                          "licence": OPENCV_FFMPEG_LICENCE,
                          "why": "RC never calls cv2.VideoCapture / VideoWriter (plan M10)"},
        "certifi": {"included": options.include_certifi, "removed": removed_certifi,
                    "licence": CERTIFI_LICENCE,
                    "why": "lib/http/client.py prefers its CA bundle; M10 ruling pending"},
        "packages": packages,
        "copyleft": sorted(p["name"] for p in packages if p["copyleft"]),
        "ruling": "M10 licence ruling is operator-gated (PKG-8) before any distribution",
    }
    _atomic_write_text(target / STAMP_NAME, json.dumps(stamp, indent=2, sort_keys=True) + "\n")
    return stamp


def read_stamp(target: Path) -> Optional[dict]:
    try:
        return json.loads((Path(target) / STAMP_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def verify_embed_dir(target: Path, *, requirements: Path, pin: Optional[EmbedPin] = None,
                     options: Optional[EmbedOptions] = None) -> list:
    """Problems that make a prebuilt python-embed/ unfit for this tree (empty = fit)."""
    pin = pin or PINS[DEFAULT_VERSION]
    options = options or EmbedOptions()
    target = Path(target)
    stamp = read_stamp(target)
    if stamp is None:
        return [f"{target.name}: no readable {STAMP_NAME} (not built by this tool)"]
    problems = []
    cp = stamp.get("cpython") or {}
    if cp.get("version") != pin.version or cp.get("sha256") != pin.sha256:
        problems.append(f"runtime {cp.get('version')} is not the pinned {pin.version}")
    if stamp.get("requirements_sha256") != sha256_file(requirements):
        problems.append("built from a different requirements.txt than this tree's lock")
    for name in ("python.exe", "pythonw.exe", pin.pth_name):
        if not (target / name).is_file():
            problems.append(f"missing {name}")
    pth = target / pin.pth_name
    if pth.is_file() and ".." not in pth.read_text(encoding="utf-8").splitlines():
        problems.append(f"{pin.pth_name} does not put the bundle root on sys.path")
    sp = site_packages(target)
    if options.strip_opencv_ffmpeg:
        left = [_rel(p, sp) for p in sorted(sp.rglob(OPENCV_FFMPEG_GLOB))] if sp.is_dir() else []
        if left:
            problems.append(f"opencv ffmpeg DLL present but the strip is on: {left}")
    if not options.include_certifi and sp.is_dir() and (sp / "certifi").exists():
        problems.append("certifi present but --drop-certifi is on")
    return problems


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def add_embed_arguments(parser: argparse.ArgumentParser) -> None:
    """Flags shared with tools/build_portable.py."""
    parser.add_argument("--python-version", default=DEFAULT_VERSION, choices=sorted(PINS),
                        help="pinned embeddable CPython (default %(default)s)")
    parser.add_argument("--embed-zip", default=None,
                        help="use this local embeddable zip (still SHA-256 verified)")
    parser.add_argument("--embed-cache", default=None,
                        help="download cache folder (default dist/embed-cache)")
    parser.add_argument("--keep-opencv-ffmpeg", action="store_true",
                        help="keep cv2/opencv_videoio_ffmpeg*.dll (LGPL-2.1); "
                             "default strips it (plan M10)")
    parser.add_argument("--drop-certifi", action="store_true",
                        help="remove certifi (MPL-2.0); default ships it unmodified")


def options_from_args(args) -> EmbedOptions:
    return EmbedOptions(strip_opencv_ffmpeg=not args.keep_opencv_ffmpeg,
                        include_certifi=not args.drop_certifi)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Build the Amberstone embedded Python runtime.")
    p.add_argument("--target", default=str(_PROJECT_ROOT / "dist" / "python-embed"))
    p.add_argument("--requirements", default=str(_PROJECT_ROOT / "requirements.txt"))
    p.add_argument("--verify", default=None, metavar="DIR",
                   help="only check a prebuilt python-embed/ against this tree")
    add_embed_arguments(p)
    args = p.parse_args(argv)
    pin = PINS[args.python_version]
    opts = options_from_args(args)
    if args.verify:
        problems = verify_embed_dir(Path(args.verify), requirements=Path(args.requirements),
                                    pin=pin, options=opts)
        for line in problems:
            print(f"  FAIL    {line}", file=sys.stderr)
        if problems:
            return 1
        print("  OK      embed dir fits this tree")
        return 0
    try:
        stamp = build_embed(Path(args.target), requirements=Path(args.requirements),
                            pin=pin, options=opts,
                            cache_dir=Path(args.embed_cache) if args.embed_cache else None,
                            local_zip=Path(args.embed_zip) if args.embed_zip else None)
    except EmbedError as exc:
        print(f"  ERROR   {exc}", file=sys.stderr)
        return 1
    print(f"  OK      python-embed built: Python {stamp['cpython']['version']}, "
          f"{len(stamp['packages'])} distributions, copyleft: {stamp['copyleft'] or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
