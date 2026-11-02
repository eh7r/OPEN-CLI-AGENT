"""RTL display helper: Arabic is converted only when drawing.

Two modes:
  words - terminals that shape Arabic letters themselves (kitty):
          raw letters, only the order of the words is reversed.
  bidi  - other terminals: arabic-reshaper + python-bidi.
AGENT_RTL_MODE=words|bidi overrides the automatic choice.
"""
import os
import re
import textwrap
import unicodedata
from functools import lru_cache

try:
    import arabic_reshaper
    from bidi import get_display
except Exception:  # library missing: bidi mode shows text as is
    arabic_reshaper = None
    get_display = None

_AR = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_TRAIL = ".,:;!?\u2026\u060c\u061b\u061f"


def available():
    return arabic_reshaper is not None and get_display is not None


def mode():
    m = os.environ.get("AGENT_RTL_MODE", "").strip().lower()
    if m in ("words", "bidi"):
        return m
    return "words" if os.environ.get("KITTY_WINDOW_ID") else "bidi"


def enabled():
    off = os.environ.get("AGENT_RTL", "").strip().lower() in ("off", "0", "false", "no")
    if off:
        return False
    return True if mode() == "words" else available()


def has_arabic(text):
    return bool(_AR.search(text))


def _cells(s):
    return sum(0 if unicodedata.combining(c) else 1 for c in s)


def _ltr_run(toks):
    """Latin/number run inside an RTL line: trailing punctuation goes to its left."""
    last = toks[-1]
    stripped = last.rstrip(_TRAIL)
    tail = last[len(stripped):]
    if tail and stripped:
        if len(toks) == 1:
            return [tail + stripped]
        return [tail + toks[0]] + toks[1:-1] + [stripped]
    return toks


import re as _re
_PP = _re.compile(r"^(.*\))([:،؛.؟!]+)$")


def _reorder_words(line):
    """Reverse word order of an RTL line; Latin/number runs keep their order."""
    runs = []
    toks = line.strip().split(" ")
    lead = toks.pop(0) if len(toks) > 1 and toks[0] in ("•", "-", "*") else ""
    for tok in toks:
        ar = has_arabic(tok)
        if ar:
            tok = _PP.sub(r"\2\1", tok)
        if runs and runs[-1][0] == ar:
            runs[-1][1].append(tok)
        else:
            runs.append((ar, [tok]))
    out = []
    for ar, toks in reversed(runs):
        out.extend(reversed(toks) if ar else _ltr_run(toks))
    if lead:
        out.append(lead)
    return " ".join(out)


@lru_cache(maxsize=1024)
def _line(line, width, align, m):
    try:
        if m == "words":
            visual = _reorder_words(line)
        else:
            shaped = arabic_reshaper.reshape(line)
            try:
                visual = get_display(shaped, base_dir="R")
            except TypeError:
                visual = get_display(shaped)
    except Exception:
        return line
    pad = width - _cells(visual)
    return " " * pad + visual if align and pad > 0 else visual


def _wrap(text, width):
    """Yield (line, paragraph_has_arabic) so wrapped lines stay RTL."""
    for para in text.split("\n"):
        rtl = has_arabic(para)
        for l in textwrap.wrap(para, width, replace_whitespace=False) or [""]:
            yield l, rtl


def render(text, width, align=True):
    """Wrap to width first, then reorder each line of an Arabic paragraph."""
    if not text or not enabled() or not has_arabic(text):
        return text
    width = max(10, int(width))
    m = mode()
    return "\n".join(
        _line(l, width, align, m) if rtl and l else l for l, rtl in _wrap(text, width)
    )
