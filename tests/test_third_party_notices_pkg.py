"""PKG-8 (docs/PACKAGING_PLAN.md M7 + M10): tracked rc-shell lockfile and the
third-party notices generator.

Two halves:

1. The lock. `rc-shell/package-lock.json` is TRACKED (the repo-wide
   `package-lock.json` ignore has a `!rc-shell/package-lock.json` negation)
   and agrees with `rc-shell/package.json` the way `npm ci` checks it: same
   dependency maps in the root entry, every direct dependency resolved inside
   its range, every `overrides` range honoured. A version bump to package.json
   that skips the lock regen (Dependabot PR #22, electron 45.0.0, applied by
   path B without `npm install --package-lock-only`) goes red here.

2. The generator, `tools/build_third_party_notices.py`, driven over fixture
   metadata in tmp_path (no network, no real site-packages): licence
   classification, marker selection for the Windows / CPython 3.14 target,
   copyleft FAILS without a recorded ruling and passes with one, deterministic
   ASCII + LF output, inputs never modified, default output is ignored build
   output.
"""
from __future__ import annotations

import ast
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import tools.build_third_party_notices as tpn

ROOT = Path(__file__).resolve().parent.parent
SHELL = ROOT / "rc-shell"
LOCK = SHELL / "package-lock.json"
PACKAGE_JSON = SHELL / "package.json"
TOOL = ROOT / "tools" / "build_third_party_notices.py"
_GIT = shutil.which("git")


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([_GIT, *args], cwd=ROOT, capture_output=True, text=True)


# --------------------------------------------------------------------------
# 1. the tracked lock
# --------------------------------------------------------------------------

@pytest.mark.skipif(_GIT is None, reason="git not on PATH - index state is unresolvable without it")
def test_rc_shell_lock_is_tracked_and_not_ignored() -> None:
    assert _git("ls-files", "--error-unmatch", "rc-shell/package-lock.json").returncode == 0, (
        "rc-shell/package-lock.json is not in the git index (M7: track it, build with npm ci)")
    proc = _git("check-ignore", "-q", "--no-index", "--", "rc-shell/package-lock.json")
    assert proc.returncode == 1, "rc-shell/package-lock.json is still matched by an ignore rule"
    # The negation is scoped: other lockfiles stay ignored.
    other = _git("check-ignore", "-q", "--no-index", "--", "ops/audit/lolmath_ds_sweep/package-lock.json")
    assert other.returncode == 0, "the repo-wide package-lock.json ignore was widened beyond rc-shell"


def test_rc_shell_lock_bytes_are_lf_ascii_lockfile_v3() -> None:
    raw = LOCK.read_bytes()
    assert b"\r" not in raw, "lock carries CR bytes - keep npm's LF output"
    assert all(b < 128 for b in raw), "lock carries non-ASCII bytes"
    assert raw.endswith(b"\n")
    lock = json.loads(raw)
    assert lock["lockfileVersion"] == 3
    assert lock["name"] == "rc-shell"


def test_rc_shell_lock_agrees_with_package_json() -> None:
    pkg = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    drift = tpn.lock_drift(pkg, lock)
    assert drift == [], "rc-shell lock is out of sync with package.json (regenerate with " \
        "`npm install --package-lock-only --ignore-scripts` in rc-shell): " + "; ".join(drift)
    # The pin the shell is built and tested on.
    assert lock["packages"]["node_modules/electron"]["version"] == pkg["devDependencies"]["electron"]


def test_rc_shell_lock_resolves_only_from_the_public_registry_with_integrity() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    bad = []
    for key, entry in sorted(lock["packages"].items()):
        if not key or entry.get("link"):
            continue
        if not str(entry.get("resolved", "")).startswith("https://registry.npmjs.org/"):
            bad.append(f"{key}: resolved {entry.get('resolved')!r}")
        if not str(entry.get("integrity", "")).startswith("sha512-"):
            bad.append(f"{key}: integrity {entry.get('integrity')!r}")
    assert not bad, "; ".join(bad[:10])


