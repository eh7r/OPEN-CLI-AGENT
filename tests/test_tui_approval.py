"""Pilot tests for the approval box: n / esc / enter deny, y allows, nothing hangs."""
import asyncio
import threading

import pytest
from textual.widgets import Input

from agent import approval, model, tui_approval
from agent.tui import AgentApp
from agent.tui_approval import ApprovalBox


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(model, "warm_up", lambda *a, **k: None)
    yield
    approval.set_handler(None)


async def _wait_for(pilot, cond, what, timeout=10.0):
    """Wait for a real condition (no fixed sleep); fail with a clear message on timeout."""
    deadline = asyncio.get_running_loop().time() + timeout
    while not cond():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"timed out waiting for: {what}")
        await pilot.pause(0.02)


def _box_shown(app):
    """The approval box exists, is mounted, and focus is on the Deny button."""
    box = getattr(app, "approval_box", None)
    return box is not None and box.is_mounted and getattr(app.focused, "id", None) == "deny"


def _box_ready(app):
    """Shown, and armed (it accepts keys). Waited for as a real condition, never patched."""
    return _box_shown(app) and app.approval_box.armed


async def _run(keys):
    app = AgentApp()
    out = {}
    async with app.run_test(size=(100, 40)) as pilot:
        t = threading.Thread(target=lambda: out.update(r=app._approval_handler("run: touch x")))
        t.start()
        try:
            await _wait_for(pilot, lambda: _box_ready(app), "approval box mounted, focused on #deny and armed")
            shown = getattr(app, "approval_box", None) is not None
            input_disabled_while = app.query_one(Input).disabled
            for k in keys:
                await pilot.press(k)
            await pilot.pause(0.3)
            t.join(timeout=3)
            return {
                "result": out.get("r"),
                "hung": t.is_alive(),
                "shown": shown,
                "input_disabled_while": input_disabled_while,
                "box_after": getattr(app, "approval_box", None),
                "input_disabled_after": app.query_one(Input).disabled,
                "pending": app.pending,
            }
        finally:
            # A failed test must not leak a handler thread blocked on done.wait(): it is
            # non-daemon and would hang the process at shutdown.
            app.resolve_approval(False)
            t.join(timeout=3)


ALLOW = (True, "")
DENY = (False, approval.DECLINED)


@pytest.mark.parametrize("keys, expected", [
    (["y"], ALLOW),
    (["n"], DENY),
    (["escape"], DENY),
    (["enter"], DENY),            # focus starts on Deny: an accidental Enter allows nothing
    (["left", "enter"], ALLOW),   # move to Allow, then confirm
])
def test_answer(keys, expected):
    r = asyncio.run(_run(keys))
    assert r["shown"] and r["input_disabled_while"]
    assert not r["hung"]
    assert r["result"] == expected
    assert r["box_after"] is None
    assert not r["input_disabled_after"]
    assert r["pending"] is None


def test_keys_before_armed_are_ignored(monkeypatch):
    """Typeahead: keys pressed before the box is armed approve nothing. The delay is made
    huge only here, so the unarmed window cannot close during the test (test_answer stays
    unpatched and waits for box.armed)."""
    monkeypatch.setattr(tui_approval, "ARM_DELAY", 30)

    async def scenario():
        app = AgentApp()
        out = {}
        async with app.run_test(size=(100, 40)) as pilot:
            t = threading.Thread(target=lambda: out.update(r=app._approval_handler("run: touch x")))
            t.start()
            try:
                await _wait_for(pilot, lambda: _box_shown(app), "approval box mounted and focused")
                box = app.approval_box
                await pilot.press("y", "left", "enter", "n", "escape")
                assert not box.armed
                still_pending = app.pending is not None and app.approval_box is box
                alive = t.is_alive()
                box._arm()
                await pilot.press("y")
                await pilot.pause(0.3)
                t.join(timeout=3)
                return still_pending, alive, out.get("r"), t.is_alive()
            finally:
                app.resolve_approval(False)
                t.join(timeout=3)

    still_pending, alive, result, hung = asyncio.run(scenario())
    assert still_pending and alive      # nothing was answered before the box was armed
    assert not hung
    assert result == ALLOW              # once armed, y works as before


async def _open_approval(app, pilot):
    """Start a blocked approval on a worker-like thread; return (thread, out)."""
    out = {}
    t = threading.Thread(target=lambda: out.update(r=app._approval_handler("run: touch x")))
    t.start()
    await _wait_for(pilot, lambda: _box_ready(app), "approval box ready")
    return t, out


def test_quit_with_pending_approval_declines_and_does_not_hang():
    async def scenario():
        app = AgentApp()
        async with app.run_test(size=(100, 40)) as pilot:
            t, out = await _open_approval(app, pilot)
            try:
                app.action_quit()
                await pilot.pause(0.3)
                t.join(timeout=3)
                return out.get("r"), t.is_alive(), app.pending
            finally:
                # The app is exiting here, so release the handler thread without touching
                # the UI (resolve_approval would note() into a closing app and mask the
                # real failure).
                if app.pending is not None:
                    box, done = app.pending
                    box["ok"] = False
                    done.set()
                t.join(timeout=3)

    result, hung, pending = asyncio.run(scenario())
    assert not hung
    assert result == DENY
    assert pending is None


def test_resolve_approval_is_idempotent(monkeypatch):
    """A second resolve (a user answer racing with quit) is a no-op: first answer wins."""
    async def scenario():
        app = AgentApp()
        notes = []
        async with app.run_test(size=(100, 40)) as pilot:
            monkeypatch.setattr(app, "note", lambda *a, **k: notes.append(a))
            t, out = await _open_approval(app, pilot)
            try:
                app.resolve_approval(False)
                app.resolve_approval(True)   # late allow must not flip the answer
                await pilot.pause(0.1)
                t.join(timeout=3)
                return out.get("r"), t.is_alive(), len(notes)
            finally:
                app.resolve_approval(False)
                t.join(timeout=3)

    result, hung, n_notes = asyncio.run(scenario())
    assert not hung
    assert result == DENY
    assert n_notes == 1                  # "declined" shown once, no second "allowed"


def test_answer_arriving_after_interrupt_does_not_flip_the_decline():
    async def scenario():
        app = AgentApp()
        async with app.run_test(size=(100, 40)) as pilot:
            t, out = await _open_approval(app, pilot)
            try:
                app.action_interrupt()                                   # quit/Esc path declines
                app.on_approval_box_answered(ApprovalBox.Answered(True))  # the user's `y` arrives late
                await pilot.pause(0.1)
                t.join(timeout=3)
                return out.get("r"), t.is_alive(), app.pending
            finally:
                app.resolve_approval(False)
                t.join(timeout=3)

    result, hung, pending = asyncio.run(scenario())
    assert not hung
    assert result == DENY
    assert pending is None
