import json
import os

import psutil

TIERS = {
    "low": "gemma4:e2b",
    "mid": "gemma4:e4b",
    "high": "gpt-oss:20b",
}

CONFIG_PATH = os.path.join(
    os.getenv("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "ai-agent", "config.json"
)


def detect_tier() -> str:
    ram_gb = psutil.virtual_memory().total / 1024**3
    if ram_gb >= 20:
        return "high"
    if ram_gb >= 12:
        return "mid"
    return "low"


def load_saved() -> dict:
    """Settings saved by the setup wizard (empty if missing or unreadable)."""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(settings: dict) -> None:
    os.makedirs(os.path.dirname(CONFIG_PATH), mode=0o700, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")


def needs_setup() -> bool:
    """True on the very first run: nothing saved and nothing set by the user."""
    return not os.path.exists(CONFIG_PATH) and not (os.getenv("AGENT_MODEL") or os.getenv("AGENT_TIER"))


# Priority: environment variable > saved setup > automatic detection
_saved = load_saved()
_saved_tier = _saved.get("tier") if _saved.get("tier") in TIERS else None
_saved_model = _saved.get("model") if isinstance(_saved.get("model"), str) else None
_env_tier = os.getenv("AGENT_TIER")

TIER = _env_tier if _env_tier in TIERS else (_saved_tier or detect_tier())
if os.getenv("AGENT_MODEL"):
    MODEL = os.getenv("AGENT_MODEL")
elif _env_tier in TIERS:
    MODEL = TIERS[_env_tier]
else:
    MODEL = _saved_model or TIERS[TIER]

THINK = os.getenv("AGENT_THINK", "0").lower() in ("1", "true", "on", "yes")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "10"))

WORKDIR = os.getenv("AGENT_WORKDIR", os.getcwd())
COMMAND_TIMEOUT = int(os.getenv("AGENT_TIMEOUT", "30"))
MAX_OUTPUT_CHARS = int(os.getenv("AGENT_MAX_OUTPUT", "4000"))

SANDBOX = os.getenv("AGENT_SANDBOX", "on").lower() != "off"
SANDBOX_NET = os.getenv("AGENT_SANDBOX_NET", "0") == "1"

CONTEXT_TOKENS = int(os.getenv("AGENT_CONTEXT", "4096"))
MAX_REPLY_TOKENS = int(os.getenv("AGENT_MAX_REPLY", "1024"))

MEMORY_DB = os.getenv(
    "AGENT_MEMORY_DB",
    os.path.join(
        os.getenv("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), "ai-agent", "memory.db"
    ),
)
