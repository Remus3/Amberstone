"""Guards for core/provider_cascade.py.

RC already has this shape by hand in more than one place: a live source
tried first, a static seed behind it, and a kill switch. The duo-synergy lane
is exactly that. Each ad-hoc copy re-decides the same four questions - which
source ran, what happens when it fails, whether a partial answer counts, and
how the consumer learns which source served it - and they do not all answer
the same way.

This is the shared primitive. The provenance stamp is the load-bearing part:
RC's own rule is that a displayed metric must carry where it came from, so
the serving provider id is attached to every result rather than left implicit.

Design borrowed (re-implemented, not vendored) from a reviewed MIT plugin's
provider registry, including its one genuinely good idea: inside a provider,
REQUIRED sub-sources raise and let the cascade move on, while OPTIONAL
sub-sources degrade to a default so a nice-to-have outage does not discard an
otherwise good answer.
"""

import pytest

from core import provider_cascade as pc


def provider(pid, value=None, boom=None):
    def call(**_kwargs):
        if boom is not None:
            raise boom
        return value

    return pc.Provider(id=pid, label=pid.upper(), call=call)


class TestOrdering:
    def test_selected_provider_runs_first(self):
        cascade = pc.ProviderCascade(
            [provider("a", {"v": 1}), provider("b", {"v": 2})], order=["a", "b"]
        )
        result = cascade.resolve(selected="b")
        assert result.source == "b"
        assert result.value["v"] == 2

    def test_falls_through_in_declared_order(self):
        cascade = pc.ProviderCascade(
            [
                provider("a", boom=RuntimeError("down")),
                provider("b", boom=RuntimeError("also down")),
                provider("c", {"v": 3}),
            ],
            order=["a", "b", "c"],
        )
        result = cascade.resolve()
        assert result.source == "c"
        assert result.fell_back is True
        assert [pid for pid, _ in result.attempted] == ["a", "b"]

    def test_selected_is_not_retried_during_fallback(self):
        calls = []

        def counting(pid, value=None, boom=None):
            def call(**_kwargs):
                calls.append(pid)
                if boom:
                    raise boom
                return value

            return pc.Provider(id=pid, label=pid, call=call)

        cascade = pc.ProviderCascade(
            [counting("a", boom=RuntimeError("x")), counting("b", {"v": 1})],
            order=["a", "b"],
        )
        cascade.resolve(selected="a")
        assert calls == ["a", "b"], "the failed selection must not run twice"

    def test_unknown_selection_still_resolves_via_order(self):
        cascade = pc.ProviderCascade([provider("a", {"v": 1})], order=["a"])
        assert cascade.resolve(selected="nope").source == "a"

    def test_order_defaults_to_registration_order(self):
        cascade = pc.ProviderCascade([provider("a", {"v": 1}), provider("b", {"v": 2})])
        assert cascade.resolve().source == "a"


class TestProvenance:
    def test_dict_results_are_stamped_in_place(self):
        cascade = pc.ProviderCascade([provider("a", {"v": 1})])
        result = cascade.resolve()
        assert result.value["source"] == "a"

    def test_stamp_does_not_clobber_an_existing_source_key(self):
        cascade = pc.ProviderCascade([provider("a", {"v": 1, "source": "inner"})])
        result = cascade.resolve()
        assert result.value["source"] == "inner"
        assert result.source == "a", "the envelope still records who served it"

    def test_non_dict_results_are_returned_untouched(self):
        cascade = pc.ProviderCascade([provider("a", [1, 2, 3])])
        result = cascade.resolve()
        assert result.value == [1, 2, 3]
        assert result.source == "a"

    def test_no_fallback_flag_when_the_first_choice_serves(self):
        cascade = pc.ProviderCascade([provider("a", {"v": 1})])
        assert cascade.resolve().fell_back is False


class TestEmptyResults:
    def test_none_counts_as_a_failure_and_cascades(self):
        cascade = pc.ProviderCascade(
            [provider("a", None), provider("b", {"v": 2})], order=["a", "b"]
        )
        assert cascade.resolve().source == "b"

    def test_empty_container_counts_as_a_failure_by_default(self):
        cascade = pc.ProviderCascade(
            [provider("a", []), provider("b", [1])], order=["a", "b"]
        )
        assert cascade.resolve().source == "b"

    def test_empty_can_be_accepted_when_asked(self):
        cascade = pc.ProviderCascade(
            [provider("a", []), provider("b", [1])],
            order=["a", "b"],
            accept_empty=True,
        )
        assert cascade.resolve().source == "a"

    def test_zero_is_not_treated_as_empty(self):
        """0 is a legitimate value, not an absent one."""
        cascade = pc.ProviderCascade(
            [provider("a", 0), provider("b", 5)], order=["a", "b"]
        )
        assert cascade.resolve().value == 0


class TestFailure:
    def test_all_failing_raises_carrying_the_first_error(self):
        first = RuntimeError("first failure")
        cascade = pc.ProviderCascade(
            [provider("a", boom=first), provider("b", boom=RuntimeError("second"))],
            order=["a", "b"],
        )
        with pytest.raises(pc.AllProvidersFailed) as excinfo:
            cascade.resolve()
        assert excinfo.value.__cause__ is first
        assert [pid for pid, _ in excinfo.value.attempted] == ["a", "b"]

    def test_empty_registry_raises(self):
        with pytest.raises(pc.AllProvidersFailed):
            pc.ProviderCascade([]).resolve()

    def test_resolve_or_none_swallows_the_failure(self):
        cascade = pc.ProviderCascade([provider("a", boom=RuntimeError("x"))])
        assert cascade.resolve_or_none() is None

    def test_kwargs_reach_the_provider(self):
        seen = {}

        def call(**kwargs):
            seen.update(kwargs)
            return {"ok": True}

        cascade = pc.ProviderCascade([pc.Provider("a", "A", call)])
        cascade.resolve(champion_id=22, mode="aram")
        assert seen == {"champion_id": 22, "mode": "aram"}


class TestOptionalHelper:
    def test_optional_swallows_and_returns_the_default(self):
        def boom():
            raise RuntimeError("sub-source down")

        assert pc.optional(boom, default=[]) == []

    def test_optional_passes_the_value_through(self):
        assert pc.optional(lambda: [1], default=[]) == [1]

    def test_optional_default_is_none_when_unspecified(self):
        def boom():
            raise RuntimeError("x")

        assert pc.optional(boom) is None
