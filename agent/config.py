import os
import psutil

TIERS = {
    "low": "gemma4:e2b",
    "mid": "gemma4:e4b",
    "high": "gpt-oss:20b",
}


def detect_tier() -> str:
    ram_gb = psutil.virtual_memory().total / 1024**3
    if ram_gb >= 20:
        return "high"
    if ram_gb >= 12:
        return "mid"
    return "low"


# Priority: AGENT_MODEL > AGENT_TIER > auto-detect
TIER = os.getenv("AGENT_TIER", detect_tier())
MODEL = os.getenv("AGENT_MODEL", TIERS[TIER])
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "10"))

WORKDIR = os.getenv("AGENT_WORKDIR", os.getcwd())
COMMAND_TIMEOUT = int(os.getenv("AGENT_TIMEOUT", "30"))
MAX_OUTPUT_CHARS = int(os.getenv("AGENT_MAX_OUTPUT", "4000"))

SANDBOX = os.getenv("AGENT_SANDBOX", "on").lower() != "off"
SANDBOX_NET = os.getenv("AGENT_SANDBOX_NET", "0") == "1"

CONTEXT_TOKENS = int(os.getenv("AGENT_CONTEXT", "4096"))
MAX_REPLY_TOKENS = int(os.getenv("AGENT_MAX_REPLY", "1024"))

MEMORY_DB = os.getenv("AGENT_MEMORY_DB", os.path.join(os.getenv("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), "ai-agent", "memory.db"))
