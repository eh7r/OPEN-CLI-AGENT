"""Pilot tests for the approval box: n / esc / enter deny, y allows, nothing hangs."""
import asyncio
import threading

import pytest
from textual.widgets import Input

from agent import approval, model
from agent.tui import AgentApp


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(model, "warm_up", lambda *a, **k: None)
    yield
    approval.set_handler(None)


async def _run(keys):
    app = AgentApp()
    out = {}
    async with app.run_test(size=(100, 40)) as pilot:
        t = threading.Thread(target=lambda: out.update(r=app._approval_handler("run: touch x")))
        t.start()
        for _ in range(100):
            await pilot.pause(0.05)
            if getattr(app, "approval_box", None) is not None:
                break
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
