#!/usr/bin/env python
"""RC's one named scratch root - what `<scratch>` means in CLAUDE.md and the
prompts (MAIN ORDER 2026-11-16 2145, E-ROOT).

Order: env RC_SCRATCH_DIR (absolute, and never a drive root or a drive-root
child), else the fleet kit's `<sidecar root>/RC/Scratch` (the folder name of
the sidecar root lives in the kit only, so no machine path enters this file),
else RuntimeError - there is no silent fallback, because the old fallbacks
(a drive-root tmp folder, a `..` climb out of a worktree) are the bug.

`python ops/loop/scratch_root.py` prints the resolved path.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
CODE = "RC"
ENV_VAR = "RC_SCRATCH_DIR"


def _kit():
    try:
        return importlib.import_module("ops.fleet_kit.fleet_lanes")
    except ImportError:
        pass
    name = "rc_fleet_kit_fleet_lanes"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, _HERE.parent / "fleet_kit" / "fleet_lanes.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _refuse_root_child(p: Path, what: str) -> Path:
    if not p.is_absolute():
        raise RuntimeError(f"{what} must be an absolute path")
    if p == Path(p.anchor) or p.parent == Path(p.anchor):
        raise RuntimeError(f"{what} refuses a drive root or a drive-root child")
    return p


def scratch_root(env=None) -> Path:
    env = os.environ if env is None else env
    override = (env.get(ENV_VAR) or "").strip().strip('"')
    if override:
        return _refuse_root_child(Path(override), ENV_VAR)
    kit = _kit()
    root = kit.sidecar_root(environ=env)
    got = kit.sidecar_dir(CODE, "Scratch", root=root or "")
    if got is None:
        raise RuntimeError(
            f"scratch root unresolved: set {ENV_VAR} or FLEET_SIDECAR_ROOT "
            f"(the sidecar root must hold a {CODE} folder)")
    return _refuse_root_child(Path(got), "sidecar scratch root")


if __name__ == "__main__":
    try:
        print(scratch_root())
    except RuntimeError as exc:
        print(f"scratch_root: {exc}", file=sys.stderr)
        sys.exit(1)
