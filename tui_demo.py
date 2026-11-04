#!/usr/bin/env python3
"""OPEN CLI AGENT - TUI demo (fake events, nothing is wired to the core yet).

Identity: white + grey only, square borders, pixel blocks, and the "decrypt"
effect from the startup logo (thinking, progress edge, streaming replies).
Rule: grey box = information, white box = where YOU act.

Run:   python tui_demo.py
Keys:  enter send | esc interrupt | F1 help | ctrl+l clear | ctrl+q quit
Try:   any text (fake task), /help /clear /new /context /model /exit
"""
import asyncio
import math
import random
import shutil
import string
import time

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Input, Static

from agent.logo import GLYPHS, RESET, WHITE as ANSI_WHITE, Decrypt, layout, pick_style

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
CTX_TOTAL = 4096

# model tiers (same three tiers as the project) and device detection
TIERS = {"gemma4:e2b": 0, "gemma4:e4b": 1, "gpt-oss:20b": 2}


def device_tier():
    """Demo thresholds by RAM; later this comes from agent/config.py."""
    try:
        import psutil
        gb = psutil.virtual_memory().total / 2 ** 30
    except Exception:
        gb = 8
    return (2 if gb >= 24 else 1 if gb >= 12 else 0), gb


def fit_color(model_tier, dev_tier):
    if model_tier > dev_tier:
        return RED          # stronger than the device
    if model_tier < dev_tier:
        return YELLOW       # weaker than the device
    return W                # fits


def _rgb(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def lerp(a, b, t):
    ra, rb = _rgb(a), _rgb(b)
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(ra, rb))


def glyph(a, b):
    """Deterministic scramble glyph (same family as the startup logo)."""
    return GLYPHS[(a * 73856093 ^ b * 2654435761) % len(GLYPHS)]


def logo_rows(cols):
    """-> (style key, rows). Same logo as the startup animation, final frame."""
    style = pick_style(max(cols - 4, 0), 99)
    items, nrows, _ = layout(style)
    rows = ["".join(" " * it[1] if it[0] == "gap" else it[2][r] for it in items)
            for r in range(nrows)]
    return style, rows


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


class Live(Static):
    """A block that animates itself until stop() / interrupt()."""

    def __init__(self, classes=""):
        super().__init__("", classes=classes)
        self.live = True
        self.timer = None
        self.t0 = time.monotonic()

    def on_mount(self):
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
        return t

    def done(self):
        self.stop(Text.assemble(("▪ thought", G2), (f" · {self.elapsed():.1f}s", G3)))


class ActionLog(Live):
    """Everything the agent does in one task: one row per action."""

    BAR = 12

    def __init__(self):
        super().__init__("actions")
        self.rows = []

    def start(self, verb, target):
        row = {"verb": verb, "target": target, "state": "run",
               "t0": time.monotonic(), "dt": 0.0, "info": "", "pct": None}
        self.rows.append(row)
        if self.is_mounted:
            self._advance()
        return row

    def progress(self, row, pct):
        row["pct"] = pct

    def finish(self, row, info):
        row.update(state="ok", info=info, pct=None, dt=time.monotonic() - row["t0"])

    def end(self):
        for r in self.rows:
            if r["state"] == "run":
                r.update(state="stop", info="interrupted", pct=None,
                         dt=time.monotonic() - r["t0"])
        self.stop(self.paint(self.elapsed()))

    interrupt = end

    def paint(self, el):
        avail = max(self.size.width - 4, 36)
        out = Text(no_wrap=True)
        for n, r in enumerate(self.rows):
            run = r["state"] == "run"
            dt = (time.monotonic() - r["t0"]) if run else r["dt"]
            if run:
                g = PIX[int(el * 8) % 4]
                right = (f"{r['pct']}% · " if r["pct"] is not None else "") + f"{dt:.1f}s"
            else:
                g = "✓" if r["state"] == "ok" else "■"
                right = (r["info"] + " · " if r["info"] else "") + f"{dt:.1f}s"
            bar = run and r["pct"] is not None
            room = avail - 8 - len(right) - (self.BAR + 1 if bar else 0) - 1
            target = r["target"]
            if len(target) > max(room, 4):
                target = target[:max(room, 4) - 1] + "…"
            pad = max(avail - 8 - len(target) - (self.BAR + 1 if bar else 0) - len(right), 1)
            if n:
                out.append("\n")
            out.append(g + " ", style=W if r["state"] != "stop" else G2)
            out.append(f"{r['verb']:<6}", style=f"bold {W}")
            out.append(target, style=G1)
            if bar:
                out.append(" ")
                filled = int(self.BAR * r["pct"] / 100)
                step = int(el * 18)
                for i in range(self.BAR):
                    if i < filled:
                        out.append("█", style=lerp(G3, W, i / (self.BAR - 1)))
                    elif i < filled + 2:
                        out.append(glyph(i, step), style=G2)     # decrypting edge
                    else:
                        out.append("░", style=G4)
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
    ("/model", "show or switch model"),
    ("/exit", "save and quit"),
])
KEYS = box_lines([
    ("enter", "send"),
    ("esc", "interrupt"),
    ("F1", "help"),
    ("ctrl+l", "clear"),
    ("ctrl+q", "quit now"),
])
LS_OUTPUT_LINES = 6
REPLY = ("I listed the folder and created main.py with a small hello script. "
         "Run it with: python main.py")
