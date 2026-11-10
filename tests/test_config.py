"""Tests for agent/config.py: tier detection, saved settings, priorities, env parsing."""
import importlib
import json
import os
import stat
from types import SimpleNamespace

import pytest

from agent import config

ENV_VARS = (
    "AGENT_MODEL", "AGENT_TIER", "AGENT_THINK", "AGENT_SANDBOX", "AGENT_SANDBOX_NET",
    "AGENT_CONTEXT", "AGENT_MAX_REPLY", "AGENT_TIMEOUT", "AGENT_MAX_OUTPUT",
    "AGENT_MAX_STEPS", "OLLAMA_HOST",
)


@pytest.fixture(autouse=True)
def restore_config(monkeypatch):
    """After each test, restore the environment and reload config to its normal state."""
    yield
    monkeypatch.undo()
    importlib.reload(config)


def load(monkeypatch, tmp_path, saved=None, ram_gb=8, **env):
    """Reload config with a clean environment, optional saved file and fake RAM."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        "psutil.virtual_memory", lambda: SimpleNamespace(total=int(ram_gb * 1024**3))
    )
    if saved is not None:
        path = tmp_path / "ai-agent" / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(saved if isinstance(saved, str) else json.dumps(saved))
    return importlib.reload(config)


# ---------- detect_tier ----------

@pytest.mark.parametrize("ram, expected", [
    (4, "low"), (11.9, "low"), (12, "mid"), (19.9, "mid"), (20, "high"), (64, "high"),
])
def test_detect_tier_thresholds(monkeypatch, tmp_path, ram, expected):
    cfg = load(monkeypatch, tmp_path, ram_gb=ram)
    assert cfg.detect_tier() == expected


def test_tiers_map_to_expected_models(monkeypatch, tmp_path):
    cfg = load(monkeypatch, tmp_path)
    assert cfg.TIERS == {"low": "gemma4:e2b", "mid": "gemma4:e4b", "high": "gpt-oss:20b"}


# ---------- load_saved / save_settings ----------

def test_load_saved_missing_file(monkeypatch, tmp_path):
    assert load(monkeypatch, tmp_path).load_saved() == {}


def test_load_saved_invalid_json(monkeypatch, tmp_path):
    assert load(monkeypatch, tmp_path, saved="{not json").load_saved() == {}


def test_load_saved_non_dict_json(monkeypatch, tmp_path):
    assert load(monkeypatch, tmp_path, saved="[1, 2, 3]").load_saved() == {}


def test_load_saved_valid(monkeypatch, tmp_path):
    cfg = load(monkeypatch, tmp_path, saved={"tier": "mid", "model": "gemma4:e4b"})
    assert cfg.load_saved() == {"tier": "mid", "model": "gemma4:e4b"}


def test_save_settings_roundtrip(monkeypatch, tmp_path):
    cfg = load(monkeypatch, tmp_path)
    cfg.save_settings({"tier": "high", "model": "gpt-oss:20b"})
    assert cfg.load_saved() == {"tier": "high", "model": "gpt-oss:20b"}


def test_save_settings_file_ends_with_newline(monkeypatch, tmp_path):
    cfg = load(monkeypatch, tmp_path)
    cfg.save_settings({"tier": "low"})
    with open(cfg.CONFIG_PATH, encoding="utf-8") as f:
        assert f.read().endswith("\n")


def test_save_settings_creates_private_directory(monkeypatch, tmp_path):
    cfg = load(monkeypatch, tmp_path)
    cfg.save_settings({"tier": "low"})
    mode = stat.S_IMODE(os.stat(os.path.dirname(cfg.CONFIG_PATH)).st_mode)
    assert mode == 0o700


def test_config_path_uses_xdg_config_home(monkeypatch, tmp_path):
    cfg = load(monkeypatch, tmp_path)
    assert cfg.CONFIG_PATH == str(tmp_path / "ai-agent" / "config.json")


# ---------- GIT_REPO_AT_LAUNCH (S1) ----------

def test_git_repo_at_launch_true_for_real_dir(monkeypatch, tmp_path):
    proj = tmp_path / "proj"
    (proj / ".git").mkdir(parents=True)
    assert load(monkeypatch, tmp_path, AGENT_WORKDIR=str(proj)).GIT_REPO_AT_LAUNCH is True


@pytest.mark.parametrize("kind", ["missing", "gitfile", "symlink"])
def test_git_repo_at_launch_false(monkeypatch, tmp_path, kind):
    proj = tmp_path / "proj"
    proj.mkdir()
    if kind == "gitfile":
        (proj / ".git").write_text("gitdir: /elsewhere\n")
    elif kind == "symlink":
        (tmp_path / "real-git").mkdir()
        (proj / ".git").symlink_to(tmp_path / "real-git", target_is_directory=True)
    assert load(monkeypatch, tmp_path, AGENT_WORKDIR=str(proj)).GIT_REPO_AT_LAUNCH is False


# ---------- needs_setup ----------

def test_needs_setup_on_first_run(monkeypatch, tmp_path):
    assert load(monkeypatch, tmp_path).needs_setup() is True


def test_needs_setup_false_after_saved(monkeypatch, tmp_path):
    assert load(monkeypatch, tmp_path, saved={"tier": "mid"}).needs_setup() is False


def test_needs_setup_false_with_env_model(monkeypatch, tmp_path):
    assert load(monkeypatch, tmp_path, AGENT_MODEL="x:1").needs_setup() is False


def test_needs_setup_false_with_env_tier(monkeypatch, tmp_path):
    assert load(monkeypatch, tmp_path, AGENT_TIER="low").needs_setup() is False


# ---------- priorities: env > saved > auto-detect ----------

def test_autodetect_when_nothing_set(monkeypatch, tmp_path):
    cfg = load(monkeypatch, tmp_path, ram_gb=16)
    assert cfg.TIER == "mid" and cfg.MODEL == "gemma4:e4b"


def test_saved_beats_autodetect(monkeypatch, tmp_path):
    cfg = load(monkeypatch, tmp_path, saved={"tier": "high", "model": "gpt-oss:20b"}, ram_gb=4)
    assert cfg.TIER == "high" and cfg.MODEL == "gpt-oss:20b"


def test_env_tier_beats_saved(monkeypatch, tmp_path):
    cfg = load(monkeypatch, tmp_path, saved={"tier": "high", "model": "gpt-oss:20b"},
               AGENT_TIER="low")
    assert cfg.TIER == "low" and cfg.MODEL == "gemma4:e2b"


def test_env_model_beats_everything(monkeypatch, tmp_path):
    cfg = load(monkeypatch, tmp_path, saved={"tier": "high", "model": "gpt-oss:20b"},
               AGENT_TIER="low", AGENT_MODEL="custom:7b")
    assert cfg.MODEL == "custom:7b"
    assert cfg.TIER == "low"


def test_invalid_env_tier_is_ignored(monkeypatch, tmp_path):
    cfg = load(monkeypatch, tmp_path, saved={"tier": "mid", "model": "gemma4:e4b"},
               AGENT_TIER="ultra")
    assert cfg.TIER == "mid" and cfg.MODEL == "gemma4:e4b"


def test_invalid_saved_tier_falls_back_to_autodetect(monkeypatch, tmp_path):
    cfg = load(monkeypatch, tmp_path, saved={"tier": "ultra"}, ram_gb=4)
    assert cfg.TIER == "low" and cfg.MODEL == "gemma4:e2b"


def test_saved_tier_without_model_uses_tier_model(monkeypatch, tmp_path):
    cfg = load(monkeypatch, tmp_path, saved={"tier": "high"})
    assert cfg.MODEL == "gpt-oss:20b"


def test_saved_model_must_be_string(monkeypatch, tmp_path):
    cfg = load(monkeypatch, tmp_path, saved={"tier": "mid", "model": 123})
    assert cfg.MODEL == "gemma4:e4b"


def test_corrupt_saved_file_falls_back_to_autodetect(monkeypatch, tmp_path):
    cfg = load(monkeypatch, tmp_path, saved="garbage", ram_gb=25)
    assert cfg.TIER == "high" and cfg.MODEL == "gpt-oss:20b"


# ---------- THINK ----------

@pytest.mark.parametrize("value", ["1", "true", "TRUE", "on", "yes", "Yes"])
def test_think_on_values(monkeypatch, tmp_path, value):
    assert load(monkeypatch, tmp_path, AGENT_THINK=value).THINK is True


@pytest.mark.parametrize("value", ["0", "false", "off", "no", "", "banana"])
def test_think_off_values(monkeypatch, tmp_path, value):
    assert load(monkeypatch, tmp_path, AGENT_THINK=value).THINK is False


def test_think_default_off(monkeypatch, tmp_path):
    assert load(monkeypatch, tmp_path).THINK is False


# ---------- sandbox flags ----------

def test_sandbox_on_by_default(monkeypatch, tmp_path):
    assert load(monkeypatch, tmp_path).SANDBOX is True


@pytest.mark.parametrize("value", ["off", "OFF", "Off"])
def test_sandbox_off(monkeypatch, tmp_path, value):
    assert load(monkeypatch, tmp_path, AGENT_SANDBOX=value).SANDBOX is False


def test_sandbox_other_values_stay_on(monkeypatch, tmp_path):
    assert load(monkeypatch, tmp_path, AGENT_SANDBOX="0").SANDBOX is True


def test_sandbox_network_closed_by_default(monkeypatch, tmp_path):
    assert load(monkeypatch, tmp_path).SANDBOX_NET is False


def test_sandbox_network_opens_only_with_1(monkeypatch, tmp_path):
    assert load(monkeypatch, tmp_path, AGENT_SANDBOX_NET="1").SANDBOX_NET is True
    assert load(monkeypatch, tmp_path, AGENT_SANDBOX_NET="yes").SANDBOX_NET is False


# ---------- numeric settings and defaults ----------

def test_numeric_defaults(monkeypatch, tmp_path):
    cfg = load(monkeypatch, tmp_path)
    assert cfg.MAX_STEPS == 10
    assert cfg.COMMAND_TIMEOUT == 30
    assert cfg.MAX_OUTPUT_CHARS == 4000
    assert cfg.CONTEXT_TOKENS == 4096
    assert cfg.MAX_REPLY_TOKENS == 1024
    assert cfg.OLLAMA_HOST == "http://localhost:11434"


def test_numeric_env_overrides(monkeypatch, tmp_path):
    cfg = load(monkeypatch, tmp_path, AGENT_MAX_STEPS="3", AGENT_TIMEOUT="5",
               AGENT_MAX_OUTPUT="100", AGENT_CONTEXT="8192", AGENT_MAX_REPLY="256",
               OLLAMA_HOST="http://example:1234")
    assert cfg.MAX_STEPS == 3
    assert cfg.COMMAND_TIMEOUT == 5
    assert cfg.MAX_OUTPUT_CHARS == 100
    assert cfg.CONTEXT_TOKENS == 8192
    assert cfg.MAX_REPLY_TOKENS == 256
    assert cfg.OLLAMA_HOST == "http://example:1234"


# ---------- memory database path ----------

def test_memory_db_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_MEMORY_DB", str(tmp_path / "custom.db"))
    assert load(monkeypatch, tmp_path).MEMORY_DB == str(tmp_path / "custom.db")


def test_memory_db_default_uses_xdg_data_home(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENT_MEMORY_DB", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    cfg = load(monkeypatch, tmp_path)
    assert cfg.MEMORY_DB == str(tmp_path / "data" / "ai-agent" / "memory.db")
