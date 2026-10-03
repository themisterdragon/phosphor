"""The terminal view: Phosphor Terminal (phosphor.app) running inside the window.

phosphor.app is written for curses. Here it gets a stand-in `curses` module whose screen is a
Tk Text widget used as a character grid: one line per row, colors as text tags. The app keeps
its own control flow; whenever it waits for a key, Tk keeps running underneath (wait_variable),
so the window stays alive. Nothing here needs the curses package, so it works on Windows too.
"""

import sys
import types
from collections import deque

import tkinter as tk
from tkinter import font as tkfont

from .eras import MAC, TERM

MOD = "Command" if MAC else "Control"
MOD_NAME = "Cmd" if MAC else "Ctrl"

# attribute bits (the color pair number sits in the low byte, shifted up by PAIR_SHIFT)
PAIR_SHIFT = 4
BOLD, DIM, REVERSE = 1 << 16, 1 << 17, 1 << 18

KEYCODES = dict(KEY_UP=1001, KEY_DOWN=1002, KEY_LEFT=1003, KEY_RIGHT=1004, KEY_HOME=1005, KEY_END=1006,
                KEY_PPAGE=1007, KEY_NPAGE=1008, KEY_BACKSPACE=1009, KEY_ENTER=1010, KEY_RESIZE=1011, KEY_DC=1012)
TK_KEYS = {"Up": "KEY_UP", "Down": "KEY_DOWN", "Left": "KEY_LEFT", "Right": "KEY_RIGHT", "Home": "KEY_HOME",
           "End": "KEY_END", "Prior": "KEY_PPAGE", "Next": "KEY_NPAGE", "BackSpace": "KEY_BACKSPACE",
           "Delete": "KEY_DC"}
TEXT_KEYS = {"Return": "\n", "KP_Enter": "\n", "Escape": "\x1b", "Tab": "\t"}


class Leave(BaseException):
    """Thrown through the terminal app to stop it: `why` is "switch" (back to the window) or "quit"."""

    def __init__(self, why):
        super().__init__(why)
        self.why = why


def palette256(n):
    """xterm's 256-color table as #rrggbb: 16 system colors, a 6x6x6 cube, then 24 grays."""
    system = ("000000 800000 008000 808000 000080 800080 008080 c0c0c0 "
              "808080 ff0000 00ff00 ffff00 0000ff ff00ff 00ffff ffffff").split()
    if n < 16:
        return "#" + system[n]
    if n >= 232:
        level = 8 + 10 * (n - 232)
        return "#{0:02x}{0:02x}{0:02x}".format(level)
    n -= 16
    steps = [0] + [55 + 40 * i for i in range(1, 6)]
    r, g, b = n // 36, (n // 6) % 6, n % 6
    return "#{:02x}{:02x}{:02x}".format(steps[r], steps[g], steps[b])


def halfway(c1, c2):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#{:02x}{:02x}{:02x}".format(*((x + y) // 2 for x, y in zip(a, b)))


