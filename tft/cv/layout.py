"""TFT HUD layout classifier: which panels are on screen (TFT program section 3.2 stage 3).

Cheap colour checks only - no OCR, no template art. Each panel in the region
profile declares:

- ``probes``: small patches whose mean RGB must sit within ``tol`` of a
  calibrated colour (a UI surface that exists only while the panel is shown);
  the panel needs ``min_match`` of them.
- ``cover``: patches that match the uniform backdrop of a panel that COVERS this
  one (the unit inspect panel and the damage meter both cover the scoreboard);
  ``cover_min`` matches hide the panel.

A panel that declares neither is assumed visible and left to field validation
(the trait panel: a row only counts when its name matches the trait lexicon).
A hidden panel makes every field on it ``absent`` - never a guess.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from tft.cv.profile import PanelSpec, Probe, Profile

PANELS = ("stage_bar", "hud_bar", "shop", "own_hp", "scoreboard", "traits")


@dataclass(frozen=True)
class Layout:
    panels: dict = field(default_factory=dict)
    scores: dict = field(default_factory=dict)

    def visible(self, panel: str | None) -> bool:
        if panel is None:
            return True
        return bool(self.panels.get(panel, False))


def _patch_stats(img, box) -> tuple[tuple[float, float, float], float]:
    """Mean RGB and the largest per-channel standard deviation of a patch."""
    from PIL import ImageStat

    st = ImageStat.Stat(img.crop(box))
    mean = tuple(st.mean[:3]) if len(st.mean) >= 3 else (st.mean[0],) * 3
    std = max(st.stddev[:3]) if len(st.stddev) >= 3 else st.stddev[0]
    return mean, std


def probe_matches(img, probe: Probe, prof: Profile) -> bool:
    box = prof.scale(probe.box, img.width, img.height)
    mean, std = _patch_stats(img, box)
    d = sum((a - b) ** 2 for a, b in zip(mean, probe.rgb)) ** 0.5
    if d > probe.tol:
        return False
    return probe.max_std is None or std <= probe.max_std


def panel_state(img, spec: PanelSpec, prof: Profile) -> tuple[bool, float]:
    """(visible, score) for one panel; score = matched fraction of its own probes."""
    score = 1.0
    if spec.probes:
        hits = sum(1 for p in spec.probes if probe_matches(img, p, prof))
        score = hits / len(spec.probes)
        if hits < spec.min_match:
            return False, score
    if spec.cover:
        covered = sum(1 for p in spec.cover if probe_matches(img, p, prof))
        if covered >= spec.cover_min:
            return False, 0.0
    return True, score


def classify(img, prof: Profile) -> Layout:
    """Classify every panel the profile declares; RGB-converts the frame once."""
    if img.mode != "RGB":
        img = img.convert("RGB")
    panels: dict = {}
    scores: dict = {}
    if not prof.fits(img.width, img.height):
        return Layout({name: False for name in prof.panels}, {})
    for name, spec in prof.panels.items():
        vis, score = panel_state(img, spec, prof)
        panels[name] = vis
        scores[name] = round(score, 3)
    return Layout(panels, scores)
