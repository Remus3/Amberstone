"""Offline flip-readiness validator for the Lane E CV icon atlas.

The client-side CV template matcher (core.vision_template_match.match_icon) is
the deterministic substrate for retiring the vision-model (Haiku/Sonnet)
escalation on fixed on-disk icon reads - objective icons, item completion,
champion portraits. Before any live flip it must be shown to actually
distinguish the icons it will be asked about. This harness measures that WITHOUT
a live game: it pastes every catalog icon onto a dark canvas at template scale
and matches it against its whole category, then reports

  * self-match accuracy   - does each icon's own crop recognize itself?
  * nearest-confuser margin - which icons collide, and by how thin a margin?
  * a threshold sweep      - at each confidence floor, how many crops resolve
                             confidently-correct vs confidently-wrong vs abstain?

IMPORTANT - this is the PRISTINE-ICON CEILING, not live in-game accuracy. Real
HUD crops carry JPEG compression, resize blur, and lighting noise, so live
numbers will be lower; the live wiring + the confidence-weighted Live-Client/CV
fusion stay operator/live-gated. A low ceiling here, though, is a hard blocker:
if the matcher cannot even tell pristine icons apart, it cannot in-game.

Usage:
    python tools/vision_atlas_validate.py                 # all 3 categories
    python tools/vision_atlas_validate.py --categories spells
    python tools/vision_atlas_validate.py --out data/vision_atlas_accuracy.md

cv2 + numpy required (opencv is an optional RC dependency). Read-only except the
atomic report write. ASCII only (repo hard rule). No em-dashes.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import core.vision_template_match as vtm  # noqa: E402 - after the sys.path bootstrap

# Confidence floors swept in the report. The live gate will pick one; the sweep
# shows the cost (missed reads) vs safety (wrong reads) tradeoff at each.
THRESHOLDS = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90)

# How many worst (thinnest-margin) confuser pairs to keep per category.
_WORST_N = 15

# Dark canvas fill for the synthetic crop (mirrors the r96 fixtures' dark HUD
# backdrop). A low non-zero value avoids a perfectly flat border.
_BG = 12


def synth_crop(tpl_rgb, bg=_BG):
    """Paste one full-res RGB icon centered on a dark canvas sized so that
    match_icon's internal template (vtm._TPL_FRAC * min-dim) lands at ~the
    icon's own scale, giving a clean self-match. Returns an (H, W, 3) uint8 RGB
    crop strictly larger than the icon (a dark border on every side)."""
    import numpy as np
    a = np.asarray(tpl_rgb)
    h, w = int(a.shape[0]), int(a.shape[1])
    ch = max(h + 2, int(round(h / vtm._TPL_FRAC)))
    cw = max(w + 2, int(round(w / vtm._TPL_FRAC)))
    canvas = np.full((ch, cw, 3), int(bg), dtype=np.uint8)
    oy = (ch - h) // 2
    ox = (cw - w) // 2
    canvas[oy:oy + h, ox:ox + w] = np.clip(a[:, :, :3], 0, 255).astype(np.uint8)
    return canvas


def _argmax(scored):
    """(best_id, best_conf) over [(stem, conf)] with a strict > tie-break
    (first candidate in list order wins ties), or (None, 0.0) when empty."""
    best_id, best_conf = None, 0.0
    for stem, conf in scored:
        if conf > best_conf:
            best_conf = conf
            best_id = stem
    return best_id, best_conf


def _self_and_confuser(scored, stem):
    """(self_conf, best_other_stem, best_other_conf) for a scored list."""
    self_conf = 0.0
    best_other, best_other_conf = None, -1.0
    for s, c in scored:
        if s == stem:
            self_conf = c
        elif c > best_other_conf:
            best_other_conf = c
            best_other = s
    return self_conf, best_other, (best_other_conf if best_other is not None else 0.0)


def validate_category(category, thresholds=THRESHOLDS, worst_n=_WORST_N):
    """Run the pristine-ceiling validation for one category. Returns a dict:

    {
      "category": str,
      "n": int,
      "self_match": {"correct": int, "total": int, "rate": float},
      "wrong": [ {"id","pred","self_conf","pred_conf"}, ... ],   # argmax != self
      "confusions": [ {"id","self_conf","confuser","confuser_conf","margin"}, ...
                      ],                                  # thinnest margin first
      "threshold_sweep": { thr: {"confident_correct","confident_wrong",
                                 "abstain"} },            # partitions n at each thr
    }
    Fail-soft: an empty atlas yields n=0 and empty sub-structures."""
    atlas = vtm._atlas(category)
    ids = sorted(atlas.keys())
    n = len(ids)
    correct = 0
    wrong = []
    confusions = []
    sweep = {float(t): {"confident_correct": 0, "confident_wrong": 0, "abstain": 0}
             for t in thresholds}

    for stem in ids:
        crop = synth_crop(atlas[stem])
        scored = vtm.score_all(crop, category)
        if not scored:
            for t in thresholds:
                sweep[float(t)]["abstain"] += 1
            wrong.append({"id": stem, "pred": None, "self_conf": 0.0, "pred_conf": 0.0})
            continue

        best_id, best_conf = _argmax(scored)
        self_conf, confuser, confuser_conf = _self_and_confuser(scored, stem)
        is_correct = best_id == stem
        if is_correct:
            correct += 1
        else:
            wrong.append({"id": stem, "pred": best_id,
                          "self_conf": round(self_conf, 3),
                          "pred_conf": round(best_conf, 3)})
        if confuser is not None:
            confusions.append({"id": stem, "self_conf": round(self_conf, 3),
                               "confuser": confuser,
                               "confuser_conf": round(confuser_conf, 3),
                               "margin": round(self_conf - confuser_conf, 3)})
        for t in thresholds:
            tk = float(t)
            if best_conf >= t:
                if is_correct:
                    sweep[tk]["confident_correct"] += 1
                else:
                    sweep[tk]["confident_wrong"] += 1
            else:
                sweep[tk]["abstain"] += 1

    confusions.sort(key=lambda d: d["margin"])
    rate = round(correct / n, 4) if n else 0.0
    # A self-match miss whose winner is a pixel-identical icon (margin ~0 at
    # conf ~1.0) is a DDragon duplicate, not a matcher weakness - DDragon ships
    # mode variants (Arena Flash, ARAM Snowball, Arena boot mirrors) as separate
    # ids with identical art, so the pixels alone cannot pick between them. We
    # surface those separately and report an effective rate that credits them.
    twins = [w for w in wrong
             if w["pred"] is not None
             and w["self_conf"] >= 0.99
             and abs(w["self_conf"] - w["pred_conf"]) < 1e-6]
    effective = round((correct + len(twins)) / n, 4) if n else 0.0
    return {
        "category": category,
        "n": n,
        "self_match": {"correct": correct, "total": n, "rate": rate},
        "identical_twins": twins,
        "effective_rate": effective,
        "wrong": wrong,
        "confusions": confusions[:worst_n],
        "threshold_sweep": sweep,
    }


def render_report(results):
    """Render the results dict {category: validate_category(...)} to a Markdown
    report string. The header flags the pristine-ceiling caveat explicitly."""
    out = []
    out.append("# CV atlas flip-readiness - pristine-icon CEILING")
    out.append("")
    out.append("Generated by `tools/vision_atlas_validate.py`. Each icon is pasted on a")
    out.append("dark canvas at template scale and matched against its whole category via")
    out.append("`core.vision_template_match.score_all`.")
    out.append("")
    out.append("This is the CEILING over pristine DDragon icons, NOT live in-game")
    out.append("accuracy. Real HUD crops carry JPEG / resize / lighting noise, so live")
    out.append("numbers run lower; the live wiring + Live-Client/CV fusion stay")
    out.append("operator/live-gated. A low ceiling here is a hard blocker regardless.")
    out.append("")

    for cat in sorted(results.keys()):
        r = results[cat]
        sm = r["self_match"]
        pct = round(sm["rate"] * 100, 1)
        out.append("## " + cat + " (n=" + str(r["n"]) + ")")
        out.append("")
        twins = r.get("identical_twins", [])
        eff = round(r.get("effective_rate", sm["rate"]) * 100, 1)
        out.append("- self-match: " + str(sm["correct"]) + "/" + str(sm["total"])
                   + " = " + str(pct) + "% (argmax == self, pre-threshold)")
        out.append("- effective: " + str(eff)
                   + "% (crediting pixel-identical duplicate icons - see below)")
        out.append("")

        if twins:
            out.append("### Pixel-identical duplicate icons (expected, not a defect)")
            out.append("")
            out.append("DDragon mode variants with identical art; the pixels cannot")
            out.append("disambiguate them, and a downstream read of either id is fine.")
            out.append("")
            out.append("| icon | identical to | conf |")
            out.append("| --- | --- | --- |")
            for w in twins:
                out.append("| " + str(w["id"]) + " | " + str(w["pred"]) + " | "
                           + str(w["self_conf"]) + " |")
            out.append("")

        genuine = [w for w in r["wrong"] if w not in twins]
        if genuine:
            out.append("### Genuinely mis-identified icons (argmax is a DIFFERENT icon)")
            out.append("")
            out.append("| icon | predicted | self conf | pred conf |")
            out.append("| --- | --- | --- | --- |")
            for w in genuine:
                out.append("| " + str(w["id"]) + " | " + str(w["pred"]) + " | "
                           + str(w["self_conf"]) + " | " + str(w["pred_conf"]) + " |")
            out.append("")

        out.append("### Thinnest confuser margins (top " + str(len(r["confusions"])) + ")")
        out.append("")
        out.append("| icon | self conf | nearest confuser | conf | margin |")
        out.append("| --- | --- | --- | --- | --- |")
        for c in r["confusions"]:
            out.append("| " + str(c["id"]) + " | " + str(c["self_conf"]) + " | "
                       + str(c["confuser"]) + " | " + str(c["confuser_conf"])
                       + " | " + str(c["margin"]) + " |")
        out.append("")

        out.append("### Threshold sweep")
        out.append("")
        out.append("| threshold | confident-correct | confident-wrong | abstain |")
        out.append("| --- | --- | --- | --- |")
        for t in sorted(r["threshold_sweep"].keys()):
            cell = r["threshold_sweep"][t]
            out.append("| " + str(t) + " | " + str(cell["confident_correct"]) + " | "
                       + str(cell["confident_wrong"]) + " | " + str(cell["abstain"]) + " |")
        out.append("")

    return "\n".join(out)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Offline CV atlas flip-readiness validator")
    ap.add_argument("--categories", default="champions,items,spells",
                    help="comma-separated category names (default: all three)")
    ap.add_argument("--out", default="data/vision_atlas_accuracy.md",
                    help="markdown report output path (atomic write)")
    ns = ap.parse_args(argv)

    results = {}
    for cat in [c.strip() for c in ns.categories.split(",") if c.strip()]:
        res = validate_category(cat)
        results[cat] = res
        sm = res["self_match"]
        print(cat + ": self-match " + str(sm["correct"]) + "/" + str(sm["total"])
              + " (" + str(round(sm["rate"] * 100, 1)) + "%), "
              + str(len(res["wrong"])) + " mis-id")

    md = render_report(results)
    out_path = Path(ns.out)
    if not out_path.is_absolute():
        out_path = _ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(md, encoding="utf-8")
    tmp.replace(out_path)
    print("wrote " + str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
