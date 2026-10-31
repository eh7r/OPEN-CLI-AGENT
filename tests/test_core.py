"""Tests for agent/core.py: run loop, MAX_STEPS, refusals, declined/SKIPPED, finish, TOO_BIG.
Everything is fake: no Ollama, no real tools."""
from types import SimpleNamespace

import ollama
import pytest

from agent import core, evaluate
from agent.model import ModelError

SCHEMAS = [{"type": "function", "function": {"name": "fake"}}]


# ---------- helpers ----------

def tc(name="terminal", **args):
    return ollama.Message.ToolCall(
        function=ollama.Message.ToolCall.Function(name=name, arguments=args)
    )


def reply(text="", *calls):
    return ollama.Message(role="assistant", content=text, tool_calls=list(calls) or None)


def role(m):
    return m["role"] if isinstance(m, dict) else m.role


class FakeModel:
    """Replaces core.ask. `replies`: list of replies/exceptions, or a callable n -> reply."""

    def __init__(self, replies):
        self.replies = replies
        self.calls = []

    def __call__(self, messages, tools=None, on_token=None, cancel=None):
        n = len(self.calls)
        self.calls.append({"messages": list(messages), "tools": tools})
        if callable(self.replies):
            item = self.replies(n)
        else:
            assert n < len(self.replies), "model was called more times than expected"
            item = self.replies[n]
        if isinstance(item, Exception):
            raise item
        if on_token and item.content:
            on_token(item.content)
        return item


class FakeExec:
    """Replaces tools.execute. `results`: list (last one repeats); default 'ok output'."""

    def __init__(self, results=None):
        self.results = results or ["ok output"]
        self.calls = []

    def __call__(self, name, args):
        i = min(len(self.calls), len(self.results) - 1)
        self.calls.append((name, dict(args)))
        return self.results[i]


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr(core.memory, "notes_block", lambda: "")
    monkeypatch.setattr(core, "SANDBOX", True)


@pytest.fixture
def setup(monkeypatch):
    def _setup(replies, results=None, max_steps=5, compact=None):
        fm = FakeModel(replies)
        ex = FakeExec(results)
        monkeypatch.setattr(core, "ask", fm)
        monkeypatch.setattr(core.tools, "execute", ex)
        monkeypatch.setattr(core.tools, "schemas", lambda: SCHEMAS)
        monkeypatch.setattr(core, "MAX_STEPS", max_steps)
        if compact:
            monkeypatch.setattr(core.context, "compact", compact)
        return fm, ex

    return _setup


def out(capsys):
    """Captured output with whitespace normalized (rich may wrap long lines)."""
    return " ".join(capsys.readouterr().out.split())


# ---------- basic flow ----------

def test_plain_answer_single_step(setup, capsys):
    fm, ex = setup([reply("Hello there")])
    core.run("hi")
    o = out(capsys)
    assert "Hello there" in o
    assert "step 1/5" in o
    assert "reached MAX_STEPS" not in o
    assert len(fm.calls) == 1
    assert ex.calls == []


def test_prints_model_name(setup, capsys):
    setup([reply("x")])
    core.run("hi")
    assert f"model: {core.MODEL}" in out(capsys)


def test_system_and_user_messages(setup, monkeypatch):
    monkeypatch.setattr(core.memory, "notes_block", lambda: "\nNOTES-HERE")
    fm, _ = setup([reply("x")])
    core.run("my task")
    msgs = fm.calls[0]["messages"]
    assert role(msgs[0]) == "system"
    assert msgs[0]["content"].startswith(core.SYSTEM_PROMPT)
    assert msgs[0]["content"].endswith("NOTES-HERE")
    assert msgs[1] == {"role": "user", "content": "my task"}


def test_tool_call_then_final_answer(setup, capsys):
    fm, ex = setup(
        [reply("", tc("terminal", command="ls")), reply("All done")],
        results=["file1 file2"],
    )
    core.run("list files")
    o = out(capsys)
    assert ex.calls == [("terminal", {"command": "ls"})]
    assert "step 1/5" in o and "step 2/5" in o
    assert "terminal: ok" in o
    assert "All done" in o
    second = fm.calls[1]["messages"]
    assert [role(m) for m in second] == ["system", "user", "assistant", "tool"]
    assert second[3] == {"role": "tool", "tool_name": "terminal", "content": "file1 file2"}


