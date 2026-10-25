"""How the core talks to a screen.

ConsoleOutput is the old plain-terminal look. The TUI passes its own object
with the same methods, so the core never prints by itself.
"""
from rich.console import Console

from agent.config import MODEL, SANDBOX

console = Console()


class Cancelled(KeyboardInterrupt):
    """Raised inside a running task when the user presses Esc in the TUI."""


class ConsoleOutput:
    def banner(self, model=None, sandbox=None):
        console.print(f"[dim]model: {MODEL if model is None else model}[/dim]")
        if not (SANDBOX if sandbox is None else sandbox):
            console.print("[red]WARNING: sandbox is OFF, commands run with your full permissions.[/red]")

    def check(self):                       # TUI: raises Cancelled after Esc
        pass

    def step(self, n, total):
        console.print(f"[dim]-- step {n}/{total}[/dim]")

    def model_start(self, step):
        pass

    def token(self, text):
        console.out(text, end="", style="green", highlight=False)

    def reply_end(self):
        console.print()

    def model_end(self):
        pass

    def tool_start(self, name, args):
        pass

    def tool_end(self, name, args, status, result):
        console.print(f"[dim]   {name}: {status}[/dim]")

    def notice(self, text, kind="info"):
        console.print(text, style="red" if kind == "error" else "dim")

    def final(self, text):
        console.print(f"\n{text}", style="green", markup=False)

    def context(self, used, total):
        pass
