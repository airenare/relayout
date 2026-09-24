from relayout.config import load_config, DEFAULT_CONFIG


def test_load_config_defaults_when_file_absent(tmp_path):
    missing = tmp_path / "does-not-exist.toml"
    config = load_config(missing)
    assert config == DEFAULT_CONFIG


def test_load_config_merges_user_overrides(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text('[hotkey]\ntaps = 3\n')
    config = load_config(config_path)
    assert config["hotkey"]["taps"] == 3
    # untouched sections/keys keep their defaults
    assert config["hotkey"]["key"] == DEFAULT_CONFIG["hotkey"]["key"]
    assert config["layouts"] == DEFAULT_CONFIG["layouts"]


def test_load_config_custom_layout_pair(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text('[layouts]\npair = ["us", "de"]\n')
    config = load_config(config_path)
    assert config["layouts"]["pair"] == ["us", "de"]
