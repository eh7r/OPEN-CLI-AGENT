from rich.console import Console

from agent import context, evaluate, file_tools, git_tools, tools  # noqa: F401
from agent.config import MAX_STEPS, MODEL, SANDBOX
from agent.model import ask

console = Console()

SYSTEM_PROMPT = (
    "You are a helpful terminal assistant. "
    "Use the terminal tool when you need to run a shell command. "
    "For files, prefer read_file, write_file and list_dir over shell commands. "
    "For git, use git_status, git_diff and git_commit. "
    "If a tool returns an error or the user declined, say clearly that the action was NOT done. "
    "If the user declines an action, stop and explain; never try another way to do the same thing. "
    "When you have the final answer, reply in plain text, briefly."
)

MAX_REFUSALS = 3

SKIPPED = (
    "Skipped: the user declined an earlier action in this task. "
    "Do not try another way; explain to the user."
)


def show_final(reply, last_result: str, declined: bool) -> None:
    text = (reply.content or "").strip()
    if not text:
        if declined:
            text = "The action was declined by you and was not performed."
        elif last_result:
            text = f"(the model gave no summary) Last tool result:\n{last_result}"
        else:
            text = "(the model returned an empty reply)"
    console.print(f"\n{text}", style="green", markup=False)


def run(task: str) -> None:
    console.print(f"[dim]model: {MODEL}[/dim]")
    if not SANDBOX:
        console.print("[red]WARNING: sandbox is OFF, commands run with your full permissions.[/red]")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]
    tracker = evaluate.Tracker()
    last_result = ""

    for step in range(1, MAX_STEPS + 1):
        console.print(f"[dim]-- step {step}/{MAX_STEPS}[/dim]")
        if tracker.refusals >= MAX_REFUSALS:
            console.print("[red]Stopped: the model kept repeating blocked calls.[/red]")
            return
        # After a refusal the model gets no tools: it can only explain.
        schemas = None if tracker.declined else tools.schemas()
        fit = context.compact(messages, schemas)
        if fit == context.TOO_BIG:
            console.print("[red]Stopped: this does not fit in the context window. Raise AGENT_CONTEXT or shorten the task.[/red]")
            return
        if fit == context.TRIMMED:
            console.print("[dim]   context trimmed to fit[/dim]")
        reply = ask(messages, schemas)
        messages.append(reply)

        if tracker.declined or not reply.tool_calls:
            show_final(reply, last_result, tracker.declined)
            return

        for call in reply.tool_calls:
            name = call.function.name
            args = dict(call.function.arguments)

            if tracker.declined:
                result, status = SKIPPED, "skipped"
            else:
                result = tracker.check(name, args)
                if result:
                    status = "refused"
                    tracker.refusals += 1
                else:
                    result, status = tracker.record(name, args, tools.execute(name, args))

            console.print(f"[dim]   {name}: {status}[/dim]")
            last_result = result
            messages.append({"role": "tool", "tool_name": name, "content": result})

    console.print("[red]Stopped: reached MAX_STEPS.[/red]")
