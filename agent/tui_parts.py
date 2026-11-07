"""Look of the interface: palette, widgets, texts and CSS (the app is in tui.py)."""
import math
import time

from rich.text import Text
from textual import events
from textual.widget import Widget
from textual.widgets import Static

from agent import config
from agent.events import Cancelled
from agent.logo import GLYPHS, Decrypt, layout, pick_style

# ---------------------------------------------------------------- palette
BG = "#0c0c0c"
W = "#f2f2f2"      # white   : input, names, active things
G1 = "#bdbdbd"     # light grey (body text)
G2 = "#8a8a8a"     # grey (secondary)
G3 = "#5c5c5c"     # dark grey (hints)
GB = "#4a4a4a"     # grey box borders
G4 = "#333333"     # empty cells
RED, YELLOW = "#ff5f5f", "#ffd75f"     # only used by the model-fit dot
PIX = "▖▘▝▗"       # pixel spinner

ORDER = {"low": 0, "mid": 1, "high": 2}


def model_tier():
    for key, name in config.TIERS.items():
        if name == config.MODEL:
            return ORDER[key]
    return ORDER[config.TIER]


def fit_color():
    m, d = model_tier(), ORDER[config.detect_tier()]
    if m > d:
        return RED          # stronger than the device
    if m < d:
        return YELLOW       # weaker than the device
    return W                # fits


def _rgb(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def lerp(a, b, t):
    ra, rb = _rgb(a), _rgb(b)
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(ra, rb))


def grad(stops, t):
    n = len(stops) - 1
    i = min(int(t * n), n - 1)
    return lerp(stops[i], stops[i + 1], t * n - i)


def glyph(a, b):
    """Deterministic scramble glyph (same family as the startup logo)."""
    return GLYPHS[(a * 73856093 ^ b * 2654435761) % len(GLYPHS)]


def logo_rows(cols):
    style = pick_style(max(cols - 4, 0), 99)
    items, nrows, _ = layout(style)
    rows = ["".join(" " * it[1] if it[0] == "gap" else it[2][r] for it in items)
            for r in range(nrows)]
    return style, rows


VERBS = {"terminal": "run", "read_file": "read", "write_file": "write", "list_dir": "list",
         "git_status": "git", "git_diff": "git", "git_commit": "git",
         "remember": "remember", "forget": "forget"}


def describe(name, args):
    """-> (verb, target) for one row of the Actions box."""
    verb = VERBS.get(name, name)
    target = ""
    for key in ("command", "path", "file_path", "filename", "file", "message", "text", "note", "key"):
        if args.get(key):
            target = str(args[key])
            break
    else:
        target = str(next(iter(args.values()), "")) if args else ""
    if name.startswith("git_"):
        target = f"{name[4:]} {target}".strip()
    return verb, " ".join(target.split())