def test_a_package_json_bump_without_a_lock_regen_is_drift() -> None:
    """Dependabot PR #22 shape (electron 44.9.1 -> 45.0.0 in package.json only)."""
    pkg = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    bumped = json.loads(json.dumps(pkg))
    bumped["devDependencies"]["electron"] = "45.0.0"
    drift = tpn.lock_drift(bumped, lock)
    assert any("electron" in d and "devDependencies" in d for d in drift), drift
    # ...and the regenerated lock shape (root entry + resolved entry) is in sync.
    regen = json.loads(json.dumps(lock))
    regen["packages"][""]["devDependencies"]["electron"] = "45.0.0"
    regen["packages"]["node_modules/electron"]["version"] = "45.0.0"
    assert tpn.lock_drift(bumped, regen) == []


def test_an_override_violation_is_drift() -> None:
    pkg = {"name": "x", "dependencies": {"a": "^1.0.0"}, "overrides": {"a": {"u": "^7.30.1"}}}
    lock = {
        "name": "x", "lockfileVersion": 3,
        "packages": {
            "": {"name": "x", "dependencies": {"a": "^1.0.0"}},
            "node_modules/a": {"version": "1.2.0", "optionalDependencies": {"u": "^7.0.0"}},
            "node_modules/u": {"version": "6.26.0"},
        },
    }
    drift = tpn.lock_drift(pkg, lock)
    assert any("override a > u" in d for d in drift), drift
    lock["packages"]["node_modules/a/node_modules/u"] = {"version": "7.30.1"}
    assert tpn.lock_drift(pkg, lock) == []


def test_real_npm_production_set_maps_to_allow_listed_licences() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    entries = tpn.npm_production_entries(lock)
    names = {cid.split("@", 1)[0] if not cid.startswith("npm:@") else cid for cid, _k, _e in entries}
    assert "npm:electron-updater" in names, "electron-updater must be in the shipped npm set"
    assert not any(cid.startswith(("npm:electron@", "npm:electron-builder@")) for cid, _k, _e in entries), (
        "dev-only packages leaked into the production set")
    unmapped = [f"{cid} {entry.get('license')}" for cid, _k, entry in entries
                if tpn.classify_expression(str(entry.get("license", ""))) != tpn.ALLOWED]
    assert not unmapped, "production npm packages outside the allow-list (need a ruling): " + "; ".join(unmapped)
    # Electron itself is a devDependency but its runtime ships.
    assert tpn.classify_expression(lock["packages"]["node_modules/electron"]["license"]) == tpn.ALLOWED


@pytest.mark.parametrize(("version", "rng", "ok"), [
    ("44.9.1", "44.9.1", True), ("45.0.0", "44.9.1", False),
    ("6.8.9", "^6.3.9", True), ("7.0.0", "^6.3.9", False), ("6.3.8", "^6.3.9", False),
    ("0.2.5", "^0.2.3", True), ("0.3.0", "^0.2.3", False), ("0.0.4", "^0.0.3", False),
    ("1.2.9", "~1.2.3", True), ("1.3.0", "~1.2.3", False),
    ("7.30.1", "^7.30.1", True), ("6.26.0", "^7.30.1", False), ("8.1.0", "^7", False),
    ("2.0.0", ">=1.2.3 <2.0.0", False), ("1.9.0", ">=1.2.3 <2.0.0", True),
    ("3.0.0", "^1.0.0 || ^3.0.0", True), ("4.1.0", "*", True), ("1.2.3-beta.1", "^1.2.0", False),
])
def test_satisfies(version: str, rng: str, ok: bool) -> None:
    assert tpn.satisfies(version, rng) is ok


# --------------------------------------------------------------------------
# 2. classification
# --------------------------------------------------------------------------

