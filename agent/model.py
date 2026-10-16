import ollama

from agent.config import CONTEXT_TOKENS, MAX_REPLY_TOKENS, MODEL, OLLAMA_HOST, THINK

_client = ollama.Client(host=OLLAMA_HOST)


class ModelError(Exception):
    pass


def ask(messages: list, tools: list | None = None, on_token=None):
    """Send messages to the model; stream the text through on_token; return the reply."""
    parts, calls = [], []
    try:
        stream = _client.chat(
            model=MODEL,
            messages=messages,
            tools=tools,
            think=THINK,
            keep_alive="30m",
            options={"num_ctx": CONTEXT_TOKENS, "num_predict": MAX_REPLY_TOKENS},
            stream=True,
        )
        for chunk in stream:
            msg = chunk.message
            if msg.content:
                parts.append(msg.content)
                if on_token:
                    on_token(msg.content)
            if msg.tool_calls:
                calls.extend(msg.tool_calls)
    except ollama.ResponseError as e:
        if e.status_code == 404:
            raise ModelError(f"Model not found. Run: ollama pull {MODEL}")
        raise ModelError(str(e))
    except Exception:
        raise ModelError("Cannot reach Ollama. Is it running?")

    return ollama.Message(role="assistant", content="".join(parts), tool_calls=calls or None)