def test_schemas_passed_to_model(setup):
    fm, _ = setup([reply("x")])
    core.run("hi")
    assert fm.calls[0]["tools"] == SCHEMAS


def test_multiple_tool_calls_in_one_reply(setup):
    fm, ex = setup(
        [
            reply("", tc("read_file", path="a"), tc("list_dir", path=".")),
            reply("done"),
        ],
        results=["A-content", "listing"],
    )
    core.run("go")
    assert [c[0] for c in ex.calls] == ["read_file", "list_dir"]
    tool_msgs = [m for m in fm.calls[1]["messages"] if role(m) == "tool"]
    assert [m["content"] for m in tool_msgs] == ["A-content", "listing"]


def test_model_error_propagates(setup):
    setup([ModelError("Cannot reach Ollama. Is it running?")])
    with pytest.raises(ModelError):
        core.run("hi")


# ---------- MAX_STEPS ----------

def test_max_steps_reached(setup, capsys):
    fm, ex = setup(lambda n: reply("", tc("terminal", command=f"echo {n}")), max_steps=3)
    core.run("loop")
    o = out(capsys)
    assert "Stopped: reached MAX_STEPS." in o
    assert len(fm.calls) == 3
    assert len(ex.calls) == 3
    assert "step 3/3" in o


# ---------- refusals ----------

def test_max_refusals_constant():
    assert core.MAX_REFUSALS == 3


def test_repeated_call_refused_then_stopped(setup, capsys):
    same = lambda n: reply("", tc("terminal", command="echo same"))
    fm, ex = setup(same, max_steps=10)
    core.run("loop")
    o = out(capsys)
    assert len(ex.calls) == evaluate.MAX_SAME_CALL  # only 2 real runs
    assert len(fm.calls) == 5  # 2 runs + 3 refusals, then stop before asking again
    assert "terminal: refused" in o
    assert "Stopped: the model kept repeating blocked calls." in o
    assert "reached MAX_STEPS" not in o


def test_refusal_message_sent_to_model(setup):
    same = lambda n: reply("", tc("terminal", command="echo same"))
    fm, _ = setup(same, max_steps=10)
    core.run("loop")
    last = fm.calls[-1]["messages"]
    refusals = [m for m in last if role(m) == "tool" and "already ran 2 times" in m["content"]]
    assert len(refusals) == 2


def test_failed_mutating_call_is_locked(setup, capsys):
    call = tc("write_file", path="a", content="x")
    fm, ex = setup(
        [reply("", call), reply("", call), reply("giving up")],
        results=["Error: could not write"],
    )
    core.run("write")
    o = out(capsys)
    assert len(ex.calls) == 1  # second identical call never reaches the tool
    assert "write_file: failed" in o
    assert "write_file: refused" in o
    second_try = fm.calls[2]["messages"][-1]
    assert "must not be repeated" in second_try["content"]


def test_failed_read_only_call_can_retry(setup, capsys):
    call = tc("read_file", path="a")
    fm, ex = setup(
        [reply("", call), reply("", call), reply("sorry")],
        results=["Error: file not found"],
    )
    core.run("read")
    assert len(ex.calls) == 2
    assert "read_file: failed" in out(capsys)


def test_blocked_call_is_locked(setup, capsys):
    call = tc("terminal", command="sudo reboot")
    fm, ex = setup(
        [reply("", call), reply("", call), reply("cannot do that")],
        results=["Error: blocked by policy: sudo"],
    )
    core.run("reboot")
    o = out(capsys)
    assert len(ex.calls) == 1
    assert "terminal: blocked" in o
    assert "terminal: refused" in o
    assert "must not be repeated" in fm.calls[2]["messages"][-1]["content"]


def test_timeout_on_mutating_tool_adds_warning(setup):
    fm, _ = setup(
        [reply("", tc("write_file", path="a", content="x")), reply("checked")],
        results=["Error: the command timed out after 30s"],
    )
    core.run("write")
    content = fm.calls[1]["messages"][-1]["content"]
    assert content.startswith("Error: the command timed out")
    assert "Do NOT repeat it" in content


# ---------- declined / SKIPPED ----------

def test_declined_removes_tools_for_next_step(setup, capsys):
    fm, ex = setup(
        [reply("", tc("write_file", path="a", content="x")), reply("I did not write it.")],
        results=["Error: the user declined this action"],
    )
    core.run("write")
    o = out(capsys)
    assert "write_file: declined" in o
    assert fm.calls[0]["tools"] == SCHEMAS
    assert fm.calls[1]["tools"] is None
    assert len(fm.calls) == 2
    assert "I did not write it." in o


