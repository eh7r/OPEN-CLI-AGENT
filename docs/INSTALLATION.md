# Installation Guide

A short guide to get Ai-Agent running on Linux.

## Requirements | المكتبات التي تحتاجها لتشغيل الـ Agent

You need four things: **Python 3.10+**, **git**, **Ollama**, and the Python libraries in `requirements.txt`.

### 1. Python and git

**Arch Linux**
```bash
sudo pacman -S python python-pip git
```

**Debian / Ubuntu**
```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip git
```

**Fedora**
```bash
sudo dnf install python3 python3-pip git
```

### 2. Ollama

Ollama runs the AI model on your machine.

**Arch Linux (pacman)**
```bash
sudo pacman -S ollama
```

**Arch Linux (yay)**
```bash
yay -S ollama
```

Don't have `yay`? Install it first:
```bash
sudo pacman -S --needed git base-devel
git clone https://aur.archlinux.org/yay.git
cd yay && makepkg -si
```

**Debian / Ubuntu / Fedora** (official install script)
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Start the Ollama service:
```bash
sudo systemctl enable --now ollama
```

If you don't use systemd, run `ollama serve` in a separate terminal instead.

### 3. Python libraries

| Library | What it is for |
|---|---|
| `ollama` | Talks to the Ollama server |
| `rich` | Terminal interface |
| `psutil` | Detects your RAM to pick a model tier |

Installed with **pip** in the Setup step below:
```bash
pip install -r requirements.txt
```

---

## Setup

```bash
git clone https://github.com/eh7r/Ai-agent.git
cd Ai-agent
python3 -m venv .venv
```

Activate the virtual environment:

**bash / zsh**
```bash
source .venv/bin/activate
```

**fish**
```fish
source .venv/bin/activate.fish
```

Install the libraries:
```bash
pip install -r requirements.txt
```

---

## Choosing a model

The agent picks a tier automatically from your RAM. You can override it at any time.

| Tier | Model | Suggested RAM |
|---|---|---|
| Low | `gemma4:e2b` | under 12 GB |
| Mid | `gemma4:e4b` | 12 to 20 GB |
| High | `gpt-oss:20b` | 20 GB or more |

Download the one you want:
```bash
ollama pull gemma4:e2b
ollama pull gemma4:e4b
ollama pull gpt-oss:20b
```

Check the current selection:
```bash
python -c "from agent.config import TIER, MODEL; print(TIER, MODEL)"
```

---

## Settings

Set these as environment variables. Priority: `AGENT_MODEL` > `AGENT_TIER` > automatic detection.

| Variable | Default | Meaning |
|---|---|---|
| `AGENT_MODEL` | from tier | Exact model name, e.g. `gpt-oss:20b` |
| `AGENT_TIER` | automatic | `low`, `mid` or `high` |
| `OLLAMA_HOST` | `http://localhost:11434` | Address of the Ollama server |
| `AGENT_MAX_STEPS` | `10` | Maximum steps per task |

Example (bash / zsh):
```bash
AGENT_MODEL=gpt-oss:20b python your_script.py
```

Example (fish):
```fish
env AGENT_MODEL=gpt-oss:20b python your_script.py
```
