# -*- mode: python ; coding: utf-8 -*-
"""
riot-commander.spec - PyInstaller build spec (Tier 3 #13, 2026-05-01).

Bundles main.py + all RC modules + the dashboard's web/ and data/ trees
into a single-folder distribution under dist/riot-commander/. Yields
`riot-commander.exe` plus the dependency folder so the recipient
doesn't need Python installed.

This is **opt-in starter infrastructure**. The current Legion 1-PC
deployment (ADR-011) uses a Python install directly - the spec exists so a
future "share RC with someone else" path is one command away rather
than a from-scratch packaging exercise.

──────────────────────────────────────────────────────────────────────
Build
──────────────────────────────────────────────────────────────────────
First time (PyInstaller is not in requirements.txt - the bundle is
opt-in, no point pinning the lib for users who never package):

    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe -m pip install pyinstaller>=6.0

Then from project root:

    $env:LOCALAPPDATA/Programs/Python/Python314/python.exe -m PyInstaller riot-commander.spec --noconfirm

Output: dist/riot-commander/riot-commander.exe (+ accompanying
dependency files). Distribute the whole `dist/riot-commander/` folder.

Smoke-test the binary from a vanilla Windows shell (no Python on PATH):

    cd dist\\riot-commander
    .\\riot-commander.exe --debug

Should write logs/<today>.log inside the bundle's working dir and
boot the dashboard at https://0.0.0.0:8888.

──────────────────────────────────────────────────────────────────────
What's bundled (datas)
──────────────────────────────────────────────────────────────────────
* web/                    - dashboard HTML/CSS/JS (always shipped)
* data/meta/              - DDragon champion + rune metadata
* data/meta_build/        - curated SR builds, ARAM rune recommendations
* data/champion_loadouts.json - loadout variants the dashboard renders
* data/vision_regions.json - Tesseract region definitions
* config/coach_settings.json (template) - user must edit
* ops/tls/                - TLS cert + key (if present); recipient may
                            need to regenerate via mkcert on their host

What's intentionally NOT bundled:
* API-Key-Claude.txt      - recipient supplies their own
* logs/                   - generated at runtime
* data/match_history.db, postgame_stats.db, rewind_history.db
                          - historical session data (huge + private)
* data/spend/, data/loadouts/ - per-user runtime state
* _archive/               - quarantined files

──────────────────────────────────────────────────────────────────────
Hidden imports
──────────────────────────────────────────────────────────────────────
Listed below are modules PyInstaller misses without help - typically
because RC imports them via importlib.import_module() inside coach
lazy-loaders, or because they're optional deps (tkinter, anthropic).

If a build smoke-test fails with `ModuleNotFoundError` at runtime,
add the missing module to `hiddenimports` and rebuild.

──────────────────────────────────────────────────────────────────────
Known limitations (first-build issues to expect)
──────────────────────────────────────────────────────────────────────
1. Tesseract OCR is NOT bundled - recipient installs separately.
   `core/vision_tesseract.py` pins the binary at
   "C:/Program Files/Tesseract-OCR/tesseract.exe".
2. Pillow image codecs may need explicit hooks on first build; if
   PNG/JPEG fails, append `--hidden-import PIL._tkinter_finder` and
   rebuild with --clean.
3. websockets 16.x (asyncio-based) and portalocker 3.x are pure-
   Python - no special hooks needed.
4. anthropic SDK pulls in tokenizers + httpx; PyInstaller's auto-
   discovery handles them, but if the resulting binary is >300 MB
   look at `excludes` for unused submodules.
"""
import os
from pathlib import Path

block_cipher = None

# Project root is the spec file's directory (PyInstaller cwd at build).
ROOT = Path(os.getcwd()).resolve()

# ── Data files: tuples of (source_path, dest_relative_path) ────────────
# Walk web/ recursively; data/ selectively (DBs and per-user runtime
# state intentionally excluded - see "What's intentionally NOT bundled"
# in the docstring).
def _gather(src_dir: Path, dest: str, *, recursive: bool = True):
    out = []
    if not src_dir.exists():
        return out
    if recursive:
        for p in src_dir.rglob("*"):
            if p.is_file():
                rel = p.relative_to(src_dir)
                out.append((str(p), str(Path(dest) / rel.parent)))
    else:
        for p in src_dir.iterdir():
            if p.is_file():
                out.append((str(p), dest))
    return out

