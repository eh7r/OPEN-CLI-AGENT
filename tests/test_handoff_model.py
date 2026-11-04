from types import SimpleNamespace

from agent import handoff, model


def _reply(text):
    return SimpleNamespace(content=text)


def test_returns_stripped_text():
    assert handoff.model_section("facts", ask=lambda *a, **k: _reply("  - next  \n")) == "- next"


def test_any_failure_gives_empty():
    def boom(*a, **k):
        raise RuntimeError("down")

    assert handoff.model_section("facts", ask=boom) == ""


def test_none_content_gives_empty():
    assert handoff.model_section("facts", ask=lambda *a, **k: _reply(None)) == ""


def test_passes_limits_cancel_and_no_tools():
    seen = {}

    def fake(messages, tools=None, on_token=None, cancel=None, max_tokens=None):
        seen.update(tools=tools, cancel=cancel, max_tokens=max_tokens, messages=messages)
        return _reply("x")

    c = lambda: None
    handoff.model_section("facts", ask=fake, cancel=c)
    assert seen["tools"] is None
    assert seen["cancel"] is c
    assert seen["max_tokens"] == handoff.MODEL_TOKENS


def test_long_input_is_cut_keeping_start_and_end():
    text = "START" + "a" * 5000 + "END"
    out = handoff._cut(text)
    assert len(out) < 1600
    assert out.startswith("START") and out.endswith("END")


def test_short_input_untouched():
    assert handoff._cut("small") == "small"


def test_ask_max_tokens_override(monkeypatch):
    seen = {}

    class FakeClient:
        def chat(self, **kw):
            seen.update(kw)
            msg = SimpleNamespace(content="hi", tool_calls=None)
            return iter([SimpleNamespace(done=True, message=msg)])

    monkeypatch.setattr(model, "_client", FakeClient())
    model.ask([{"role": "user", "content": "x"}], max_tokens=200)
    assert seen["options"]["num_predict"] == 200
    model.ask([{"role": "user", "content": "x"}])
    assert seen["options"]["num_predict"] == model.MAX_REPLY_TOKENS
