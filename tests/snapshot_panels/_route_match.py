"""
tests/snapshot_panels/_route_match.py
RM-1506: Playwright route matchers that stay on the driver side.

A route matcher must be a string glob or a compiled regex, never a function.
Playwright Python cannot send a function to the driver, so one callable matcher
widens its whole context to the glob **/* and every request of every page then
makes a round trip through the Python process (test_route_matcher_no_wide_
interception_rm1506.py has the measurement and the guard).

Both patterns here also compile under JavaScript, because the driver is what
evaluates them: no inline flag, no named group, no lookbehind.
"""
import re


def on_host(host):
    """Matches a URL whose hostname IS `host`, case-insensitively, and nothing
    that only carries it as a substring (`https://x.example/?q=<host>`,
    `https://<host>.evil.example/`, `https://<host>@evil.example/`)."""
    return re.compile(rf"^https?://{re.escape(host)}(?::\d+)?(?:[/?#]|$)", re.IGNORECASE)


def on_path(path):
    """Matches a URL whose path IS `path` on any host, whatever its query or
    fragment; what `lambda u: urlsplit(u).path == path` answered."""
    return re.compile(rf"^[a-z][a-z0-9+.-]*://[^/?#]*{re.escape(path)}(?:[?#]|$)")
