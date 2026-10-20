"""Tests for agent/shell.py: output, exit codes, timeout, truncation, errors.
bwrap is replaced by plain /bin/sh; sandbox.py has its own tests."""
import os
import shlex
import time

import pytest

from agent import shell
from agent.sandbox import SandboxUnavailable


@pytest.fixture(autouse=True)
def plain_shell(monkeypatch, tmp_path):
    monkeypatch.setattr(shell, "build_argv", lambda c: ["/bin/sh", "-c", c])
    monkeypatch.setattr(shell, "WORKDIR", str(tmp_path))


def alive(pid: int) -> bool:
    """True if the process exists and is not a zombie (Linux)."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            stat = f.read()
    except OSError:
        return False
    return stat.rsplit(")", 1)[1].split()[0] != "Z"


# ---------- _truncate ----------

def test_truncate_short_unchanged(monkeypatch):
    monkeypatch.setattr(shell, "MAX_OUTPUT_CHARS", 100)
    assert shell._truncate("a" * 100) == "a" * 100
    assert shell._truncate("") == ""


def test_truncate_long_keeps_start_and_end(monkeypatch):
    monkeypatch.setattr(shell, "MAX_OUTPUT_CHARS", 100)
    text = "A" * 60 + "Z" * 60  # 120 chars, 20 over the limit
    assert shell._truncate(text) == "A" * 50 + "\n...[20 characters truncated]...\n" + "Z" * 50


# ---------- run_command: output ----------

def test_stdout_and_exit_code():
    assert shell.run_command("echo hello") == "exit code: 0\nstdout:\nhello"


def test_stderr_only():
    assert shell.run_command("echo oops >&2") == "exit code: 0\nstderr:\noops"


def test_stdout_and_stderr():
    result = shell.run_command("echo out; echo err >&2")
    assert result == "exit code: 0\nstdout:\nout\nstderr:\nerr"


def test_nonzero_exit_code():
    assert shell.run_command("exit 3") == "exit code: 3"


def test_failing_command_reports_stderr():
    result = shell.run_command("ls /definitely/not/here")
    assert result.startswith("exit code: ")
    assert not result.startswith("exit code: 0")
    assert "stderr:" in result


def test_no_output_gives_only_exit_code():
    assert shell.run_command("true") == "exit code: 0"


def test_whitespace_only_output_is_omitted():
    assert shell.run_command("printf '  \\n'") == "exit code: 0"


def test_trailing_newlines_stripped():
    assert shell.run_command("printf 'hi\\n\\n\\n'") == "exit code: 0\nstdout:\nhi"


def test_invalid_utf8_is_replaced_not_crashing():
    result = shell.run_command("printf '\\377'")
    assert result.startswith("exit code: 0")
    assert "\ufffd" in result


# ---------- run_command: environment ----------

def test_runs_in_workdir(tmp_path):
    result = shell.run_command("pwd -P")
    assert os.path.realpath(tmp_path) in result


def test_command_can_create_files_in_workdir(tmp_path):
    shell.run_command("echo data > made.txt")
    assert (tmp_path / "made.txt").read_text().strip() == "data"


def test_stdin_is_closed():
    # cat would hang forever if stdin were inherited; with DEVNULL it ends at once
    start = time.monotonic()
    result = shell.run_command("cat")
    assert result == "exit code: 0"
    assert time.monotonic() - start < 5


def test_build_argv_receives_the_command(monkeypatch):
    seen = []

    def spy(command):
        seen.append(command)
        return ["/bin/sh", "-c", "true"]

    monkeypatch.setattr(shell, "build_argv", spy)
    shell.run_command("some command here")
    assert seen == ["some command here"]


# ---------- run_command: output limit ----------

def test_long_output_is_truncated(monkeypatch):
    monkeypatch.setattr(shell, "MAX_OUTPUT_CHARS", 100)
    result = shell.run_command("seq 1 500")
    assert "characters truncated" in result
    assert result.startswith("exit code: 0\nstdout:\n1\n")
    assert result.rstrip().endswith("500")


# ---------- run_command: timeout ----------

def test_timeout_kills_and_reports(monkeypatch):
    monkeypatch.setattr(shell, "COMMAND_TIMEOUT", 1)
    start = time.monotonic()
    result = shell.run_command("sleep 10")
    assert result == "Error: the command timed out after 1s and was killed."
    assert time.monotonic() - start < 5


def test_timeout_kills_child_processes_too(monkeypatch, tmp_path):
    monkeypatch.setattr(shell, "COMMAND_TIMEOUT", 1)
    pidfile = tmp_path / "child.pid"
    shell.run_command(f"sleep 30 & echo $! > {shlex.quote(str(pidfile))}; wait")
    pid = int(pidfile.read_text().strip())
    for _ in range(30):
        if not alive(pid):
            break
        time.sleep(0.1)
    assert not alive(pid)


# ---------- run_command: errors ----------

def test_sandbox_unavailable_becomes_error_text(monkeypatch):
    def boom(command):
        raise SandboxUnavailable("bubblewrap (bwrap) is not installed")

    monkeypatch.setattr(shell, "build_argv", boom)
    assert shell.run_command("ls") == "Error: bubblewrap (bwrap) is not installed"


def test_cannot_start_process(monkeypatch):
    monkeypatch.setattr(shell, "build_argv", lambda c: ["/nonexistent/binary"])
    result = shell.run_command("ls")
    assert result.startswith("Error: could not start the command:")
