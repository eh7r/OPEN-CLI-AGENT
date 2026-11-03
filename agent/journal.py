"""A record of what happened in a session, written by code (never by the model)."""

MAX_TASKS = 200
TASK_CHARS = 200
ARGS_CHARS = 200
RESULT_CHARS = 300
REPLY_CHARS = 600

OUTCOMES = ("running", "done", "cancelled", "error", "full")


def _cut(value, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        text = text[: limit - 3].rstrip() + "..."
    return text


class Journal:
    """One entry per task: outcome, tools that ran, and the last reply."""

    def __init__(self, tasks=None):
        self.tasks = [t for t in (tasks if isinstance(tasks, list) else []) if isinstance(t, dict)]
        self._cur = None

    def begin(self, task: str) -> None:
        self._cur = {
            "task": _cut(task, TASK_CHARS),
            "outcome": "running",
            "note": "",
            "reply": "",
            "tools": [],
        }
        self.tasks.append(self._cur)
        del self.tasks[:-MAX_TASKS]

    def tool(self, name, args, status, result) -> None:
        if self._cur is None:
            return
        self._cur["tools"].append({
            "name": str(name),
            "args": _cut(args, ARGS_CHARS),
            "status": str(status),
            "result": _cut(result, RESULT_CHARS),
        })

    def reply(self, text) -> None:
        if self._cur is not None and str(text or "").strip():
            self._cur["reply"] = _cut(text, REPLY_CHARS)

    def end(self, outcome: str, note: str = "") -> None:
        if self._cur is None:
            return
        self._cur["outcome"] = outcome if outcome in OUTCOMES else "error"
        self._cur["note"] = _cut(note, RESULT_CHARS)
        self._cur = None


class Recording:
    """Wraps an output object: forwards every call and records what the core reports."""

    def __init__(self, out, journal: Journal):
        self._out = out
        self._journal = journal
        self._buf = ""

    def __getattr__(self, name):
        return getattr(self._out, name)

    def model_start(self, step):
        self._buf = ""
        return self._out.model_start(step)

    def token(self, text):
        self._buf += text
        return self._out.token(text)

    def model_end(self):
        self._journal.reply(self._buf)
        return self._out.model_end()

    def tool_end(self, name, args, status, result):
        self._journal.tool(name, args, status, result)
        return self._out.tool_end(name, args, status, result)