@pytest.mark.parametrize(("expr", "klass"), [
    ("MIT", "allowed"), ("ISC", "allowed"), ("Python-2.0", "allowed"), ("BlueOak-1.0.0", "allowed"),
    ("MIT-CMU", "allowed"), ("(MIT OR CC0-1.0)", "allowed"), ("MIT OR Apache-2.0", "allowed"),
    ("BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0", "allowed"),
    ("MIT OR GPL-3.0-or-later", "allowed"), ("MIT AND LGPL-2.1-or-later", "copyleft"),
    ("MPL-2.0", "copyleft"), ("LGPL-2.1+", "copyleft"), ("AGPL-3.0-only", "copyleft"),
    ("GPL-2.0-only WITH Classpath-exception-2.0", "copyleft"),
    ("BSL-1.0", "allowed"), ("BUSL-1.1", "restricted"), ("SSPL-1.0", "restricted"),
    ("Unlicense", "allowed"), ("UNLICENSED", "restricted"), ("CC-BY-NC-4.0", "restricted"),
    ("Foo-1.0", "unknown"), ("", "unknown"), ("MIT AND", "unknown"), ("(MIT", "unknown"),
    ("LicenseRef-Copyleft-Text-LGPL", "copyleft"),
])
def test_classify_expression(expr: str, klass: str) -> None:
    assert tpn.classify_expression(expr) == klass


@pytest.mark.parametrize(("headers", "expr", "source"), [
    ({"License-Expression": "MIT-CMU", "License": "junk"}, "MIT-CMU", "License-Expression"),
    ({"License": "MPL-2.0"}, "MPL-2.0", "License field"),
    ({"License": "Apache 2.0"}, "Apache-2.0", "License field"),
    ({"License": "MIT OR Apache-2.0"}, "MIT OR Apache-2.0", "License field"),
    ({"License": "Files: Everything except for the benchmarks/*.json files.",
      "Classifier": ["License :: OSI Approved :: Apache Software License"]}, "Apache-2.0", "classifiers"),
    ({"Classifier": ["License :: OSI Approved :: MIT License", "License :: OSI Approved"]}, "MIT", "classifiers"),
    ({"Classifier": ["License :: OSI Approved :: GNU Lesser General Public License v2 or later (LGPLv2+)"]},
     "LGPL", "classifiers"),
    ({"License": "Copyright x\n        Permission is hereby granted, free of charge, to any person"}, "MIT",
     "License field text scan"),
    ({"License": "Copyright x\n        GNU LESSER GENERAL PUBLIC LICENSE\n        Version 2.1"},
     "LicenseRef-Copyleft-Text-LGPL", "License field text scan"),
    ({"License": "UNKNOWN"}, "UNKNOWN", "none"),
    ({}, "UNKNOWN", "none"),
])
def test_licence_from_metadata_precedence(headers: dict, expr: str, source: str) -> None:
    assert tpn.licence_from_metadata(headers) == (expr, source)


def test_marker_selection_for_the_windows_314_target() -> None:
    text = (
        "numpy==2.4.6 ; python_full_version < '3.12' \\\n    --hash=sha256:aa\n"
        "numpy==2.5.3 ; python_full_version >= '3.12' \\\n    --hash=sha256:bb\n    # via -r x\n"
        "h11==0.16.0 ; sys_platform != 'emscripten' \\\n    --hash=sha256:cc\n"
        "httpx2-jsfetch==1.0 ; python_full_version >= '3.12' and sys_platform == 'emscripten' \\\n"
        "    --hash=sha256:dd\n"
        "certifi==2026.10.19 \\\n    --hash=sha256:ee\n"
    )
    pins, problems = tpn.parse_requirements(text)
    assert problems == []
    selected, sel_problems = tpn.select_pins(pins, tpn.target_env("3.14"))
    assert sel_problems == []
    assert {k: v.version for k, v in selected.items()} == {
        "numpy": "2.5.3", "h11": "0.16.0", "certifi": "2026.10.19"}
    selected_311, _ = tpn.select_pins(pins, tpn.target_env("3.11"))
    assert selected_311["numpy"].version == "2.4.6"
    with pytest.raises(ValueError):
        tpn.eval_marker("frobnicate == 'x'", tpn.target_env())


