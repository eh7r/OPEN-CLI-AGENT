import os
import stat

import pytest

from agent import handoff


def _tasks():
    return [
        {"task": "شغل pwd", "outcome": "done", "note": "", "reply": "", "tools": [
            {"name": "terminal", "args": {"command": "pwd"}, "status": "ok",
             "result": "exit code: 0 stdout: /tmp"}]},
        {"task": "اكتب a.txt", "outcome": "done", "note": "", "reply": "تم", "tools": [
            {"name": "write_file", "args": {"path": "a.txt", "content": "hello"}, "status": "ok",
             "result": "Wrote a.txt"},
            {"name": "write_file", "args": {"path": "b.txt", "content": "x"}, "status": "declined",
             "result": "Error: the user declined this action."}]},
        {"task": "شغل false", "outcome": "done", "note": "", "reply": "", "tools": [
            {"name": "terminal", "args": {"command": "false"}, "status": "failed",
             "result": "exit code: 1 stderr: boom"}]},
        {"task": "مهمة ملغاة", "outcome": "cancelled", "note": "", "reply": "", "tools": []},
    ]


def test_header():
    text = handoff.build("deadbeef", "/w", _tasks())
    assert text.startswith("Handoff for session deadbeef\nWork dir: /w\n")


def test_tasks_are_listed_with_outcomes():
    text = handoff.build("deadbeef", "/w", _tasks())
    assert "1. [done] شغل pwd" in text
    assert "4. [cancelled] مهمة ملغاة" in text


def test_only_successful_writes_are_listed():
    text = handoff.build("deadbeef", "/w", _tasks())
    assert "- a.txt" in text
    assert "- b.txt" not in text


def test_commands_show_exit_codes():
    text = handoff.build("deadbeef", "/w", _tasks())
    assert "- pwd -> exit 0" in text
    assert "- false -> exit 1" in text


def test_problems_list_declined_failed_and_cancelled():
    text = handoff.build("deadbeef", "/w", _tasks())
    assert "- task 2: write_file b.txt (declined)" in text
    assert "- task 3: terminal false (failed)" in text
    assert "- task 4: cancelled" in text


def test_unknown_status_is_a_problem():
    tasks = [{"task": "t", "outcome": "done", "tools": [
        {"name": "terminal", "args": {"command": "x"}, "status": "weird", "result": ""}]}]
    assert "(weird)" in handoff.build("deadbeef", "/w", tasks)


def test_last_reply():
    text = handoff.build("deadbeef", "/w", _tasks()[:2])
    assert "Last reply:\nتم" in text


def test_last_reply_none():
    assert "Last reply:\n(none)" in handoff.build("deadbeef", "/w", _tasks())


def test_old_text_args_are_parsed():
    tasks = [{"task": "t", "outcome": "done", "tools": [
        {"name": "write_file", "args": "{'content': 'hello', 'path': 'a.txt'}", "status": "ok", "result": ""}]}]
    assert "- a.txt" in handoff.build("deadbeef", "/w", tasks)


def test_old_text_args_with_double_quotes():
    tasks = [{"task": "t", "outcome": "done", "tools": [
        {"name": "write_file", "args": "{'content': \"it's\", 'path': \"my 'file'.txt\"}",
         "status": "ok", "result": ""}]}]
    assert "- my 'file'.txt" in handoff.build("deadbeef", "/w", tasks)


def test_long_sessions_are_capped():
    tasks = [{"task": f"t{i}", "outcome": "done", "note": "", "reply": "", "tools": []} for i in range(40)]
    text = handoff.build("deadbeef", "/w", tasks)
    assert "26. [done] t25" in text
    assert "1. [done] t0" not in text
    assert "(+25 earlier)" in text


def test_model_section_is_marked():
    text = handoff.build("deadbeef", "/w", _tasks(), model_text="  do X next ")
    assert "Next steps and tips (written by the model, check them):\ndo X next" in text


def test_no_model_section_when_empty():
    assert "written by the model" not in handoff.build("deadbeef", "/w", _tasks(), model_text="  ")


def test_empty_journal():
    text = handoff.build(None, "/w", [])
    assert "unsaved" in text and "- none" in text


def test_junk_in_the_journal_is_ignored():
    tasks = [{"task": "t", "outcome": "done", "tools": "junk"},
             {"task": "u", "outcome": "done", "tools": [5, {"name": "terminal", "args": {"command": "ls"},
                                                             "status": "ok", "result": "exit code: 0"}]},
             "oops"]
    text = handoff.build("deadbeef", "/w", tasks)
    assert "- ls -> exit 0" in text


def test_save_writes_a_private_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    path = handoff.save("deadbeef", "hello مرحبا")
    assert path == str(tmp_path / "ai-agent" / "handoffs" / "deadbeef.md")
    assert open(path, encoding="utf-8").read() == "hello مرحبا"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert [n for n in os.listdir(os.path.dirname(path)) if n.startswith(".tmp")] == []


def test_save_refuses_a_bad_id(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    with pytest.raises(ValueError):
        handoff.save("../x", "text")
