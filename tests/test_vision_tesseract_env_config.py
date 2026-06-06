# arch: P4.2 Tesseract path env-config (RC_TESSERACT_CMD) | section=vision-tests | frozen=no
"""RC_TESSERACT_CMD env override for the Tesseract binary path (refactor-plan P4.2).

The OCR pipeline pinned a hardcoded Program Files tesseract.exe. This adds an env
override so a non-default / clean-machine / bundled install can point at its own
binary with no code edit. pytesseract is NOT installed in CI, so every test that
exercises ``_ensure_tesseract`` injects a fake ``pytesseract`` module via sys.modules
(the module imports pytesseract lazily inside the function, so the top-level import of
``core.vision_tesseract`` stays dependency-free).
"""
from __future__ import annotations

import sys
import types

from core import vision_tesseract as vt


def _fake_pytesseract(cmd: str):
    mod = types.ModuleType("pytesseract")
    mod.pytesseract = types.SimpleNamespace(tesseract_cmd=cmd)
    return mod


def test_candidates_env_first(monkeypatch, tmp_path):
    exe = tmp_path / "tess.exe"
    monkeypatch.setenv(vt._TESSERACT_ENV, str(exe))
    cands = vt._tesseract_candidates()
    assert cands[0] == str(exe)
    assert cands[-1] == vt._TESSERACT_DEFAULT


def test_candidates_default_only_when_unset(monkeypatch):
    monkeypatch.delenv(vt._TESSERACT_ENV, raising=False)
    assert vt._tesseract_candidates() == [vt._TESSERACT_DEFAULT]


def test_ensure_pins_env_override(monkeypatch, tmp_path):
    exe = tmp_path / "tess.exe"
    exe.write_text("x", encoding="utf-8")
    fake = _fake_pytesseract("tesseract")  # bare PATH name, not a real file
    monkeypatch.setitem(sys.modules, "pytesseract", fake)
    monkeypatch.setenv(vt._TESSERACT_ENV, str(exe))
    vt._ensure_tesseract()
    assert fake.pytesseract.tesseract_cmd == str(exe)


def test_ensure_keeps_already_valid_cmd(monkeypatch, tmp_path):
    good = tmp_path / "already.exe"
    good.write_text("x", encoding="utf-8")
    other = tmp_path / "env.exe"
    other.write_text("x", encoding="utf-8")
    fake = _fake_pytesseract(str(good))  # already points at a real file
    monkeypatch.setitem(sys.modules, "pytesseract", fake)
    monkeypatch.setenv(vt._TESSERACT_ENV, str(other))
    vt._ensure_tesseract()
    assert fake.pytesseract.tesseract_cmd == str(good)  # not overridden


def test_ensure_ignores_missing_env_path(monkeypatch, tmp_path):
    missing = tmp_path / "nope.exe"  # never created
    fake = _fake_pytesseract("tesseract")
    monkeypatch.setitem(sys.modules, "pytesseract", fake)
    monkeypatch.setenv(vt._TESSERACT_ENV, str(missing))
    vt._ensure_tesseract()
    # A non-existent env path is never pinned (it may fall through to the default
    # install path if that exists on the host, but never to the missing path).
    assert fake.pytesseract.tesseract_cmd != str(missing)
