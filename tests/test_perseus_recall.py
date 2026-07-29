"""Guards for tools/perseus_recall.py - the compact projection over vault recall.

CLAUDE.md now makes "recall before starting any non-trivial item" mandatory. The
raw MCP recall response works against that: it returns the full entity body
TWICE per hit (``content`` and ``body_json``), and LEDGER entities routinely
carry multi-kilobyte bodies. A four-hit query costs thousands of tokens of
context, every session, for what is usually a three-field answer.

So the projection is not cosmetic - it is what makes the mandatory step
affordable. The rule this file pins: a projected hit NEVER carries the raw
body fields.
"""

import json

import pytest

from tools import perseus_recall as pr


def hit(key="k", category="project", summary="a summary", content="X" * 5000):
    return {
        "key": key,
        "category": category,
        "summary": summary,
        "content": content,
        "body_json": json.dumps({"content": content, "summary": summary}),
        "decay_score": 0.99,
        "id": "mem-abc",
    }


class TestProjection:
    def test_drops_the_raw_body_fields(self):
        [row] = pr.project([hit()])
        assert "content" not in row
        assert "body_json" not in row

    def test_keeps_the_identifying_fields(self):
        [row] = pr.project([hit(key="my-key", category="settled")])
        assert row["key"] == "my-key"
        assert row["category"] == "settled"

    def test_trims_the_summary(self):
        [row] = pr.project([hit(summary="y" * 500)], chars=80)
        assert len(row["summary"]) <= 80

    def test_falls_back_to_body_content_when_summary_is_missing(self):
        raw = hit(summary="")
        [row] = pr.project([raw], chars=40)
        assert row["summary"], "a hit with no summary must still say something"
        assert row["summary"].startswith("X")

    def test_summary_is_single_line(self):
        raw = hit(summary="line one\nline two\n\nline three")
        [row] = pr.project([raw])
        assert "\n" not in row["summary"]

    def test_projection_is_much_smaller_than_the_raw_hit(self):
        raw = hit()
        projected = pr.project([raw])
        assert len(json.dumps(projected)) < len(json.dumps([raw])) / 10

    @pytest.mark.parametrize("bad", [None, "string", 123, [], {}])
    def test_malformed_hits_never_raise(self, bad):
        assert pr.project([bad]) == [] or isinstance(pr.project([bad]), list)

    def test_empty_input(self):
        assert pr.project([]) == []

    def test_missing_keys_default_rather_than_raise(self):
        [row] = pr.project([{"key": "only-key"}])
        assert row["key"] == "only-key"
        assert row["category"] == "?"


class TestFormatting:
    def test_one_line_per_hit(self):
        text = pr.format_lines(pr.project([hit(key="a"), hit(key="b")]))
        assert len(text.splitlines()) == 2

    def test_line_carries_category_and_key(self):
        text = pr.format_lines(pr.project([hit(key="my-key", category="settled")]))
        assert "settled" in text
        assert "my-key" in text

    def test_empty_renders_a_no_hits_marker(self):
        assert pr.format_lines([]).strip() == pr.NO_HITS