IDLE_HINT = Text("/ commands · F1 help · ctrl+q quit", style=G3)
STATE_LABEL = {"analyzing": "Analyzing request", "thinking": "Thinking",
               "executing": "Executing", "replying": "Replying"}

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
"""


class DemoApp(App):
    CSS = CSS
    BINDINGS = [
        Binding("escape", "interrupt", "Interrupt", show=False),
        Binding("f1", "help", "Help", show=False),
        Binding("ctrl+l", "clear", "Clear", show=False),
    ]

    def __init__(self):
        super().__init__()
        self.working = False
        self.started = False
        self.state = "idle"
        self.model = "gemma4:e4b"
        self.dev_tier, self.ram_gb = device_tier()
        self.used = 300
        self.session_title = ""
        self.session_id = self._new_id()
        self._active = []
        self._pulse = None

    @staticmethod
    def _new_id():
        return "ses_" + "".join(random.choices(string.ascii_letters + string.digits, k=24))

    # ----- layout
    def compose(self) -> ComposeResult:
        with Horizontal(id="top"):
            yield Static(COMMANDS, classes="panel", id="p1")
            yield Static(KEYS, classes="panel", id="p2")
        yield Logo()
        yield GlowRule(id="rule")
        yield Static("", id="status")
        yield VerticalScroll(id="chat")
        with Vertical(id="inputwrap"):
            with Horizontal(id="box"):
                yield Static(">", id="prompt")
                yield Input(placeholder="Type a message…", id="inp")
            yield Static("", id="modeline")
        with Horizontal(id="bar"):
            yield Static(IDLE_HINT, id="hint")
            yield Static("", id="ctx")

    def on_mount(self):
        self.query_one("#p1").border_title = "Commands"
        self.query_one("#p2").border_title = "Keys"
        self.note("Try: list the files here and create a hello script")
        self.update_status()
        self.update_ctx()
        self.paint_state()
        self.query_one(Input).focus()
        self.fit()

    def on_resize(self, event: events.Resize):
        self.fit()

    def fit(self):
        try:
            self.query_one("#top").display = (not self.started) and self.size.height >= 30
        except Exception:
            pass

    @property
    def chat(self):
        return self.query_one("#chat", VerticalScroll)

    # ----- model line (dot = does the model fit this device?)
    def update_status(self):
        col = fit_color(TIERS.get(self.model, 1), self.dev_tier)
        t = Text.assemble(("● ", col), ("ollama: ", G2), (self.model, f"bold {W}"),
                          ("  · /model to switch", G3))
        if col == RED:
            t.append("  · heavier than this device", style=G3)
        elif col == YELLOW:
            t.append("  · lighter than this device can run", style=G3)
        self.query_one("#status", Static).update(t)

    # ----- agent state (the core will call set_state from its real events)
    def set_state(self, state):
        self.state = state
        self.paint_state()

    def paint_state(self):
        if self.state == "idle":
            t = Text.assemble(("▪ ", G3), ("Waiting for input…", G2))
        else:
            now = time.monotonic()
            t = Text()
            t.append(PIX[int(now * 8) % 4] + " ", style=W)
            t.append(STATE_LABEL[self.state], style=f"bold {W}")
            t.append(("." * (int(now * 3) % 4)).ljust(3), style=G2)
        self.query_one("#modeline", Static).update(t)

    def update_ctx(self):
        pct = min(self.used / CTX_TOTAL, 1.0)
        style = G1 if pct < 0.70 else f"bold {W}" if pct < 0.85 else f"bold reverse {W}"
        n = round(pct * 8)
        t = Text.assemble((f"{self.used / 1000:.1f}k/{CTX_TOTAL / 1000:.0f}k ", G2),
                          ("█" * n, style), ("░" * (8 - n), G4),
                          (f" {pct * 100:.0f}%", style))
        if pct >= 0.85:
            t.append(" FULL ", style=f"bold reverse {W}")
        self.query_one("#ctx", Static).update(t)

    # ----- helpers
    async def add(self, w):
        await self.chat.mount(w)
        if isinstance(w, Live):
            self._active.append(w)
        self.chat.scroll_end(animate=False)
        return w

    def note(self, text, style=G3):
        self.chat.mount(Static(Text(text, style=style), classes="note"))
        self.chat.scroll_end(animate=False)

    def set_working(self, on):
        self.working = on
        if on:
            self._pulse = self.set_interval(1 / 20, self._pulse_tick)
        else:
            if self._pulse:
                self._pulse.stop()
                self._pulse = None
            self.query_one("#box").styles.border = ("solid", W)
            self.query_one("#hint", Static).update(IDLE_HINT)
            self.set_state("idle")

    def _pulse_tick(self):
        t = time.monotonic()
        k = (math.sin(t * 4) + 1) / 2
        self.query_one("#box").styles.border = ("solid", lerp("#6a6a6a", W, k))
        p = int(t * 14) % 14
        pos = p if p <= 7 else 14 - p
        hint = Text()
        for i in range(8):
            near = abs(i - pos) <= 1
            hint.append("▪" if near else "·", style=W if near else G4)
        hint.append("  ")
        hint.append("esc", style=f"bold {W}")
        hint.append(" interrupt", style=G3)
        self.query_one("#hint", Static).update(hint)
        self.paint_state()

    # ----- input
    def on_input_submitted(self, event: Input.Submitted):
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text.startswith("/"):
            return self.command(text)
        if self.working:
            return self.note("Still working — press esc to interrupt.", G2)
        if not self.started:
            self.started = True
            self.session_title = text[:40]
            self.fit()
        self.chat.mount(Static(Text.assemble(("> ", f"bold {W}"), (text, W)), classes="user"))
        self.run_worker(self.fake_task(), exclusive=True)

    def command(self, text):
        parts = text.split()
        cmd = parts[0]
        if cmd == "/exit":
            self.exit()
        elif cmd == "/clear":
            self.action_clear()
        elif cmd == "/new":
            self.action_clear()
            self.started = False
            self.used = 300
            self.session_title = ""
            self.session_id = self._new_id()
            self.update_ctx()
            self.fit()
        elif cmd == "/help":
            self.action_help()
        elif cmd == "/context":
            self.note(f"Context: {self.used}/{CTX_TOTAL} tokens", G1)
        elif cmd == "/fill":
            self.used = 3600
            self.update_ctx()
        elif cmd == "/model":
            if len(parts) == 1:
                self.note("models: " + " · ".join(TIERS) + f" · now: {self.model}", G1)
            elif parts[1] in TIERS:
                self.model = parts[1]
                self.update_status()
            else:
                self.note(f"unknown model: {parts[1]}", G2)
        else:
            self.note(f"unknown command: {cmd} · /help", G2)

    def action_help(self):
        self.note("/help /clear /new /context /model /exit", G1)

    def action_clear(self):
        self.chat.remove_children()

    def action_interrupt(self):
        if self.working:
            self.workers.cancel_all()

    # ----- fake task (the core's real events replace this later)
    async def fake_task(self):
        t0 = time.monotonic()
        self.set_working(True)
        try:
            self.set_state("analyzing")
            await asyncio.sleep(0.9)

            self.set_state("thinking")
            th = await self.add(ThinkingLine())
            await asyncio.sleep(1.8)
            th.done()

            self.set_state("executing")
            log = await self.add(ActionLog())
            log.border_title = "Actions"
            r = log.start("run", "ls -la ~/Project/playground")
            await asyncio.sleep(1.3)
            log.finish(r, f"{LS_OUTPUT_LINES} lines")
            r = log.start("write", "main.py")
            for p in range(0, 101, 2):
                log.progress(r, p)
                await asyncio.sleep(0.04)
            log.finish(r, "42 lines")
            r = log.start("run", "python main.py")
            await asyncio.sleep(0.9)
            log.finish(r, "1 line")
            log.end()

            self.set_state("replying")
            reply = Static("", classes="reply")
            await self.add(reply)
            step = 0
            for i in range(0, len(REPLY) + 1, 2):
                trail = "".join(glyph(i + k, step) for k in range(min(3, len(REPLY) - i)))
                reply.update(Text.assemble((REPLY[:i], G1), (trail, G3)))
                self.chat.scroll_end(animate=False)
                step += 1
                await asyncio.sleep(0.02)
            reply.update(Text(REPLY, style=G1))

            self.used += 620
            self.update_ctx()
            self.note(f"▪ worked {time.monotonic() - t0:.0f}s")
            if self.used >= CTX_TOTAL * 0.85:
                self.note("Context is almost full — open a new session with /new", W)
        except asyncio.CancelledError:
            for w in self._active:
                w.interrupt()
            self.note("■ interrupted", G2)
            raise
        finally:
            self._active.clear()
            self.set_working(False)


def exit_screen(title, sid):
    cols = shutil.get_terminal_size((80, 24)).columns
    _, rows = logo_rows(cols)
    print()
    for r in rows:
        print("  " + ANSI_WHITE + r + RESET)
    print()
    print(f"  \033[2mSession \033[0m  \033[1m{title}\033[0m")
    print(f"  \033[2mContinue\033[0m  \033[1magent -s {sid}\033[0m")
    print()


if __name__ == "__main__":
    app = DemoApp()
    app.run()
    if app.session_title:
        exit_screen(app.session_title, app.session_id)
