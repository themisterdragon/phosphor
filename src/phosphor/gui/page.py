"""Page: a read-only text area the views write into, with clickable, keyboard-selectable items.
Also the small dialogs, drawn in the current era's colors."""

import tkinter as tk
from tkinter import font as tkfont


class Page:
    def __init__(self, parent, gui, scrollbar=True):
        self.gui = gui
        self.frame = tk.Frame(parent, bd=0, highlightthickness=0)
        self.t = tk.Text(self.frame, wrap="word", bd=0, highlightthickness=0, cursor="arrow", takefocus=0,
                         undo=False, exportselection=False)
        self.sb = None
        if scrollbar:
            self.sb = tk.Scrollbar(self.frame, command=self.t.yview, bd=0, highlightthickness=0, width=12)
            self.t.configure(yscrollcommand=self.sb.set)
            self.sb.pack(side="right", fill="y")
        self.t.pack(side="left", fill="both", expand=True)
        self.items = []         # (start, end, action)
        self.keys = {}          # a key the user can press -> item number
        self.sel = -1
        self.reveal_job = None
        self.t.bind("<Button-1>", lambda e: "break")  # clicks only act through items; no text cursor
        self.t.tag_bind("item", "<Enter>", lambda e: self.t.configure(cursor="hand2"))
        self.t.tag_bind("item", "<Leave>", lambda e: self.t.configure(cursor="arrow"))

    # -- writing
    def clear(self):
        self.stop_reveal()
        self.t.configure(state="normal")
        for name in self.t.tag_names():
            if name.startswith("i") and name[1:].isdigit():
                self.t.tag_delete(name)
        self.t.delete("1.0", "end")
        self.items = []
        self.keys = {}
        self.sel = -1

    def w(self, text, *tags):
        self.t.insert("end", text, tags)
        return self

    def nl(self, n=1):
        self.t.insert("end", "\n" * n)
        return self

    def item(self, action, text=None, *tags, key=None):
        """Start a clickable item (or write `text` as one). Close it with end_item()."""
        self._start = self.t.index("end-1c")
        self._action = action
        self._key = key
        if text is not None:
            self.w(text, *tags)
            self.end_item()
        return self

    def end_item(self):
        start, end = self._start, self.t.index("end-1c")
        n = len(self.items)
        name = f"i{n}"
        self.t.tag_add(name, start, end)
        self.t.tag_add("item", start, end)
        self.t.tag_bind(name, "<ButtonRelease-1>", lambda e, n=n: self.click(n))
        self.items.append((start, end, self._action))
        if self._key:
            self.keys[str(self._key).lower()] = n
        return n

    def embed(self, widget, **kw):
        self.t.window_create("end", window=widget, **kw)

    def done(self, select=None, top=True):
        self.t.configure(state="disabled")
        if select is not None and self.items:
            self.select(max(0, min(select, len(self.items) - 1)), see=not top)
        if top:
            self.t.yview_moveto(0)

    # -- selection
    def select(self, i, see=True):
        self.t.tag_remove("sel_row", "1.0", "end")
        if not (0 <= i < len(self.items)):
            self.sel = -1
            return
        self.sel = i
        start, end, _ = self.items[i]
        self.t.tag_add("sel_row", start, end)
        self.t.tag_raise("sel_row")
        if see:
            self.t.see(end)
            self.t.see(start)

    def move(self, d):
        if not self.items:
            self.scroll(d)
            return
        if self.sel < 0:
            self.select(0 if d > 0 else len(self.items) - 1)
        else:
            self.select((self.sel + d) % len(self.items))

    def activate(self, i=None):
        i = self.sel if i is None else i
        if 0 <= i < len(self.items):
            self.items[i][2]()
            return True
        return False

    def click(self, n):
        self.select(n, see=False)
        self.gui.root.after_idle(lambda: self.activate(n))

    def scroll(self, d, unit="units"):
        self.t.yview_scroll(d * (3 if unit == "units" else 1), unit)

    # -- the typewriter effect: lines appear one after another; any key shows the rest
    def reveal(self, ms=14):
        self.stop_reveal()
        last = int(self.t.index("end-1c").split(".")[0])
        self.t.tag_add("unseen", "1.0", "end")
        self.t.tag_configure("unseen", elide=True)

        def step(line):
            if line > last:
                self.reveal_job = None
                return
            self.t.tag_remove("unseen", f"{line}.0", f"{line + 1}.0")
            self.reveal_job = self.t.after(ms, step, line + 1)

        step(1)

    def stop_reveal(self):
        if self.reveal_job:
            self.t.after_cancel(self.reveal_job)
            self.reveal_job = None
        self.t.tag_remove("unseen", "1.0", "end")

    def revealing(self):
        return self.reveal_job is not None


