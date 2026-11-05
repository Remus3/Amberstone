"""
tests/snapshot_panels/_route_match.py
RM-1506: Playwright route matchers that stay on the driver side.

A route matcher must be a string glob or a compiled regex, never a function.
Playwright Python cannot send a function to the driver, so one callable matcher
widens its whole context to the glob **/* and every request of every page then
makes a round trip through the Python process. The measurement and the guard:
test_route_matcher_no_wide_interception_rm1506.py.

Both patterns here also compile under JavaScript, because the driver is what
evaluates them: no inline flag, no named group, no lookbehind.
"""
import re


def on_host(host):
    """Matches a URL whose hostname IS `host`, case-insensitively, and nothing
    that only carries it as a substring (`https://x.example/?q=<host>`,
    `https://<host>.evil.example/`, `https://<host>@evil.example/`).

    NOT exact against the `urlsplit(url).hostname == host` callable it replaced.
    Known divergence: a URL with userinfo (`https://user@<host>/s/x.woff2`: the
    callable True, this False), so such a request would miss the stub. Measured
    2026-11-05: 0 divergences on 222 real URLs and no tracked URL uses userinfo,
    so the regex is not widened for a URL nothing uses. It also answers False
    where the callable answered True on a scheme other than http or https, on a
    scheme-less URL, and on an empty or non-numeric port."""
    return re.compile(rf"^https?://{re.escape(host)}(?::\d+)?(?:[/?#]|$)", re.IGNORECASE)


def on_path(path):
    """Matches a URL whose path IS `path` on any host, whatever its query or
    fragment; what `lambda u: urlsplit(u).path == path` answered on an absolute
    URL with a lower-case scheme (it answers False on an upper-case scheme or a
    URL with no scheme, where the lambda answered True)."""
    return re.compile(rf"^[a-z][a-z0-9+.-]*://[^/?#]*{re.escape(path)}(?:[?#]|$)")
