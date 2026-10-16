import os
import sys

from rich.console import Console

console = Console()


def _start(args: list) -> None:
    from agent import config, setup

    if args[:1] == ["--setup"]:
        setup.run_wizard()
        return

    if config.needs_setup() and sys.stdin.isatty():
        if not setup.run_wizard():
            return
        # Restart so every module loads the newly saved settings.
        os.execv(sys.executable, [sys.executable, *sys.argv])

    from agent import memory
    from agent.core import run
    from agent.model import ModelError

    if args[:1] == ["--notes"]:
        memory.show_notes()
        return
    try:
        task = " ".join(args) or console.input("[bold cyan]Task: [/bold cyan]")
        run(task)
    except ModelError as e:
        console.print(f"[red]Error:[/red] {e}")


def main() -> None:
    try:
        _start(sys.argv[1:])
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Cancelled.[/yellow]")


if __name__ == "__main__":
    main()
