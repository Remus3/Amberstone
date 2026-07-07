import importlib.util
import pathlib
spec = importlib.util.spec_from_file_location("routing", pathlib.Path(__file__).resolve().parents[1] / "routing.py")
routing = importlib.util.module_from_spec(spec); spec.loader.exec_module(routing)

def test_privacy_never_leaves_machine():
    assert routing.choose_model(120_000, 2, privacy=True) == "rc-local"   # even huge+hard stays local
def test_small_routine_is_local():
    assert routing.choose_model(4_000, 0, privacy=False) == "rc-local"
def test_tier2_escalates_to_deepseek():
    assert routing.choose_model(8_000, 2, privacy=False) == "rc-deepseek"
def test_large_context_forces_deepseek():
    assert routing.choose_model(60_000, 0, privacy=False) == "rc-deepseek"
def test_hard_arch_is_deferred():
    assert routing.choose_model(8_000, 3, privacy=False) == "DEFER-TO-CLAUDE"
