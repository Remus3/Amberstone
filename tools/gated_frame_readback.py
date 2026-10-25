"""gated_frame_readback.py - read the live vision frame ONCE and decode it in memory.

The hand-off live read-back S6 asks a lane, while a game is up, to GET
``http://127.0.0.1:8889/latest-frame`` with the ``X-RC-Token`` header, decode the
bytes with Pillow in memory, and record format / size / mode / the Pillow
version and the time. Two cycles of lane 9 lost that read-back to the same two
traps, so this tool does it in ONE command:

1. The relay answers a JSON ENVELOPE (``vision_server/_frame.py``
   ``get_latest_frame``: ``b64``, ``ts``, ``size``, ``source``, ``width``,
   ``height``, ``format``, ``primary``, ``event_meta``), not raw image bytes.
   Handing the body to Pillow directly fails to decode (s134 gated c12).
2. ``core.vision_token`` raises at import inside a lane worktree, because the
   gitignored ``config/vision_token.txt`` exists only in the MAIN checkout
   (s134 gated c13). This tool never imports it: it resolves the token itself,
   env ``RC_VISION_TOKEN`` first, then this checkout's ``config/vision_token.txt``,
   then the main checkout's (found through the linked worktree's ``.git`` file
   and its ``commondir``). It reads that file and nothing else there.

It is READ-ONLY and makes exactly ONE request. It never prints the token (only
its source), never saves the frame, never writes anywhere, and never ticks a row:
the output is a measurement for the evidence contract in
``docs/LIVE_GAME_GATED_SYNC.md``, not a row closure.

USAGE
    python tools/gated_frame_readback.py           # text to stdout
    python tools/gated_frame_readback.py --json    # machine-readable

Exit 0 = a frame decoded; 1 = the request failed; 2 = no token; 3 = a reply that
did not decode to an image.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_RELAY_URL = "http://127.0.0.1:8889/latest-frame"
_TIMEOUT = 5.0
_ROOT = Path(__file__).resolve().parent.parent
_TOKEN_REL = Path("config") / "vision_token.txt"


def main_checkout(root: Path = _ROOT) -> Path | None:
    """The main checkout of a linked worktree, or None when ``root`` is not one.

    A linked worktree's ``.git`` is a FILE holding ``gitdir: <path>``; that
    gitdir's ``commondir`` file names the shared ``.git`` (either may be
    relative). Its parent is the main checkout.
    """
    dotgit = root / ".git"
    if not dotgit.is_file():
        return None
    try:
        line = dotgit.read_text(encoding="utf-8").splitlines()[0].strip()
        if not line.startswith("gitdir:"):
            return None
        gitdir = Path(line[len("gitdir:"):].strip())
        if not gitdir.is_absolute():
            gitdir = root / gitdir
        common = (gitdir / "commondir").read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, UnicodeDecodeError, IndexError):
        return None
    common_path = Path(common)
    if not common_path.is_absolute():
        common_path = gitdir / common_path
    return common_path.resolve().parent


def _legal(tok: str) -> bool:
    """Printable ASCII only - the same bar ``core.vision_token._checked`` sets."""
    return bool(tok) and all(0x21 <= ord(c) <= 0x7E for c in tok)


def _first_line(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return ""
    return lines[0].strip() if lines else ""


def resolve_token(root: Path = _ROOT,
                  environ: dict | None = None) -> tuple[str, str]:
    """``(token, source)``; source is env / config / main-config, or ("", "none")."""
    env = (os.environ if environ is None else environ).get("RC_VISION_TOKEN", "")
    if env.strip() and _legal(env.strip()):
        return env.strip(), "env"
    tok = _first_line(root / _TOKEN_REL)
    if _legal(tok):
        return tok, "config"
    main = main_checkout(root)
    if main is not None:
        tok = _first_line(main / _TOKEN_REL)
        if _legal(tok):
            return tok, "main-config"
    return "", "none"


def decode_envelope(body: bytes) -> tuple[bytes | None, dict]:
    """Split the relay reply into ``(image_bytes, meta)``.

    A JSON envelope yields its ``b64`` decoded and every other key as meta. A
    body that is not JSON is passed through as raw image bytes with empty meta,
    so a relay that ever serves the image directly still decodes.
    """
    try:
        env = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return body, {}
    if not isinstance(env, dict):
        return None, {}
    meta = {k: v for k, v in env.items() if k != "b64"}
    b64 = env.get("b64")
    if not isinstance(b64, str) or not b64:
        return None, meta
    try:
        return base64.b64decode(b64, validate=False), meta
    except (ValueError, TypeError):
        return None, meta


def pillow_facts(raw: bytes) -> dict:
    """Format / size / mode / luma extrema of ``raw``, decoded in memory only."""
    from PIL import Image, __version__ as pil_version
    with Image.open(io.BytesIO(raw)) as img:
        img.load()
        facts = {"format": img.format, "width": img.size[0],
                 "height": img.size[1], "mode": img.mode,
                 "pillow": pil_version}
        facts["luma_extrema"] = list(img.convert("L").getextrema())
    return facts


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect: a 3xx would be a second request (and a new host)."""

    def redirect_request(self, *_a, **_k):
        return None


