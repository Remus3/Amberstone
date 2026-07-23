"""
Headless pseudo-screen for the Riot Commander in-game overlay HUD.

Renders the overlay dock at 2560x1440 with NO League and NO live game, so
overlay UI / UX / theme work can happen fully offline. It drives the same
?overlay=1 + ?ui_mock=1 fixture path the live overlay uses, injects a
synthetic backdrop (the overlay body is transparent by design, so a raw
capture would read black), and writes a downscaled PNG.

Usage:
    python tools/pseudo_screen_overlay.py <mode>

    mode in {sr, aram, mayhem, complete}. Pass "all" to render every mode.

Requires a RUNNING local dashboard at https://127.0.0.1:8888 (RC supervisor).
It does NOT need League, LCU, or a live game - the frame comes from the
committed /data/ui_mock/active_match_<mode>.json fixtures.

Out: tools/pseudo_screen_out/overlay_<mode>_2560.png

Rendering technique (mirrors the scratch ops/runtime/ui_recon/recon.py):
  - ignore_https_errors + --ignore-certificate-errors bypasses the mkcert
    self-signed :8888 cert.
  - deviceScaleFactor=2 renders at 2x then Lanczos-downscales to 2560x1440
    for crisp text output.
  - ovscale=1.333 (= 2560/1920 = 1440/1080) maps the 1920x1080 design-px
    widget field 1:1 onto the 2560x1440 canvas; without it the dock pins
    top-left at 1080p design-px.
"""
import io
import os
import sys
import time
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

# Default target = the live RC dashboard. Override with RC_PSEUDO_BASE to point
# at an alternate origin (e.g. a static server rooted at a worktree's web/ dir
# when validating fixtures that the live server does not yet serve).
BASE = os.environ.get("RC_PSEUDO_BASE", "https://127.0.0.1:8888")
OUT_DIR = Path(__file__).resolve().parent / "pseudo_screen_out"

# Target canvas. 2560/1920 == 1440/1080 == 1.3333, so the overlay design-px
# field maps 1:1 when ?ovscale is this ratio.
CANVAS_W = 2560
CANVAS_H = 1440
OVSCALE = 1.333

# The ui_mock ?mode= URL param the fixture dispatcher (_amMockUrl in
# web/js/main.js) understands. mayhem + complete were added alongside this
# harness.
MODES = ("sr", "aram", "mayhem", "complete")

# Synthetic backdrop. The overlay body is transparent by design (it composits
# over the live game in the Electron window), so a headless capture reads
# black. Inject the proven HEXCORE gradient from the HARNESS only - never from
# web/css/overlay.css, or the background would leak into the real overlay
# window over the live game.
BACKDROP_CSS = (
    "html,body{background:transparent!important;}"
    "#rc-pseudo-backdrop{position:fixed;inset:0;z-index:-1;pointer-events:none;"
    "background:radial-gradient(130% 120% at 50% -10%,"
    "#1a1206 0%,#0d0a07 45%,#050404 100%);}"
)
BACKDROP_JS = (
    "() => {"
    "  if (!document.getElementById('rc-pseudo-backdrop')) {"
    "    const d = document.createElement('div');"
    "    d.id = 'rc-pseudo-backdrop';"
    "    document.body.insertBefore(d, document.body.firstChild);"
    "  }"
    "}"
)

# Inventory of what actually painted, for the proof report.
INVENTORY_JS = r"""() => {
  const ready = document.body.classList.contains('ovx-ready');
  const shell = document.body.dataset.shell || '';
  const uiMock = document.body.dataset.uiMock || '';
  const widgets = [];
  document.querySelectorAll('.ovx-widget').forEach((el) => {
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    const visible = cs.visibility !== 'hidden' &&
                    cs.display !== 'none' &&
                    r.width > 4 && r.height > 4;
    if (visible) {
      widgets.push(el.id || el.className);
    }
  });
  return { ready, shell, uiMock, widgetCount: widgets.length, widgets };
}"""


def _wait_for_ready(page, timeout_s=12.0):
    """Poll for body.ovx-ready (overlay_layout marks it after first place)."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if page.evaluate("() => document.body.classList.contains('ovx-ready')"):
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.25)
    return False


def render(mode, browser):
    if mode not in MODES:
        return {"mode": mode, "error": f"unknown mode (want one of {MODES})"}
    ctx = browser.new_context(
        ignore_https_errors=True,
        viewport={"width": CANVAS_W, "height": CANVAS_H},
        device_scale_factor=2,
    )
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    # Belt-and-suspenders mock forcing (WAKEUP 2026-07-22a caveat): set the
    # localStorage flag on the origin BEFORE the app boots, AND pass ?ui_mock=1
    # on the URL. add_init_script runs before any page script on every nav.
    page.add_init_script("try { localStorage.setItem('rc-ui-mock', '1'); } catch (e) {}")

    url = (
        f"{BASE}/?overlay=1&ui_mock=1&mode={mode}"
        f"&ovscale={OVSCALE}#active-match"
    )
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=25_000)
    except Exception as e:  # noqa: BLE001
        ctx.close()
        return {"mode": mode, "error": f"goto: {e}"}

    ok_ready = _wait_for_ready(page)
    # Short settle for the async fixture fetch + DS pane render after ready.
    time.sleep(2.0)

    # Inject the synthetic backdrop from the harness (not from overlay.css).
    try:
        page.add_style_tag(content=BACKDROP_CSS)
        page.evaluate(BACKDROP_JS)
    except Exception as e:  # noqa: BLE001
        errors.append(f"backdrop: {e}")
    time.sleep(0.4)

    inv = {}
    try:
        inv = page.evaluate(INVENTORY_JS)
    except Exception as e:  # noqa: BLE001
        inv = {"inventory_error": str(e)}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"overlay_{mode}_2560.png"
    try:
        raw = page.screenshot(type="png")
        # deviceScaleFactor=2 gives a 5120x2880 buffer; Lanczos-downscale to
        # the 2560x1440 target for crisp output.
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        if img.size != (CANVAS_W, CANVAS_H):
            img = img.resize((CANVAS_W, CANVAS_H), Image.LANCZOS)
        img.save(out_path, "PNG")
        # Cheap non-black check: sample the mean luminance over RGB bytes.
        small = img.resize((64, 36), Image.BILINEAR)
        buf = small.tobytes()
        mean = sum(buf) / float(len(buf))
    except Exception as e:  # noqa: BLE001
        ctx.close()
        return {"mode": mode, "error": f"screenshot: {e}", "errors": errors[:3]}

    ctx.close()
    return {
        "mode": mode,
        "url": url,
        "out": str(out_path),
        "ovx_ready": ok_ready,
        "mean_luma": round(mean, 2),
        "non_black": mean > 8.0,
        "inventory": inv,
        "errors": errors[:5],
    }


def main():
    arg = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
    if not arg:
        print("usage: python tools/pseudo_screen_overlay.py <sr|aram|mayhem|complete|all>")
        return 2
    modes = list(MODES) if arg == "all" else [arg]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--ignore-certificate-errors",
            ],
        )
        results = [render(m, browser) for m in modes]
        browser.close()

    for r in results:
        print("=" * 60)
        for k, v in r.items():
            print(f"  {k}: {v}")
    any_ok = any(r.get("non_black") for r in results)
    return 0 if any_ok else 1


if __name__ == "__main__":
    sys.exit(main())