def test_real_requirements_select_one_pin_per_name_for_the_target() -> None:
    pins, problems = tpn.parse_requirements((ROOT / "requirements.txt").read_text(encoding="utf-8"))
    assert problems == [] and pins, problems
    selected, sel_problems = tpn.select_pins(pins, tpn.target_env("3.14"))
    assert sel_problems == []
    assert "certifi" in selected and "opencv-python" in selected
    assert "httpx2-jsfetch" not in selected, "an emscripten-only pin was selected for the Windows target"


# --------------------------------------------------------------------------
# 3. the generator end to end over fixture metadata
# --------------------------------------------------------------------------

MIT_TEXT = "MIT License\n\nCopyright (c) 2026 Fixture Authors\n\nPermission is hereby granted, free of charge.\n"
# Non-ASCII fixture characters built from code points so this file stays ASCII.
COPY, EMDASH, UUML = chr(0xA9), chr(0x2014), chr(0xFC)


def _dist(site: Path, name: str, version: str, *, expr: str = "", licence: str = "",
          classifiers: tuple = (), licence_text: str = MIT_TEXT, record: tuple = ()) -> Path:
    d = site / f"{name.replace('-', '_')}-{version}.dist-info"
    (d / "licenses").mkdir(parents=True)
    lines = ["Metadata-Version: 2.4", f"Name: {name}", f"Version: {version}"]
    if expr:
        lines.append(f"License-Expression: {expr}")
    if licence:
        lines.append(f"License: {licence}")
    lines.extend(f"Classifier: {c}" for c in classifiers)
    lines.append("License-File: LICENSE")
    (d / "METADATA").write_text("\n".join(lines) + "\n\nA long description.\n", encoding="utf-8", newline="\n")
    (d / "licenses" / "LICENSE").write_text(licence_text, encoding="utf-8", newline="\n")
    (d / "RECORD").write_text("".join(f"{r},sha256=x,1\n" for r in record), encoding="utf-8", newline="\n")
    return d


def _npm_pkg(node_root: Path, key: str, name: str, version: str, licence: str, *,
             licence_file: bool = True, author: str = "Fixture Author") -> None:
    d = node_root / key
    d.mkdir(parents=True)
    (d / "package.json").write_text(json.dumps({"name": name, "version": version, "license": licence,
                                                "author": author}), encoding="utf-8")
    if licence_file:
        (d / "LICENSE").write_text(f"{licence} licence text of {name}\n", encoding="utf-8", newline="\n")


