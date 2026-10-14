import sys

from rich.console import Console

from agent import memory
from agent.core import run
from agent.model import ModelError

console = Console()


def main() -> None:
    if sys.argv[1:2] == ["--notes"]:
        memory.show_notes()
        return
    try:
        task = " ".join(sys.argv[1:]) or console.input("[bold cyan]Task: [/bold cyan]")
        run(task)
    except ModelError as e:
        console.print(f"[red]Error:[/red] {e}")
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Cancelled.[/yellow]")


if __name__ == "__main__":
    main()