# No proxy (the token header must never leave loopback) and no redirects (the
# read-back is ONE request). The real relay does neither, so this only guards.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def read_back(url: str = _RELAY_URL, root: Path = _ROOT,
              environ: dict | None = None, now=time.time) -> tuple[int, dict]:
    """Do the ONE GET and return ``(exit_code, report)``."""
    token, source = resolve_token(root, environ)
    report: dict = {"url": url, "token_source": source}
    if not token:
        report["error"] = "no vision token (env, config or main-config)"
        return 2, report
    req = urllib.request.Request(url, headers={"X-RC-Token": token})
    report["wall"] = now()
    try:
        with _OPENER.open(req, timeout=_TIMEOUT) as resp:
            report["http"] = resp.status
            body = resp.read()
    except urllib.error.HTTPError as exc:
        report["http"] = exc.code
        # The relay's error body is a short JSON reason (404 no_frame_yet before
        # the first frame is cached; 401 unauthorized) - keep it, bounded.
        try:
            reply = exc.read(200).decode("ascii", "backslashreplace")
        except OSError:
            reply = ""
        report["error"] = f"HTTP {exc.code} {reply}".rstrip()
        return 1, report
    except (urllib.error.URLError, OSError) as exc:
        report["error"] = f"{type(exc).__name__}: {getattr(exc, 'reason', exc)}"
        return 1, report
    report["body_bytes"] = len(body)
    raw, meta = decode_envelope(body)
    report["meta"] = meta
    ts = meta.get("ts")
    if isinstance(ts, (int, float)) and ts > 0:
        report["age_s"] = round(report["wall"] - float(ts), 2)
    if not raw:
        report["error"] = "reply carried no image bytes"
        return 3, report
    report["image_bytes"] = len(raw)
    try:
        report["pillow"] = pillow_facts(raw)
    except Exception as exc:  # noqa: BLE001 - any decode failure is the answer
        report["error"] = f"Pillow could not decode: {type(exc).__name__}"
        return 3, report
    return 0, report


def _render(report: dict) -> str:
    out = [f"url {report['url']}  token_source {report['token_source']}"]
    if "http" in report:
        out.append(f"http {report['http']}  body_bytes {report.get('body_bytes')}")
    if "wall" in report:
        local = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(report["wall"]))
        out.append(f"wall {report['wall']:.2f} ({local})  age_s {report.get('age_s')}")
    meta = report.get("meta") or {}
    if meta:
        out.append("meta " + " ".join(f"{k}={meta[k]}" for k in sorted(meta)))
    pil = report.get("pillow")
    if pil:
        out.append(f"pillow {pil['pillow']}: format {pil['format']} size "
                   f"{pil['width']}x{pil['height']} mode {pil['mode']} "
                   f"luma {tuple(pil['luma_extrema'])}  image_bytes "
                   f"{report.get('image_bytes')}")
    if "error" in report:
        out.append(f"error {report['error']}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--url", default=_RELAY_URL, help="relay frame URL")
    args = ap.parse_args(argv)
    code, report = read_back(args.url)
    text = json.dumps(report, sort_keys=True) if args.json else _render(report)
    sys.stdout.write(text.encode("ascii", "backslashreplace").decode("ascii") + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
