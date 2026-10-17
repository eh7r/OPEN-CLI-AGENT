"""Tests for agent/setup.py: tier choice, download step, wizard flow and saving."""
from types import SimpleNamespace

import pytest

from agent import config, setup


def text(capsys) -> str:
    """Captured output with line wraps collapsed, so wrapping never breaks an assertion."""
    return " ".join(capsys.readouterr().out.split())


def fake_ask(monkeypatch, answers):
    """Replace setup._ask with scripted answers; returns the list of prompts shown."""
    prompts, it = [], iter(answers)

    def _ask(prompt):
        prompts.append(prompt)
        answer = next(it)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    monkeypatch.setattr(setup, "_ask", _ask)
    return prompts


@pytest.fixture
def wizard(monkeypatch):
    """Run the wizard with everything outside the user's machine faked."""
    def run(answers, installed=frozenset(), detected="mid", ram_gb=16):
        saved, downloads = [], []
        monkeypatch.setattr(config, "detect_tier", lambda: detected)
        monkeypatch.setattr(config, "save_settings", saved.append)
        monkeypatch.setattr(
            "psutil.virtual_memory", lambda: SimpleNamespace(total=int(ram_gb * 1024**3))
        )
        monkeypatch.setattr(setup, "_installed", lambda: installed)
        monkeypatch.setattr(setup, "_download", downloads.append)
        prompts = fake_ask(monkeypatch, answers)
        result = setup.run_wizard()
        return SimpleNamespace(result=result, saved=saved, downloads=downloads, prompts=prompts)
    return run


# ---------- _installed ----------

def test_installed_returns_model_names(monkeypatch):
    hosts = []

    class FakeClient:
        def __init__(self, host):
            hosts.append(host)

        def list(self):
            return SimpleNamespace(models=[SimpleNamespace(model="a:1"), SimpleNamespace(model="b:2")])

    monkeypatch.setattr(setup.ollama, "Client", FakeClient)
    assert setup._installed() == {"a:1", "b:2"}
    assert hosts == [config.OLLAMA_HOST]


def test_installed_none_when_ollama_unreachable(monkeypatch):
    class BrokenClient:
        def __init__(self, host):
            raise ConnectionError("down")

    monkeypatch.setattr(setup.ollama, "Client", BrokenClient)
    assert setup._installed() is None


