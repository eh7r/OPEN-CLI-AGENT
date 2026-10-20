"""Tests for agent/git_tools.py on a temporary git repo (never your real project).
confirm is faked; _resolve is replaced by a simple resolver (file_tools has its own tests)."""
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agent import approval, git_tools, shell, tools


# ---------- helpers ----------

def g(repo, *args):
    """Run git directly in the test repo (setup and checks)."""
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


class Approver:
    """Replaces git_tools.confirm: records what was asked, answers with self.answer."""

    def __init__(self):
        self.asked = []
        self.answer = (True, "")

    def __call__(self, description):
        self.asked.append(description)
        return self.answer


DECLINED = "Error: the user declined this action. It was NOT performed."


# ---------- fixtures ----------

@pytest.fixture
def repo(monkeypatch, tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    env = {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CEILING_DIRECTORIES": str(tmp_path),
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    root = tmp_path / "repo"
    root.mkdir()
    g(root, "init", "-q")
    g(root, "symbolic-ref", "HEAD", "refs/heads/main")
    (root / "a.txt").write_text("one\n")
    (root / "b.txt").write_text("bee\n")
    g(root, "add", "a.txt", "b.txt")
    g(root, "commit", "-q", "-m", "initial")

    monkeypatch.setattr(git_tools, "WORKDIR", str(root))
    monkeypatch.setattr(git_tools, "_resolve", lambda p: root / p)
    return root


@pytest.fixture
def approve(monkeypatch):
    approver = Approver()
    monkeypatch.setattr(git_tools, "confirm", approver)
    return approver


# ---------- _git ----------

def test_git_returns_code_and_output(repo):
    assert git_tools._git("rev-parse", "--is-inside-work-tree") == (0, "true")


def test_git_error_has_nonzero_code(repo):
    code, output = git_tools._git("not-a-command")
    assert code != 0
    assert "not-a-command" in output


def test_git_call_arguments(monkeypatch):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"], captured["kw"] = cmd, kw
        return SimpleNamespace(returncode=0, stdout="o", stderr="e")

    monkeypatch.setattr(git_tools.subprocess, "run", fake_run)
    assert git_tools._git("status") == (0, "oe")
    assert captured["cmd"] == ["git", "--no-pager", "status"]
    kw = captured["kw"]
    assert kw["cwd"] == git_tools.WORKDIR
    assert kw["stdin"] == subprocess.DEVNULL
    assert kw["timeout"] == git_tools.GIT_TIMEOUT
    assert kw["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert "shell" not in kw  # no shell: arguments are never interpreted


def test_git_not_installed(monkeypatch):
    def boom(*a, **kw):
        raise FileNotFoundError()

    monkeypatch.setattr(git_tools.subprocess, "run", boom)
    assert git_tools._git("status") == (1, "git is not installed.")


def test_git_timeout(monkeypatch):
    def boom(*a, **kw):
        raise subprocess.TimeoutExpired("git", 30)

    monkeypatch.setattr(git_tools.subprocess, "run", boom)
    assert git_tools._git("status") == (1, f"git timed out after {git_tools.GIT_TIMEOUT}s.")


# ---------- _format ----------

def test_format_success():
    assert git_tools._format(0, "some output") == "some output"


def test_format_empty_output():
    assert git_tools._format(0, "") == "(no output)"


def test_format_error():
    assert git_tools._format(2, "bad thing") == "Error (git exit 2): bad thing"


# ---------- git_status ----------

def test_status_clean(repo):
    assert git_tools.git_status(git_tools.StatusArgs()) == "## main"


def test_status_modified_and_untracked(repo):
    (repo / "a.txt").write_text("changed\n")
    (repo / "new.txt").write_text("x\n")
    lines = git_tools.git_status(git_tools.StatusArgs()).splitlines()
    assert lines[0] == "## main"
    assert " M a.txt" in lines
    assert "?? new.txt" in lines


def test_status_outside_repo(monkeypatch, tmp_path, repo):
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.setattr(git_tools, "WORKDIR", str(plain))
    result = git_tools.git_status(git_tools.StatusArgs())
    assert result.startswith("Error (git exit 128)")


# ---------- git_diff ----------

def test_diff_defaults():
    args = git_tools.DiffArgs()
    assert args.staged is False
    assert args.path == ""


def test_diff_no_changes(repo):
    assert git_tools.git_diff(git_tools.DiffArgs()) == "(no output)"


def test_diff_unstaged(repo):
    (repo / "a.txt").write_text("two\n")
    result = git_tools.git_diff(git_tools.DiffArgs())
    assert "-one" in result and "+two" in result


def test_diff_staged_flag(repo):
    (repo / "a.txt").write_text("two\n")
    g(repo, "add", "a.txt")
    assert git_tools.git_diff(git_tools.DiffArgs()) == "(no output)"
    assert "+two" in git_tools.git_diff(git_tools.DiffArgs(staged=True))


def test_diff_path_filter(repo):
    (repo / "a.txt").write_text("two\n")
    (repo / "b.txt").write_text("three\n")
    result = git_tools.git_diff(git_tools.DiffArgs(path="a.txt"))
    assert "a.txt" in result
    assert "b.txt" not in result


def test_diff_is_truncated(monkeypatch, repo):
    monkeypatch.setattr(shell, "MAX_OUTPUT_CHARS", 200)
    (repo / "a.txt").write_text("\n".join(f"line {i}" for i in range(500)) + "\n")
    assert "characters truncated" in git_tools.git_diff(git_tools.DiffArgs())


# ---------- git_commit ----------

def test_commit_success(repo, approve):
    (repo / "a.txt").write_text("two\n")
    result = git_tools.git_commit(git_tools.CommitArgs(message="update a", files=["a.txt"]))
    assert "[main" in result and "update a" in result
    assert g(repo, "log", "-1", "--format=%s") == "update a"
    assert g(repo, "status", "--short") == ""


def test_commit_asks_with_clear_description(repo, approve):
    (repo / "a.txt").write_text("two\n")
    (repo / "b.txt").write_text("three\n")
    git_tools.git_commit(git_tools.CommitArgs(message="both", files=["a.txt", "b.txt"]))
    assert approve.asked == ["the agent wants to commit 2 file(s): a.txt, b.txt with message: both"]


def test_commit_declined_does_nothing(repo, approve):
    approve.answer = (False, DECLINED)
    (repo / "a.txt").write_text("two\n")
    result = git_tools.git_commit(git_tools.CommitArgs(message="nope", files=["a.txt"]))
    assert result == DECLINED
    assert g(repo, "rev-list", "--count", "HEAD") == "1"
    assert g(repo, "status", "--short") == "M a.txt"


def test_commit_without_terminal_is_refused(monkeypatch, repo):
    monkeypatch.setattr(git_tools, "confirm", approval.confirm)  # the real one
    (repo / "a.txt").write_text("two\n")
    result = git_tools.git_commit(git_tools.CommitArgs(message="x", files=["a.txt"]))
    assert result.startswith("Error: approval is needed")
    assert g(repo, "rev-list", "--count", "HEAD") == "1"


def test_commit_needs_at_least_one_file():
    with pytest.raises(ValidationError):
        git_tools.CommitArgs(message="x", files=[])


@pytest.mark.parametrize("message", ["", "   ", "m" * 201])
def test_commit_bad_message_never_asks(repo, approve, message):
    result = git_tools.git_commit(git_tools.CommitArgs(message=message, files=["a.txt"]))
    assert result == "Error: the commit message must be 1 to 200 characters."
    assert approve.asked == []


def test_commit_message_200_chars_ok(repo, approve):
    (repo / "a.txt").write_text("two\n")
    git_tools.git_commit(git_tools.CommitArgs(message="m" * 200, files=["a.txt"]))
    assert g(repo, "log", "-1", "--format=%s") == "m" * 200


def test_commit_message_is_stripped(repo, approve):
    (repo / "a.txt").write_text("two\n")
    git_tools.git_commit(git_tools.CommitArgs(message="  hello  ", files=["a.txt"]))
    assert g(repo, "log", "-1", "--format=%s") == "hello"
    assert approve.asked[0].endswith("with message: hello")


def test_commit_only_the_listed_files(repo, approve):
    (repo / "a.txt").write_text("two\n")
    (repo / "b.txt").write_text("three\n")
    git_tools.git_commit(git_tools.CommitArgs(message="only a", files=["a.txt"]))
    assert g(repo, "show", "--name-only", "--format=", "HEAD") == "a.txt"
    assert g(repo, "status", "--short") == "M b.txt"


def test_commit_new_untracked_file(repo, approve):
    (repo / "c.txt").write_text("new\n")
    git_tools.git_commit(git_tools.CommitArgs(message="add c", files=["c.txt"]))
    assert g(repo, "show", "--name-only", "--format=", "HEAD") == "c.txt"


def test_commit_with_nothing_to_commit_fails_clearly(repo, approve):
    result = git_tools.git_commit(git_tools.CommitArgs(message="empty", files=["a.txt"]))
    assert result.startswith("Error: the commit failed:")
    assert "Do not repeat this commit" in result
    assert g(repo, "rev-list", "--count", "HEAD") == "1"


def test_commit_add_failure_is_reported(repo, approve):
    result = git_tools.git_commit(git_tools.CommitArgs(message="x", files=["missing.txt"]))
    assert result.startswith("Error (git exit 128)")
    assert g(repo, "rev-list", "--count", "HEAD") == "1"


# ---------- registry ----------

def test_tools_are_registered():
    for name in ("git_status", "git_diff", "git_commit"):
        assert name in tools._REGISTRY


def test_execute_git_status_through_registry(repo):
    assert tools.execute("git_status", {}) == "## main"


def test_execute_git_commit_invalid_arguments(repo, approve):
    result = tools.execute("git_commit", {"message": "x", "files": []})
    assert result.startswith("Error: invalid arguments for 'git_commit'")
    assert approve.asked == []
