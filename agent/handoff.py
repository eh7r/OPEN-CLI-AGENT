"""The handoff text: built by code from the session journal, so every fact is exact."""
import os
import re
import tempfile

from agent import sessions

MAX_TASKS = 15
MAX_FILES = 20
MAX_COMMANDS = 15
MAX_PROBLEMS = 15

MARKS = {
    "done": "done",
    "cancelled": "cancelled",
    "error": "error",
    "full": "context full",
    "running": "unfinished",
}


def _tools(task: dict) -> list:
    tools = task.get("tools")
    if not isinstance(tools, list):
        return []
    return [t for t in tools if isinstance(t, dict)]


def _arg(tool: dict, key: str) -> str:
    """One argument of a tool call; works for dict args and for old saved text args."""
    args = tool.get("args")
    if isinstance(args, dict):
        return str(args.get(key, ""))
    m = re.search(r"""'%s': (?:'([^']*)'|"([^"]*)")""" % re.escape(key), str(args or ""))
    if m:
        return m.group(1) or m.group(2) or ""
    return ""


def _exit_code(tool: dict):
    m = re.match(r"exit code: (-?\d+)", str(tool.get("result", "")))
    return m.group(1) if m else None


def _describe(tool: dict) -> str:
    detail = _arg(tool, "command") or _arg(tool, "path") or _arg(tool, "message")
    return f"{tool.get('name', '?')} {detail}".strip()


def _section(title: str, items: list, earlier: int = 0) -> list:
    out = [title]
    if earlier:
        out.append(f"- (+{earlier} earlier)")
    out.extend(items or ["- none"])
    out.append("")
    return out


def build(session_id, workdir, tasks, model_text: str = "") -> str:
    tasks = [t for t in (tasks or []) if isinstance(t, dict)]
    out = [f"Handoff for session {session_id or 'unsaved'}", f"Work dir: {workdir}", ""]

    shown = tasks[-MAX_TASKS:]
    first = len(tasks) - len(shown) + 1
    lines = [
        f"{first + i}. [{MARKS.get(t.get('outcome'), t.get('outcome', '?'))}] {t.get('task', '')}"
        for i, t in enumerate(shown)
    ]
    out += _section("Tasks:", lines, len(tasks) - len(shown))

    files = []
    for t in tasks:
        for tool in _tools(t):
            if tool.get("name") == "write_file" and tool.get("status") == "ok":
                path = _arg(tool, "path")
                if path and path not in files:
                    files.append(path)
    out += _section("Files written:", [f"- {p}" for p in files[-MAX_FILES:]], max(0, len(files) - MAX_FILES))

    cmds = []
    for t in tasks:
        for tool in _tools(t):
            if tool.get("name") == "terminal" and tool.get("status") in ("ok", "failed", "timeout"):
                code = _exit_code(tool)
                result = f"exit {code}" if code is not None else str(tool.get("status"))
                cmds.append(f"- {_arg(tool, 'command')} -> {result}")
    out += _section("Commands run:", cmds[-MAX_COMMANDS:], max(0, len(cmds) - MAX_COMMANDS))

    problems = []
    for n, t in enumerate(tasks, 1):
        for tool in _tools(t):
            if tool.get("status") != "ok":
                problems.append(f"- task {n}: {_describe(tool)} ({tool.get('status')})")
        outcome = t.get("outcome")
        if outcome in ("error", "cancelled", "full", "running"):
            note = t.get("note")
            problems.append(f"- task {n}: {MARKS[outcome]}" + (f": {note}" if note else ""))
    out += _section("Problems:", problems[-MAX_PROBLEMS:], max(0, len(problems) - MAX_PROBLEMS))

    reply = tasks[-1].get("reply", "") if tasks else ""
    out += ["Last reply:", reply or "(none)", ""]

    if model_text and model_text.strip():
        out += ["Next steps and tips (written by the model, check them):", model_text.strip(), ""]
    return "\n".join(out).rstrip() + "\n"


MODEL_INPUT_CHARS = 1500
MODEL_TOKENS = 200
MODEL_PROMPT = (
    "Below are the facts of a coding-agent session. Write at most 5 short bullet points: "
    "what is left to do and tips for continuing. Use only these facts, do not invent anything. "
    "Reply in the same language as the tasks."
)


def _cut(text: str, limit: int = MODEL_INPUT_CHARS) -> str:
    """Keep the start (tasks) and the end (problems, last reply) of a long handoff."""
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + "\n...\n" + text[-half:]


def model_section(text: str, ask=None, cancel=None) -> str:
    """Short model-written next steps from the code-built handoff; "" on any failure."""
    if ask is None:
        from agent import model

        ask = model.ask
    messages = [
        {"role": "system", "content": MODEL_PROMPT},
        {"role": "user", "content": _cut(text)},
    ]
    try:
        reply = ask(messages, None, cancel=cancel, max_tokens=MODEL_TOKENS)
        return (getattr(reply, "content", "") or "").strip()
    except Exception:
        return ""


def handoffs_dir() -> str:
    return os.path.join(os.path.dirname(sessions.sessions_dir()), "handoffs")


def save(session_id: str, text: str) -> str:
    """Atomic write of <data>/handoffs/<id>.md; returns the path."""
    if not sessions.valid_id(session_id):
        raise ValueError("bad session id")
    folder = handoffs_dir()
    os.makedirs(folder, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        path = os.path.join(folder, session_id + ".md")
        os.replace(tmp, path)
        return path
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raiseo
