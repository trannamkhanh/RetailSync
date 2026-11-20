from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

import yaml


def test_audit15_performance_config_always_uses_container_paths(tmp_path, monkeypatch):
    spec = spec_from_file_location("audit_perf", Path(__file__).resolve().parents[1] / "prepare_performance.py")
    script = module_from_spec(spec)
    spec.loader.exec_module(script)
    output = tmp_path / "config.yaml"
    monkeypatch.setattr(sys, "argv", ["prepare_performance.py", "normal", "--run-id", "TEST-run",
                                     "--output", str(output)])
    script.main()
    config = yaml.safe_load(output.read_text())
    assert config["ca_file"] == "/repo/.certs/ca.crt"
    assert config["terminal_cert_dir"] == "/repo/.certs/pos"
    assert config["tokens_file"] == "/repo/.tokens/demo_tokens.json"