@pytest.fixture()
def tree(tmp_path: Path) -> dict:
    req = tmp_path / "requirements.txt"
    req.write_text(
        "certifi==2026.10.19 \\\n    --hash=sha256:aa\n"
        "pillow==13.0.0 \\\n    --hash=sha256:bb\n"
        "opencv-python==5.0.0.93 \\\n    --hash=sha256:cc\n"
        "numpy==2.4.6 ; python_full_version < '3.12' \\\n    --hash=sha256:dd\n"
        "numpy==2.5.3 ; python_full_version >= '3.12' \\\n    --hash=sha256:ee\n",
        encoding="utf-8", newline="\n")
    site = tmp_path / "site-packages"
    _dist(site, "certifi", "2026.10.19", licence="MPL-2.0",
          classifiers=("License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)",),
          licence_text="This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.\n")
    _dist(site, "pillow", "13.0.0", expr="MIT-CMU",
          licence_text=f"The Python Imaging Library (PIL) is\n\n    Copyright {COPY} 1997-2011 by Secret Labs AB\n"
                       f"    Copyright {COPY} 2010 by Jeffrey A. Clark and contributors {EMDASH} M{UUML}ller\n")
    _dist(site, "opencv-python", "5.0.0.93", licence="Apache 2.0",
          record=("cv2/__init__.py", "cv2/opencv_videoio_ffmpeg500_64.dll"))
    (site / "cv2").mkdir()
    (site / "cv2" / "__init__.py").write_text("", encoding="utf-8")
    (site / "cv2" / "opencv_videoio_ffmpeg500_64.dll").write_bytes(b"MZ")
    _dist(site, "numpy", "2.5.3", expr="BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0")

    node_root = tmp_path / "rc-shell"
    pkg = {"name": "rc-shell", "version": "0.4.0", "dependencies": {"electron-updater": "^6.3.9"},
           "devDependencies": {"electron": "44.9.1", "gpl-dev-tool": "^1.0.0"}}
    lock = {"name": "rc-shell", "version": "0.4.0", "lockfileVersion": 3, "requires": True, "packages": {
        "": {"name": "rc-shell", "version": "0.4.0", "dependencies": {"electron-updater": "^6.3.9"},
             "devDependencies": {"electron": "44.9.1", "gpl-dev-tool": "^1.0.0"}},
        "node_modules/electron-updater": {"version": "6.8.9", "license": "MIT",
                                          "dependencies": {"lazy-val": "^1.0.5", "sax": "^1.2.4"}},
        "node_modules/lazy-val": {"version": "1.0.5", "license": "MIT"},
        "node_modules/sax": {"version": "1.4.1", "license": "BlueOak-1.0.0"},
        "node_modules/electron": {"version": "44.9.1", "license": "MIT", "dev": True},
        "node_modules/gpl-dev-tool": {"version": "1.0.0", "license": "GPL-3.0-only", "dev": True},
    }}
    node_root.mkdir()
    (node_root / "package.json").write_text(json.dumps(pkg, indent=2) + "\n", encoding="utf-8", newline="\n")
    (node_root / "package-lock.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8", newline="\n")
    _npm_pkg(node_root, "node_modules/electron-updater", "electron-updater", "6.8.9", "MIT")
    _npm_pkg(node_root, "node_modules/lazy-val", "lazy-val", "1.0.5", "MIT", licence_file=False,
             author="Vladimir Krivosheev")
    _npm_pkg(node_root, "node_modules/sax", "sax", "1.4.1", "BlueOak-1.0.0")

    dist = node_root / "node_modules" / "electron" / "dist"
    dist.mkdir(parents=True)
    (dist / "version").write_text("44.9.1", encoding="utf-8")
    (dist / "LICENSE").write_text("Copyright (c) Electron contributors\n\nPermission is hereby granted, free of "
                                  "charge\n", encoding="utf-8", newline="\n")
    (dist / "ffmpeg.dll").write_bytes(b"MZ")
    (dist / "electron.exe").write_bytes(b"MZ")
    (dist / "LICENSES.chromium.html").write_text(
        '<html><body><div class="product">\n<span class="title">zlib</span>\n'
        '<div class="license">\n<pre>Permission is granted to anyone to use this software</pre>\n</div>\n</div>\n'
        '<div class="product">\n<span class="title">ffmpeg</span>\n<div class="license">\n'
        '<pre>Most files in FFmpeg are under the GNU Lesser General Public License version 2.1</pre>\n'
        '</div>\n</div>\n</body></html>\n', encoding="utf-8", newline="\n")

    embed = tmp_path / "python-embed"
    embed.mkdir()
    (embed / "python314.dll").write_bytes(b"MZ")
    (embed / "LICENSE.txt").write_text("PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2\n", encoding="utf-8",
                                       newline="\n")
    return {"tmp": tmp_path, "req": req, "site": site, "node_root": node_root, "embed": embed, "dist": dist}


def _argv(t: dict, out: Path, *extra: str) -> list:
    return ["--requirements", str(t["req"]), "--site-packages", str(t["site"]), "--python-embed", str(t["embed"]),
            "--node-root", str(t["node_root"]), "--out", str(out), *extra]


M10_RULINGS = ("--ruling", "py:certifi=M10-TEST", "--ruling", "py:opencv-python:*=M10-TEST",
               "--ruling", "electron-runtime:*=M10-TEST")


