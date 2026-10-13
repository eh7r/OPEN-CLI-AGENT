from pathlib import Path

from pydantic import BaseModel, Field

from agent.approval import confirm
from agent.config import MAX_OUTPUT_CHARS, WORKDIR
from agent.permissions import SENSITIVE
from agent.tools import register

IGNORED = {".git", ".venv", "__pycache__", "node_modules"}
MAX_ENTRIES = 200


def _resolve(path: str) -> Path:
    """Turn a user path into a real path that must stay inside WORKDIR."""
    root = Path(WORKDIR).resolve()
    target = (root / path).resolve()
    if target != root and root not in target.parents:
        raise ValueError("path is outside the working directory")
    if SENSITIVE.search(str(target.relative_to(root))):
        raise ValueError("access to this file is not allowed")
    return target


class ReadArgs(BaseModel):
    path: str = Field(description="File path, relative to the working directory")


class WriteArgs(BaseModel):
    path: str = Field(description="File path, relative to the working directory")
    content: str = Field(description="The full text to write into the file")


class ListArgs(BaseModel):
    path: str = Field(default=".", description="Directory path, relative to the working directory")


@register("read_file", "Read a text file from the working directory", ReadArgs)
def read_file(args: ReadArgs) -> str:
    target = _resolve(args.path)
    if not target.is_file():
        return f"Error: '{args.path}' is not a file or does not exist."
    with open(target, "rb") as f:
        data = f.read(MAX_OUTPUT_CHARS + 1)
    if b"\0" in data:
        return "Error: this looks like a binary file."
    text = data[:MAX_OUTPUT_CHARS].decode("utf-8", errors="replace")
    if len(data) > MAX_OUTPUT_CHARS:
        text += "\n...[file truncated]..."
    return text


@register("write_file", "Create or overwrite a text file in the working directory", WriteArgs)
def write_file(args: WriteArgs) -> str:
    target = _resolve(args.path)
    if target.is_dir():
        return f"Error: '{args.path}' is a directory."
    action = "overwrite" if target.exists() else "create"
    allowed, message = confirm(f"the agent wants to {action} '{args.path}' ({len(args.content)} characters)")
    if not allowed:
        return message
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(args.content, encoding="utf-8")
    return f"OK: wrote {len(args.content)} characters to '{args.path}'."


@register("list_dir", "List the files and folders in a directory", ListArgs)
def list_dir(args: ListArgs) -> str:
    target = _resolve(args.path)
    if not target.is_dir():
        return f"Error: '{args.path}' is not a directory or does not exist."
    entries = sorted(
        (p for p in target.iterdir() if p.name not in IGNORED),
        key=lambda p: (not p.is_dir(), p.name.lower()),
    )
    lines = [p.name + ("/" if p.is_dir() else "") for p in entries[:MAX_ENTRIES]]
    if len(entries) > MAX_ENTRIES:
        lines.append(f"...[{len(entries) - MAX_ENTRIES} more entries]")
    return "\n".join(lines) or "(empty directory)"
