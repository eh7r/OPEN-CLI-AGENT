from types import SimpleNamespace

from agent import handoff

TASKS = [{"task": "fix bug", "outcome": "done", "reply": "fixed", "tools": []}]


def _fake_save(store):
    def save(sid, text):
        store[sid] = text
        return f"/x/{sid}.md"

    return save


def test_saves_with_model_section(monkeypatch):
    store = {}
    monkeypatch.setattr(handoff, "save", _fake_save(store))
    ask = lambda *a, **k: SimpleNamespace(content="- next")
    path, text = handoff.generate("abc", "/w", TASKS, ask=ask)
    assert path == "/x/abc.md"
    assert "Next steps" in text and "- next" in text
    assert store["abc"] == text


def test_use_model_false_never_asks(monkeypatch):
    monkeypatch.setattr(handoff, "save", _fake_save({}))

    def ask(*a, **k):
        raise AssertionError("must not be called")

    path, text = handoff.generate("abc", "/w", TASKS, ask=ask, use_model=False)
    assert path and "Next steps" not in text


def test_model_failure_still_saves_base(monkeypatch):
    store = {}
    monkeypatch.setattr(handoff, "save", _fake_save(store))

    def boom(*a, **k):
        raise RuntimeError("down")

    path, text = handoff.generate("abc", "/w", TASKS, ask=boom)
    assert path and "fix bug" in text and "Next steps" not in text


def test_save_failure_returns_text_without_path(monkeypatch):
    def bad(sid, text):
        raise OSError("disk")

    monkeypatch.setattr(handoff, "save", bad)
    path, text = handoff.generate("abc", "/w", TASKS, use_model=False)
    assert path is None and "fix bug" in text


def test_unsaved_session_is_not_written(monkeypatch):
    def never(sid, text):
        raise AssertionError("must not save")

    monkeypatch.setattr(handoff, "save", never)
    path, text = handoff.generate(None, "/w", TASKS, use_model=False)
    assert path is None and "unsaved" in text
