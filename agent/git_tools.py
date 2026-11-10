import os
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field

from agent.approval import confirm
from agent.config import GIT_REPO_AT_LAUNCH, WORKDIR
from agent.file_tools import _resolve
from agent.sandbox import SandboxUnavailable, build_git_argv, git_env
from agent.shell import _truncate
from agent.tools import register

GIT_TIMEOUT = 30

NO_REPO = (
    "Error: git tools are off: the working directory had no real .git folder when the agent "
    "started (missing, a symlink, a gitfile, or removed since). Start the agent from the repository root."
)


def _no_repo() -> str | None:
    """NO_REPO unless WORKDIR/.git was a real folder at launch and still is one now.
    A .git created later (e.g. by a sandboxed command) is never trusted."""
    git = os.path.join(WORKDIR, ".git")
    if GIT_REPO_AT_LAUNCH and os.path.isdir(git) and not os.path.islink(git):
        return None
    return NO_REPO


def _git(*args: str, write: bool = False) -> tuple[int, str]:
    """Run git without a shell, inside bwrap unless the sandbox is off.
    Only `write=True` (add/commit) can change .git. Returns (exit code, combined output)."""
    if refusal := _no_repo():
        return 1, refusal
    wd = str(Path(WORKDIR).resolve())
    try:
        argv = build_git_argv(wd, list(args), write=write)
    except SandboxUnavailable as e:
        return 1, str(e)
    try:
        proc = subprocess.run(
            argv,
            cwd=wd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=GIT_TIMEOUT,
            env={**os.environ, **git_env(wd)},
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
    if refusal := _no_repo():
        return refusal
    return _format(*_git("status", "--short", "--branch"))


@register("git_diff", "Show the changes in the git repository", DiffArgs)
def git_diff(args: DiffArgs) -> str:
    if refusal := _no_repo():
        return refusal
    cmd = ["diff"]
    if args.staged:
        cmd.append("--staged")
    if args.path:
        cmd += ["--", str(_resolve(args.path))]
    return _format(*_git(*cmd))


@register("git_commit", "Commit the given files with a message (asks the user first)", CommitArgs)
def git_commit(args: CommitArgs) -> str:
    if refusal := _no_repo():
        return refusal
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

    code, output = _git("add", "--", *paths, write=True)
    if code != 0:
        return _format(code, output)
    code, output = _git("commit", "-m", message, "--", *paths, write=True)
    if code != 0:
        return f"Error: the commit failed: {_truncate(output)} The files may be staged (check with git_status). Do not repeat this commit; tell the user."
    return _format(code, output)
