import yaml
import pathlib
CFG = pathlib.Path(__file__).resolve().parents[1] / "config.yaml"

def test_config_has_expected_models_and_fallbacks():
    data = yaml.safe_load(CFG.read_text(encoding="utf-8"))
    names = {m["model_name"] for m in data["model_list"]}
    assert {"rc-main","rc-local","rc-background","rc-deepseek","rc-deepseek-pro","rc-nemotron"} <= names
    rs = data["router_settings"]
    fb = {k: v for d in rs["fallbacks"] for k, v in d.items()}
    assert "rc-deepseek" in fb["rc-main"] and "rc-nemotron" in fb["rc-main"]
    cwfb = {k: v for d in rs["context_window_fallbacks"] for k, v in d.items()}
    assert "rc-deepseek" in cwfb["rc-main"]
    # no literal secrets
    raw = CFG.read_text(encoding="utf-8")
    assert "sk-" not in raw and "nvapi-" not in raw