def test_copyleft_fails_loudly_without_a_ruling(tree: dict, capsys: pytest.CaptureFixture) -> None:
    out = tree["tmp"] / "build" / "THIRD_PARTY_NOTICES.txt"
    rc = tpn.main(_argv(tree, out))
    err = capsys.readouterr().err
    assert rc == 1
    for cid in ("py:certifi", "py:opencv-python:cv2/opencv_videoio_ffmpeg500_64.dll",
                "electron-runtime:ffmpeg.dll", "electron-runtime:chromium-credits"):
        assert f"COPYLEFT WITHOUT RULING: {cid}" in err, (cid, err)
    text = out.read_text(encoding="ascii")
    assert "STATUS: INCOMPLETE" in text and "NOT FOR DISTRIBUTION" in text
    assert "ruling: PENDING" in text
    assert "1 of 2 Chromium products name a copyleft licence" in text
    assert "    - ffmpeg (LGPL)" in text
    assert "    - zlib" not in text, "a permissive Chromium product was flagged"
    # Exactly the four M10 items, nothing else, are problems.
    assert err.count("PROBLEM") == 4, err


def test_recorded_rulings_clear_copyleft_and_are_written(tree: dict, capsys: pytest.CaptureFixture) -> None:
    out = tree["tmp"] / "out" / "THIRD_PARTY_NOTICES.txt"
    rc = tpn.main(_argv(tree, out, *M10_RULINGS))
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    text = out.read_text(encoding="ascii")
    assert "STATUS: COMPLETE" in text
    assert "ruling: M10-TEST" in text
    # Shipped content is attributed; dev-only packages are not.
    for needle in ("npm:electron-updater@6.8.9", "npm:sax@1.4.1", "py:numpy 2.5.3", "py:pillow 13.0.0",
                   "cpython:python 3.14", "electron-runtime:electron 44.9.1",
                   "Vladimir Krivosheev", "generated from the SPDX MIT template"):
        assert needle in text, needle
    assert "gpl-dev-tool" not in text and "npm:electron@" not in text


def test_output_is_deterministic_ascii_lf(tree: dict) -> None:
    a = tree["tmp"] / "a.txt"
    b = tree["tmp"] / "b.txt"
    assert tpn.main(_argv(tree, a, *M10_RULINGS)) == 0
    assert tpn.main(_argv(tree, b, *M10_RULINGS)) == 0
    raw = a.read_bytes()
    assert raw == b.read_bytes()
    assert b"\r" not in raw and all(c < 128 for c in raw)
    text = raw.decode("ascii")
    assert "Copyright (c) 1997-2011 by Secret Labs AB" in text
    assert "contributors - Muller" in text
    assert str(tree["tmp"]) not in text, "an absolute input path leaked into the notices"


def test_stripped_opencv_ffmpeg_dll_is_not_reported(tree: dict, capsys: pytest.CaptureFixture) -> None:
    (tree["site"] / "cv2" / "opencv_videoio_ffmpeg500_64.dll").unlink()
    rc = tpn.main(_argv(tree, tree["tmp"] / "n.txt", "--check", "--ruling", "py:certifi=M10-TEST",
                        "--ruling", "electron-runtime:*=M10-TEST"))
    err = capsys.readouterr().err
    assert rc == 0, err
    assert "opencv_videoio_ffmpeg" not in err


def test_check_mode_writes_nothing_and_inputs_are_untouched(tree: dict) -> None:
    def digest() -> str:
        h = hashlib.sha256()
        for p in sorted(tree["tmp"].rglob("*")):
            if p.is_file():
                h.update(p.relative_to(tree["tmp"]).as_posix().encode() + b"\0" + p.read_bytes())
        return h.hexdigest()

    before = digest()
    out = tree["tmp"] / "never.txt"
    assert tpn.main(_argv(tree, out, "--check")) == 1
    assert not out.exists()
    assert digest() == before


