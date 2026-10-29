"""Approval box: sits above the input, the rest of the interface stays alive."""
from rich.text import Text
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Static

from agent.tui_parts import BG, G2, G3, GB, W

APPROVAL_CSS = f"""
ApprovalBox {{ height: auto; border: solid {W}; background: {BG}; padding: 1 2; margin-top: 1; }}
#ap-body {{ height: auto; }}
#ap-btns {{ height: 3; margin-top: 1; }}
#ap-btns Button {{ min-width: 14; height: 3; margin-right: 2; border: solid {GB};
                  background: {BG}; color: {G2}; }}
#ap-btns Button:focus {{ border: solid {W}; color: {W}; text-style: bold; }}
#ap-keys {{ height: 1; }}
"""


class ApprovalBox(Vertical):
    """y = allow, n / esc = deny, arrows move, enter presses the focused button.
    Focus starts on Deny, so an accidental Enter never allows anything."""

    BINDINGS = [
        Binding("y", "answer(True)", show=False),
        Binding("n", "answer(False)", show=False),
        Binding("escape", "answer(False)", show=False),
        Binding("left,up", "app.focus_previous", show=False),
        Binding("right,down", "app.focus_next", show=False),
    ]

    class Answered(Message):
        def __init__(self, ok: bool):
            super().__init__()
            self.ok = ok

    def __init__(self, description, workdir):
        super().__init__()
        self.description = description
        self.workdir = workdir

    def compose(self):
        body = Text()
        body.append("Allow this action?\n\n", style=f"bold {W}")
        body.append(self.description + "\n\n", style=W)
        body.append("in  ", style=G3)
        body.append(self.workdir, style=G2)
        keys = Text()
        keys.append("y", style=f"bold {W}")
        keys.append(" allow · ", style=G3)
        keys.append("n", style=f"bold {W}")
        keys.append(" deny · ", style=G3)
        keys.append("←→", style=f"bold {W}")
        keys.append(" choose · ", style=G3)
        keys.append("enter", style=f"bold {W}")
        keys.append(" confirm", style=G3)
        yield Static(body, id="ap-body")
        with Horizontal(id="ap-btns"):
            yield Button("Allow", id="allow")
            yield Button("Deny", id="deny")
        yield Static(keys, id="ap-keys")

    def on_mount(self):
        self.query_one("#deny", Button).focus()

    def on_button_pressed(self, event: Button.Pressed):
        event.stop()
        self.post_message(self.Answered(event.button.id == "allow"))

    def action_answer(self, ok: bool):
        self.post_message(self.Answered(ok))
