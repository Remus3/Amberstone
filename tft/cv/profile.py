"""TFT HUD region profile: rectangles authored at native resolution, scaled per frame.

Spec: docs/TFT_PROGRAM.md section 3.2 stage 2. Regions are authored once at
2560x1440 native in tracked ``config/tft_regions/2560x1440.json`` (rectangles and
probe colours only - no art) and scaled to the frame size with the same semantics
as ``core.vision_tesseract._scale_bbox`` (``int(v * frame / base)`` per axis).

Resolution handling (the profile key is resolution + UI scale):

- An exact ``<W>x<H>.json`` whose ``ui_scale`` matches is used as is.
- Otherwise a profile of the SAME aspect ratio and UI scale is used scaled
  (``exact=False``): the TFT HUD scales uniformly with resolution, so the
  2560x1440 map also covers a 1920x1080 client and the 1280x720 relay frame.
  Callers lower confidence by ``conf_factor`` for a scaled profile.
- Any other aspect ratio has no profile: ``load_profile`` returns None and every
  field reads ``absent`` until a profile file for it exists.

Box format everywhere is ``[left, top, right, bottom]`` in base pixels.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

_log = logging.getLogger("rc.tft.cv.profile")

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = ROOT / "config" / "tft_regions"
BASE_RESOLUTION = (2560, 1440)
ASPECT_TOLERANCE = 0.01
SCALED_CONF_FACTOR = 0.9

# The client's own settings file (P0 probe: FullscreenMode=1, 2560x1440). It
# carries ResolutionSizeX / ResolutionSizeY; no UI-scale key was found in it
# (measured 2026-10-25), so the UI scale defaults to 1.0.
CLIENT_INI_RELPATH = Path("TFT") / "Saved" / "Config" / "WindowsClient" / "GameUserSettings.ini"

_SIMPLE_FIELDS = ("stage", "timer", "level", "xp", "gold", "streak", "streak_icon", "own_hp")


def _num(v) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"not a number: {v!r}")
    return float(v)


def _box(v) -> tuple[float, float, float, float]:
    if not isinstance(v, (list, tuple)) or len(v) != 4:
        raise ValueError(f"box must be [l, t, r, b]: {v!r}")
    lft, top, rgt, bot = (_num(x) for x in v)
    if rgt <= lft or bot <= top:
        raise ValueError(f"empty box: {v!r}")
    return (lft, top, rgt, bot)


def _shift(box, dx: float, dy: float):
    return (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)


@dataclass(frozen=True)
class Probe:
    """A small patch whose mean colour identifies a panel (or a cover over it)."""

    box: tuple[float, float, float, float]
    rgb: tuple[float, float, float]
    tol: float
    max_std: float | None = None


@dataclass(frozen=True)
class PanelSpec:
    probes: tuple[Probe, ...] = ()
    min_match: int = 0
    cover: tuple[Probe, ...] = ()
    cover_min: int = 0


@dataclass(frozen=True)
class Profile:
    key: str
    base_w: int
    base_h: int
    ui_scale: float
    exact: bool
    boxes: dict = field(default_factory=dict)
    groups: dict = field(default_factory=dict)
    panels: dict = field(default_factory=dict)
    field_panel: dict = field(default_factory=dict)
    source: str = ""

    @property
    def aspect(self) -> float:
        return self.base_w / self.base_h

    @property
    def conf_factor(self) -> float:
        return 1.0 if self.exact else SCALED_CONF_FACTOR

    def fits(self, frame_w: int, frame_h: int) -> bool:
        """True when a frame of this size can be read with this profile."""
        if frame_w <= 0 or frame_h <= 0:
            return False
        return abs(frame_w / frame_h - self.aspect) <= ASPECT_TOLERANCE * self.aspect

    def scale(self, box, frame_w: int, frame_h: int) -> tuple[int, int, int, int]:
        """Base-pixel box -> frame-pixel crop box (``_scale_bbox`` semantics, clamped)."""
        sx = frame_w / self.base_w
        sy = frame_h / self.base_h
        lft, top, rgt, bot = box
        out = [int(lft * sx), int(top * sy), int(rgt * sx), int(bot * sy)]
        out[0] = max(0, min(out[0], frame_w - 1))
        out[1] = max(0, min(out[1], frame_h - 1))
        out[2] = max(out[0] + 1, min(out[2], frame_w))
        out[3] = max(out[1] + 1, min(out[3], frame_h))
        return (out[0], out[1], out[2], out[3])

    def box(self, name: str, frame_size) -> tuple[int, int, int, int]:
        return self.scale(self.boxes[name], *frame_size)

    def group(self, name: str, frame_size) -> list[dict]:
        """Expanded repeated group (odds slots, shop cards, scoreboard rows, trait rows)."""
        fw, fh = frame_size
        return [{k: self.scale(b, fw, fh) for k, b in slot.items()}
                for slot in self.groups.get(name, ())]

    def panel_of(self, field_name: str) -> str | None:
        return self.field_panel.get(field_name)


def _expand_group(spec: dict) -> list[dict]:
    """``{"slots": [{box map}, ...]}`` (explicit) or ``{"first", "step", "count"}``."""
    slots = spec.get("slots")
    if slots is not None:
        if not isinstance(slots, list) or not 1 <= len(slots) <= 16:
            raise ValueError("group 'slots' must be a list of 1..16 box maps")
        out = []
        for slot in slots:
            if not isinstance(slot, dict) or not slot:
                raise ValueError("each group slot must be a non-empty box map")
            out.append({k: _box(v) for k, v in slot.items()})
        return out
    first = spec.get("first")
    if not isinstance(first, dict) or not first:
        raise ValueError("group needs a non-empty 'first' map of boxes")
    step = spec.get("step", [0, 0])
    if not isinstance(step, (list, tuple)) or len(step) != 2:
        raise ValueError("group 'step' must be [dx, dy]")
    dx, dy = _num(step[0]), _num(step[1])
    count = spec.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 16:
        raise ValueError("group 'count' must be an int 1..16")
    base = {k: _box(v) for k, v in first.items()}
    return [{k: _shift(b, dx * i, dy * i) for k, b in base.items()} for i in range(count)]


def _probe(v) -> Probe:
    if not isinstance(v, dict):
        raise ValueError(f"probe must be an object: {v!r}")
    rgb = v.get("rgb")
    if not isinstance(rgb, (list, tuple)) or len(rgb) != 3:
        raise ValueError(f"probe rgb must be [r, g, b]: {v!r}")
    max_std = v.get("max_std")
    return Probe(
        box=_box(v.get("box")),
        rgb=tuple(_num(c) for c in rgb),
        tol=_num(v.get("tol", 20)),
        max_std=None if max_std is None else _num(max_std),
    )


def _panel(v) -> PanelSpec:
    if not isinstance(v, dict):
        raise ValueError(f"panel must be an object: {v!r}")
    probes = tuple(_probe(p) for p in v.get("probes", ()))
    cover = tuple(_probe(p) for p in v.get("cover", ()))
    min_match = int(v.get("min_match", len(probes)))
    cover_min = int(v.get("cover_min", len(cover) and 1))
    if probes and not 1 <= min_match <= len(probes):
        raise ValueError("panel min_match out of range")
    if cover and not 1 <= cover_min <= len(cover):
        raise ValueError("panel cover_min out of range")
    return PanelSpec(probes=probes, min_match=min_match if probes else 0,
                     cover=cover, cover_min=cover_min if cover else 0)


def parse_profile(data: dict, *, exact: bool = True, source: str = "") -> Profile:
    """Validate a profile document and build a ``Profile``; raises ValueError."""
    if not isinstance(data, dict):
        raise ValueError("profile document must be an object")
    base = data.get("base")
    if not isinstance(base, (list, tuple)) or len(base) != 2:
        raise ValueError("profile 'base' must be [W, H]")
    bw, bh = int(_num(base[0])), int(_num(base[1]))
    if bw <= 0 or bh <= 0:
        raise ValueError("profile base must be positive")
    ui_scale = _num(data.get("ui_scale", 1.0))
    fields = data.get("fields")
    if not isinstance(fields, dict):
        raise ValueError("profile 'fields' must be an object")
    boxes: dict = {}
    groups: dict = {}
    field_panel: dict = {}
    for name, spec in fields.items():
        if not isinstance(spec, dict):
            raise ValueError(f"field {name!r} must be an object")
        if "box" in spec:
            boxes[name] = _box(spec["box"])
        elif "group" in spec:
            groups[name] = _expand_group(spec["group"])
        else:
            raise ValueError(f"field {name!r} needs 'box' or 'group'")
        panel = spec.get("panel")
        if panel is not None:
            field_panel[name] = str(panel)
    missing = [f for f in _SIMPLE_FIELDS if f not in boxes]
    missing += [g for g in ("odds", "shop", "scoreboard", "traits") if g not in groups]
    if missing:
        raise ValueError(f"profile is missing fields: {missing}")
    panels_raw = data.get("panels", {})
    if not isinstance(panels_raw, dict):
        raise ValueError("profile 'panels' must be an object")
    panels = {k: _panel(v) for k, v in panels_raw.items()}
    unknown = sorted({p for p in field_panel.values() if p not in panels})
    if unknown:
        raise ValueError(f"fields name undeclared panels: {unknown}")
    key = str(data.get("profile") or f"{bw}x{bh}@ui{ui_scale:g}")
    return Profile(key=key, base_w=bw, base_h=bh, ui_scale=ui_scale, exact=exact,
                   boxes=boxes, groups=groups, panels=panels,
                   field_panel=field_panel, source=source)


def _read_doc(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _log.warning("TFT region profile %s unreadable: %s", path.name, exc)
        return None
    return data if isinstance(data, dict) else None


def load_profile(resolution=None, ui_scale: float = 1.0, *,
                 config_dir: Path | None = None) -> Profile | None:
    """The profile for a client running at ``resolution`` (default 2560x1440).

    Exact file first, then a same-aspect profile (scaled, ``exact=False``),
    else None (fields read absent). Never raises: a bad file logs and is skipped.
    """
    d = Path(config_dir) if config_dir is not None else CONFIG_DIR
    w, h = resolution if resolution is not None else BASE_RESOLUTION
    w, h = int(w), int(h)
    if w <= 0 or h <= 0:
        return None
    exact_path = d / f"{w}x{h}.json"
    candidates: list[tuple[Path, bool]] = []
    if exact_path.is_file():
        candidates.append((exact_path, True))
    try:
        others = sorted(p for p in d.glob("*x*.json") if p != exact_path)
    except OSError:
        others = []
    candidates.extend((p, False) for p in others)
    for path, exact in candidates:
        data = _read_doc(path)
        if data is None:
            continue
        try:
            prof = parse_profile(data, exact=exact, source=path.name)
        except ValueError as exc:
            _log.warning("TFT region profile %s invalid: %s", path.name, exc)
            continue
        if abs(prof.ui_scale - float(ui_scale)) > 1e-6:
            continue
        if exact and (prof.base_w, prof.base_h) == (w, h):
            return prof
        if not exact and prof.fits(w, h):
            return prof
    return None


_INI_KEY = re.compile(r"^\s*(ResolutionSizeX|ResolutionSizeY)\s*=\s*(\d+)\s*$", re.M)


def resolution_from_ini(text: str) -> tuple[int, int] | None:
    """(W, H) from the client's GameUserSettings.ini text, or None."""
    found = dict(_INI_KEY.findall(text or ""))
    try:
        w, h = int(found["ResolutionSizeX"]), int(found["ResolutionSizeY"])
    except (KeyError, ValueError):
        return None
    return (w, h) if w > 0 and h > 0 else None


def client_ini_path() -> Path | None:
    base = os.environ.get("LOCALAPPDATA")
    return Path(base) / CLIENT_INI_RELPATH if base else None


def load_client_profile(ini_path: Path | None = None, *,
                        config_dir: Path | None = None) -> Profile | None:
    """Profile for the resolution the local client is configured to (passive read)."""
    path = ini_path if ini_path is not None else client_ini_path()
    res = None
    if path is not None:
        try:
            res = resolution_from_ini(Path(path).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            res = None
    return load_profile(res, config_dir=config_dir)
