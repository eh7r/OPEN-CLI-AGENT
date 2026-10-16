import sys

from rich.console import Console
from rich.markup import escape

console = Console()


def confirm(description: str) -> tuple[bool, str]:
    """Ask the user to approve an action. Returns (allowed, message for the model)."""
    if not sys.stdin.isatty():
        return False, "Error: approval is needed but there is no interactive terminal."
    console.print(f"[yellow][PERMISSION][/yellow] {escape(description)}")
    answer = console.input("Allow? [y/N] ").strip().lower()
    if answer in ("y", "yes"):
        return True, ""
    return False, "Error: the user declined this action. It was NOT performed, so there is no result from it. Do not retry it or try another way; tell the user it was declined."