class Grid:
    """The curses "window" the app draws on, shown in a Text widget."""

    def __init__(self, text, font, pairs):
        self.text = text
        self.font = font
        self.pairs = pairs            # pair number -> (fg index, bg index)
        self.queue = deque()          # keys waiting to be read
        self.signal = tk.BooleanVar(text, False)
        self.wait_ms = -1             # how long a key read waits: -1 forever, 0 not at all
        self.stop = None              # set to "switch"/"quit" to unwind the app at its next key read
        self.running = False
        self.background = 0
        self.rows = self.cols = 0
        self.cells = []
        self.drawn = []
        self.tags = set()
        text.bind("<Configure>", lambda e: self.measure())
        self.measure()

    # -- size
    def measure(self):
        w, h = self.text.winfo_width(), self.text.winfo_height()
        cw, lh = max(1, self.font.measure("M")), max(1, self.font.metrics("linespace"))
        rows, cols = max(2, (h - 8) // lh), max(10, (w - 8) // cw)
        if (rows, cols) == (self.rows, self.cols):
            return
        old = self.cells
        self.rows, self.cols = rows, cols
        self.cells = [[(old[y][x] if y < len(old) and x < len(old[y]) else (" ", self.background))
                       for x in range(cols)] for y in range(rows)]
        self.reset_text()
        if self.running:
            self.queue.append(KEYCODES["KEY_RESIZE"])
            self.signal.set(True)

    def reset_text(self):
        t = self.text
        t.configure(state="normal")
        t.delete("1.0", "end")
        t.insert("1.0", "\n".join(" " * self.cols for _ in range(self.rows)))
        t.configure(state="disabled")
        self.drawn = [None] * self.rows

    # -- colors
    def colors(self, attr):
        fg, bg = self.pairs.get((attr >> PAIR_SHIFT) & 0xFF, (7, 0))
        fg, bg = palette256(fg if fg >= 0 else 7), palette256(bg if bg >= 0 else 0)
        if attr & REVERSE:
            fg, bg = bg, fg
        if attr & DIM:
            fg = halfway(fg, bg)
        return fg, bg

    def tag(self, attr, solid=False):
        """A text tag for these attributes; `solid` paints the cell in the text color (a full block)."""
        name = f"s{attr}" if solid else f"t{attr}"
        if name not in self.tags:
            fg, bg = self.colors(attr)
            weight = "bold" if attr & BOLD else "normal"
            self.text.tag_configure(name, foreground=fg, background=fg if solid else bg,
                                    font=(self.font.actual("family"), self.font.actual("size"), weight))
            self.tags.add(name)
        return name

    def forget_colors(self):
        for name in self.tags:
            self.text.tag_delete(name)
        self.tags = set()
        self.drawn = [None] * self.rows
        self.text.configure(bg=self.colors(self.background)[1])

    # -- what the app calls
    def getmaxyx(self):
        return self.rows, self.cols

    def keypad(self, on):
        pass

    def bkgd(self, ch, attr=0):
        self.background = attr
        self.forget_colors()

    def erase(self):
        self.cells = [[(" ", self.background)] * self.cols for _ in range(self.rows)]

    def addstr(self, y, x, s, attr=0):
        if not (0 <= y < self.rows and 0 <= x < self.cols):
            raise CursesError("outside the screen")
        row = self.cells[y]
        for i, ch in enumerate(s[: self.cols - x]):
            row[x + i] = (ch, attr)

    def nodelay(self, on):
        self.wait_ms = 0 if on else -1

    def timeout(self, ms):
        self.wait_ms = ms

    def refresh(self):
        t = self.text
        t.configure(state="normal")
        for y in range(self.rows):
            row = self.cells[y]
            if row == self.drawn[y]:
                continue
            t.delete(f"{y + 1}.0", f"{y + 1}.end")
            runs, x = [], 0
            while x < self.cols:
                ch, attr = row[x]
                solid = ch == "█"
                end = x + 1
                while end < self.cols and row[end][1] == attr and (row[end][0] == "█") == solid:
                    end += 1
                piece = " " * (end - x) if solid else "".join(c for c, _ in row[x:end])
                runs += [piece, self.tag(attr, solid)]
                x = end
            t.insert(f"{y + 1}.0", *runs)
            self.drawn[y] = list(row)
        t.configure(state="disabled")
        t.update_idletasks()

    def get_wch(self):
        k = self.read_key()
        if k is None:
            raise CursesError("no key")
        return k

    def getch(self):
        k = self.read_key()
        if k is None:
            return -1
        return ord(k) if isinstance(k, str) else k

    # -- keys
    def check(self):
        if self.stop:
            raise Leave(self.stop)

    def pause(self, ms):
        done = tk.BooleanVar(self.text, False)
        self.text.after(max(1, ms), done.set, True)
        self.text.wait_variable(done)
        self.check()

    def read_key(self):
        self.check()
        if not self.queue and self.wait_ms != 0:
            self.signal.set(False)
            timer = self.text.after(self.wait_ms, self.signal.set, True) if self.wait_ms > 0 else None
            self.text.wait_variable(self.signal)
            if timer:
                self.text.after_cancel(timer)
            self.check()
        return self.queue.popleft() if self.queue else None

    def press(self, e):
        ctrl = bool(e.state & 0x4) or (MAC and bool(e.state & 0x8))
        if ctrl and e.keysym.lower() == "c":
            if self.text.tag_ranges("sel"):
                self.copy()
                return "break"
        if ctrl and e.keysym.lower() == "v":
            self.paste()
            return "break"
        if e.keysym in TK_KEYS:
            self.queue.append(KEYCODES[TK_KEYS[e.keysym]])
        elif e.keysym in TEXT_KEYS:
            self.queue.append(TEXT_KEYS[e.keysym])
        elif e.state & 0x4 and len(e.keysym) == 1 and e.keysym.isalpha():
            self.queue.append(chr(ord(e.keysym.lower()) - ord("a") + 1))  # Ctrl+letter, as a terminal sends it
        elif e.char and e.char.isprintable():
            self.queue.append(e.char)
        else:
            return None
        self.text.tag_remove("sel", "1.0", "end")
        self.signal.set(True)
        return "break"

    def copy(self):
        try:
            chosen = self.text.get("sel.first", "sel.last")
        except tk.TclError:
            return
        self.text.clipboard_clear()
        self.text.clipboard_append("\n".join(line.rstrip() for line in chosen.split("\n")))

    def paste(self):
        try:
            got = self.text.clipboard_get()
        except tk.TclError:
            return
        for ch in got.replace("\r", ""):
            if ch == "\n" or ch.isprintable():
                self.queue.append(ch)
        self.signal.set(True)


class CursesError(Exception):
    pass


def make_curses(view):
    """A stand-in `curses` module wired to this terminal view."""
    m = types.ModuleType("curses")
    m.error = CursesError
    m.__dict__.update(KEYCODES)
    m.COLOR_BLACK, m.COLOR_RED, m.COLOR_GREEN, m.COLOR_YELLOW = 0, 1, 2, 3
    m.COLOR_BLUE, m.COLOR_MAGENTA, m.COLOR_CYAN, m.COLOR_WHITE = 4, 5, 6, 7
    m.COLORS = 256
    m.A_BOLD, m.A_DIM, m.A_REVERSE, m.A_NORMAL = BOLD, DIM, REVERSE, 0

    def init_pair(n, fg, bg):
        view.pairs[n] = (fg, bg)
        if view.grid:
            view.grid.forget_colors()

    m.init_pair = init_pair
    m.color_pair = lambda n: n << PAIR_SHIFT
    m.start_color = lambda: None
    m.curs_set = lambda n: None
    m.update_lines_cols = lambda: None
    m.napms = lambda ms: view.grid.pause(ms)
    m.ungetch = lambda k: view.grid.queue.appendleft(chr(k) if isinstance(k, int) and 0 <= k < 256 else k)

    def wrapper(fn, *a, **kw):
        raise CursesError("the terminal view runs the app itself")

    m.wrapper = wrapper
    return m


def import_app(fake):
    """A fresh import of phosphor.app bound to the stand-in curses (a real curses, if any, is put back)."""
    import importlib
    real = sys.modules.get("curses")
    package = sys.modules[__package__.rpartition(".")[0]]
    sys.modules["curses"] = fake
    try:
        sys.modules.pop(package.__name__ + ".app", None)
        if hasattr(package, "app"):
            delattr(package, "app")
        return importlib.import_module(package.__name__ + ".app")
    finally:
        if real is not None:
            sys.modules["curses"] = real
        else:
            sys.modules.pop("curses", None)


class TermArgs:
    def __init__(self, no_boot, leave):
        self.no_boot = no_boot
        self.leave = leave


class ConsoleView:
    """Covers the window with the terminal app until it asks to switch back, or quits."""

    def __init__(self, gui):
        self.gui = gui
        self.grid = None
        self.pairs = {}

    def family(self):
        have = set(tkfont.families(self.gui.root))
        for name in TERM:
            if name in have:
                return name
        return tkfont.nametofont("TkFixedFont", self.gui.root).actual("family")

    def start(self, boot):
        gui = self.gui
        self.font = tkfont.Font(gui.root, family=self.family(), size=-gui.term_px())
        self.text = tk.Text(gui.root, font=self.font, wrap="none", bd=0, highlightthickness=0, padx=4, pady=4,
                            spacing1=0, spacing2=0, spacing3=0, cursor="xterm", bg="#000000",
                            selectbackground="#6a6a6a", inactiveselectbackground="#6a6a6a", insertwidth=0)
        self.text.place(x=0, y=0, relwidth=1, relheight=1)
        tk.Misc.lift(self.text)
        self.build_menu()
        gui.root.update_idletasks()
        self.grid = Grid(self.text, self.font, self.pairs)
        self.text.bind("<Key>", self.grid.press)
        self.text.bind("<Button-3>", lambda e: self.edit_menu.tk_popup(e.x_root, e.y_root))
        for seq, fn in ((f"<{MOD}-Shift-W>", lambda: self.request("switch")),
                        (f"<{MOD}-Shift-w>", lambda: self.request("switch")),
                        (f"<{MOD}-q>", lambda: self.request("quit")),
                        (f"<{MOD}-equal>", lambda: gui.zoom(1)), (f"<{MOD}-minus>", lambda: gui.zoom(-1))):
            self.text.bind(seq, lambda e, fn=fn: (fn(), "break")[1])
        self.text.focus_set()
        gui.root.after_idle(lambda: self.run(boot))

    def build_menu(self):
        gui = self.gui
        bar = self.menubar = tk.Menu(gui.root)
        f = tk.Menu(bar, tearoff=False)
        f.add_command(label="Quit", accelerator=f"{MOD_NAME}+Q", command=lambda: self.request("quit"))
        bar.add_cascade(label="File", menu=f, underline=0)
        e = self.edit_menu = tk.Menu(bar, tearoff=False)
        e.add_command(label="Copy", accelerator=f"{MOD_NAME}+C", command=lambda: self.grid and self.grid.copy())
        e.add_command(label="Paste", accelerator=f"{MOD_NAME}+V", command=lambda: self.grid and self.grid.paste())
        bar.add_cascade(label="Edit", menu=e, underline=0)
        v = tk.Menu(bar, tearoff=False)
        v.add_command(label="Window View", accelerator=f"{MOD_NAME}+Shift+W", command=lambda: self.request("switch"))
        v.add_separator()
        v.add_command(label="Bigger Text", accelerator=f"{MOD_NAME}+=", command=lambda: gui.zoom(1))
        v.add_command(label="Smaller Text", accelerator=f"{MOD_NAME}+-", command=lambda: gui.zoom(-1))
        bar.add_cascade(label="View", menu=v, underline=0)
        gui.root.config(menu=bar)

    def zoom(self):
        if self.grid:
            self.font.configure(size=-self.gui.term_px())
            self.grid.forget_colors()
            self.grid.measure()

    def request(self, why):
        """Menu, shortcut, or close box: stop the app at its next key read (or now, if it isn't running)."""
        if self.grid and self.grid.running:
            self.grid.stop = why
            self.grid.signal.set(True)
        else:
            self.close()
            self.gui.left_terminal(why)

    def leave(self, why):
        raise Leave(why)  # the terminal app's own W WINDOW VIEW item

    def run(self, boot):
        if self.grid is None:
            return
        why, crash = "quit", None
        try:
            app = import_app(make_curses(self))
            term_app = app.App(self.grid, TermArgs(not boot, self.leave), shared=self.gui)
            self.grid.running = True
            term_app.run()
        except Leave as e:
            why = e.why
        except Exception as e:  # noqa: BLE001 - report it in the window instead of dying
            why, crash = "switch", e
        self.close()
        self.gui.left_terminal(why, crash)

    def close(self):
        self.grid = None
        self.gui.root.config(menu=self.gui.menubar)
        for w in (getattr(self, "text", None), getattr(self, "menubar", None)):
            if w is not None:
                w.destroy()
