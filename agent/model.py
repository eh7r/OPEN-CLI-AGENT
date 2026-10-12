import ollama

from agent.config import MODEL, OLLAMA_HOST

_client = ollama.Client(host=OLLAMA_HOST)


class ModelError(Exception):
    pass


def ask(messages: list, tools: list | None = None):
    """Send messages to the model and return its reply message."""
    try:
        response = _client.chat(model=MODEL, messages=messages, tools=tools, keep_alive="30m", think=False)
    except ollama.ResponseError as e:
        if e.status_code == 404:
            raise ModelError(f"Model not found. Run: ollama pull {MODEL}")
        raise ModelError(str(e))
    except Exception:
        raise ModelError("Cannot reach Ollama. Is it running?")
    return response.message
