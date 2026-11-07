<div align="center">

# OPEN CLI AGENT

A local AI agent for the terminal. It runs on Ollama, executes commands inside a sandbox, and asks for approval before any risky action.

![Status](https://img.shields.io/badge/status-work%20in%20progress-orange)
![Python](https://img.shields.io/badge/python-3.14-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial-blue)


</div>

> [!WARNING]
> This is a personal project that is still under development. It has not had an official release, and commands or behavior may change.

<div align="center">
  <img src="docs/assets/preview.gif" width="100%" alt="OPEN CLI AGENT running in a terminal" />
</div>

## About

I started this project to understand how a coding agent works from the inside, and to build one where safety is enforced by code instead of by the prompt. Everything runs locally through [Ollama](https://ollama.com), so no API key is needed and no data leaves the machine.

The agent can run shell commands, read and write files inside a working directory, and use Git. Each action goes through a permission layer, and commands run in a bubblewrap sandbox. This README describes what I built, the decisions behind it, and what is still missing.

Contents: [Installation](#installation) · [Usage](#usage) · [How it works](#how-it-works) · [Design decisions](#design-decisions) · [Configuration](#configuration) · [Development](#development) · [Status](#status) · [License](#license)

## Installation

Requirements:

- Linux. The sandbox depends on [bubblewrap](https://github.com/containers/bubblewrap), so other systems are not supported.
- Python 3.14. I developed and tested on 3.14.
- [Ollama](https://ollama.com) with at least one supported model pulled.
- [pipx](https://pipx.pypa.io).

```bash
# Pull a model (see the tiers below)
ollama pull gemma4:e4b

# Install the openagent command
pipx install git+https://github.com/eh7r/OPEN-CLI-AGENT.git
```

To work on the code instead, clone the repository and install it in editable mode:

```bash
git clone https://github.com/eh7r/OPEN-CLI-AGENT.git
cd OPEN-CLI-AGENT
pipx install -e .
```

On first launch, a short wizard asks for the model tier and the display language.

### Model tiers

The tier is chosen per device. The code is the same for all of them, because the model adapter hides the differences.

| Tier | Model | Intended hardware |
|---|---|---|
| Light | `gemma4:e2b` | Low-RAM machines |
| Balanced | `gemma4:e4b` | Most laptops |
| Strong | `gpt-oss:20b` | Powerful hardware |

The wizard suggests a tier based on RAM. It can be changed later with `--setup`.

## Usage

Run `openagent` from any project folder. That folder becomes the agent's working directory.

```bash
openagent              # full-screen TUI
openagent --plain      # plain terminal session
openagent -c           # continue the last session
openagent -s <id>      # continue a specific session
openagent --setup      # run the setup wizard again
openagent --notes      # list saved notes
```

Slash commands inside a session:

| Command | Description |
|---|---|
| `/help` | Show commands and keys |
| `/new` | Start a new session |
| `/clear` | Clear the screen |
| `/context` | Show context usage |
| `/model` | Show model details |
| `/handoff` | Copy a continuation summary to the clipboard |
| `/exit` | Save the session and quit |

`Esc` interrupts a running task. The session stays open after each reply, and the context is shared across tasks.

## How it works

<div align="center">
  <img src="docs/assets/architecture.jpg" width="100%" alt="System architecture" />
</div>

A task goes through the agent loop in `core.py`. The model either answers or requests a tool call. A tool call is validated against the registry, passed through the permission layer, executed inside the sandbox, and evaluated. The result is returned to the model, within a step limit.

Project layout:

```text
OPEN-CLI-AGENT/
├── main.py              entry point
├── pyproject.toml       packaging, defines the openagent command
├── agent/
│   ├── core.py          agent loop
│   ├── model.py         Ollama adapter (streaming, warm-up, cancel)
│   ├── tools.py         tool registry and argument validation
│   ├── permissions.py   permission layer
│   ├── approval.py      approval flow
│   ├── sandbox.py       bubblewrap sandbox
│   ├── shell.py         command execution
│   ├── file_tools.py    read, write, list
│   ├── git_tools.py     status, diff, commit
│   ├── evaluate.py      outcome classification and retry rules
│   ├── context.py       context trimming
│   ├── memory.py        notes (SQLite)
│   ├── sessions.py      saved sessions
│   ├── journal.py       per-session journal
│   ├── handoff.py       handoff generation
│   ├── rtl.py           Arabic right-to-left rendering
│   ├── tui.py           full-screen interface (Textual)
│   ├── tui_parts.py     widgets and theme
│   ├── events.py        events from the core to the UI
│   ├── cli.py           plain session
│   └── setup.py         first-run wizard
├── tests/               pytest suite
└── docs/                guides and images
```

## Design decisions

### Permission layer

Every tool call is classified before it runs. Known-safe commands run directly, dangerous ones are blocked, and everything else shows the exact action and waits for a yes or no. I set three rules for failures:

1. The same tool with the same arguments runs at most twice.
2. A refusal from the user is not a technical error. The model must not try another tool to get around it.
3. Dangerous actions are never retried automatically. A command may have partly run before a timeout, and running it again could cause a double effect.

### Sandbox

Commands run in bubblewrap. The network is closed by default, the home directory is hidden, `/usr` and `.git` are read-only, `.env` is hidden, and the environment is cleared. If bubblewrap is missing, the agent refuses to run commands instead of falling back silently. The sandbox can be turned off with `AGENT_SANDBOX=off`, and it prints a warning when it is.

File tools are confined to the working directory and block sensitive files. Git tools stay outside the sandbox and do not support push, reset, or shell access. Commits require approval.

### Notes memory

Notes are stored in SQLite and tied to the absolute project path, not the folder name. Global notes are kept separately. Saving a note always shows the exact text and asks for approval, and deleting one asks first. The model never touches the database directly. Saved notes are given to the model as untrusted data, not as instructions, and secrets are rejected by pattern and length checks.

### Speed on CPU

Two changes made the biggest difference on CPU-only hardware.

Gemma models spent most of their time on hidden thinking. Setting `think=False` brought a two-step task on `gemma4:e2b` from about 40 seconds to 3 seconds. Thinking can be re-enabled with `AGENT_THINK=1`.

The first reply on `gemma4:e4b` took about 22 seconds, and the timing log showed that this was the model reading the system prompt and tool schemas (about 800 tokens). The agent now sends the real session start once at launch with `num_predict=1`, so the prompt is cached. A cached prompt costs 0.1 to 0.4 seconds. The warm-up itself still takes around 30 seconds on a cold start, and the status line says so while it runs.

### Handoff

When the context reaches 85% or the session is full, the agent prints a summary for continuing in a new session. The summary is built by code from a journal written during the work: tasks and their outcome, files written, commands with exit codes, errors, declined actions, and the last reply. A short section with remaining work and tips is written by the model from the journal facts only. It is marked as model-written, and it is skipped if the call fails.

### Arabic right-to-left display

Arabic text is converted at render time only, so stored text is never changed. kitty, my terminal, shapes and connects Arabic letters by itself, so reshaping the letters made the text look scrambled. What kitty lacks is word order. The `words` mode reverses the order of Arabic words only and keeps English and number runs in place. Other terminals use `arabic-reshaper` with `python-bidi`. The mode is detected automatically and can be forced with `AGENT_RTL_MODE`.

## Configuration

The configuration file is `~/.config/ai-agent/config.json`, and environment variables override it. Sessions are stored in `~/.local/share/ai-agent/sessions/`. The folder names still use the earlier project name `ai-agent`.

| Variable | Effect |
|---|---|
| `AGENT_SANDBOX=off` | Disable the sandbox (prints a warning) |
| `AGENT_SANDBOX_NET=1` | Allow network access inside the sandbox |
| `AGENT_THINK=1` | Enable model thinking (slower) |
| `AGENT_RTL=on\|off` | Force Arabic RTL processing on or off |
| `AGENT_RTL_MODE=words\|bidi` | Choose the RTL strategy |
| `AGENT_TRACE=1` | Write request timings to `/tmp/agent-trace.log` |

## Development

```bash
pip install -r requirements-dev.txt
pytest -q
```

The suite has 468 tests covering the permission layer, sandbox (including real bubblewrap runs), tools, memory, sessions, handoff, RTL rendering, and the approval dialog.

## Status

Done:

- Agent loop, tool registry, permission layer, observe and retry rules
- Terminal, file, and Git tools
- bubblewrap sandbox
- Notes memory and context management
- First-run wizard and streaming replies
- Full-screen TUI with approval dialog
- Arabic RTL display
- Saved sessions and handoff
- Packaging with pipx

Planned:

- `/sessions`, `/notes`, `/memory`, and `/setup` commands
- Skills
- Connectors for GitHub and the browser
- Testing across all three model tiers
- A first official release

Known limitations:

- Arabic display has only been tested in kitty.
- A cancelled request keeps running in Ollama until it finishes.
- A small gap appears after "لا" inside some Arabic words, probably caused by the font.

## License

Released under the [PolyForm Noncommercial License 1.0.0](LICENSE). The source is available, but commercial use is not permitted.

Written by [Yazeed](https://github.com/eh7r). Tutorials on [Yazeed Labs](https://www.youtube.com/@YazeedLabs).
