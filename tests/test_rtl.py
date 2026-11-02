from agent import rtl

AR = "\u0645\u0631\u062d\u0628\u0627"


def test_english_unchanged():
    assert rtl.render("hello world", 40) == "hello world"


def test_arabic_is_converted():
    assert rtl.render(AR, 20, align=False) != AR


def test_right_align_fills_width():
    assert len(rtl.render(AR, 20)) == 20


def test_wrap_before_bidi():
    lines = rtl.render((AR + " ") * 10, 20).split("\n")
    assert len(lines) > 1
    assert all(len(l) <= 20 for l in lines)


def test_mixed_keeps_english_word():
    text = "\u0627\u0641\u062a\u062d main.py \u0627\u0644\u0622\u0646"
    assert "main.py" in rtl.render(text, 40, align=False)


def test_blank_lines_kept():
    assert rtl.render(AR + "\n\n" + AR, 20).split("\n")[1] == ""


def test_missing_library_falls_back(monkeypatch):
    monkeypatch.setattr(rtl, "arabic_reshaper", None)
    assert rtl.render(AR, 20) == AR


def test_env_off(monkeypatch):
    monkeypatch.setenv("AGENT_RTL", "off")
    assert rtl.render(AR, 20) == AR