datas = []
datas += _gather(ROOT / "web",                 "web")
datas += _gather(ROOT / "data" / "meta",       "data/meta")
datas += _gather(ROOT / "data" / "meta_build", "data/meta_build")
for fname in ("champion_loadouts.json", "vision_regions.json"):
    src = ROOT / "data" / fname
    if src.exists():
        datas.append((str(src), "data"))
# Bundle the config template if present - recipient edits in place.
cfg = ROOT / "config" / "coach_settings.json"
if cfg.exists():
    datas.append((str(cfg), "config"))
# TLS cert is optional; mkcert-issued, regenerable.
for fname in ("rc.pem", "rc-key.pem"):
    src = ROOT / "ops" / "tls" / fname
    if src.exists():
        datas.append((str(src), "ops/tls"))


# ── Hidden imports ─────────────────────────────────────────────────────
# Coaches are lazy-loaded by string name in coaches/__init__.py and
# core/game_snapshot.py - PyInstaller's static analysis misses these.
hiddenimports = [
    "coaches.aram_coach",
    "coaches.arena_coach",
    "coaches.brawl_coach",
    "coaches.sr_coach",
    "coaches.tft_coach",
    "coaches.tft_pbe_coach",
    "coaches._base_coach",
    "coaches.adaptation_hint",
    "coaches.experimental_builder",
    "coaches.loadout_resolver",
    "coaches.champ_pool_recommender",
    # Dashboard route sub-modules (dashboard/routes_*.py) are imported by
    # string name in dashboard/_dispatch.py and siblings - PyInstaller's
    # static analysis misses every one. They are appended dynamically just
    # below this list (glob of dashboard/routes_*.py) so the set stays
    # correct as routes are added or removed. This replaced a stale
    # hand-list of 7 of ~54 modules (P2-W4 hw2 slice H follow-up).
    # OBS publisher pulls websockets lazily; pre-declare.
    "websockets",
    "websockets.exceptions",
    "websockets.client",
    # portalocker (Tier 3 #14 swap)
    "portalocker",
    "portalocker.exceptions",
    # anthropic SDK
    "anthropic",
    "anthropic.types",
    # PIL - Tk-finder hook is the usual missing piece on Windows.
    "PIL._tkinter_finder",
]

# Append every dashboard route module by globbing the files on disk. Using a
# glob-of-files (not a grep of dispatch references) guarantees we only declare
# modules that actually exist, so a route deleted upstream never leaves a
# dangling hidden import - and a route added upstream is picked up with no spec
# edit. dashboard/_dispatch.py imports these via importlib by string name.
_dash_dir = ROOT / "dashboard"
hiddenimports += sorted(
    f"dashboard.{p.stem}" for p in _dash_dir.glob("routes_*.py")
)


# ── Excludes - submodules we don't ship to keep the bundle smaller. ────
# Trim if a runtime ImportError surfaces.
excludes = [
    "tkinter.test",
    "test",
    "unittest",
    "pydoc_data",
    "lib2to3",
    # If the Phase 3 supervisor is shipped separately, exclude its
    # sklearn / pandas heavy deps; uncomment if you don't want them:
    # "pandas", "sklearn", "scipy",
]


# ── PyInstaller graph ──────────────────────────────────────────────────
a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="riot-commander",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,           # UPX often trips antivirus; not worth the savings
    console=True,        # keep console so --debug logs land in the user's terminal
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # PyInstaller on Windows requires a .ico for the EXE icon and hard-fails
    # the build on an .svg (web/icon.svg is the dashboard favicon, not an
    # ICO). Ship the default PyInstaller icon until a real rc.ico exists.
    # (P2-W4 hw2 slice H: was icon=str(ROOT/"web"/"icon.svg") - build-breaker.)
    icon=str(ROOT / "web" / "rc.ico") if (ROOT / "web" / "rc.ico").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="riot-commander",
)
