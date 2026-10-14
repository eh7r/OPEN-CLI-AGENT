import os
import signal
import subprocess

from agent.config import COMMAND_TIMEOUT, MAX_OUTPUT_CHARS, WORKDIR
from agent.sandbox import SandboxUnavailable, build_argv


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    half = MAX_OUTPUT_CHARS // 2
    cut = len(text) - MAX_OUTPUT_CHARS
    return f"{text[:half]}\n...[{cut} characters truncated]...\n{text[-half:]}"


def run_command(command: str) -> str:
    """Run a shell command in the sandbox with a timeout and an output limit."""
    try:
        argv = build_argv(command)
    except SandboxUnavailable as e:
        return f"Error: {e}"

    try:
        proc = subprocess.Popen(
            argv,
            cwd=WORKDIR,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            start_new_session=True,
        )
    except OSError as e:
        return f"Error: could not start the command: {e}"

    try:
        out, err = proc.communicate(timeout=COMMAND_TIMEOUT)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        return f"Error: the command timed out after {COMMAND_TIMEOUT}s and was killed."

    parts = [f"exit code: {proc.returncode}"]
    if out.strip():
        parts.append("stdout:\n" + _truncate(out.rstrip()))
    if err.strip():
        parts.append("stderr:\n" + _truncate(err.rstrip()))
    return "\n".join(parts)
