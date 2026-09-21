"""Pin: an empty parametrize list must fail at collection, not skip.

Without this, a guard parametrized over a data table (for example the
cross-repo digest check over ``sorted(SHARED_SHA256)`` in
``tests/test_loop_concurrency.py``) silently degrades to a skip when the table
is emptied, and a skip reads as green. The option lives in ``pytest.ini``.
"""


def test_empty_parameter_set_fails_at_collect(pytestconfig):
    assert pytestconfig.getini("empty_parameter_set_mark") == "fail_at_collect"
