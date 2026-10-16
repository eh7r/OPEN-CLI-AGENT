from agent import context as c


def conversation(results):
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "task"}]
    for size in results:
        messages.append({"role": "assistant", "content": "", "tool_calls": []})
        messages.append({"role": "tool", "tool_name": "t", "content": "x" * size})
    return messages


def tool_contents(messages):
    return [m["content"] for m in messages if m["role"] == "tool"]


def budget():
    return c.CONTEXT_TOKENS - c.MAX_REPLY_TOKENS


def test_small_conversation_is_untouched():
    messages = conversation([100])
    before = [dict(m) for m in messages]
    assert c.compact(messages) == c.OK
    assert messages == before


def test_old_tool_results_are_replaced_and_the_latest_kept():
    messages = conversation([4000] * 6)
    system, user = dict(messages[0]), dict(messages[1])
    count = len(messages)

    assert c.compact(messages) == c.TRIMMED

    results = tool_contents(messages)
    assert results[0].startswith("[older output removed")
    assert len(results[-1]) == 4000
    assert c.estimate_tokens(messages) <= budget()
    assert len(messages) == count
    assert messages[0] == system and messages[1] == user


def test_a_single_huge_result_is_shrunk():
    messages = conversation([20000])
    assert c.compact(messages) == c.TRIMMED
    result = tool_contents(messages)[0]
    assert len(result) < 20000
    assert "trimmed to fit" in result
    assert c.estimate_tokens(messages) <= budget()


def test_task_that_can_never_fit_is_reported():
    messages = [{"role": "user", "content": "y" * 40000}]
    assert c.compact(messages) == c.TOO_BIG


def test_tool_schemas_count_toward_the_budget():
    messages = conversation([2000, 2000])
    schema = [{"x": "y" * 6000}]
    assert c.estimate_tokens(messages, schema) > c.estimate_tokens(messages)
    assert c.compact(conversation([2000, 2000])) == c.OK
    assert c.compact(messages, schema) == c.TRIMMED
