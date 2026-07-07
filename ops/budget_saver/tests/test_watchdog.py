import importlib.util
import pathlib
spec = importlib.util.spec_from_file_location("wd", pathlib.Path(__file__).resolve().parents[1] / "watchdog.py")
wd = importlib.util.module_from_spec(spec); spec.loader.exec_module(wd)
def test_arms_below_threshold():
    assert wd.should_arm(remaining_frac=0.02, threshold=0.05) is True
def test_holds_above_threshold():
    assert wd.should_arm(remaining_frac=0.20, threshold=0.05) is False
