import os
import queue
import threading
import time

import ollama

from agent.config import CONTEXT_TOKENS, MAX_REPLY_TOKENS, MODEL, OLLAMA_HOST, THINK

_client = ollama.Client(host=OLLAMA_HOST)


class ModelError(Exception):
    pass


def _trace(chunk, n_messages, wall):
    """With AGENT_TRACE=1, append one timing line per request to /tmp/agent-trace.log."""
    if os.getenv("AGENT_TRACE", "0").lower() not in ("1", "true", "on", "yes"):
        return

    def sec(name):
        return (getattr(chunk, name, None) or 0) / 1e9

    line = (
        f"msgs={n_messages} prompt_tokens={getattr(chunk, 'prompt_eval_count', 0)} "
        f"prompt_s={sec('prompt_eval_duration'):.1f} out_tokens={getattr(chunk, 'eval_count', 0)} "
        f"gen_s={sec('eval_duration'):.1f} load_s={sec('load_duration'):.1f} wall_s={wall:.1f}\n"
    )
    try:
        with open("/tmp/agent-trace.log", "a") as f:
            f.write(line)
    except OSError:
        pass


def ask(messages: list, tools: list | None = None, on_token=None, cancel=None):
    """Send messages to the model; stream the text through on_token; return the reply.
    cancel() is called every 0.1s while waiting and may raise to stop waiting."""
    parts, calls = [], []
    q = queue.Queue()
    t0 = time.monotonic()

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
        if getattr(val, 'done', False):
            _trace(val, len(messages), time.monotonic() - t0)
        msg = val.message
        if msg.content:
            parts.append(msg.content)
            if on_token:
                on_token(msg.content)
        if msg.tool_calls:
            calls.extend(msg.tool_calls)

    return ollama.Message(role="assistant", content="".join(parts), tool_calls=calls or None)


def warm_up(messages: list | None = None, tools: list | None = None) -> None:
    """Load the model and, when given the session start, read the system prompt and tool
    definitions now, so the first real request only has to read the user's message."""
    try:
        if messages:
            _client.chat(
                model=MODEL,
                messages=messages,
                tools=tools,
                think=THINK,
                keep_alive="30m",
                options={"num_ctx": CONTEXT_TOKENS, "num_predict": 1},
            )
        else:
            _client.generate(model=MODEL, prompt="", keep_alive="30m", options={"num_ctx": CONTEXT_TOKENS})
    except Exception:
        pass
