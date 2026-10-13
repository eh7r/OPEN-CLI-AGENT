import os
import subprocess

from pydantic import BaseModel, Field

from agent.approval import confirm
from agent.config import WORKDIR
from agent.file_tools import _resolve
from agent.shell import _truncate
from agent.tools import register

GIT_TIMEOUT = 30


def _git(*args: str) -> tuple[int, str]:
    """Run git without a shell. Returns (exit code, combined output)."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        proc = subprocess.run(
            ["git", "--no-pager", *args],
            cwd=WORKDIR,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=GIT_TIMEOUT,
            env=env,
        )
    except FileNotFoundError:
        return 1, "git is not installed."
    except subprocess.TimeoutExpired:
        return 1, f"git timed out after {GIT_TIMEOUT}s."
    output = (proc.stdout + proc.stderr).strip()
    return proc.returncode, output


def _format(code: int, output: str) -> str:
    if code != 0:
        return f"Error (git exit {code}): {_truncate(output)}"
    return _truncate(output) if output else "(no output)"


class DiffArgs(BaseModel):
    staged: bool = Field(default=False, description="Show staged changes instead of unstaged")
    path: str = Field(default="", description="Limit the diff to this path (optional)")


class CommitArgs(BaseModel):
    message: str = Field(description="The commit message (short, one line)")
    files: list[str] = Field(min_length=1, description="Files to include in the commit")


class StatusArgs(BaseModel):
    pass


@register("git_status", "Show changed files in the git repository", StatusArgs)
def git_status(args: StatusArgs) -> str:
    return _format(*_git("status", "--short", "--branch"))


@register("git_diff", "Show the changes in the git repository", DiffArgs)
def git_diff(args: DiffArgs) -> str:
    cmd = ["diff"]
    if args.staged:
        cmd.append("--staged")
    if args.path:
        cmd += ["--", str(_resolve(args.path))]
    return _format(*_git(*cmd))


@register("git_commit", "Commit the given files with a message (asks the user first)", CommitArgs)
def git_commit(args: CommitArgs) -> str:
    message = args.message.strip()
    if not message or len(message) > 200:
        return "Error: the commit message must be 1 to 200 characters."
    paths = [str(_resolve(f)) for f in args.files]

    allowed, reply = confirm(
        f"the agent wants to commit {len(paths)} file(s): {', '.join(args.files)} "
        f"with message: {message}"
    )
    if not allowed:
        return reply

    code, output = _git("add", "--", *paths)
    if code != 0:
        return _format(code, output)
    code, output = _git("commit", "-m", message, "--", *paths)
    if code != 0:
        return f"Error: the commit failed: {_truncate(output)} The files may be staged (check with git_status). Do not repeat this commit; tell the user."
    return _format(code, output)