# ---------------------------------------------------------------- widgets
class Logo(Static):
    """Plays the decrypt animation once on start, then stays as the static logo."""

    def __init__(self):
        super().__init__("", id="logo")
        self._key = None
        self._anim = Decrypt()
        self._t0 = None
        self._timer = None

    def on_mount(self):
        self._t0 = time.monotonic()
        self._timer = self.set_interval(1 / 25, self._play)

    def _static(self, width):
        key, rows = logo_rows(width)
        self._key = key
        self.update(Text("\n".join(rows), style=f"bold {W}", no_wrap=True))

    def _play(self):
        t = time.monotonic() - self._t0
        width = self.size.width
        if width <= 0:
            return
        if t >= self._anim.done_at + 0.1:
            self._timer.stop()
            self._timer = None
            self._static(width)
            return
        cols = max(width - 4, 0)
        style = pick_style(cols, 99)
        pad = max(0, (cols - layout(style)[2]) // 2)
        lines = [ln[pad:] for ln in self._anim.frame(t, cols, 99)]
        self.update(Text.from_ansi("\n".join(lines)))

    def on_resize(self, event: events.Resize):
        if self._timer is None:
            key, _ = logo_rows(event.size.width)
            if key != self._key:
                self._static(event.size.width)


class GlowRule(Widget):
    """White line with a soft neon glow sweeping left to right."""

    def on_mount(self):
        self.set_interval(1 / 24, self.refresh)

    def render(self):
        w = max(self.size.width, 1)
        span = 9.0
        pos = (time.monotonic() * 24) % (w + 4 * span) - 2 * span
        t = Text(no_wrap=True)
        for i in range(w):
            d = (i - pos) / span
            k = math.exp(-d * d * 1.6)
            t.append("━", style=("bold " if k > 0.55 else "") + lerp("#2a2a2a", "#ffffff", k))
        return t


class CopyToast(Widget):
    """Top-right '| Copied to clipboard' with a glowing rule under it."""

    TEXT = "| Copied to clipboard"

    def __init__(self):
        super().__init__(id="copytoast")
        self.display = False
        self._timer = None

    def compose(self):
        yield Static(Text(self.TEXT, style="bold " + W), id="copytext")
        yield GlowRule()

    def show(self):
        self.display = True
        if self._timer:
            self._timer.stop()
        self._timer = self.set_timer(1.5, self.hide)

    def hide(self):
        self.display = False


class Live(Static):
    """A block that animates itself until stop() / interrupt()."""

    def __init__(self, classes=""):
        super().__init__("", classes=classes)
        self.live = True
        self.timer = None
        self.t0 = time.monotonic()

    def on_mount(self):
        if not self.live:
            return
        self.timer = self.set_interval(1 / 20, self._advance)
        self._advance()

    def elapsed(self):
        return time.monotonic() - self.t0

    def _advance(self):
        if self.live:
            self.update(self.paint(self.elapsed()))

    def stop(self, final):
        if self.live:
            self.live = False
            if self.timer:
                self.timer.stop()
            self.update(final)

    def interrupt(self):
        self.stop(Text.assemble(("■ ", W), ("interrupted", G2)))


class ThinkingLine(Live):
    """'thinking' decrypts letter by letter, then scrambles again (loop)."""

    LABEL = "thinking"
    WAIT_NOTICE = 30

    def __init__(self):
        super().__init__("thinking")

    def paint(self, el):
        cyc = el % 2.6
        step = int(el * 13)
        t = Text(no_wrap=True)
        t.append("▪ ", style=W)
        for i, ch in enumerate(self.LABEL):
            lock = 0.25 + i * 0.14
            if cyc >= lock:
                t.append(ch, style=f"bold {W}" if cyc - lock < 0.25 else G1)
            else:
                t.append(glyph(i, step), style=G3 if lock - cyc > 0.5 else G2)
        t.append(f"  {el:.1f}s", style=G3)
        if el >= self.WAIT_NOTICE:
            t.append("  · still waiting for the model (Esc to cancel)", style=G2)
        return t

    def done(self):
        self.stop(Text.assemble(("▪ thought", G2), (f" · {self.elapsed():.1f}s", G3)))


class ActionLog(Live):
    """Everything the agent does in one task: one row per real tool call."""

    def __init__(self):
        super().__init__("actions")
        self.rows = []

    def on_mount(self):
        self.border_title = "Actions"

    def start(self, verb, target):
        row = {"verb": verb, "target": target, "state": "run",
               "t0": time.monotonic(), "dt": 0.0, "info": ""}
        self.rows.append(row)
        if self.is_mounted:
            self._advance()
        return row

    def finish(self, row, info, ok=True):
        row.update(state="ok" if ok else "fail", info=info, dt=time.monotonic() - row["t0"])
        if self.is_mounted:
            self._advance()

    def end(self):
        for r in self.rows:
            if r["state"] == "run":
                r.update(state="stop", info="interrupted", dt=time.monotonic() - r["t0"])
        self.stop(self.paint(self.elapsed()))

    interrupt = end

    def paint(self, el):
        avail = max(self.size.width - 4, 36)
        out = Text(no_wrap=True)
        for n, r in enumerate(self.rows):
            run = r["state"] == "run"
            dt = (time.monotonic() - r["t0"]) if run else r["dt"]
            if run:
                g, right = PIX[int(el * 8) % 4], f"{dt:.1f}s"
            else:
                g = {"ok": "✓", "fail": "✗"}.get(r["state"], "■")
                right = (r["info"] + " · " if r["info"] else "") + f"{dt:.1f}s"
            room = max(avail - 8 - len(right) - 1, 4)
            target = r["target"]
            if len(target) > room:
                target = target[:room - 1] + "…"
            pad = max(avail - 8 - len(target) - len(right), 1)
            if n:
                out.append("\n")
            out.append(g + " ", style=W if r["state"] in ("run", "ok") else G2)
            out.append(f"{r['verb']:<6}", style=f"bold {W}")
            out.append(target, style=G1)
            out.append(" " * pad)
            out.append(right, style=G3)
        return out


# ---------------------------------------------------------------- app
def box_lines(rows):
    return "\n".join(f"[bold {W}]{a:<10}[/][{G2}]{b}[/]" for a, b in rows)


COMMANDS = box_lines([
    ("/help", "show commands"),
    ("/clear", "clear the screen"),
    ("/new", "start a new session"),
    ("/context", "context usage"),
    ("/model", "model and device fit"),
    ("/notes", "show saved notes"),
    ("/sessions", "list saved sessions"),
    ("/exit", "quit"),
])
KEYS = box_lines([
    ("enter", "send"),
    ("esc", "interrupt"),
    ("F1", "help"),
    ("ctrl+l", "clear"),
    ("ctrl+q", "quit now"),
])
IDLE_HINT = Text("/ commands · F1 help · ctrl+q quit", style=G3)
STATE_LABEL = {"analyzing": "Analyzing request", "thinking": "Thinking",
               "executing": "Executing", "replying": "Replying",
               "approval": "Waiting for your approval", "stopping": "Stopping"}

CSS = f"""
Screen {{ background: {BG}; color: {G1}; }}
#top {{ height: 9; padding: 1 2 0 2; }}
.panel {{ width: 1fr; height: 100%; border: solid {GB}; padding: 0 1;
         color: {G2}; border-title-color: {W}; border-title-style: bold; }}
#p1 {{ margin-right: 1; }}
#logo {{ height: auto; padding: 1 2 0 2; }}
#rule {{ height: 1; margin: 1 2 0 2; }}
#status {{ height: 1; padding: 0 2; margin-top: 1; }}
#chat {{ height: 1fr; padding: 0 2; scrollbar-size-vertical: 1;
        scrollbar-color: {G4}; scrollbar-background: {BG}; }}
.user {{ width: 100%; border: solid {GB}; padding: 0 1; margin-top: 1; }}
.approve {{ width: 100%; border: solid {W}; padding: 0 1; margin-top: 1; }}
.actions {{ width: 100%; border: solid {GB}; padding: 0 1; margin-top: 1;
           border-title-color: {W}; border-title-style: bold; }}
.thinking {{ width: 100%; padding: 0 1; margin-top: 1; }}
.reply {{ width: 100%; padding: 0 1; margin-top: 1; color: {G1}; }}
.note {{ width: 100%; padding: 0 1; margin-top: 1; color: {G3}; }}
#inputwrap {{ height: auto; padding: 0 2; }}
#box {{ height: 3; border: solid {W}; padding: 0 1; margin-top: 1; }}
#prompt {{ width: 2; color: {W}; text-style: bold; }}
Input {{ width: 1fr; border: none; background: transparent; padding: 0; height: 1; }}
Input:focus {{ border: none; background: transparent; }}
Input > .input--placeholder {{ color: {G3}; }}
#modeline {{ height: 1; padding: 0 1; }}
#bar {{ height: 1; padding: 0 2; }}
#hint {{ width: 1fr; }}
#ctx {{ width: auto; }}
Screen {{ layers: base overlay; }}
#copytoast {{ layer: overlay; dock: top; width: 100%; height: 2; align-horizontal: right; }}
#copytext {{ width: 26; height: 1; }}
#copytoast GlowRule {{ width: 26; height: 1; margin: 0; }}
Screen > .screen--selection {{ background: #ffffff; color: #000000; }}
Input > .input--selection {{ background: #ffffff; color: #000000; }}
"""


class TuiOutput:
    """What the core calls while a task runs (in a worker thread)."""

    def __init__(self, app):
        self.app = app

    def _ui(self, fn, *args):
        self.app.call_from_thread(fn, *args)

    def banner(self, model=None, sandbox=None):
        pass

    def check(self):
        if self.app.cancel_flag.is_set():
            raise Cancelled()

    def step(self, n, total):
        pass

    def model_start(self, step):
        self._ui(self.app.ui_model_start, step)

    def token(self, text):
        self.check()
        self._ui(self.app.ui_token, text)

    def reply_end(self):
        self._ui(self.app.ui_reply_end)

    def model_end(self):
        self._ui(self.app.ui_model_end)

    def tool_start(self, name, args):
        self._ui(self.app.ui_tool_start, name, args)

    def tool_end(self, name, args, status, result):
        self._ui(self.app.ui_tool_end, status, result)

    def notice(self, text, kind="info"):
        self._ui(self.app.note, text.strip(), W if kind == "error" else G2)

    def final(self, text):
        self._ui(self.app.ui_final, text)

    def context(self, used, total):
        self._ui(self.app.ui_ctx, used)
