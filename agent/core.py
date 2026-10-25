from rich.console import Console

from agent import context, evaluate, file_tools, git_tools, memory, tools  # noqa: F401
from agent.config import CONTEXT_TOKENS, MAX_STEPS, MODEL, SANDBOX
from agent.events import ConsoleOutput
from agent.model import ask

console = Console()

MAX_REFUSALS = 3

DONE, STOPPED, TOO_BIG = "done", "stopped", "too_big"

SYSTEM_PROMPT = (
    "You are a helpful terminal assistant. "
    "Use the terminal tool when you need to run a shell command. "
    "For files, prefer read_file, write_file and list_dir over shell commands. "
    "For git, use git_status, git_diff and git_commit. "
    "Use remember only when the user asks you to keep a fact for future sessions (never secrets); use forget to delete a note. "
    "For counting or measuring files (lines, sizes) run a command such as wc -l; do not guess. "
    "If a tool returns an error or the user declined, say clearly that the action was NOT done. "
    "If the user declines an action, stop and explain; never try another way to do the same thing. "
    "Always reply in the same language the user writes in. "
    "When you have the final answer, reply in plain text, briefly."
)

SKIPPED = (
    "Skipped: the user declined an earlier action in this task. "
    "Do not try another way; explain to the user."
)


def banner() -> None:
    ConsoleOutput().banner(MODEL, SANDBOX)


def new_session() -> list:
    """The starting messages of a conversation (system prompt plus saved notes)."""
    return [{"role": "system", "content": SYSTEM_PROMPT + memory.notes_block()}]


def finish(reply, last_result: str, declined: bool, out) -> None:
    """The reply text was already streamed; only fill in when the model said nothing."""
    if (reply.content or "").strip():
        return
    if declined:
        text = "The action was declined by you and was not performed."
    elif last_result:
        text = f"(the model gave no summary) Last tool result:\n{last_result}"
    else:
        text = "(the model returned an empty reply)"
    out.final(text)


def run(task: str, messages: list | None = None, out=None) -> str:
    """Run one task. Pass the same `messages` list again to continue the conversation.
    `out` is where everything is shown (plain terminal by default, the TUI passes its own).
    Returns DONE, STOPPED or TOO_BIG."""
    out = out or ConsoleOutput()
    if messages is None:
        out.banner(MODEL, SANDBOX)
        messages = new_session()
    messages.append({"role": "user", "content": task})
    tracker = evaluate.Tracker()
    last_result = ""

    for step in range(1, MAX_STEPS + 1):
        out.check()
        out.step(step, MAX_STEPS)
        if tracker.refusals >= MAX_REFUSALS:
            out.notice("Stopped: the model kept repeating blocked calls.", "error")
            return STOPPED

        # After a refusal the model gets no tools: it can only explain.
        schemas = None if tracker.declined else tools.schemas()
        fit = context.compact(messages, schemas)
        if fit == context.TOO_BIG:
            out.notice("Stopped: this does not fit in the context window. Raise AGENT_CONTEXT or shorten the task.", "error")
            return TOO_BIG
        if fit == context.TRIMMED:
            out.notice("   context trimmed to fit")
        out.context(context.estimate_tokens(messages, schemas), CONTEXT_TOKENS)

        out.model_start(step)
        reply = ask(messages, schemas, on_token=out.token)
        out.model_end()
        messages.append(reply)
        if (reply.content or "").strip():
            out.reply_end()

        if tracker.declined or not reply.tool_calls:
            finish(reply, last_result, tracker.declined, out)
            return DONE

        for call in reply.tool_calls:
            out.check()
            name = call.function.name
            args = dict(call.function.arguments)
            out.tool_start(name, args)

            if tracker.declined:
                result, status = SKIPPED, "skipped"
            else:
                result = tracker.check(name, args)
                if result:
                    status = "refused"
                    tracker.refusals += 1
                else:
                    result, status = tracker.record(name, args, tools.execute(name, args))

            out.tool_end(name, args, status, result)
            last_result = result
            messages.append({"role": "tool", "tool_name": name, "content": result})

    out.notice("Stopped: reached MAX_STEPS.", "error")
    return STOPPED
