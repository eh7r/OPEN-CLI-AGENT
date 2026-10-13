from rich.console import Console

from agent import file_tools, tools  # noqa: F401
from agent.config import MAX_STEPS, MODEL
from agent.model import ask

console = Console()

SYSTEM_PROMPT = (
    "You are a helpful terminal assistant. "
    "Use the terminal tool when you need to run a shell command. "
    "For files, prefer read_file, write_file and list_dir over shell commands. "
    "If a tool returns an error or the user declined, say clearly that the action was NOT done. "
    "When you have the final answer, reply in plain text, briefly."
)


def run(task: str) -> None:
    console.print(f"[dim]model: {MODEL}[/dim]")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]
    last_result = ""

    for step in range(1, MAX_STEPS + 1):
        console.print(f"[dim]-- step {step}/{MAX_STEPS}[/dim]")
        reply = ask(messages, tools.schemas())
        messages.append(reply)

        if not reply.tool_calls:
            text = (reply.content or "").strip()
            if not text and last_result:
                text = f"(the model gave no summary) Last tool result:\n{last_result}"
            elif not text:
                text = "(the model returned an empty reply)"
            console.print(f"\n{text}", style="green", markup=False)
            return

        for call in reply.tool_calls:
            last_result = tools.execute(call.function.name, dict(call.function.arguments))
            messages.append(
                {"role": "tool", "tool_name": call.function.name, "content": last_result}
            )

    console.print("[red]Stopped: reached MAX_STEPS.[/red]")