@pytest.mark.parametrize(("mutate", "needle"), [
    (lambda t: (t["site"] / "pillow-13.0.0.dist-info" / "METADATA").write_text(
        "Metadata-Version: 2.4\nName: pillow\nVersion: 12.9.0\nLicense-Expression: MIT-CMU\n", encoding="utf-8"),
     "py:pillow pinned 13.0.0 but site-packages has 12.9.0"),
    (lambda t: _dist(t["site"], "pytest", "9.0.0", expr="MIT"), "py:pytest 9.0.0 is installed but not pinned"),
    (lambda t: _dist(t["site"], "mystery", "1.0", licence="Some Custom Terms v9"), "UNKNOWN WITHOUT RULING: py:mystery"),
    (lambda t: (t["dist"] / "version").write_text("44.5.1", encoding="utf-8"),
     "runtime dist is 44.5.1 but the lock pins 44.9.1"),
    (lambda t: shutil.rmtree(t["node_root"] / "node_modules" / "sax"), "npm:sax@1.4.1 is in the lock but not installed"),
    (lambda t: (t["node_root"] / "package.json").write_text(json.dumps(
        {"name": "rc-shell", "dependencies": {"electron-updater": "^6.3.9"},
         "devDependencies": {"electron": "45.0.0", "gpl-dev-tool": "^1.0.0"}}), encoding="utf-8"),
     "npm lock drift: devDependencies differ"),
])
def test_each_audit_gap_is_a_problem(tree: dict, capsys: pytest.CaptureFixture, mutate, needle: str) -> None:
    mutate(tree)
    rc = tpn.main(_argv(tree, tree["tmp"] / "x.txt", "--check", *M10_RULINGS))
    err = capsys.readouterr().err
    assert rc == 1
    assert needle in err, err


def test_missing_sources_fail_closed(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    rc = tpn.main(["--requirements", str(tmp_path / "nope.txt"), "--node-root", str(tmp_path),
                   "--out", str(tmp_path / "n.txt"), "--check"])
    err = capsys.readouterr().err
    assert rc == 1
    for needle in ("python payload NOT AUDITED", "npm payload NOT AUDITED", "electron payload NOT AUDITED",
                   "CPython payload NOT AUDITED"):
        assert needle in err, needle


def test_bad_ruling_argument_is_a_usage_error(tree: dict) -> None:
    assert tpn.main(_argv(tree, tree["tmp"] / "u.txt", "--ruling", "py:certifi")) == 2
    assert tpn.main(_argv(tree, tree["tmp"] / "u.txt", "--ruling", "py:certifi=has space")) == 2


# --------------------------------------------------------------------------
# 4. the tool itself
# --------------------------------------------------------------------------

def test_shipped_rulings_are_recorded_ids_only() -> None:
    """The M10 ruling is operator-gated: nothing may be cleared by an empty id."""
    for pattern, rid in tpn.RULINGS.items():
        assert pattern.strip() and tpn.RULING_ID_RE.match(rid), (pattern, rid)


def test_generator_reads_local_metadata_only() -> None:
    tree = ast.parse(TOOL.read_text(encoding="utf-8"))
    banned = {"urllib", "http", "socket", "ssl", "requests", "httpx", "subprocess", "shutil", "ftplib"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & banned, sorted(imported & banned)


def test_tool_source_is_ascii_lf() -> None:
    raw = TOOL.read_bytes()
    assert b"\r" not in raw and all(c < 128 for c in raw)


@pytest.mark.skipif(_GIT is None, reason="git not on PATH - ignore status is unresolvable without it")
def test_default_output_is_ignored_build_output_and_never_tracked() -> None:
    rel = tpn.DEFAULT_OUT.relative_to(ROOT).as_posix()
    assert _git("check-ignore", "-q", "--no-index", "--", rel).returncode == 0, f"{rel} is not ignored"
    tracked = _git("ls-files").stdout.splitlines()
    assert tracked, "git ls-files listed nothing - the census below would pass vacuously"
    generated = [p for p in tracked if Path(p).name.upper().startswith("THIRD_PARTY_NOTICES")]
    assert not generated, f"a generated notices file is tracked: {generated}"
