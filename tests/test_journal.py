import json

from agent.journal import MAX_TASKS, Journal, Recording


class FakeOut:
    def __init__(self):
        self.calls = []

    def model_start(self, step):
        self.calls.append(("model_start", step))

    def token(self, text):
        self.calls.append(("token", text))

    def model_end(self):
        self.calls.append(("model_end",))

    def tool_end(self, name, args, status, result):
        self.calls.append(("tool_end", name, status))

    def notice(self, text, kind="info"):
        self.calls.append(("notice", text, kind))


def test_begin_and_end():
    j = Journal()
    j.begin("شغل pwd")
    j.end("done")
    assert j.tasks[0]["task"] == "شغل pwd"
    assert j.tasks[0]["outcome"] == "done"


def test_tool_result_is_cut():
    j = Journal()
    j.begin("t")
    j.tool("terminal", {"command": "ls"}, "ok", "x" * 1000)
    r = j.tasks[0]["tools"][0]["result"]
    assert len(r) <= 300 and r.endswith("...")


def test_unknown_outcome_becomes_error():
    j = Journal()
    j.begin("t")
    j.end("weird")
    assert j.tasks[0]["outcome"] == "error"


def test_tool_without_a_task_is_ignored():
    j = Journal()
    j.tool("terminal", {}, "ok", "x")
    assert j.tasks == []


def test_task_cap_keeps_the_newest():
    j = Journal()
    for i in range(MAX_TASKS + 5):
        j.begin(f"t{i}")
        j.end("done")
    assert len(j.tasks) == MAX_TASKS
    assert j.tasks[-1]["task"] == f"t{MAX_TASKS + 4}"


def test_loaded_tasks_are_filtered():
    j = Journal([{"task": "a"}, "junk", 5])
    assert len(j.tasks) == 1


def test_always_json_safe():
    j = Journal()
    j.begin("t")
    j.tool("x", {"p": object()}, "ok", object())
    j.end("done")
    json.dumps(j.tasks, ensure_ascii=False)


def test_recording_forwards_other_calls():
    out = FakeOut()
    rec = Recording(out, Journal())
    rec.notice("hi", "error")
    assert ("notice", "hi", "error") in out.calls


def test_recording_keeps_the_streamed_reply():
    j = Journal()
    j.begin("t")
    rec = Recording(FakeOut(), j)
    rec.model_start(1)
    rec.token("hel")
    rec.token("lo")
    rec.model_end()
    j.end("done")
    assert j.tasks[0]["reply"] == "hello"


def test_empty_last_reply_does_not_erase_an_earlier_one():
    j = Journal()
    j.begin("t")
    rec = Recording(FakeOut(), j)
    rec.model_start(1)
    rec.token("plan")
    rec.model_end()
    rec.model_start(2)
    rec.model_end()
    assert j.tasks[0]["reply"] == "plan"


def test_recording_records_and_forwards_tools():
    out = FakeOut()
    j = Journal()
    j.begin("t")
    rec = Recording(out, j)
    rec.tool_end("terminal", {"command": "pwd"}, "ok", "/tmp")
    assert ("tool_end", "terminal", "ok") in out.calls
    t = j.tasks[0]["tools"][0]
    assert t["name"] == "terminal" and t["status"] == "ok"


def test_non_list_loaded_journal_is_ignored():
    assert Journal("junk").tasks == []
    assert Journal(5).tasks == []


def test_journal_roundtrips_inside_a_session_file(tmp_path, monkeypatch):
    from agent import sessions

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    j = Journal()
    j.begin("شغل pwd")
    j.tool("terminal", {"command": "pwd"}, "ok", "/tmp")
    j.end("done")
    s = sessions.create("شغل pwd", [{"role": "system", "content": "s"}], "/w")
    s["journal"] = j.tasks
    sessions.save(s)
    back = Journal(sessions.load(s["id"])["journal"])
    assert back.tasks[0]["tools"][0]["name"] == "terminal"
