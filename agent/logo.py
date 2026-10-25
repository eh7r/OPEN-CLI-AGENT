#!/usr/bin/env python3
"""
OPEN CLI AGENT - startup animation (decrypt effect).

The name is always ONE line (blocks, 5 or 3 rows tall), big and white.
While a letter is still locked it shows grey scrambling glyphs in the
same block shape; when it unlocks it flashes and settles to solid white.

    python3 open-cli-agent-anim.py          full screen, centred, replays (Ctrl+C exits)
    python3 open-cli-agent-anim.py --once   inline, plays once and exits (for agent startup)

Sizes (picked from the terminal width, re-checked every frame):
    big      5 rows, 102 cols   (needs >= 106 cols)
    compact  3 rows,  51 cols   (needs >=  54 cols)
    text     1 row,   14 cols   (anything smaller)
No colour (NO_COLOR, TERM=dumb, pipe) = static plain logo, no animation.
"""
import os
import random
import shutil
import sys
import time

RESET, HIDE, SHOW = "\033[0m", "\033[?25l", "\033[?25h"
HOME, CLEAR, CLR_EOL = "\033[H", "\033[2J", "\033[K"
ALT_ON, ALT_OFF = "\033[?1049h", "\033[?1049l"

# scrambling letters: dark grey -> light grey as they get close to unlocking
GRAYS = ("\033[38;5;238m", "\033[38;5;244m", "\033[38;5;250m")
FLASH = "\033[1;97m"                # the moment a letter unlocks
WHITE = "\033[1;38;5;255m"          # final text

TEXT = "OPEN CLI AGENT"
GLYPHS = "#%&@$?!*+=/{}[]<>~^"

SPEED = 0.075         # how often the scrambled glyphs change
STAGGER = 0.12        # delay between letters unlocking
START_DELAY = 0.4
JITTER = 0.15
FLASH_DURATION = 0.35
HOLD_DURATION = 5.0   # full-screen mode: time the finished name stays before replay
INITIAL_DELAY = 0.4
SEED = 42
FPS = 25

# 3x5 pixel font
PX = {
    "O": ("111", "101", "101", "101", "111"),
    "P": ("111", "101", "111", "100", "100"),
    "E": ("111", "100", "111", "100", "111"),
    "N": ("101", "111", "111", "111", "101"),
    "C": ("111", "100", "100", "100", "111"),
    "L": ("100", "100", "100", "100", "111"),
    "I": ("111", "010", "010", "010", "111"),
    "A": ("111", "101", "111", "101", "101"),
    "G": ("111", "100", "101", "101", "111"),
    "T": ("111", "010", "010", "010", "010"),
}
HALF = {(False, False): " ", (True, False): "▀", (False, True): "▄", (True, True): "█"}

# style: (min cols, columns per pixel, half blocks?, letter gap, word gap)
STYLES = {"big": (106, 2, False, 2, 6), "compact": (54, 1, True, 1, 3)}


def letter_rows(ch, px_w, half):
    px = ["".join(c * px_w for c in row) for row in PX[ch]]
    if half:                                   # 5 pixel rows -> 3 text rows
        px.append("0" * len(px[0]))
        return ["".join(HALF[(a == "1", b == "1")] for a, b in zip(px[r], px[r + 1]))
                for r in (0, 2, 4)]
    return ["".join("█" if c == "1" else " " for c in row) for row in px]


def pick_style(cols, lines):
    for name in ("big", "compact"):
        if cols >= STYLES[name][0] and lines >= STYLES_ROWS[name]:
            return name
    return "text"


STYLES_ROWS = {"big": 5, "compact": 3}


def layout(style):
    """-> (items, nrows, width). item = ('gap', n) | ('letter', index, rows)."""
    items, idx = [], 0
    words = TEXT.split(" ")
    if style == "text":
        for wi, word in enumerate(words):
            if wi:
                items.append(("gap", 1))
            for ch in word:
                items.append(("letter", idx, [ch]))
                idx += 1
        return items, 1, len(TEXT)
    _, px_w, half, lgap, wgap = STYLES[style]
    for wi, word in enumerate(words):
        if wi:
            items.append(("gap", wgap))
        for li, ch in enumerate(word):
            if li:
                items.append(("gap", lgap))
            items.append(("letter", idx, letter_rows(ch, px_w, half)))
            idx += 1
    nrows = len(items[0][2])
    width = sum(i[1] if i[0] == "gap" else len(i[2][0]) for i in items)
    return items, nrows, width


