"""Tests for agent/git_tools.py on a temporary git repo (never your real project).
confirm is faked; _resolve is replaced by a simple resolver (file_tools has its own tests).
Every repo test runs twice: git on the host (sandbox off) and git inside real bwrap."""
import functools
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agent import approval, git_tools, sandbox, shell, tools


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


def hook(path, marker):
    """Write an executable shell script that creates `marker` when it runs."""
    path.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    path.chmod(0o755)


@functools.cache
def bwrap_works():
    if shutil.which("bwrap") is None:
        return False
    probe = subprocess.run(
        ["bwrap", "--unshare-all", "--ro-bind", "/usr", "/usr", "--symlink", "usr/lib", "/lib",
         "--symlink", "usr/lib64", "/lib64", "--", "/usr/bin/true"],
        capture_output=True,
    )
    return probe.returncode == 0


# ---------- fixtures ----------

@pytest.fixture(params=["host", "bwrap"])
def repo(request, monkeypatch, tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    if request.param == "bwrap" and not bwrap_works():
        pytest.skip("bwrap cannot run here")
    env = {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CEILING_DIRECTORIES": str(tmp_path),
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    root = tmp_path / "repo"
    root.mkdir()
    g(root, "init", "-q")
    g(root, "symbolic-ref", "HEAD", "refs/heads/main")
    # identity in the repo config: the sandbox clears the environment
    g(root, "config", "user.name", "Test")
    g(root, "config", "user.email", "test@example.com")
    (root / "a.txt").write_text("one\n")
    (root / "b.txt").write_text("bee\n")
    g(root, "add", "a.txt", "b.txt")
    g(root, "commit", "-q", "-m", "initial")

    monkeypatch.setattr(git_tools, "WORKDIR", str(root))
    monkeypatch.setattr(git_tools, "GIT_REPO_AT_LAUNCH", True)
    monkeypatch.setattr(git_tools, "_resolve", lambda p: root / p)
    monkeypatch.setattr(sandbox, "SANDBOX", request.param == "bwrap")
    monkeypatch.setattr(sandbox, "SANDBOX_NET", False)
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


@pytest.fixture
def fake_repo(monkeypatch, tmp_path):
    """An empty .git folder present at launch, sandbox off: for tests that fake subprocess.run."""
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(git_tools, "WORKDIR", str(tmp_path))
    monkeypatch.setattr(git_tools, "GIT_REPO_AT_LAUNCH", True)
    monkeypatch.setattr(sandbox, "SANDBOX", False)
    return tmp_path


def test_git_call_arguments(monkeypatch, fake_repo):
    tmp_path = fake_repo
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"], captured["kw"] = cmd, kw
        return SimpleNamespace(returncode=0, stdout="o", stderr="e")

    monkeypatch.setattr(git_tools.subprocess, "run", fake_run)
    assert git_tools._git("status") == (0, "oe")
    assert captured["cmd"] == [
        "git", "--no-pager",
        "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
        "status",
    ]
    kw = captured["kw"]
    assert kw["cwd"] == str(tmp_path)
    assert kw["stdin"] == subprocess.DEVNULL
    assert kw["timeout"] == git_tools.GIT_TIMEOUT
    env = kw["env"]
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_DIR"] == str(tmp_path / ".git")
    assert env["GIT_WORK_TREE"] == str(tmp_path)
    assert env["GIT_CEILING_DIRECTORIES"] == str(tmp_path)
    assert "shell" not in kw  # no shell: arguments are never interpreted


def test_git_not_installed(monkeypatch, fake_repo):
    def boom(*a, **kw):
        raise FileNotFoundError()

    monkeypatch.setattr(git_tools.subprocess, "run", boom)
    assert git_tools._git("status") == (1, "git is not installed.")


def test_git_missing_bwrap_is_reported(monkeypatch, fake_repo):
    monkeypatch.setattr(sandbox, "SANDBOX", True)
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)
    code, output = git_tools._git("status")
    assert code == 1
    assert "bubblewrap (bwrap) is not installed" in output


def test_git_timeout(monkeypatch, fake_repo):
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
    assert result.startswith("Error: git tools are off")


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


# ---------- S1 / S6 regressions: git never runs repo-controlled code on the host ----------

def test_repo_planted_by_a_sandboxed_command_never_runs_on_host(monkeypatch, tmp_path):
    """S1 PoC: no repo at launch; a terminal command creates .git with core.fsmonitor."""
    if shutil.which("git") is None or not bwrap_works():
        pytest.skip("needs git and a working bwrap")
    proj = tmp_path / "proj"
    proj.mkdir()
    marker = tmp_path / "PWNED"  # outside the workdir: only the host can write it
    for mod in (sandbox, shell, git_tools):
        monkeypatch.setattr(mod, "WORKDIR", str(proj))
    monkeypatch.setattr(sandbox, "SANDBOX", True)
    monkeypatch.setattr(sandbox, "SANDBOX_NET", False)
    monkeypatch.setattr(git_tools, "GIT_REPO_AT_LAUNCH", False)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))

    planted = shell.run_command(
        "git init -q . && printf '#!/bin/sh\\ntouch %s\\n' > .git/x && chmod +x .git/x "
        "&& git config core.fsmonitor \"$PWD/.git/x\"" % marker
    )
    assert planted.startswith("exit code: 0"), planted

    status = git_tools.git_status(git_tools.StatusArgs())
    diff = git_tools.git_diff(git_tools.DiffArgs())
    assert not marker.exists()
    assert "git tools are off" in status
    assert "git tools are off" in diff


