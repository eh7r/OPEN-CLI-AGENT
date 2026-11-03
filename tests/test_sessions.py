import json
import os
import stat

import pytest

from agent import sessions


@pytest.fixture(autouse=True)
def data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    return tmp_path


MSGS = [{"role": "system", "content": "sys"}, {"role": "user", "content": "مرحبا hello"}]


def test_title_collapses_whitespace():
    assert sessions.make_title("  list   the\nfiles ") == "list the files"


def test_title_is_cut():
    t = sessions.make_title("x" * 200)
    assert len(t) == sessions.TITLE_MAX and t.endswith("...")


def test_title_empty():
    assert sessions.make_title("   ") == "Untitled"


def test_roundtrip_keeps_arabic():
    s = sessions.create("مرحبا", MSGS, "/work")
    sessions.save(s)
    back = sessions.load(s["id"])
    assert back["messages"] == MSGS
    assert back["title"] == "مرحبا" and back["workdir"] == "/work"


def test_id_format():
    assert sessions.valid_id(sessions.create("t", MSGS, "/w")["id"])


@pytest.mark.parametrize("bad", ["../etc/passwd", "zzzzzzzz", "abc", "", None, "ABCDEF12", "a" * 9])
def test_bad_ids_are_rejected(bad):
    assert sessions.load(bad) is None


def test_save_refuses_bad_id():
    with pytest.raises(ValueError):
        sessions.save({"id": "../x", "messages": MSGS})


def test_corrupt_file_returns_none(data_home):
    folder = sessions.sessions_dir()
    os.makedirs(folder)
    with open(os.path.join(folder, "deadbeef.json"), "w") as f:
        f.write("{not json")
    assert sessions.load("deadbeef") is None


def test_wrong_shape_returns_none():
    folder = sessions.sessions_dir()
    os.makedirs(folder)
    with open(os.path.join(folder, "deadbeef.json"), "w") as f:
        json.dump({"id": "deadbeef", "messages": ["oops"]}, f)
    assert sessions.load("deadbeef") is None


def test_id_must_match_file_name():
    folder = sessions.sessions_dir()
    os.makedirs(folder)
    with open(os.path.join(folder, "deadbeef.json"), "w") as f:
        json.dump({"id": "cafebabe", "messages": MSGS}, f)
    assert sessions.load("deadbeef") is None


def test_file_is_private():
    s = sessions.create("t", MSGS, "/w")
    sessions.save(s)
    path = os.path.join(sessions.sessions_dir(), s["id"] + ".json")
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_no_temp_files_left():
    s = sessions.create("t", MSGS, "/w")
    sessions.save(s)
    assert [n for n in os.listdir(sessions.sessions_dir()) if n.startswith(".tmp")] == []


def test_update_changes_messages_and_time(monkeypatch):
    monkeypatch.setattr(sessions, "_now", lambda: "2026-01-01T00:00:00+00:00")
    s = sessions.create("t", MSGS, "/w")
    monkeypatch.setattr(sessions, "_now", lambda: "2026-01-02T00:00:00+00:00")
    sessions.update(s, MSGS + [{"role": "assistant", "content": "ok"}])
    back = sessions.load(s["id"])
    assert len(back["messages"]) == 3
    assert back["created"] != back["updated"]


def test_objects_with_model_dump_are_saved():
    class Msg:
        def model_dump(self, exclude_none=False):
            return {"role": "assistant", "content": "hi"}

    s = sessions.create("t", [MSGS[0], Msg()], "/w")
    sessions.save(s)
    assert sessions.load(s["id"])["messages"][1] == {"role": "assistant", "content": "hi"}


def test_last_and_list_are_newest_first(monkeypatch):
    stamps = iter(["2026-01-01T00:00:00+00:00", "2026-01-03T00:00:00+00:00", "2026-01-02T00:00:00+00:00"])
    monkeypatch.setattr(sessions, "_now", lambda: next(stamps))
    ids = []
    for title in ("a", "b", "c"):
        s = sessions.create(title, MSGS, "/w")
        sessions.save(s)
        ids.append(s["id"])
    order = [s["title"] for s in sessions.list_all()]
    assert order == ["b", "c", "a"]
    assert sessions.last()["title"] == "b"


def test_last_with_no_sessions():
    assert sessions.last() is None
    assert sessions.list_all() == []


def test_estimate_tokens_accepts_loaded_tool_calls():
    from agent import context

    loaded = [
        {"role": "system", "content": "sys"},
        {"role": "assistant", "content": "",
         "tool_calls": [{"function": {"name": "terminal", "arguments": {"command": "pwd"}}}]},
        {"role": "tool", "tool_name": "terminal", "content": "ok"},
    ]
    assert context.estimate_tokens(loaded) > 0
