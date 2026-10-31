import queue
import threading

import ollama

from agent.config import CONTEXT_TOKENS, MAX_REPLY_TOKENS, MODEL, OLLAMA_HOST, THINK

_client = ollama.Client(host=OLLAMA_HOST)


class ModelError(Exception):
    pass


def ask(messages: list, tools: list | None = None, on_token=None, cancel=None):
    """Send messages to the model; stream the text through on_token; return the reply.
    cancel() is called every 0.1s while waiting and may raise to stop waiting."""
    parts, calls = [], []
    q = queue.Queue()

    def reader():
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
                q.put(("chunk", chunk))
            q.put(("end", None))
        except BaseException as e:
            q.put(("error", e))

    threading.Thread(target=reader, daemon=True).start()
    while True:
        try:
            kind, val = q.get(timeout=0.1)
        except queue.Empty:
            if cancel:
                cancel()
            continue
        if kind == "end":
            break
        if kind == "error":
            if isinstance(val, ollama.ResponseError):
                if val.status_code == 404:
                    raise ModelError(f"Model not found. Run: ollama pull {MODEL}")
                raise ModelError(str(val))
            raise ModelError("Cannot reach Ollama. Is it running?")
        msg = val.message
        if msg.content:
            parts.append(msg.content)
            if on_token:
                on_token(msg.content)
        if msg.tool_calls:
            calls.extend(msg.tool_calls)

    return ollama.Message(role="assistant", content="".join(parts), tool_calls=calls or None)


def warm_up() -> None:
    """Load the model into memory so the first real request does not wait for it."""
    try:
        _client.generate(model=MODEL, prompt="", keep_alive="30m", options={"num_ctx": CONTEXT_TOKENS})
    except Exception:
        pass