class Decrypt:
    def __init__(self):
        rng = random.Random(SEED)
        n = len(TEXT.replace(" ", ""))
        self.lock_at = [START_DELAY + i * STAGGER + (rng.random() * 2 - 1) * JITTER
                        for i in range(n)]
        self.done_at = max(self.lock_at) + FLASH_DURATION

    def frame(self, t, cols, lines, color=True, center_y=False):
        """Pure function of time t -> list of text lines."""
        style = pick_style(cols, lines)
        items, nrows, width = layout(style)
        pad_x = max(0, (cols - width) // 2)
        step = int(t / SPEED)
        out = []
        for r in range(nrows):
            line = " " * pad_x
            for it in items:
                if it[0] == "gap":
                    line += " " * it[1]
                    continue
                _, i, rows = it
                cells = rows[r]
                locked = t >= self.lock_at[i]
                if locked and not color:
                    line += cells
                    continue
                if locked:
                    paint = FLASH if t - self.lock_at[i] < FLASH_DURATION else WHITE
                else:
                    left = self.lock_at[i] - t
                    paint = GRAYS[0 if left > 0.7 else 1 if left > 0.35 else 2]
                    cells = "".join(
                        " " if c == " " else
                        GLYPHS[(i * 73856093 ^ r * 19349663 ^ k * 83492791 ^ step * 2654435761)
                               % len(GLYPHS)]
                        for k, c in enumerate(cells))
                line += (paint + cells + RESET) if color else cells
            out.append(line)
        if center_y:
            out = [""] * max(0, (lines - nrows) // 2) + out
        return out


def term():
    s = shutil.get_terminal_size((80, 24))
    return s.columns, s.lines


def static_logo(out=None):
    out = out or sys.stdout
    cols, lines = term()
    final = Decrypt().done_at + 1
    out.write("\n".join(l.rstrip() for l in Decrypt().frame(final, cols, lines, color=False)) + "\n")
    out.flush()


def run_once(out):
    """Inline: play once where the cursor is, leave the logo on screen."""
    cols, lines = term()
    anim = Decrypt()
    nrows = layout(pick_style(cols, lines))[1]
    out.write(HIDE)
    try:
        start, first = time.monotonic(), True
        while True:
            t = time.monotonic() - start
            body = "\n".join(l + CLR_EOL for l in anim.frame(t, cols, lines)) + "\n"
            out.write(("" if first else f"\033[{nrows}A\r") + body)
            out.flush()
            first = False
            if t >= anim.done_at:
                break
            time.sleep(1 / FPS)
    finally:
        out.write(RESET + SHOW)
        out.flush()


def run_fullscreen(out):
    anim = Decrypt()
    out.write(ALT_ON + HIDE + CLEAR)
    out.flush()
    try:
        time.sleep(INITIAL_DELAY)
        start, size = time.monotonic(), None
        while True:
            cols, lines = term()
            if (cols, lines) != size:                  # resized: wipe old layout
                size = (cols, lines)
                out.write(CLEAR)
            t = time.monotonic() - start
            if t > anim.done_at + HOLD_DURATION:       # replay
                start, t = time.monotonic(), 0.0
            rows = anim.frame(t, cols, lines, center_y=True)
            out.write(HOME + "\n".join(l + CLR_EOL for l in rows))
            out.flush()
            time.sleep(1 / FPS)
    except KeyboardInterrupt:
        pass
    finally:
        out.write(RESET + SHOW + ALT_OFF)
        out.flush()


def main(argv):
    out = sys.stdout
    plain = (not out.isatty() or os.environ.get("NO_COLOR")
             or os.environ.get("TERM") == "dumb")
    if plain:
        static_logo(out)
    elif "--once" in argv:
        run_once(out)
    else:
        run_fullscreen(out)


if __name__ == "__main__":
    main(sys.argv[1:])
