import re
"""The full-screen interface of the agent (Textual).

White = where you act, grey = information. The core talks to this file only
through TuiOutput (agent/events.py has the plain-terminal twin).
"""
import math
import shutil
import os as _os
import threading

from agent import sessions
from agent.journal import Journal, Recording
from agent import handoff
import time

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, Static

from agent import approval, config, context, core, model, memory, rtl, tools
from agent.events import Cancelled
from agent.tui_approval import APPROVAL_CSS, ApprovalBox
from agent.logo import RESET, WHITE as ANSI_WHITE
from agent.tui_parts import (
    COMMANDS, CSS, CopyToast, G1, G2, G3, G4, GlowRule, IDLE_HINT, KEYS, Logo, ORDER, PIX, RED, STATE_LABEL,
    ActionLog, ThinkingLine, TuiOutput, W, YELLOW, describe, fit_color, glyph, lerp, logo_rows, model_tier,
)


_HAR = re.compile("[\u064B-\u065F\u0670]")
_AR = re.compile("[\u0600-\u06FF]")
_BUL = re.compile(r"(?m)^(\s*)[*-] ")


class AgentApp(App):
    CSS = CSS + APPROVAL_CSS
    BINDINGS = [
        Binding("escape", "interrupt", "Interrupt", show=False),
        Binding("ctrl+q", "quit", "Quit", show=False, priority=True),
        Binding("f1", "help", "Help", show=False),
        Binding("ctrl+l", "clear", "Clear", show=False),
    ]

    def __init__(self, resume=None):
        super().__init__()
        self.history = core.new_session()
        self.session = None
        self.journal = Journal()
        self.working = False
        self.started = False
        self.agent_state = "idle"
        self.cancel_flag = threading.Event()
        self.pending = None            # (box, done) while waiting for y/n
        self.used = 0
        self.auto_handoff = False
        self.session_title = ""
        if resume:
            saved = resume["messages"]
            rest = saved[1:] if saved and saved[0].get("role") == "system" else saved
            self.history = core.new_session() + rest
            self.session = resume
            self.journal = Journal(resume.get("journal"))
            self.session_title = resume["title"]
            self.started = True
        self._active = []
        self._pulse = None
        self.think = None
        self.actions = None
        self.row = None
        self.reply_w = None
        self.reply_text = ""
        self.first_token = False

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
        yield CopyToast()

    def copy_to_clipboard(self, text: str) -> None:
        super().copy_to_clipboard(text)
        self.query_one(CopyToast).show()

    def action_help_quit(self) -> None:
        pass

    def on_mount(self):
        self.query_one("#p1").border_title = "Commands"
        self.query_one("#p2").border_title = "Keys"
        approval.set_handler(self._approval_handler)
        self.warming = True
        threading.Thread(target=self._warm, daemon=True).start()
        if not config.SANDBOX:
            self.note("WARNING: sandbox is OFF, commands run with your full permissions.", W)
        self.used = context.estimate_tokens(self.history, tools.schemas())
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
    def _warm(self):
        model.warm_up(list(self.history), tools.schemas())
        try:
            self.call_from_thread(self.warm_done)
        except Exception:
            pass

    def warm_done(self):
        self.warming = False
        self.update_status()

    def update_status(self):
        col = fit_color()
        t = Text.assemble(("● ", col), ("ollama: ", G2), (config.MODEL, f"bold {W}"),
                          ("  · warming up, first reply is slow" if getattr(self, "warming", False)
                           else "  · /model for details", G3))
        if col == RED:
            t.append("  · heavier than this device", style=G3)
        elif col == YELLOW:
            t.append("  · lighter than this device can run", style=G3)
        self.query_one("#status", Static).update(t)

    # ----- agent state (driven by the core's real events)
    def set_agent_state(self, state):
        self.agent_state = state
        self.paint_state()

    def paint_state(self):
        if self.agent_state == "idle":
            t = Text.assemble(("▪ ", G3), ("Waiting for input…", G2))
        else:
            now = time.monotonic()
            t = Text()
            t.append(PIX[int(now * 8) % 4] + " ", style=W)
            t.append(STATE_LABEL[self.agent_state], style=f"bold {W}")
            t.append(("." * (int(now * 3) % 4)).ljust(3), style=G2)
        self.query_one("#modeline", Static).update(t)

    def update_ctx(self):
        total = config.CONTEXT_TOKENS
        pct = min(self.used / total, 1.0)
        style = G1 if pct < 0.70 else f"bold {W}" if pct < 0.85 else f"bold reverse {W}"
        n = round(pct * 8)
        t = Text.assemble((f"{self.used / 1000:.1f}k/{total / 1000:.0f}k ", G2),
                          ("█" * n, style), ("░" * (8 - n), G4),
                          (f" {pct * 100:.0f}%", style))
        if pct >= 0.85:
            t.append(" FULL ", style=f"bold reverse {W}")
        self.query_one("#ctx", Static).update(t)

    # ----- helpers
    def rtl_text(self, text, extra=0):
        """Arabic only: wrap to the chat width, then reshape and reorder."""
        w = self.chat.size.width - 3 - extra
        if w > 10 and _AR.search(text):
            text = _BUL.sub(r"\1• ", _HAR.sub("", text.replace("**", "")))
        return rtl.render(text, w) if w > 10 else text

    def rtl_stream(self, text, trail):
        """Arabic reply while streaming: the trail sits at the left edge of the last line."""
        shown = self.rtl_text(text)
        if shown == text:
            return None
        head, nl, last = shown.rpartition("\n")
        pad = len(last) - len(last.lstrip(" "))
        k = min(len(trail), pad)
        return Text.assemble((head + nl, G1), (trail[:k], G3), (last[k:], G1))

    def note(self, text, style=G3):
        self.chat.mount(Static(Text(self.rtl_text(text), style=style), classes="note"))
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
            self.set_agent_state("idle")

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

    def on_ready(self):
        if self.session is None:
            return
        self.fit()
        self.used = context.estimate_tokens(self.history, tools.schemas())
        self.update_ctx()
        self.note(f"Continuing: {self.session['title']}", G1)
        where = self.session.get("workdir")
        if where and where != _os.getcwd():
            self.note(f"Saved in {where}; you are in a different folder.", G2)

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
            self.session_title = sessions.make_title(text)
            self.fit()
        self.chat.mount(Static(Text.assemble(("> ", f"bold {W}"), (self.rtl_text(text, 4), W)), classes="user"))
        self.chat.scroll_end(animate=False)
        self.cancel_flag.clear()
        self.set_working(True)
        self.set_agent_state("analyzing")
        self.run_worker(lambda: self._work(text), thread=True, exclusive=True, exit_on_error=False)

    def command(self, text):
        cmd = text.split()[0]
        if cmd == "/exit":
            self.action_interrupt()
            self.exit()
        elif cmd == "/clear":
            self.action_clear()
        elif cmd == "/new":
            if self.working:
                return self.note("Wait for the task to finish (or press esc), then /new.", G2)
            self.action_clear()
            self.history = core.new_session()
            self.session = None
            self.journal = Journal()
            self.started = False
            self.auto_handoff = False
            self.session_title = ""
            self.used = context.estimate_tokens(self.history, tools.schemas())
            self.update_ctx()
            self.fit()
        elif cmd == "/handoff":
            self.start_handoff(copy=True)
        elif cmd == "/help":
            self.action_help()
        elif cmd == "/context":
            self.note(f"Context: {self.used}/{config.CONTEXT_TOKENS} tokens (estimate)", G1)
        elif cmd == "/model":
            names = {v: k for k, v in ORDER.items()}
            self.note(f"{config.MODEL} · model tier: {names[model_tier()]} · "
                      f"this device: {config.detect_tier()}", G1)
        elif cmd == "/notes":
            rows = memory.list_notes()
            if not rows:
                return self.note("No saved notes.", G2)
            for note_id, label, text in rows:
                self.note(f"#{note_id} [{label}] {text}", G1)
        elif cmd == "/sessions":
            items = [x for x in sessions.list_all() if x.get("title")][:10]
            if not items:
                return self.note("No saved sessions.", G2)
            for x in items:
                when = str(x.get("updated", ""))[:16].replace("T", " ")
                self.note(f"{x['id']}  {when}  {x.get('workdir', '')}", G1)
                self.note("  " + self.rtl_text(x["title"], 2), G2)
            self.note("Continue with: openagent -s <id>", G2)
        elif cmd == "/setup":
            names = {v: k for k, v in ORDER.items()}
            lines = [
                ("Current settings", G1),
                (f"  model:    {config.MODEL} · tier: {names[model_tier()]}", G1),
                (f"  config:   {config.CONFIG_PATH}", G1),
                (f"  memory:   {config.MEMORY_DB}", G1),
                ("", G2),
                ("To change the model tier: quit (ctrl+q), then run", G2),
                ("  openagent --setup", G1),
                ("To use a model for one run only:", G2),
                ("  AGENT_MODEL=<model> openagent", G1),
                ("  AGENT_TIER=<low|mid|high> openagent", G1),
                ("Environment variables override the saved setup.", G2),
            ]
            for line, color in lines:
                self.note(line, color)
        else:
            self.note(f"unknown command: {cmd} · /help", G2)

    def action_help(self):
        self.note("/help /clear /new /context /model /notes /sessions /setup /handoff /exit", G1)

    def action_clear(self):
        self.chat.remove_children()

    def action_quit(self):
        self.action_interrupt()
        self.exit()

    def action_interrupt(self):
        if self.working:
            self.cancel_flag.set()
            self.set_agent_state("stopping")

    # ----- approval (the core asks, you answer y / n in the input box)
    def _approval_handler(self, description):
        """Runs in the worker thread: blocks until you answer."""
        box, done = {}, threading.Event()
        self.call_from_thread(self.show_approval, description, box, done)
        done.wait()
        if box.get("ok"):
            return True, ""
        return False, approval.DECLINED

    def show_approval(self, description, box, done):
        self.pending = (box, done)
        self.set_agent_state("approval")
        inp = self.query_one(Input)
        inp.disabled = True
        self.approval_box = ApprovalBox(description, config.WORKDIR)
        self.query_one("#inputwrap").mount(self.approval_box, before="#box")
        self.chat.scroll_end(animate=False)

    def on_approval_box_answered(self, message):
        message.stop()
        if getattr(self, "approval_box", None) is not None:
            self.approval_box.remove()
            self.approval_box = None
        self.query_one(Input).disabled = False
        self.query_one(Input).focus()
        self.resolve_approval(message.ok)

    def resolve_approval(self, ok):
        if self.pending is None:
            return
        box, done = self.pending
        self.pending = None
        box["ok"] = ok
        done.set()
        self.note("✓ allowed" if ok else "■ declined", G2)
        self.set_agent_state("executing" if ok else "thinking")

    # ----- worker thread
    def _work(self, text):
        t0 = time.monotonic()
        mark = len(self.history)
        cancelled, err, note = False, None, None
        outcome, why = "done", ""
        self.journal.begin(text)
        try:
            status = core.run(text, self.history, out=Recording(TuiOutput(self), self.journal))
            if status == core.TOO_BIG:
                del self.history[mark:]
                outcome = "full"
                note = "This session is full. Type /new to start a new one."
            elif status == core.STOPPED:
                outcome, why = "error", "stopped: repeated blocked calls or step limit"
        except Cancelled:
            del self.history[mark:]
            cancelled = True
            outcome = "cancelled"
        except model.ModelError as e:
            del self.history[mark:]
            err = str(e)
            outcome, why = "error", err
        except Exception as e:
            del self.history[mark:]
            err = f"{type(e).__name__}: {e}"
            outcome, why = "error", err
        self.journal.end(outcome, why)
        self._save(text)
        used = context.estimate_tokens(self.history, tools.schemas())
        try:
            self.call_from_thread(self.ui_task_end, time.monotonic() - t0, cancelled, err, note, used)
        except Exception:
            pass

    def _save(self, text):
        """Write the session file after a task; a failure never stops the agent."""
        try:
            if self.session is None:
                if not any(t.get("outcome") == "done" for t in self.journal.tasks):
                    return
                self.session = sessions.create(self.session_title or text, self.history, _os.getcwd())
            self.session["journal"] = self.journal.tasks
            sessions.update(self.session, self.history)
        except (OSError, ValueError, TypeError):
            pass

    # ----- events from the core (run in the app thread)
    async def ui_model_start(self, step):
        self.first_token = False
        self.set_agent_state("analyzing" if step == 1 else "thinking")
        self.think = ThinkingLine()
        self._active.append(self.think)
        await self.chat.mount(self.think)
        self.chat.scroll_end(animate=False)

    async def ui_token(self, text):
        if not self.first_token:
            self.first_token = True
            if self.think:
                self.think.done()
                self.think = None
            self.set_agent_state("replying")
            self.reply_text = ""
            self.reply_w = Static("", classes="reply")
            await self.chat.mount(self.reply_w)
        self.reply_text += text
        n = len(self.reply_text)
        trail = "".join(glyph(n + k, n) for k in range(3))
        t = self.rtl_stream(self.reply_text, trail)
        self.reply_w.update(t if t is not None else Text.assemble((self.reply_text, G1), (trail, G3)))
        self.chat.scroll_end(animate=False)

    def ui_reply_end(self):
        if self.reply_w is not None:
            self.reply_w.update(Text(self.rtl_text(self.reply_text), style=G1))
            self.reply_w = None

    def ui_model_end(self):
        if self.think:
            self.think.done()
            self.think = None

    async def ui_tool_start(self, name, args):
        if self.actions is None:
            self.actions = ActionLog()
            self._active.append(self.actions)
            await self.chat.mount(self.actions)
        verb, target = describe(name, args)
        self.row = self.actions.start(verb, target)
        self.set_agent_state("executing")
        self.chat.scroll_end(animate=False)

    def ui_tool_end(self, status, result):
        result = result or ""
        failed = status in ("refused", "skipped") or result.lstrip().startswith("Error")
        if self.actions is not None and self.row is not None:
            n = len(result.splitlines())
            if status in ("refused", "skipped"):
                info = status
            elif failed:
                info = "error"
            else:
                info = f"{n} line{'' if n == 1 else 's'}"
            self.actions.finish(self.row, info, ok=not failed)
        self.set_agent_state("thinking")

    def ui_final(self, text):
        self.chat.mount(Static(Text(self.rtl_text(text), style=G1), classes="reply"))
        self.chat.scroll_end(animate=False)

    def ui_ctx(self, used):
        self.used = used
        self.update_ctx()

    def ui_task_end(self, elapsed, cancelled, err, note, used):
        if self.reply_w is not None:
            self.ui_reply_end()
        for w in self._active:
            w.interrupt()
        self._active.clear()
        self.think = self.actions = self.row = None
        self.used = used
        self.update_ctx()
        if cancelled:
            self.note("■ interrupted", G2)
        elif err:
            self.note("✗ " + err, W)
        else:
            self.note(f"▪ worked {elapsed:.0f}s")
        if note:
            self.note(note, W)
        elif used >= config.CONTEXT_TOKENS * 0.85:
            self.note("Context is almost full — open a new session with /new", W)
        self.set_working(False)
        if (note or used >= config.CONTEXT_TOKENS * 0.85) and not self.auto_handoff and self.journal.tasks:
            self.auto_handoff = True
            self.start_handoff()

    def _cancel_check(self):
        if self.cancel_flag.is_set():
            raise Cancelled()

    def start_handoff(self, copy=False):
        if self.working:
            return self.note("Wait for the task to finish (or press esc), then /handoff.", G2)
        if not self.journal.tasks:
            return self.note("Nothing to hand off yet.", G2)
        self.note("Writing the handoff... (esc skips the model part)", G1)
        self.cancel_flag.clear()
        self.set_working(True)
        self.set_agent_state("analyzing")
        self.run_worker(lambda: self._handoff_work(copy), thread=True, exclusive=True, exit_on_error=False)

    def _handoff_work(self, copy=False):
        sid = self.session["id"] if self.session else None
        tasks = list(self.journal.tasks)
        try:
            path, text = handoff.generate(sid, _os.getcwd(), tasks, cancel=self._cancel_check)
        except Cancelled:
            path, text = handoff.generate(sid, _os.getcwd(), tasks, use_model=False)
        try:
            self.call_from_thread(self.ui_handoff_done, path, text, copy)
        except Exception:
            pass

    def ui_handoff_done(self, path, text, copy=False):
        self.set_working(False)
        self.note(text, G1)
        self.note(f"Handoff saved: {path}" if path else "Handoff not saved (no saved session yet).", G1)
        if copy:
            try:
                self.copy_to_clipboard(text)
            except Exception:
                self.note("Could not copy to the clipboard.", G2)


def exit_screen(title, session_id=None):
    cols = shutil.get_terminal_size((80, 24)).columns
    _, rows = logo_rows(cols)
    print()
    for r in rows:
        print("  " + ANSI_WHITE + r + RESET)
    print()
    print(f"  \033[2mSession \033[0m  \033[1m{title}\033[0m")
    if session_id:
        print(f"  \033[2mContinue \033[0m \033[1mopenagent -s {session_id}\033[0m")
    print()


def run(resume=None):
    app = AgentApp(resume)
    app.run()
    if app.session_title:
        exit_screen(app.session_title, app.session["id"] if app.session else None)