# ------------------------------------------------------------------ dialogs
class Dialog:
    """A small modal box in the era's colors. result is None when cancelled."""

    def __init__(self, gui, title, build):
        self.gui = gui
        self.result = None
        c, f = gui.colors, gui.fonts
        top = self.top = tk.Toplevel(gui.root, bg=c["bg"])
        top.title(title)
        top.transient(gui.root)
        top.resizable(False, False)
        self.body = tk.Frame(top, bg=c["bg"], padx=18, pady=14)
        self.body.pack(fill="both", expand=True)
        tk.Label(self.body, text=gui.tx(title), bg=c["bg"], fg=c["hi"], font=f["head"], anchor="w").pack(fill="x")
        build(self)
        top.bind("<Escape>", lambda e: self.close(None))
        top.protocol("WM_DELETE_WINDOW", lambda: self.close(None))
        top.update_idletasks()
        r = gui.root
        x = r.winfo_rootx() + (r.winfo_width() - top.winfo_reqwidth()) // 2
        y = r.winfo_rooty() + max(40, (r.winfo_height() - top.winfo_reqheight()) // 3)
        top.geometry(f"+{max(0, x)}+{max(0, y)}")
        gui.modal = self
        try:
            top.wait_visibility()
            top.grab_set()
        except tk.TclError:
            pass
        top.wait_window()
        gui.modal = None

    def label(self, text, dim=False):
        c = self.gui.colors
        tk.Label(self.body, text=text, bg=c["bg"], fg=c["dim"] if dim else c["fg"], font=self.gui.fonts["body"],
                 justify="left", anchor="w", wraplength=self.gui.px(460)).pack(fill="x", pady=(8, 0))

    def button(self, parent, text, cmd, default=False):
        c = self.gui.colors
        b = tk.Button(parent, text=text, command=cmd, font=self.gui.fonts["ui"], bg=c.get("face", c["bar_bg"]),
                      fg=c.get("face_fg", c["bar_fg"]), activebackground=c["sel_bg"], activeforeground=c["sel_fg"],
                      highlightbackground=c["bg"], highlightcolor=c["hi"], highlightthickness=2,
                      relief="raised" if "face" in c else "flat", bd=2 if "face" in c else 0, padx=12, pady=3)
        b.pack(side="right", padx=(8, 0))
        b.bind("<Return>", lambda e: cmd())
        if default:
            b.configure(default="active")
        return b

    def buttons(self, pairs):
        row = tk.Frame(self.body, bg=self.gui.colors["bg"])
        row.pack(fill="x", pady=(14, 0))
        for text, cmd, default in reversed(pairs):
            self.button(row, text, cmd, default)
        return row

    def close(self, result):
        self.result = result
        try:
            self.top.grab_release()
        except tk.TclError:
            pass
        self.top.destroy()


def ask(gui, title, prompt, initial=""):
    """A line of text from the user, or None."""
    def build(d):
        c = gui.colors
        d.label(prompt)
        var = tk.StringVar(d.top, initial)
        e = tk.Entry(d.body, textvariable=var, font=gui.fonts["body"], bg=c.get("field", c["bg"]), fg=c["fg"],
                     insertbackground=c["fg"], highlightthickness=2, highlightcolor=c["hi"],
                     highlightbackground=c["dim"], relief="sunken" if "face" in c else "flat", bd=2 if "face" in c else 4,
                     width=44)
        e.pack(fill="x", pady=(8, 0))
        e.select_range(0, "end")
        e.focus_set()
        e.bind("<Return>", lambda ev: d.close(var.get().strip()))
        d.buttons([("Cancel", lambda: d.close(None), False), ("OK", lambda: d.close(var.get().strip()), True)])
    return Dialog(gui, title, build).result


def choose(gui, title, prompt, options):
    """One of options (a list of labels) as its index, or None. Number keys pick, too."""
    def build(d):
        c = gui.colors
        if prompt:
            d.label(prompt)
        lb = tk.Listbox(d.body, font=gui.fonts["body"], bg=c.get("field", c["bg"]), fg=c["fg"],
                        selectbackground=c["sel_bg"], selectforeground=c["sel_fg"], highlightthickness=2,
                        highlightcolor=c["hi"], highlightbackground=c["dim"], activestyle="none",
                        height=min(10, len(options)), width=min(60, max(24, max(len(o) for o in options) + 5)),
                        relief="flat", bd=4, exportselection=False)
        for i, o in enumerate(options):
            lb.insert("end", f"{i + 1}  {o}" if i < 9 else f"   {o}")
        lb.pack(fill="both", pady=(8, 0))
        lb.selection_set(0)
        lb.focus_set()

        def pick(i=None):
            if i is None:
                cur = lb.curselection()
                i = cur[0] if cur else None
            d.close(i)

        lb.bind("<Return>", lambda e: pick())
        lb.bind("<Double-Button-1>", lambda e: pick())
        for n in range(1, min(9, len(options)) + 1):
            lb.bind(str(n), lambda e, n=n: pick(n - 1))
        d.buttons([("Cancel", lambda: d.close(None), False), ("OK", pick, True)])
    return Dialog(gui, title, build).result


def confirm(gui, title, text, yes="OK"):
    def build(d):
        d.label(text)
        row = d.buttons([("Cancel", lambda: d.close(False), False), (yes, lambda: d.close(True), True)])
        row.winfo_children()[-1].focus_set()
    return bool(Dialog(gui, title, build).result)


def message(gui, title, text):
    def build(d):
        d.label(text)
        row = d.buttons([("OK", lambda: d.close(True), True)])
        row.winfo_children()[0].focus_set()
    Dialog(gui, title, build)


def resolve_family(root, candidates):
    have = set(tkfont.families(root))
    for f in candidates:
        if f.startswith("Tk"):
            return tkfont.nametofont(f, root).actual("family")
        if f in have:
            return f
    return tkfont.nametofont("TkDefaultFont", root).actual("family")
