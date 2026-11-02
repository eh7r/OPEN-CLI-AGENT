import pytest
from agent import rtl


@pytest.fixture(autouse=True)
def words_mode(monkeypatch):
    monkeypatch.setenv("AGENT_RTL_MODE", "words")
    monkeypatch.delenv("AGENT_RTL", raising=False)


def test_reorder_arabic_words():
    assert rtl._reorder_words("واحد اثنين ثلاثة اربعة") == "اربعة ثلاثة اثنين واحد"


def test_english_run_keeps_order():
    assert rtl._reorder_words("مرحبا هذا agent 123 اختبار") == "اختبار agent 123 هذا مرحبا"


def test_plain_english_untouched():
    assert rtl.render("hello world", 40) == "hello world"


def test_render_right_aligns():
    out = rtl.render("واحد اثنين", 30)
    assert out == " " * (30 - len("اثنين واحد")) + "اثنين واحد"


def test_mode_env_override(monkeypatch):
    monkeypatch.setenv("AGENT_RTL_MODE", "bidi")
    assert rtl.mode() == "bidi"
    monkeypatch.setenv("AGENT_RTL_MODE", "words")
    assert rtl.mode() == "words"


def test_rtl_off(monkeypatch):
    monkeypatch.setenv("AGENT_RTL", "off")
    assert rtl.render("واحد اثنين", 30) == "واحد اثنين"


def test_punctuation_after_number_moves_left():
    assert rtl._reorder_words("إليك الأرقام من 1 إلى 5:") == ":5 إلى 1 من الأرقام إليك"


def test_english_with_inner_punctuation_keeps_order():
    assert rtl._reorder_words("هذا agent, 123 اختبار") == "اختبار agent, 123 هذا"


def test_wrapped_english_line_stays_rtl():
    out = rtl.render("لتحديد اسم المجلد الذي أنا فيه سأستخدم أمر (Print Working Directory).", 40)
    last = out.split("\n")[-1]
    assert last.startswith(" ") and last.strip().startswith(".")


def test_pure_number_lines_untouched():
    assert rtl.render("1\n2\nواحد", 20).split("\n")[:2] == ["1", "2"]
