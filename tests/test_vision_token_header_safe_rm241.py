"""RM-241: a newline-bearing RC_VISION_TOKEN must fail at RESOLVE time.

Before the fix `env.strip()` kept internal newlines; urllib then refused the
header with a ValueError whose text carried the raw token, and every caller
that logs its exception wrote the secret to logs/. The resolver now rejects
such a value once, loudly, with a message that never contains the token.
"""
from __future__ import annotations

import http.client
import logging
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import vision_token as vt  # noqa: E402

SECRET = "SEKRETPART"


@pytest.mark.parametrize("bad", [
    f"abc\ndef-{SECRET}",
    f"abc\rdef-{SECRET}",
    f"abc\x1bdef-{SECRET}",
    f"abc def-{SECRET}",
    f"abc\x7fdef-{SECRET}",
    f"abc\u00e9def-{SECRET}",
])
def test_bad_env_token_raises_without_echoing_it(bad, caplog):
    caplog.set_level(logging.DEBUG)
    with mock.patch.dict("os.environ", {"RC_VISION_TOKEN": bad}):
        with pytest.raises(RuntimeError) as ei:
            vt._resolve()
    assert SECRET not in str(ei.value)
    assert all(SECRET not in r.getMessage() for r in caplog.records)


def test_bad_config_token_raises(tmp_path):
    cfg = tmp_path / "vision_token.txt"
    cfg.write_text(f"abc\x00def-{SECRET}\n", encoding="utf-8")
    with mock.patch.dict("os.environ", {"RC_VISION_TOKEN": ""}), \
            mock.patch.object(vt, "_CONFIG_PATH", cfg):
        with pytest.raises(RuntimeError) as ei:
            vt._resolve()
    assert SECRET not in str(ei.value)


def test_good_tokens_still_resolve(tmp_path):
    with mock.patch.dict("os.environ", {"RC_VISION_TOKEN": "  0123abcdEF-_.~  "}):
        assert vt._resolve() == ("0123abcdEF-_.~", "env")
    cfg = tmp_path / "vision_token.txt"
    cfg.write_text("deadbeef\nsecond line ignored\n", encoding="utf-8")
    with mock.patch.dict("os.environ", {"RC_VISION_TOKEN": ""}), \
            mock.patch.object(vt, "_CONFIG_PATH", cfg):
        assert vt._resolve() == ("deadbeef", "config")


def test_the_leak_mechanism_is_real():
    """Positive control: urllib does put the raw value in its exception."""
    conn = http.client.HTTPConnection("127.0.0.1", 9)
    conn.putrequest("GET", "/")  # no socket opened until send
    with pytest.raises(ValueError) as ei:
        conn.putheader("X-RC-Token", f"abc\ndef-{SECRET}")
    assert SECRET in str(ei.value)
