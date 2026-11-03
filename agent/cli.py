"""Command line entry: one task (agent "task") or an interactive session (agent)."""
import os
import sys
import threading

from rich.console import Console
from rich.markup import escape

try:  # arrow keys and history in the prompt (Linux/macOS)
    import readline  # noqa: F401
except ImportError:
    pass

console = Console()

EXIT_WORDS = {"exit", "quit", "/exit", "/quit", ":q"}


def _one_shot(task: str) -> None:
    from agent import core
    from agent.model import ModelError

    try:
        core.run(task)
    except ModelError as e:
        console.print(f"[red]Error:[/red] {e}")


def _save(session, task, messages):
    """Write the session file after a finished task; a failure never stops the agent."""
    from agent import sessions

    try:
        if session is None:
            session = sessions.create(task, messages, os.getcwd())
        sessions.update(session, messages)
    except (OSError, ValueError, TypeError):
        pass
    return session


def _bye(session) -> None:
    if session:
        console.print(f"[dim]Session[/dim]  {escape(session['title'])}")
        console.print(f"[dim]Continue[/dim] agent -s {session['id']}")


def _find_session(args: list):
    from agent import sessions

    if args[0] == "-c":
        found = sessions.last()
        if found is None:
            console.print("[yellow]No saved sessions yet.[/yellow]")
        return found
    if len(args) < 2:
        console.print("[yellow]Usage: agent -s <session id>[/yellow]")
        return None
    found = sessions.load(args[1])
    if found is None:
        console.print(f"[red]Session not found:[/red] {escape(args[1])}")
    return found


def _plain_session(resume=None) -> None:
    from agent import core, model, tools

    core.banner()
    console.print("[dim]Type a task. Ctrl+D or 'exit' to quit, Ctrl+C cancels a running task.[/dim]")
    messages = core.new_session()
    session = None
    if resume:
        saved = resume["messages"]
        messages += saved[1:] if saved and saved[0].get("role") == "system" else saved
        session = resume
        console.print(f"[dim]Continuing: {escape(resume['title'])}[/dim]")
    threading.Thread(target=model.warm_up, args=(list(messages), tools.schemas()), daemon=True).start()

    while True:
        try:
            task = console.input("[bold cyan]> [/bold cyan]").strip()
        except EOFError:
            console.print()
            _bye(session)
            return
        except KeyboardInterrupt:
            console.print("\n[dim]Press Ctrl+D or type exit to quit.[/dim]")
            continue

        if not task:
            continue
        if task.lower() in EXIT_WORDS:
            _bye(session)
            return

        mark = len(messages)
        try:
            status = core.run(task, messages)
        except KeyboardInterrupt:
            del messages[mark:]
            console.print("\n[yellow]Cancelled.[/yellow]")
            continue
        except model.ModelError as e:
            del messages[mark:]
            console.print(f"[red]Error:[/red] {e}")
            continue

        if status != core.TOO_BIG:
            session = _save(session, task, messages)
        if status == core.TOO_BIG:
            del messages[mark:]
            if mark > 1:
                console.print("[yellow]This session is full. Start a new one by running agent again.[/yellow]")
                _bye(session)
                return


def _session(resume=None) -> None:
    """The full-screen interface when there is a real terminal, else the plain one."""
    if sys.stdin.isatty() and sys.stdout.isatty():
        try:
            from agent import tui
        except ImportError:
            console.print("[yellow]Textual is not installed (pip install textual); using the plain terminal.[/yellow]")
        else:
            tui.run(resume)
            return
    _plain_session(resume)


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

    if args[:1] == ["--notes"]:
        memory.show_notes()
        return
    if args[:1] == ["--plain"]:
        _plain_session()
        return
    resume = None
    if args[:1] in (["-c"], ["-s"]):
        resume = _find_session(args)
        if resume is None:
            return
        args = []
    if args:
        _one_shot(" ".join(args))
    else:
        _session(resume)


def main() -> None:
    try:
        _start(sys.argv[1:])
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Cancelled.[/yellow]")
