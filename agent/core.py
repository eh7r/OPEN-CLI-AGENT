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
    "When you have the final answer, reply in plain text."
)


def run(task: str) -> None:
    console.print(f"[dim]model: {MODEL}[/dim]")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    for step in range(1, MAX_STEPS + 1):
        console.print(f"[dim]-- step {step}/{MAX_STEPS}[/dim]")
        reply = ask(messages, tools.schemas())
        messages.append(reply)

        if not reply.tool_calls:
            console.print(f"\n[green]{reply.content}[/green]")
            return

        for call in reply.tool_calls:
            result = tools.execute(call.function.name, dict(call.function.arguments))
            messages.append(
                {"role": "tool", "tool_name": call.function.name, "content": result}
            )

    console.print("[red]Stopped: reached MAX_STEPS.[/red]")