def test_declined_then_empty_reply_prints_declined_message(setup, capsys):
    setup(
        [reply("", tc("write_file", path="a", content="x")), reply("")],
        results=["Error: the user declined this action"],
    )
    core.run("write")
    assert "The action was declined by you and was not performed." in out(capsys)


def test_declined_ignores_tool_calls_after_decline(setup):
    fm, ex = setup(
        [
            reply("", tc("write_file", path="a", content="x")),
            reply("", tc("terminal", command="tee a")),  # tries to get around the refusal
        ],
        results=["Error: the user declined this action"],
    )
    core.run("write")
    assert len(ex.calls) == 1  # the second attempt is never executed
    assert len(fm.calls) == 2


def test_second_call_in_same_reply_is_skipped(setup, capsys):
    fm, ex = setup(
        [
            reply("", tc("write_file", path="a", content="1"), tc("write_file", path="b", content="2")),
            reply("explained"),
        ],
        results=["Error: the user declined this action"],
    )
    core.run("write two")
    o = out(capsys)
    assert len(ex.calls) == 1
    assert "write_file: declined" in o
    assert "write_file: skipped" in o
    tool_msgs = [m for m in fm.calls[1]["messages"] if role(m) == "tool"]
    assert tool_msgs[1]["content"] == core.SKIPPED


# ---------- finish ----------

def test_empty_reply_after_tool_shows_last_result(setup, capsys):
    setup(
        [reply("", tc("terminal", command="ls")), reply("")],
        results=["RESULT-TEXT"],
    )
    core.run("ls")
    o = out(capsys)
    assert "(the model gave no summary) Last tool result:" in o
    assert "RESULT-TEXT" in o


def test_empty_reply_no_tools(setup, capsys):
    setup([reply("")])
    core.run("hi")
    assert "(the model returned an empty reply)" in out(capsys)


def test_finish_silent_when_model_spoke(capsys):
    core.finish(SimpleNamespace(content="Already streamed"), "last", False, core.ConsoleOutput())
    assert capsys.readouterr().out == ""


def test_finish_whitespace_counts_as_empty(capsys):
    core.finish(SimpleNamespace(content="   \n "), "", False, core.ConsoleOutput())
    assert "(the model returned an empty reply)" in out(capsys)


def test_finish_none_content(capsys):
    core.finish(SimpleNamespace(content=None), "res", False, core.ConsoleOutput())
    assert "(the model gave no summary)" in out(capsys)


def test_finish_declined_wins_over_last_result(capsys):
    core.finish(SimpleNamespace(content=""), "some result", True, core.ConsoleOutput())
    o = out(capsys)
    assert "declined by you" in o
    assert "some result" not in o


# ---------- context ----------

def test_too_big_stops_before_asking_model(setup, capsys):
    fm, _ = setup([reply("never")], compact=lambda m, s: core.context.TOO_BIG)
    core.run("huge task")
    o = out(capsys)
    assert fm.calls == []
    assert "does not fit in the context window" in o
    assert "AGENT_CONTEXT" in o


def test_trimmed_prints_note_and_continues(setup, capsys):
    fm, _ = setup([reply("fine")], compact=lambda m, s: core.context.TRIMMED)
    core.run("task")
    o = out(capsys)
    assert "context trimmed to fit" in o
    assert len(fm.calls) == 1
    assert "fine" in o


def test_compact_receives_tools_then_none_after_decline(setup):
    seen = []

    def spy(messages, schemas):
        seen.append(schemas)
        return core.context.OK

    setup(
        [reply("", tc("write_file", path="a", content="x")), reply("ok")],
        results=["Error: the user declined this action"],
        compact=spy,
    )
    core.run("write")
    assert seen == [SCHEMAS, None]


# ---------- sandbox warning ----------

def test_warning_when_sandbox_off(setup, monkeypatch, capsys):
    monkeypatch.setattr(core, "SANDBOX", False)
    setup([reply("x")])
    core.run("hi")
    assert "WARNING: sandbox is OFF" in out(capsys)


def test_no_warning_when_sandbox_on(setup, capsys):
    setup([reply("x")])
    core.run("hi")
    assert "sandbox is OFF" not in out(capsys)
