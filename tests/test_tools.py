import io
import sys

import pytest
from pydantic import BaseModel

from agent import file_tools, git_tools, memory, tools  # noqa: F401


def run(name, **args):
    return tools.execute(name, args)


@pytest.fixture
def workdir(tmp_path_factory, monkeypatch):
    work = tmp_path_factory.mktemp("work")
    monkeypatch.setattr(file_tools, "WORKDIR", str(work))
    monkeypatch.setattr(file_tools, "confirm", lambda description: (True, ""))
    return work


# ---------- registry ----------

def test_unknown_tool_is_reported():
    assert tools.execute("nope", {}).startswith("Error: unknown tool 'nope'")


def test_missing_arguments_are_reported_not_raised():
    result = tools.execute("read_file", {})
    assert result.startswith("Error: invalid arguments for 'read_file'")
    assert "path" in result


def test_wrong_argument_type_is_reported():
    assert tools.execute("list_dir", {"path": 123}).startswith("Error: invalid arguments")


def test_a_crashing_tool_returns_an_error_text():
    class Empty(BaseModel):
        pass

    @tools.register("boom_test", "always fails", Empty)
    def boom(args):
        raise RuntimeError("kaboom")

    try:
        assert tools.execute("boom_test", {}) == "Error: tool 'boom_test' failed: kaboom"
    finally:
        tools._REGISTRY.pop("boom_test")


def test_schemas_describe_every_tool():
    schemas = tools.schemas()
    names = {s["function"]["name"] for s in schemas}
    assert names >= {
        "terminal", "read_file", "write_file", "list_dir",
        "git_status", "git_diff", "git_commit", "remember", "forget",
    }
    for schema in schemas:
        assert schema["type"] == "function"
        params = schema["function"]["parameters"]
        assert params["type"] == "object"
        assert "title" not in params
        assert schema["function"]["description"]


# ---------- terminal: the guard sits in front of the shell ----------

def test_terminal_blocked_command_never_reaches_the_shell(monkeypatch):
    calls = []
    monkeypatch.setattr(tools.shell, "run_command", lambda command: calls.append(command) or "ran")
    assert run("terminal", command="rm -rf /").startswith("Error: blocked by policy")
    assert calls == []


def test_terminal_safe_command_reaches_the_shell(monkeypatch):
    monkeypatch.setattr(tools.shell, "run_command", lambda command: f"ran: {command}")
    assert run("terminal", command="ls") == "ran: ls"


def test_terminal_unapproved_command_does_not_run(monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(tools.shell, "run_command", lambda command: calls.append(command) or "ran")
    assert run("terminal", command="touch x").startswith("Error: approval is needed")
    assert calls == []


# ---------- file tools ----------

def test_write_and_read_roundtrip(workdir):
    assert run("write_file", path="notes/a.txt", content="hello\n").startswith("OK")
    assert (workdir / "notes" / "a.txt").read_text() == "hello\n"
    assert run("read_file", path="notes/a.txt") == "hello\n"


def test_write_asks_first_and_says_create_or_overwrite(workdir, monkeypatch):
    seen = []
    monkeypatch.setattr(file_tools, "confirm", lambda description: seen.append(description) or (True, ""))
    run("write_file", path="a.txt", content="1")
    run("write_file", path="a.txt", content="2")
    assert "create" in seen[0]
    assert "overwrite" in seen[1]


def test_declined_write_changes_nothing(workdir, monkeypatch):
    monkeypatch.setattr(file_tools, "confirm", lambda description: (False, "Error: the user declined this action."))
    assert run("write_file", path="a.txt", content="x").startswith("Error: the user declined")
    assert not (workdir / "a.txt").exists()


@pytest.mark.parametrize("path", ["../evil.txt", "/etc/passwd", "a/../../evil.txt"])
def test_paths_outside_the_workdir_are_refused(workdir, path):
    assert "outside the working directory" in run("read_file", path=path)
    assert "outside the working directory" in run("write_file", path=path, content="x")
    assert not (workdir.parent / "evil.txt").exists()


def test_symlink_cannot_escape_the_workdir(workdir, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "secret.txt").write_text("top secret")
    (workdir / "link").symlink_to(outside, target_is_directory=True)

    result = run("read_file", path="link/secret.txt")
    assert "top secret" not in result
    assert "outside the working directory" in result

    run("write_file", path="link/new.txt", content="x")
    assert not (outside / "new.txt").exists()


@pytest.mark.parametrize("path", [".env", ".ssh/config", "keys/id_rsa", ".env.local", "deploy/id_ed25519"])
def test_sensitive_paths_are_refused(workdir, path):
    assert "not allowed" in run("read_file", path=path)
    assert "not allowed" in run("write_file", path=path, content="x")
    assert not (workdir / path).exists()


def test_long_files_are_truncated(workdir):
    (workdir / "big.txt").write_text("a" * 10000)
    result = run("read_file", path="big.txt")
    assert "[file truncated]" in result
    assert len(result) < 4100


def test_binary_files_are_refused(workdir):
    (workdir / "bin.dat").write_bytes(b"ab\x00cd")
    assert "binary file" in run("read_file", path="bin.dat")


def test_missing_files_and_directories_are_reported(workdir):
    (workdir / "d").mkdir()
    assert "does not exist" in run("read_file", path="nope.txt")
    assert "is not a file" in run("read_file", path="d")
    assert "is a directory" in run("write_file", path="d", content="x")


def test_list_dir_hides_noise_and_sorts(workdir):
    for folder in ("src", ".git", ".venv", "__pycache__", "node_modules"):
        (workdir / folder).mkdir()
    for name in ("b.txt", "A.txt"):
        (workdir / name).write_text("x")
    assert run("list_dir").splitlines() == ["src/", "A.txt", "b.txt"]


def test_list_dir_reports_empty_and_long_directories(workdir):
    (workdir / "empty").mkdir()
    assert run("list_dir", path="empty") == "(empty directory)"

    (workdir / "many").mkdir()
    for i in range(205):
        (workdir / "many" / f"f{i:03}.txt").write_text("x")
    lines = run("list_dir", path="many").splitlines()
    assert len(lines) == 201
    assert lines[-1] == "...[5 more entries]"
