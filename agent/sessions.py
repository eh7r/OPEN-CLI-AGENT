"""Saved sessions: one JSON file per conversation under the data folder."""
import json
import os
import re
import secrets
import tempfile
from datetime import datetime, timezone

_ID_RE = re.compile(r"^[0-9a-f]{8}$")
TITLE_MAX = 60


def sessions_dir() -> str:
    base = os.getenv("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "ai-agent", "sessions")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def valid_id(session_id) -> bool:
    return isinstance(session_id, str) and bool(_ID_RE.match(session_id))


def make_title(task: str) -> str:
    """The first task, one line, cut to TITLE_MAX characters (no model call)."""
    text = " ".join(task.split())
    if len(text) > TITLE_MAX:
        text = text[: TITLE_MAX - 3].rstrip() + "..."
    return text or "Untitled"


def _plain(obj):
    """Fallback for objects json cannot write (for example ollama messages)."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump(exclude_none=True)
    return str(obj)


def create(task: str, messages: list, workdir: str) -> dict:
    now = _now()
    return {
        "id": secrets.token_hex(4),
        "title": make_title(task),
        "workdir": workdir,
        "created": now,
        "updated": now,
        "messages": list(messages),
    }


def save(session: dict) -> None:
    """Atomic write: a temp file in the same folder, then rename."""
    if not valid_id(session.get("id")):
        raise ValueError("bad session id")
    folder = sessions_dir()
    os.makedirs(folder, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, default=_plain)
        os.replace(tmp, os.path.join(folder, session["id"] + ".json"))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def update(session: dict, messages: list) -> None:
    session["messages"] = list(messages)
    session["updated"] = _now()
    save(session)


def load(session_id: str):
    """The session dict, or None if the id is bad, the file is missing or broken."""
    if not valid_id(session_id):
        return None
    path = os.path.join(sessions_dir(), session_id + ".json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("id") != session_id:
        return None
    msgs = data.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return None
    if not all(isinstance(m, dict) and "role" in m for m in msgs):
        return None
    return data


def list_all() -> list:
    """All valid sessions, newest first."""
    try:
        names = os.listdir(sessions_dir())
    except OSError:
        return []
    found = []
    for name in names:
        if name.endswith(".json") and valid_id(name[:-5]):
            data = load(name[:-5])
            if data:
                found.append(data)
    found.sort(key=lambda s: str(s.get("updated", "")), reverse=True)
    return found


def last():
    items = list_all()
    return items[0] if items else None