@pytest.mark.parametrize(
    "at_launch, now",
    [
        (False, "none"),      # no repo at start-up
        (False, "dir"),       # .git planted after start-up
        (True, "none"),       # .git removed since start-up
        (True, "gitfile"),    # replaced by a gitfile
        (True, "symlink"),    # replaced by a symlink
    ],
)
def test_git_tools_refuse_without_a_real_repo(monkeypatch, tmp_path, approve, at_launch, now):
    proj = tmp_path / "proj"
    proj.mkdir()
    if now == "dir":
        (proj / ".git").mkdir()
    elif now == "gitfile":
        (proj / ".git").write_text("gitdir: /elsewhere\n")
    elif now == "symlink":
        (tmp_path / "other").mkdir()
        (proj / ".git").symlink_to(tmp_path / "other", target_is_directory=True)
    monkeypatch.setattr(git_tools, "WORKDIR", str(proj))
    monkeypatch.setattr(git_tools, "GIT_REPO_AT_LAUNCH", at_launch)
    monkeypatch.setattr(git_tools, "_resolve", lambda p: proj / p)
    calls = []
    monkeypatch.setattr(git_tools.subprocess, "run", lambda *a, **kw: calls.append(a))

    for result in (
        git_tools.git_status(git_tools.StatusArgs()),
        git_tools.git_diff(git_tools.DiffArgs()),
        git_tools.git_commit(git_tools.CommitArgs(message="m", files=["a.txt"])),
    ):
        assert result.startswith("Error:")
        assert "git tools are off" in result
    assert calls == []  # git never started
    assert approve.asked == []  # nothing to approve


def test_fsmonitor_in_repo_config_never_runs(repo, approve, tmp_path):
    marker = tmp_path / "FSMONITOR_RAN"
    hook(repo / ".git" / "fsmon", marker)
    g(repo, "config", "core.fsmonitor", str(repo / ".git" / "fsmon"))
    (repo / "a.txt").write_text("changed\n")

    git_tools.git_status(git_tools.StatusArgs())
    git_tools.git_diff(git_tools.DiffArgs())
    git_tools.git_commit(git_tools.CommitArgs(message="c", files=["a.txt"]))
    assert not marker.exists()


def test_commit_never_runs_repo_hooks(repo, approve):
    """S6: pre-commit / commit-msg / post-commit from .git/hooks are ignored."""
    for name in ("pre-commit", "commit-msg", "post-commit"):
        hook(repo / ".git" / "hooks" / name, repo / f"{name}.ran")
    (repo / "a.txt").write_text("changed\n")

    result = git_tools.git_commit(git_tools.CommitArgs(message="c", files=["a.txt"]))
    assert not result.startswith("Error"), result
    assert g(repo, "log", "-1", "--format=%s") == "c"
    assert not list(repo.glob("*.ran"))


def test_hooks_path_in_repo_config_is_overridden(repo, approve):
    hooks = repo / "myhooks"
    hooks.mkdir()
    hook(hooks / "pre-commit", repo / "hookspath.ran")
    g(repo, "config", "core.hooksPath", str(hooks))
    (repo / "a.txt").write_text("changed\n")

    git_tools.git_commit(git_tools.CommitArgs(message="c", files=["a.txt"]))
    assert not (repo / "hookspath.ran").exists()


def test_status_and_diff_cannot_write_git_dir_in_sandbox(repo, monkeypatch):
    """Read-only tools mount .git read-only inside bwrap."""
    if not sandbox.SANDBOX:
        pytest.skip("bwrap variant only")
    code, output = git_tools._git("config", "core.evil", "x")
    assert code != 0
    assert "evil" not in (repo / ".git" / "config").read_text()


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
