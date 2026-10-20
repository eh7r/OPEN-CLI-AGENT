"""Tests for agent/model.py: streaming, on_token, tool_calls, ModelError. No real Ollama."""
from types import SimpleNamespace

import ollama
import pytest

from agent import model


def chunk(content=None, tool_calls=None):
    return SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))


def make_call(name="terminal", **args):
    return ollama.Message.ToolCall(
        function=ollama.Message.ToolCall.Function(name=name, arguments=args)
    )


class FakeClient:
    """Stands in for ollama.Client. `result` is a list of chunks, or an exception to raise."""

    def __init__(self, result):
        self.result = result
        self.kwargs = None

    def chat(self, **kwargs):
        self.kwargs = kwargs
        if isinstance(self.result, Exception):
            raise self.result
        return iter(self.result)


@pytest.fixture
def fake(monkeypatch):
    def install(result):
        client = FakeClient(result)
        monkeypatch.setattr(model, "_client", client)
        return client

    return install


MSGS = [{"role": "user", "content": "hi"}]


# ---------- streaming and text ----------

def test_joins_text_chunks(fake):
    fake([chunk("Hel"), chunk("lo "), chunk("world")])
    reply = model.ask(MSGS)
    assert reply.content == "Hello world"
    assert reply.role == "assistant"


def test_on_token_called_in_order(fake):
    fake([chunk("a"), chunk("b"), chunk("c")])
    seen = []
    model.ask(MSGS, on_token=seen.append)
    assert seen == ["a", "b", "c"]


def test_on_token_skips_empty_and_none(fake):
    fake([chunk(""), chunk(None), chunk("x"), chunk("")])
    seen = []
    reply = model.ask(MSGS, on_token=seen.append)
    assert seen == ["x"]
    assert reply.content == "x"


def test_works_without_on_token(fake):
    fake([chunk("ok")])
    assert model.ask(MSGS).content == "ok"


def test_empty_stream_gives_empty_content(fake):
    fake([])
    reply = model.ask(MSGS)
    assert reply.content == ""
    assert not reply.tool_calls


# ---------- tool calls ----------

def test_collects_tool_calls(fake):
    c1 = make_call("terminal", command="ls")
    fake([chunk(tool_calls=[c1])])
    reply = model.ask(MSGS)
    assert len(reply.tool_calls) == 1
    assert reply.tool_calls[0].function.name == "terminal"
    assert dict(reply.tool_calls[0].function.arguments) == {"command": "ls"}


def test_collects_tool_calls_across_chunks(fake):
    c1 = make_call("read_file", path="a.txt")
    c2 = make_call("list_dir", path=".")
    c3 = make_call("git_status")
    fake([chunk(tool_calls=[c1]), chunk("x"), chunk(tool_calls=[c2, c3])])
    reply = model.ask(MSGS)
    names = [c.function.name for c in reply.tool_calls]
    assert names == ["read_file", "list_dir", "git_status"]
    assert reply.content == "x"


def test_no_tool_calls_gives_none(fake):
    fake([chunk("just text")])
    assert model.ask(MSGS).tool_calls is None


def test_tool_calls_with_no_text(fake):
    fake([chunk(tool_calls=[make_call(command="pwd")])])
    reply = model.ask(MSGS)
    assert reply.content == ""
    assert reply.tool_calls


# ---------- request sent to Ollama ----------

def test_passes_expected_arguments(fake):
    client = fake([chunk("ok")])
    schemas = [{"type": "function", "function": {"name": "t"}}]
    model.ask(MSGS, schemas)
    kw = client.kwargs
    assert kw["model"] == model.MODEL
    assert kw["messages"] == MSGS
    assert kw["tools"] == schemas
    assert kw["think"] == model.THINK
    assert kw["stream"] is True
    assert kw["keep_alive"] == "30m"
    assert kw["options"] == {
        "num_ctx": model.CONTEXT_TOKENS,
        "num_predict": model.MAX_REPLY_TOKENS,
    }


def test_tools_default_is_none(fake):
    client = fake([chunk("ok")])
    model.ask(MSGS)
    assert client.kwargs["tools"] is None


# ---------- errors ----------

def test_404_model_not_found(fake):
    fake(ollama.ResponseError("not found", 404))
    with pytest.raises(model.ModelError) as exc:
        model.ask(MSGS)
    assert "Model not found" in str(exc.value)
    assert f"ollama pull {model.MODEL}" in str(exc.value)


def test_other_response_error_keeps_message(fake):
    fake(ollama.ResponseError("server exploded", 500))
    with pytest.raises(model.ModelError) as exc:
        model.ask(MSGS)
    assert "server exploded" in str(exc.value)
    assert "Model not found" not in str(exc.value)


def test_connection_error_at_start(fake):
    fake(ConnectionError("refused"))
    with pytest.raises(model.ModelError) as exc:
        model.ask(MSGS)
    assert "Cannot reach Ollama" in str(exc.value)


def test_unexpected_exception_becomes_model_error(fake):
    fake(RuntimeError("boom"))
    with pytest.raises(model.ModelError) as exc:
        model.ask(MSGS)
    assert "Cannot reach Ollama" in str(exc.value)


def test_connection_drops_mid_stream(fake):
    def broken():
        yield chunk("part")
        raise ConnectionError("lost")

    fake_client = FakeClient(None)
    fake_client.chat = lambda **kw: broken()
    model._client = fake_client  # restored below
    seen = []
    try:
        with pytest.raises(model.ModelError) as exc:
            model.ask(MSGS, on_token=seen.append)
    finally:
        model._client = _ORIGINAL_CLIENT
    assert "Cannot reach Ollama" in str(exc.value)
    assert seen == ["part"]


def test_model_error_is_exception():
    assert issubclass(model.ModelError, Exception)


_ORIGINAL_CLIENT = model._client