def test_installed_none_when_list_fails(monkeypatch):
    class FailingClient:
        def __init__(self, host):
            pass

        def list(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(setup.ollama, "Client", FailingClient)
    assert setup._installed() is None


# ---------- _choose_tier ----------

@pytest.mark.parametrize("answer, expected", [
    ("1", "low"), ("2", "mid"), ("3", "high"),
])
def test_choose_tier_by_number(monkeypatch, answer, expected):
    fake_ask(monkeypatch, [answer])
    assert setup._choose_tier("mid") == expected


@pytest.mark.parametrize("recommended", ["low", "mid", "high"])
def test_choose_tier_enter_gives_recommended(monkeypatch, recommended):
    fake_ask(monkeypatch, [""])
    assert setup._choose_tier(recommended) == recommended


def test_choose_tier_prompt_shows_recommended_number(monkeypatch):
    prompts = fake_ask(monkeypatch, [""])
    setup._choose_tier("high")
    assert "Enter = 3" in prompts[0] and "1-3" in prompts[0]


@pytest.mark.parametrize("bad", ["0", "4", "-1", "abc", "1.5", "99"])
def test_choose_tier_rejects_bad_input_then_accepts(monkeypatch, capsys, bad):
    fake_ask(monkeypatch, [bad, "2"])
    assert setup._choose_tier("low") == "mid"
    assert "Please type a number from 1 to 3" in text(capsys)


# ---------- _download ----------

def test_download_without_ollama_binary(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(setup.shutil, "which", lambda name: None)
    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **k: calls.append(a))
    setup._download("gemma4:e2b")
    assert calls == []
    out = text(capsys)
    assert "not found" in out and "ollama pull gemma4:e2b" in out


def test_download_success_runs_pull(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(setup.shutil, "which", lambda name: "/usr/bin/ollama")
    monkeypatch.setattr(
        setup.subprocess, "run", lambda cmd, **k: (calls.append(cmd), SimpleNamespace(returncode=0))[1]
    )
    setup._download("gemma4:e4b")
    assert calls == [["ollama", "pull", "gemma4:e4b"]]
    assert "failed" not in text(capsys)


def test_download_failure_prints_retry_hint(monkeypatch, capsys):
    monkeypatch.setattr(setup.shutil, "which", lambda name: "/usr/bin/ollama")
    monkeypatch.setattr(setup.subprocess, "run", lambda cmd, **k: SimpleNamespace(returncode=1))
    setup._download("gpt-oss:20b")
    out = text(capsys)
    assert "download failed" in out and "ollama pull gpt-oss:20b" in out


# ---------- run_wizard: choosing and saving ----------

@pytest.mark.parametrize("answer, tier, model", [
    ("1", "low", "gemma4:e2b"),
    ("2", "mid", "gemma4:e4b"),
    ("3", "high", "gpt-oss:20b"),
])
def test_wizard_saves_chosen_tier_and_model(wizard, answer, tier, model):
    r = wizard([answer], installed={model})
    assert r.result is True
    assert r.saved == [{"tier": tier, "model": model}]


def test_wizard_enter_picks_detected_tier(wizard):
    r = wizard([""], installed={"gpt-oss:20b"}, detected="high")
    assert r.saved == [{"tier": "high", "model": "gpt-oss:20b"}]


def test_wizard_shows_ram_tiers_and_one_recommendation(wizard, capsys):
    wizard([""], installed={"gemma4:e4b"}, detected="mid", ram_gb=16)
    out = text(capsys)
    assert "Detected RAM: 16 GB" in out
    for label, model in [("Light", "gemma4:e2b"), ("Balanced", "gemma4:e4b"), ("Strongest", "gpt-oss:20b")]:
        assert label in out and model in out
    assert out.count("recommended") == 1


def test_wizard_prints_saved_summary(wizard, capsys):
    wizard(["2"], installed={"gemma4:e4b"})
    out = text(capsys)
    assert "Saved: Balanced (gemma4:e4b)" in out and "--setup" in out


def test_wizard_real_save_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CONFIG_PATH", str(tmp_path / "ai-agent" / "config.json"))
    monkeypatch.setattr(config, "detect_tier", lambda: "mid")
    monkeypatch.setattr(setup, "_installed", lambda: {"gpt-oss:20b"})
    fake_ask(monkeypatch, ["3"])
    assert setup.run_wizard() is True
    assert config.load_saved() == {"tier": "high", "model": "gpt-oss:20b"}


# ---------- run_wizard: download step ----------

def test_wizard_model_installed_no_download_question(wizard):
    r = wizard(["2"], installed={"gemma4:e4b"})
    assert len(r.prompts) == 1 and r.downloads == []


def test_wizard_latest_suffix_counts_as_installed(wizard):
    r = wizard(["2"], installed={"gemma4:e4b:latest"})
    assert len(r.prompts) == 1 and r.downloads == []


@pytest.mark.parametrize("answer", ["", "y", "yes"])
def test_wizard_downloads_when_user_agrees(wizard, answer):
    r = wizard(["2", answer], installed=set())
    assert r.downloads == ["gemma4:e4b"]
    assert r.saved == [{"tier": "mid", "model": "gemma4:e4b"}]


@pytest.mark.parametrize("answer", ["n", "no", "nope", "x"])
def test_wizard_skips_download_when_user_declines_but_still_saves(wizard, answer):
    r = wizard(["2", answer], installed=set())
    assert r.downloads == []
    assert r.saved == [{"tier": "mid", "model": "gemma4:e4b"}]


def test_wizard_ollama_unreachable_hint_and_still_saves(wizard, capsys):
    r = wizard(["1"], installed=None)
    out = text(capsys)
    assert "Ollama is not reachable" in out and "ollama serve" in out
    assert len(r.prompts) == 1 and r.downloads == []
    assert r.saved == [{"tier": "low", "model": "gemma4:e2b"}]


# ---------- run_wizard: cancelling ----------

@pytest.mark.parametrize("exc", [KeyboardInterrupt(), EOFError()])
def test_wizard_cancel_at_tier_choice_saves_nothing(wizard, capsys, exc):
    r = wizard([exc])
    assert r.result is False and r.saved == []
    assert "nothing was saved" in text(capsys)


@pytest.mark.parametrize("exc", [KeyboardInterrupt(), EOFError()])
def test_wizard_cancel_at_download_question_saves_nothing(wizard, capsys, exc):
    r = wizard(["2", exc], installed=set())
    assert r.result is False and r.saved == [] and r.downloads == []
    assert "nothing was saved" in text(capsys)
