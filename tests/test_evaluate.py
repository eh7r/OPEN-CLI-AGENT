import pytest

from agent import evaluate as ev


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Error: the user declined this action. It was NOT performed.", ev.DECLINED),
        ("Error: the user declined to run this command. It was NOT performed.", ev.DECLINED),
        ("Error: blocked by policy (fork bomb). Do not retry this command.", ev.BLOCKED),
        ("Error: the command timed out after 30s and was killed.", ev.TIMEOUT),
        ("Error (git exit 1): git timed out after 30s.", ev.TIMEOUT),
        ("Error: unknown tool 'foo'. Available: terminal", ev.FAILED),
        ("Error: invalid arguments for 'terminal': command: Field required.", ev.FAILED),
        ("exit code: 1\nstderr:\nboom", ev.FAILED),
        ("exit code: 127", ev.FAILED),
        ("exit code: 0\nstdout:\nhi", ev.OK),
        ("OK: saved a project note.", ev.OK),
        ("hello world", ev.OK),
        ("", ev.OK),
    ],
)
def test_classify(text, expected):
    assert ev.classify(text) == expected


@pytest.mark.parametrize(
    "name, args, expected",
    [
        ("read_file", {"path": "a"}, False),
        ("list_dir", {}, False),
        ("git_status", {}, False),
        ("git_diff", {}, False),
        ("write_file", {"path": "a", "content": "b"}, True),
        ("git_commit", {"message": "m", "files": ["a"]}, True),
        ("remember", {"text": "x"}, True),
        ("terminal", {"command": "ls"}, False),
        ("terminal", {"command": "touch x"}, True),
        ("terminal", {"command": "rm -rf x"}, True),
    ],
)
def test_is_mutating(name, args, expected):
    assert ev.is_mutating(name, args) is expected


def test_same_call_runs_at_most_twice():
    t = ev.Tracker()
    args = {"path": "a.txt"}
    for _ in range(2):
        assert t.check("read_file", args) is None
        t.record("read_file", args, "content")
    assert "already ran 2 times" in t.check("read_file", args)
    assert t.check("read_file", {"path": "b.txt"}) is None


def test_argument_order_does_not_matter():
    t = ev.Tracker()
    t.record("x", {"a": 1, "b": 2}, "ok")
    t.record("x", {"b": 2, "a": 1}, "ok")
    assert t.check("x", {"a": 1, "b": 2}) is not None


def test_failed_mutating_call_is_never_repeated():
    t = ev.Tracker()
    args = {"command": "touch x"}
    _, status = t.record("terminal", args, "exit code: 1\nstderr:\nnope")
    assert status == ev.FAILED
    assert "must not be repeated" in t.check("terminal", args)


def test_failed_read_only_call_may_be_retried():
    t = ev.Tracker()
    args = {"path": "a"}
    t.record("read_file", args, "Error: tool 'read_file' failed: nope")
    assert t.check("read_file", args) is None


def test_successful_mutating_call_is_not_locked():
    t = ev.Tracker()
    args = {"path": "a", "content": "b"}
    t.record("write_file", args, "OK: wrote 1 characters to 'a'.")
    assert t.check("write_file", args) is None


def test_timeout_on_mutating_command_warns_and_locks():
    t = ev.Tracker()
    args = {"command": "touch x"}
    text, status = t.record("terminal", args, "Error: the command timed out after 30s and was killed.")
    assert status == ev.TIMEOUT
    assert "WARNING" in text and "Do NOT repeat" in text
    assert "must not be repeated" in t.check("terminal", args)


def test_timeout_on_read_only_command_does_not_warn():
    t = ev.Tracker()
    args = {"command": "ls"}
    text, status = t.record("terminal", args, "Error: the command timed out after 30s and was killed.")
    assert status == ev.TIMEOUT
    assert "WARNING" not in text
    assert t.check("terminal", args) is None


def test_decline_sets_flag_and_locks_the_call():
    t = ev.Tracker()
    args = {"path": "a", "content": "b"}
    assert not t.declined
    _, status = t.record("write_file", args, "Error: the user declined this action. It was NOT performed.")
    assert status == ev.DECLINED
    assert t.declined
    assert "must not be repeated" in t.check("write_file", args)


def test_blocked_call_is_locked_but_is_not_a_decline():
    t = ev.Tracker()
    args = {"command": "rm -rf /"}
    t.record("terminal", args, "Error: blocked by policy (x). Do not retry this command.")
    assert not t.declined
    assert "must not be repeated" in t.check("terminal", args)
