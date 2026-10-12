from rich.console import Console

from agent.config import MAX_STEPS, MODEL
from agent.model import ask

console = Console()

SYSTEM_PROMPT = (
    "You are a helpful terminal assistant. "
    "Use the terminal tool when you need to run a shell command. "
    "When you have the final answer, reply in plain text."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "terminal",
            "description": "Run a shell command and return its output",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to run",
                    }
                },
                "required": ["command"],
            },
        },
    }
]


def run_tool(name: str, args: dict) -> str:
    """Simulated tools: print what the model wants, execute nothing."""
    if name == "terminal":
        command = args.get("command", "")
        console.print(f"[yellow][SIMULATED][/yellow] would run: [bold]{command}[/bold]")
        return "[simulated] the command was not executed"
    return f"unknown tool: {name}"


def run(task: str) -> None:
    console.print(f"[dim]model: {MODEL}[/dim]")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    for step in range(1, MAX_STEPS + 1):
        console.print(f"[dim]-- step {step}/{MAX_STEPS}[/dim]")
        reply = ask(messages, TOOLS)
        messages.append(reply)

        if not reply.tool_calls:
            console.print(f"\n[green]{reply.content}[/green]")
            return

        for call in reply.tool_calls:
            result = run_tool(call.function.name, dict(call.function.arguments))
            messages.append(
                {"role": "tool", "tool_name": call.function.name, "content": result}
            )

    console.print("[red]Stopped: reached MAX_STEPS.[/red]")
