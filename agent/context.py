"""Keep the conversation inside the model's context window (no model calls)."""
import json

from agent.config import CONTEXT_TOKENS, MAX_REPLY_TOKENS

OK, TRIMMED, TOO_BIG = "ok", "trimmed", "too_big"

CHARS_PER_TOKEN = 3  # conservative estimate: there is no tokenizer here
MIN_KEEP_CHARS = 300


def _get(msg, key):
    return msg.get(key) if isinstance(msg, dict) else getattr(msg, key, None)


def _chars(messages) -> int:
    total = 0
    for m in messages:
        total += len(_get(m, "content") or "") + 8
        for call in _get(m, "tool_calls") or []:
            total += len(call.function.name) + len(str(call.function.arguments)) + 20
    return total


def estimate_tokens(messages, tools_schema=None) -> int:
    chars = _chars(messages)
    if tools_schema:
        chars += len(json.dumps(tools_schema))
    return chars // CHARS_PER_TOKEN + 1


def compact(messages: list, tools_schema=None) -> str:
    """Shrink old tool results in place until the conversation fits the budget."""
    budget = CONTEXT_TOKENS - MAX_REPLY_TOKENS
    if estimate_tokens(messages, tools_schema) <= budget:
        return OK

    tool_idx = [i for i, m in enumerate(messages) if _get(m, "role") == "tool"]

    # 1) Replace older tool results with a short note, oldest first.
    for i in tool_idx[:-1]:
        if estimate_tokens(messages, tools_schema) <= budget:
            return TRIMMED
        old = _get(messages[i], "content") or ""
        if len(old) > 80:
            messages[i] = {
                **messages[i],
                "content": f"[older output removed to save space: {len(old)} characters]",
            }

    # 2) Still too big: shrink the newest tool result (keep its start and end).
    if tool_idx:
        last = messages[tool_idx[-1]]
        text = _get(last, "content") or ""
        over_chars = (estimate_tokens(messages, tools_schema) - budget) * CHARS_PER_TOKEN
        keep = max(MIN_KEEP_CHARS, len(text) - over_chars - 100)
        if keep < len(text):
            half = keep // 2
            messages[tool_idx[-1]] = {
                **last,
                "content": text[:half] + "\n...[trimmed to fit the context window]...\n" + text[-half:],
            }

    return TRIMMED if estimate_tokens(messages, tools_schema) <= budget else TOO_BIG
