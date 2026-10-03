"""Phosphor in a window: news and weather through the eras, plus the real terminal app on demand."""

import argparse
import queue
import sys
import threading
import time

try:
    import tkinter as tk
    from tkinter import filedialog
    from tkinter import font as tkfont
except ImportError:  # Linux without the Tk package; main() explains
    tk = None

from .. import __version__
from ..core import (NAME, OFFLINE_CHOICES, SORTS, THEME_NAMES, FeedStore, Library, Weather, add_feeds,
                    arrange, article_text, conditions, find_places, get_article, html_to_paragraphs,
                    load_config, location_from, merge_stories, open_url, place_label, probe_feed, read_opml,
                    save_config, short_err)
from .eras import BY_KEY, ERAS, MAC, colors_for, system_dark
from .looks import LOOKS, stamp_saved, unit_letter

if tk:
    from .page import Page, ask, choose, confirm, message, resolve_family

MOD = "Command" if MAC else "Control"
MOD_LABEL = "Cmd" if MAC else "Ctrl"
TEXT_STEPS = (-2, -1, 0, 1, 2, 3, 4)
STARTED = time.time()
WEB = ("earlyweb", "portal")   # the browser eras: a toolbar, underlined links, a scroll bar


class Gui:
    def __init__(self, args):
        self.args = args
        self.cfg = load_config()
        if self.cfg.get("gui_era") not in BY_KEY:
            self.cfg["gui_era"] = "modern"
        self.library = Library()
        self.store = FeedStore(self.library)
        self.wx = Weather(self.library)
        self.articles = {}
        self.read = set(self.cfg.get("read", []))
        self.mod_label = MOD_LABEL
        self.version = __version__

        self.root = tk.Tk(className=NAME)
        self.root.title(NAME)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        reported = self.root.winfo_fpixels("1i") / 96
        dpi = reported
        if dpi < 1.25 and self.root.winfo_screenwidth() >= 2600 and not MAC:
            dpi = 2  # Xwayland without scaling reports a huge screen at 96 dpi
        self.scale = max(1.0, dpi)
        boost = self.scale / max(1.0, reported)
        if boost > 1.01:  # Tk believes the screen is 96 dpi: scale every font (and the menus and dialogs) to match
            self.root.tk.call("tk", "scaling", float(self.root.tk.call("tk", "scaling")) * boost)
            for name in tkfont.names(self.root):
                f = tkfont.nametofont(name, self.root)
                size = f.cget("size")
                if size < 0:  # given in pixels, which tk scaling doesn't touch
                    f.configure(size=round(size * boost))
        try:
            import base64
            from ..icon import png
            self.icon = tk.PhotoImage(master=self.root, data=base64.b64encode(png(4)).decode())
            self.root.iconphoto(True, self.icon)
        except tk.TclError:
            pass

        self.q = queue.Queue()
        self.screen = ("home",)
        self.back_stack, self.fwd_stack = [], []
        self.sort, self.filt, self.full = "NEWEST", "", True
        self.pages = {}
        self.weather_data, self.weather_err = None, None
        self.fetching, self.failed = set(), {}
        self.loading_feeds = False
        self.updated = None
        self.flash = None          # a short message for the status line
        self.modal = None
        self.term = None
        self.tt_buf = ""
        self.blink = True
        self.syncing = threading.Event()
        self.container = None

        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        size = self.cfg.get("gui_size") or f"{min(sw - 60, self.px(1200))}x{min(sh - 100, self.px(820))}"
        self.root.geometry(size)
        self.root.minsize(self.px(640), self.px(440))
        self.root.bind("<Key>", self.on_key)
        self.bind_shortcuts()
        self.root.after(80, self.pump)
        self.root.after(1000, self.tick)
        self.apply_era()
        if not getattr(args, "offline", False):  # (the self-test brings its own stories and weather)
            self.load_feeds()
            if self.cfg.get("location"):
                self.load_weather()
        if not self.cfg.get("gui_seen"):
            self.cfg["gui_seen"] = True
            self.save()
            self.say(f"Tip: View › Era travels through time, or press {MOD_LABEL}+[ and {MOD_LABEL}+].")
        if self.cfg.get("gui_mode") == "terminal":
            self.root.after_idle(lambda: self.enter_terminal(boot=not args.no_boot))

    # ------------------------------------------------------------------ basics
    def px(self, n):
        return int(round(n * self.scale))

    def tx(self, s):
        if self.era.upper or (self.era.key == "phosphor" and self.cfg.get("uppercase", True)):
            return s.upper()
        return s

    def save(self):
        self.cfg["read"] = self.cfg.get("read", [])[-3000:]
        try:
            save_config(self.cfg)
        except OSError as e:
            self.say(f"Couldn't save settings: {e}")

    def mark_read(self, link):
        if link in self.read:
            return
        self.read.add(link)
        self.cfg["read"] = (self.cfg.get("read", []) + [link])[-3000:]
        self.save()

    def run_bg(self, fn, done):
        """fn() on a worker thread; done(value, error) back on the Tk thread."""
        def go():
            try:
                v, err = fn(), None
            except Exception as e:  # noqa: BLE001 - reported in the window
                v, err = None, short_err(e)
            self.q.put((done, v, err))
        threading.Thread(target=go, daemon=True).start()

    def pump(self):
        try:
            while True:
                done, v, err = self.q.get_nowait()
                done(v, err)
        except queue.Empty:
            pass
        self.root.after(80, self.pump)

    def tick(self):
        """Once a second: the blinking prompt and the clock in the status line."""
        self.blink = not self.blink
        if not self.term and self.container:
            self.update_status()
        self.root.after(530 if self.era.key == "phosphor" else 1000, self.tick)

    # ------------------------------------------------------------------ data
    def feeds_for(self, key):
        feeds = self.cfg["feeds"]
        return feeds if key is None else [f for f in feeds if f["url"] == key]

    def raw_items(self, key):
        results = []
        for f in self.feeds_for(key):
            c = self.store.cache.get(f["url"])
            if c is not None:
                results.append(c)
            else:  # not fetched yet this session: what the offline library has, so the window fills at once
                results.append({"stories": self.library.stories_for(f["url"], f["title"])})
        return merge_stories(results)

    def items_for(self, key):
        return arrange(self.raw_items(key), self.sort, self.filt, self.read)

    def counts(self, key):
        items = self.raw_items(key)
        return len(items), sum(1 for s in items if s["link"] not in self.read)

    def list_title(self, key):
        if key is None:
            return "All Stories"
        f = self.feeds_for(key)
        return f[0]["title"] if f else "Stories"

    def load_feeds(self, force=False):
        if self.loading_feeds:
            return
        self.loading_feeds = True
        self.update_status()

        def done(res, err):
            self.loading_feeds = False
            self.updated = time.time()
            if err:
                self.say(f"Couldn't load the feeds: {err}")
            else:
                off = [c for c in res if c.get("offline")]
                bad = [f["title"] for f, c in zip(self.cfg["feeds"], res) if c["error"] and not c.get("offline")]
                if off:
                    self.say("Offline: showing the stories saved on this computer.")
                elif bad:
                    self.say("Couldn't reach: " + ", ".join(bad))
            self.refresh_view()
            self.sync_library()

        feeds = list(self.cfg["feeds"])
        self.run_bg(lambda: self.store.get_all(feeds, force), done)

    def sync_library(self):
        if self.syncing.is_set():
            return
        self.syncing.set()
        keep, feeds = int(self.cfg.get("offline_keep", 100)), list(self.cfg["feeds"])

        def done(v, err):
            self.syncing.clear()
            self.update_status()
            if self.screen[0] == "settings":
                self.refresh_view()

        self.run_bg(lambda: self.library.sync(keep, feeds), done)

    def load_weather(self, force=False):
        if not self.cfg.get("location"):
            return

        def done(v, err):
            self.weather_data, self.weather_err = v, err and f"The weather service didn't answer ({err})."
            self.refresh_view()

        self.run_bg(lambda: self.wx.get(self.cfg, force), done)

    def weather_line(self):
        if not self.cfg.get("location"):
            return "Set your city"
        d = self.weather_data
        if not d:
            return self.cfg["location"]["name"].split(",")[0] + ": " + ("loading…" if not self.weather_err else "unavailable")
        cur = d["current"]
        return (f"{self.cfg['location']['name'].split(',')[0]}: {round(cur['temperature_2m'])}°{unit_letter(self.cfg)} "
                f"{conditions(cur['weather_code'], cur.get('is_day', 1))[0].capitalize()}")

    def weather_short(self):
        d = self.weather_data
        return f"{round(d['current']['temperature_2m'])}°" if d else ""

    def weather_stamp(self):
        if self.wx.saved_at:
            return "Offline: " + stamp_saved(self.wx.saved_at)
        d = self.weather_data
        return f"as of {d['current']['time'][11:16]}" if d else ""

    def loading_line(self):
        return "Loading stories…" if self.loading_feeds else "No stories yet."

    def empty_line(self):
        if self.filt:
            return "Nothing matches that search."
        if not self.cfg["feeds"]:
            return "No feeds yet. Add some under Manage Feeds."
        return self.loading_line()

    # -- articles
    def article_for(self, s):
        """(paragraphs, note) for a story; starts fetching the full text when it isn't here yet."""
        link = s["link"]
        summary = html_to_paragraphs(s["summary"]) or [("p", "(No text here. Open it in your browser.)")]
        if not self.full or not link.startswith("http"):
            return summary, None
        paras = article_text(self.library, self.articles, link)
        if paras:
            return paras, None
        if link in self.failed:
            return summary, f"Full text unavailable ({self.failed[link]}). Showing the feed's summary."
        if link not in self.fetching:
            self.fetching.add(link)

            def done(v, err):
                self.fetching.discard(link)
                if not v:
                    self.failed[link] = err or "no article text found"
                if len(self.screen) > 3 and self.screen[3] == link:
                    self.refresh_view()

            self.run_bg(lambda: get_article(self.library, self.articles, link), done)
        return summary, "Getting the full story…"

    # ------------------------------------------------------------------ era and layout
    @property
    def era(self):
        return BY_KEY[self.cfg.get("gui_era", "modern")]

    def dark(self):
        t = self.cfg.get("gui_theme", "system")
        return system_dark() if t == "system" else t == "dark"

    def make_fonts(self):
        step = self.cfg.get("gui_text", 0)
        fonts = {}
        for role, (families, size, style) in self.era.fonts.items():
            fam = resolve_family(self.root, families)
            sz = max(7, round(size * (1 + 0.12 * step)))
            if self.era.key == "teletext" and getattr(self, "tt_size", None):
                sz = round(self.tt_size * size / 15)
            fonts[role] = tkfont.Font(self.root, family=fam, size=sz, weight="bold" if "bold" in style else "normal")
        fonts.setdefault("small", fonts["body"])
        fonts.setdefault("ui", fonts["body"])
        fonts["barfont"] = fonts["head"]
        fonts["listhi"] = tkfont.Font(self.root, family=fonts["body"].actual("family"),
                                      size=fonts["body"].actual("size"), weight="bold")
        return fonts

    def apply_era(self):
        """Build the window for the current era (layout, colors, fonts) and draw the screen."""
        era = self.era
        self.colors = c = colors_for(era, self.dark(), self.cfg.get("theme", "green"))
        self.fonts = self.make_fonts()
        self.look = LOOKS[era.key](self)
        if self.container is not None:
            self.container.destroy()
        self.root.configure(bg=c["bg"])
        self.container = tk.Frame(self.root, bg=c["bg"])
        self.container.pack(fill="both", expand=True)
        self.status = tk.Label(self.container, anchor="w", font=self.fonts["ui"] if era.layout == "panes" or
                               era.key in WEB else self.fonts["body"], padx=self.px(8), pady=self.px(3))
        self.status.pack(side="bottom", fill="x")
        self.toolbar_address = None
        self.search_var = None
        if era.key in WEB:
            self.build_browser_bar()
        if era.layout == "panes":
            self.build_panes()
        else:
            self.build_page()
        self.style_status()
        self.fill_era_menu()
        self.root.title(f"{NAME} — {era.label}")
        self.render(fresh=True)

    def page_widget(self, parent, scrollbar):
        p = Page(parent, self, scrollbar)
        self.style_text(p)
        return p

    def style_text(self, p, bg=None, pad=12):
        c, f = self.colors, self.fonts
        bg = bg or c["bg"]
        t = p.t
        p.frame.configure(bg=bg)
        t.configure(bg=bg, fg=c["fg"], font=f["body"], padx=self.px(pad), pady=self.px(pad // 2 + 4),
                    insertbackground=bg, selectbackground=bg, inactiveselectbackground=bg,
                    spacing1=0, spacing3=self.px(1))
        if p.sb:
            p.sb.configure(bg=c.get("face", c["bg"]), troughcolor=bg, activebackground=c["dim"],
                           elementborderwidth=1 if "face" in c else 0, relief="flat")
        portal = self.era.key in WEB
        tag = t.tag_configure
        tag("body", foreground=c["fg"], font=f["body"])
        tag("fg", foreground=c["fg"])
        tag("head", foreground=c["hi"], font=f["head"])
        tag("big", foreground=c["hi"], font=f["big"], spacing1=self.px(2), spacing3=self.px(4))
        tag("headline", foreground=c["hi"], font=f["big"])
        tag("small", font=f["small"])
        tag("dim", foreground=c["dim"])
        tag("hi", foreground=c["hi"])
        tag("link", foreground=c["link"], underline=portal)
        tag("visited", foreground=c["visited"], underline=portal)
        tag("bar", background=c["bar_bg"], foreground=c["bar_fg"])
        tag("barfont", font=f["head"])
        tag("note", foreground=c["text"].get("red") or c["text"].get("orange") or c["hi"])
        tag("para", spacing3=self.px(9))
        tag("center", justify="center")
        tag("mono", font=f.get("mono", f["body"]))
        tag("h2", foreground=c["hi"], font=f["head"], spacing1=self.px(10), spacing3=self.px(6))
        tag("titlelink", foreground=c["link"])
        for name, col in c.get("text", {}).items():
            tag(name, foreground=col)
        tag("white", foreground=c["text"].get("white", c["fg"]))
        tag("blue", foreground=c["text"].get("blue", c["dim"]))
        tag("side", lmargin2=self.px(20), foreground=c["fg"], font=f["ui"], spacing1=self.px(3), spacing3=self.px(3))
        tag("sidehi", lmargin2=self.px(20), foreground=c["hi"], font=self.fonts["listhi"], spacing1=self.px(3), spacing3=self.px(3))
        tag("sidedim", lmargin2=self.px(20), foreground=c["dim"], font=f["small"])
        tag("sidehead", foreground=c["dim"], font=f["small"], spacing1=self.px(10), spacing3=self.px(4))
        tag("listhi", foreground=c["hi"], font=self.fonts["listhi"], spacing1=self.px(6))
        tag("listread", foreground=c["dim"], font=f["body"], spacing1=self.px(6))
        tag("listdim", foreground=c["dim"], font=f["small"], spacing3=self.px(6))
        zero = f["body"].measure("0")
        tag("hang3", lmargin2=zero * 3)
        tag("hang6", lmargin2=zero * 6)
        tag("huge", foreground=c["hi"], font=(f["big"].actual("family"), round(f["body"].actual("size") * 2.6), "bold"))
        tag("indent", lmargin1=f["body"].measure("(•) "), lmargin2=f["body"].measure("(•) "))
        tag("row", lmargin1=self.px(8), lmargin2=self.px(8), rmargin=self.px(8))
        tag("gap", font=(f["small"].actual("family"), 2))
        tag("sel_row", background=c["sel_bg"], foreground=c["sel_fg"])
        t.tag_raise("sel_row")
        t.tag_configure("unseen", elide=True)

    def build_page(self):
        era, c = self.era, self.colors
        self.page = self.page_widget(self.container, scrollbar=era.key in WEB)
        self.pages_shown = [self.page]
        if era.cols and era.key != "teletext":
            self.page.t.configure(width=era.cols + 2)
            self.page.frame.pack(side="top", fill="y", expand=True, anchor="w")
        else:
            self.page.frame.pack(side="top", fill="both", expand=True)
        if era.cols:
            self.page.t.bind("<Configure>", self.char_resize, add="+")
        if era.key == "teletext":
            self.page.t.configure(width=40, padx=self.px(16))
            self.container.bind("<Configure>", self.fit_teletext)
        if era.key == "portal":
            self.page.t.bind("<Configure>", self.center_column)
        if era.key == "earlyweb":
            self.page.t.bind("<Configure>", self.cap_lines)

    def cap_lines(self, e):
        """Early Web runs flush left like an unstyled page, but lines stop at a readable length."""
        self.page.t.tag_configure("cap", rmargin=max(0, e.width - self.px(1000)))

    def center_column(self, e):
        pad = max(self.px(16), (e.width - self.px(860)) // 2)
        if int(str(self.page.t.cget("padx"))) != pad:
            self.page.t.configure(padx=pad)

    def fit_teletext(self, e=None):
        """Teletext fills the TV: pick the text size that fits 40 columns and about 24 rows."""
        if e is not None and e.widget is not self.container:
            return
        w = self.container.winfo_width() - self.px(40)
        h = self.container.winfo_height() - self.status.winfo_height() - self.px(20)
        fam = self.fonts["body"].actual("family")
        best = 10
        for size in range(10, 60):
            f = tkfont.Font(self.root, family=fam, size=size, weight="bold")
            if f.measure("0" * 40) > w or f.metrics("linespace") * 25 > h:
                break
            best = size
        if best != getattr(self, "tt_size", None):
            self.tt_size = best
            self.root.after_idle(self.refit)

    def refit(self):
        self.fonts = self.make_fonts()
        self.style_text(self.page, pad=16)
        self.page.t.configure(padx=self.px(16))
        self.style_status()
        self.render()

    def build_browser_bar(self):
        c, f = self.colors, self.fonts
        early = self.era.key == "earlyweb"
        bar = tk.Frame(self.container, bg=c["face"], bd=2, relief="raised")
        bar.pack(side="top", fill="x")
        row = tk.Frame(bar, bg=c["face"])
        row.pack(fill="x", padx=self.px(4), pady=self.px(3))
        names = ("Back", "Forward", "Home", "Reload") if early else ("◀ Back", "Forward ▶", "Home", "Reload")
        for label, cmd in zip(names, (self.back, self.forward, lambda: self.go(("home",)), self.reload)):
            tk.Button(row, text=label, command=cmd, font=f["ui"], bg=c["face"], fg=c["face_fg"], relief="raised",
                      bd=2, padx=self.px(8), activebackground=c["face"], activeforeground=c["face_fg"],
                      highlightthickness=0, takefocus=0).pack(side="left", padx=(0, self.px(4)))
        loc = tk.Frame(bar, bg=c["face"])
        loc.pack(fill="x", padx=self.px(4), pady=(0, self.px(4)))
        tk.Label(loc, text="URL:" if early else "Location:", font=f["ui"], bg=c["face"], fg=c["face_fg"]).pack(side="left")
        self.toolbar_address = tk.Label(loc, font=f["ui"], bg=c["field"], fg=c["fg"], anchor="w", relief="sunken",
                                        bd=2, padx=self.px(4))
        self.toolbar_address.pack(side="left", fill="x", expand=True, padx=(self.px(6), 0))

    def build_panes(self):
        c, f = self.colors, self.fonts
        head_bg = c["bar_bg"]
        head = tk.Canvas(self.container, height=self.px(46), bg=head_bg, highlightthickness=0, bd=0)
        head.pack(side="top", fill="x")
        tk.Frame(self.container, height=1, bg=c["line"]).pack(side="top", fill="x")
        name = f"{NAME} Reader" if self.era.key == "reader" else NAME
        self.search_var = tk.StringVar(self.root, self.filt)
        entry = tk.Entry(head, textvariable=self.search_var, font=f["ui"], bg=c["bg"], fg=c["fg"], width=28,
                         insertbackground=c["fg"], relief="flat", highlightthickness=1, highlightbackground=c["line"],
                         highlightcolor=c["link"])
        entry.bind("<Return>", lambda e: self.set_filter(self.search_var.get()))
        entry.bind("<Escape>", lambda e: (self.search_var.set(""), self.set_filter(""), self.root.focus_set()))
        reload = tk.Button(head, text="Refresh", command=self.reload, font=f["ui"], bg=c["bg"], fg=c["fg"],
                           activebackground=c["sel_bg"], activeforeground=c["sel_fg"], relief="flat", bd=0,
                           highlightthickness=1, highlightbackground=c["line"], padx=self.px(10), takefocus=0)
        self.search_entry = entry

        def draw(e=None):
            head.delete("all")
            w, h = head.winfo_width(), head.winfo_height()
            if self.era.key == "reader":  # the glossy bar of the day: a light top half over a deeper bottom
                top, bottom = c["gloss"]
                head.create_rectangle(0, 0, w, h // 2, fill=top, outline="")
                head.create_rectangle(0, h // 2, w, h, fill=bottom, outline="")
            head.create_text(self.px(16), h // 2, text=name, anchor="w", fill=c["bar_fg"], font=f["big"])
            if self.era.key == "reader":
                x = self.px(16) + f["big"].measure(name) + self.px(8)
                head.create_text(x, h // 2 - self.px(6), text="beta", anchor="w", fill=c["text"]["orange"],
                                 font=f["small"])
            head.create_window(w - self.px(12), h // 2, window=reload, anchor="e")
            head.create_window(w - self.px(24) - reload.winfo_reqwidth(), h // 2, window=entry, anchor="e")
            head.create_text(w - self.px(32) - reload.winfo_reqwidth() - entry.winfo_reqwidth(), h // 2,
                             text="Search", anchor="e", fill=c["bar_fg"], font=f["ui"])

        head.bind("<Configure>", draw)
        pw = tk.PanedWindow(self.container, orient="horizontal", bg=c["line"], sashwidth=1, bd=0, showhandle=False)
        pw.pack(fill="both", expand=True)
        self.side = self.page_widget(pw, scrollbar=False)
        self.style_text(self.side, bg=c["side_bg"], pad=4)
        self.side.t.configure(width=24)
        pw.add(self.side.frame, minsize=self.px(160), width=self.px(230), stretch="never")
        self.content = tk.Frame(pw, bg=c["bg"])
        pw.add(self.content, stretch="always")
        self.split = tk.PanedWindow(self.content, orient="horizontal", bg=c["line"], sashwidth=1, bd=0)
        self.listp = self.page_widget(self.split, scrollbar=True)
        self.style_text(self.listp, pad=6)
        self.listp.t.configure(width=34)
        self.readp = self.page_widget(self.split, scrollbar=True)
        self.style_text(self.readp, pad=22)
        self.split.add(self.listp.frame, minsize=self.px(220), width=self.px(360), stretch="never")
        self.split.add(self.readp.frame, stretch="always")
        self.mainp = self.page_widget(self.content, scrollbar=True)
        self.style_text(self.mainp, pad=22)
        self.page = self.mainp
        self.panes_outer = pw
        self.container.bind("<Configure>", self.fit_panes, add="+")

    def fit_panes(self, e):
        """Narrow windows: the sidebar and the story list give up room so the story stays readable."""
        if e.widget is not self.container:
            return
        side = max(self.px(150), min(self.px(230), e.width // 5))
        lst = max(self.px(200), min(self.px(380), (e.width - side) * 2 // 5))
        try:
            self.panes_outer.paneconfigure(self.side.frame, width=side)
            self.split.paneconfigure(self.listp.frame, width=lst)
        except tk.TclError:
            pass

    def style_status(self):
        c, key = self.colors, self.era.key
        if key in ("phosphor", "teletype", "teletext"):
            self.status.configure(bg=c["bg"], fg=c["fg"], font=self.fonts["body"])
        elif key == "bbs":
            self.status.configure(bg=c["sel_bg"], fg=c["sel_fg"])
        elif key in WEB:
            self.status.configure(bg=c["face"], fg=c["face_fg"], relief="sunken", bd=1)
        else:
            self.status.configure(bg=c["side_bg"], fg=c["dim"])

    def say(self, text):
        """A message in the status line until the next screen."""
        self.flash = text
        self.update_status()

    def update_status(self):
        if self.term or not self.container:
            return
        key = self.era.key
        msg = self.flash
        busy = self.loading_feeds or bool(self.fetching)
        hints = self.hints()
        if key == "phosphor":
            text = "]" + (self.tx(msg) + " " if msg else "") + ("█" if self.blink else " ")
            if not msg:
                text += "   " + self.tx(hints)
        elif key == "teletype":
            text = self.tx(msg or hints)
        elif key == "teletext":
            text = f"P{self.tt_buf:_<3}" if self.tt_buf else (msg or "Key a page number, or use the colored links")
        elif key == "bbs":
            left = max(0, 60 - int((time.time() - STARTED) // 60))
            text = f" Node 1 │ 14,400 bps │ Time left: {left} min │ " + (msg or hints)
        elif key == "portal":
            text = msg or ("Connecting to feeds…" if busy else "Document: Done")
        elif key == "earlyweb":
            text = msg or ("Transferring data…" if busy else "Document done.")
        else:
            parts = [msg] if msg else []
            if busy:
                parts.append("Updating…")
            elif self.updated:
                parts.append("Updated " + time.strftime("%H:%M", time.localtime(self.updated)))
            parts.append(f"{self.library.count()[1]} stories saved for offline")
            text = "   ·   ".join(parts)
        self.status.configure(text=text)

    def hints(self):
        s = self.screen[0]
        if s == "list":
            return "1-0 read  N/P page  S sort  / search  R reload  Esc back"
        if s == "story":
            return "Space scroll  N/P next/prev  T full text/summary  O browser  Esc back"
        if s == "weather":
            return "R refresh  L place  U units  Esc back"
        return "Press a number, or arrows + Return"

    def address(self):
        s = self.screen
        if s[0] == "list":
            return "phosphor://news/" + ("all" if s[1] is None else self.slug(s[1]))
        if s[0] == "story":
            return f"phosphor://news/{'all' if s[1] is None else self.slug(s[1])}/{s[2] + 1}"
        return "phosphor://" + s[0]

    def slug(self, url):
        t = self.list_title(url)
        return "".join(ch if ch.isalnum() else "-" for ch in t.lower()).strip("-")

    # ------------------------------------------------------------------ drawing
    def render(self, fresh=False, keep=False):
        """Draw the current screen. keep: a background update; hold each pane's scroll and selection."""
        if self.term:
            return
        era, look, s = self.era, self.look, self.screen
        saved = {}
        if keep:
            for p in self.all_pages():
                saved[id(p)] = (p.t.yview()[0], p.sel)
        if self.toolbar_address is not None:
            self.toolbar_address.configure(text=self.address())
        if era.layout == "panes":
            self.render_panes()
        else:
            p = self.page
            self.drawn_chars = self.page_chars()
            p.clear()
            if s[0] == "home":
                look.home(p)
            elif s[0] == "list":
                items, page, pages, start = self.paged(s[1])
                look.story_list(p, s[1], items, page, pages, start)
            elif s[0] == "story":
                items, idx = self.story_items()
                if idx is None:
                    self.screen = ("list", s[1])
                    return self.render()
                paras, note = self.article_for(items[idx])
                look.story(p, s[1], items, idx, paras, note)
            elif s[0] == "weather":
                look.weather(p, self.weather_data, self.weather_err if self.cfg.get("location") else
                             "No place set yet. Pick Change Place.")
            elif s[0] == "feeds":
                look.feeds(p)
            elif s[0] == "settings":
                look.settings(p)
            if era.key == "earlyweb":
                p.t.tag_add("cap", "1.0", "end")
            p.done(select=0 if s[0] in ("home", "settings", "feeds", "list") and not keep else None)
            if fresh and era.key in ("teletype", "phosphor") and self.cfg.get("typewriter", True):
                p.reveal(10 if era.key == "phosphor" else 22)
        for p in self.all_pages():
            if id(p) in saved:
                y, sel = saved[id(p)]
                p.t.yview_moveto(y)
                if sel >= 0:
                    p.select(sel, see=False)
        self.update_status()

    def all_pages(self):
        if self.era.layout == "panes":
            return [self.side, self.listp, self.readp, self.mainp]
        return [self.page]

    def show_split(self, split):
        if split:
            self.mainp.frame.pack_forget()
            self.split.pack(fill="both", expand=True)
        else:
            self.split.pack_forget()
            self.mainp.frame.pack(fill="both", expand=True)

    def render_panes(self):
        s, look = self.screen, self.look
        self.side.clear()
        look.sidebar(self.side)
        self.side.done(top=False)
        if s[0] in ("home", "list", "story"):
            self.show_split(True)
            key = s[1] if len(s) > 1 else None
            items = self.items_for(key)
            idx = None
            if s[0] == "story":
                items, idx = self.story_items()
            self.listp.clear()
            look.list_rows(self.listp, key, items, idx)
            self.listp.done(top=idx is None)
            if idx is not None:
                self.listp.select(idx)
            self.readp.clear()
            if idx is not None:
                paras, note = self.article_for(items[idx])
                look.article(self.readp, items[idx], paras, note, idx, len(items))
            else:
                look.today(self.readp)
            self.readp.done()
        else:
            self.show_split(False)
            p = self.mainp
            p.clear()
            if s[0] == "weather":
                look.weather(p, self.weather_data, self.weather_err if self.cfg.get("location") else
                             "No place set yet. Pick Change Place.")
            elif s[0] == "feeds":
                look.feeds(p)
            else:
                look.settings(p)
            p.done()

    def refresh_view(self):
        """New data arrived: redraw without losing the reader's place."""
        if not self.term and self.modal is None:
            self.render(keep=True)

    def paged(self, key):
        items = self.items_for(key)
        per = self.look.per_page
        if not per:
            return items, 0, 1, 0
        pages = max(1, -(-len(items) // per))
        page = max(0, min(self.pages.get(key, 0), pages - 1))
        self.pages[key] = page
        return items, page, pages, page * per

    def story_items(self):
        """(items, index) for the story screen, following the story if a reload moved it."""
        s = self.screen
        items = self.items_for(s[1])
        link = s[3] if len(s) > 3 else None
        if link:
            for i, it in enumerate(items):
                if it["link"] == link:
                    return items, i
            # it dropped out of the list (a search, or the feed moved on): keep showing it
            gone = next((it for it in self.raw_items(s[1]) if it["link"] == link), None)
            if gone:
                return [gone], 0
        if items and 0 <= s[2] < len(items):
            return items, s[2]
        return items, None

    def page_chars(self):
        """How many characters fit across the page now (the screen eras size their bars to it)."""
        t = self.page.t
        width = t.winfo_width() - 2 * int(str(t.cget("padx")))
        if width < 50:
            return 200
        return max(30, width // max(1, self.fonts["body"].measure("0")) - 1)

    def char_resize(self, e):
        if self.page_chars() != getattr(self, "drawn_chars", None):
            if getattr(self, "resize_job", None):
                self.root.after_cancel(self.resize_job)
            self.resize_job = self.root.after(120, lambda: self.render(keep=True))

    def content_width(self):
        p = self.page if self.era.layout != "panes" else self.mainp
        return max(self.px(400), min(p.t.winfo_width() - self.px(60), self.px(900)))

    # ------------------------------------------------------------------ navigation
    def go(self, screen, push=True):
        if screen[0] == "story":
            items = self.items_for(screen[1])
            if not (0 <= screen[2] < len(items)):
                return
            link = items[screen[2]]["link"]
            screen = ("story", screen[1], screen[2], link)
            self.mark_read(link)
            if self.look.per_page:
                self.pages[screen[1]] = screen[2] // self.look.per_page
        if push and screen != self.screen:
            # the panes eras open stories in place: don't stack every story read
            if not (self.era.layout == "panes" and screen[0] == "story" and self.screen[0] in ("story", "list", "home")
                    and self.screen[0] != "home"):
                self.back_stack.append(self.screen)
            self.fwd_stack = []
        self.screen = screen
        self.flash = None
        self.tt_buf = ""
        self.render(fresh=True)

    def back(self):
        if self.back_stack:
            self.fwd_stack.append(self.screen)
            self.go(self.back_stack.pop(), push=False)
        elif self.screen[0] != "home":
            self.go(("home",), push=False)

    def forward(self):
        if self.fwd_stack:
            self.back_stack.append(self.screen)
            self.go(self.fwd_stack.pop(), push=False)

    def next_story(self, d):
        s = self.screen
        if s[0] == "story":
            items, idx = self.story_items()
            if idx is not None and 0 <= idx + d < len(items):
                self.go(("story", s[1], idx + d), push=False)
            else:
                self.say("That's the last story." if d > 0 else "That's the first story.")
        elif s[0] in ("list", "home") and self.era.layout == "panes":
            key = s[1] if len(s) > 1 else None
            if self.items_for(key):
                self.go(("story", key, 0 if d > 0 else len(self.items_for(key)) - 1))

    def turn(self, d):
        key = self.screen[1]
        self.pages[key] = self.pages.get(key, 0) + d
        self.render(fresh=True)

    def teletext_number(self):
        s = self.screen
        if s[0] == "home":
            return 100
        if s[0] == "list":
            return 101 if s[1] is None else 301 + self.feed_index(s[1])
        if s[0] == "story":
            return 102 + s[2] if s[1] is None and s[2] < 98 else 101
        return {"weather": 400, "settings": 700, "feeds": 701}.get(s[0], 100)

    def feed_index(self, url):
        return next((i for i, f in enumerate(self.cfg["feeds"]) if f["url"] == url), 0)

    def teletext_goto(self, n):
        feeds = self.cfg["feeds"]
        if n == 100:
            self.go(("home",))
        elif n == 101:
            self.go(("list", None))
        elif 102 <= n <= 199 and n - 102 < len(self.items_for(None)):
            self.go(("story", None, n - 102))
        elif 301 <= n < 301 + len(feeds):
            self.go(("list", feeds[n - 301]["url"]))
        elif n == 400:
            self.go(("weather",))
        elif n == 700:
            self.go(("settings",))
        elif n == 701:
            self.go(("feeds",))
        else:
            self.say(f"P{n} is not in this service. Try 100 for the index.")

    # ------------------------------------------------------------------ keys
    def bind_shortcuts(self):
        r = self.root
        for seq, fn in ((f"<{MOD}-q>", self.quit), (f"<{MOD}-r>", self.reload),
                        (f"<{MOD}-equal>", lambda: self.zoom(1)), (f"<{MOD}-plus>", lambda: self.zoom(1)),
                        (f"<{MOD}-minus>", lambda: self.zoom(-1)),
                        (f"<{MOD}-bracketleft>", lambda: self.step_era(-1)),
                        (f"<{MOD}-bracketright>", lambda: self.step_era(1)),
                        (f"<{MOD}-Shift-W>", self.enter_terminal), (f"<{MOD}-Shift-w>", self.enter_terminal),
                        (f"<{MOD}-f>", self.search),
                        ("<Alt-Left>", self.back), ("<Alt-Right>", self.forward), ("<Alt-Home>", lambda: self.go(("home",)))):
            r.bind(seq, lambda e, fn=fn: None if self.term or self.modal else (fn(), "break")[1])

    def active_page(self):
        if self.era.layout == "panes":
            return self.mainp if self.screen[0] in ("weather", "feeds", "settings") else self.listp
        return self.page

    def reading_page(self):
        if self.era.layout == "panes" and self.screen[0] in ("home", "list", "story"):
            return self.readp
        return self.page

    def on_key(self, e):
        if self.term or self.modal or isinstance(e.widget, (tk.Entry, tk.Button)):
            return None
        if e.state & 0x4 or (MAC and e.state & 0x8) or (e.state & 0x8 and not MAC and e.keysym not in ("Left", "Right")):
            return None  # Ctrl/Cmd/Alt combinations belong to the menus
        ks, ch = e.keysym, (e.char or "")
        p = self.active_page()
        if p.revealing():
            p.stop_reveal()
            return "break"
        s = self.screen[0]
        panes = self.era.layout == "panes"
        if self.era.key == "teletext" and ch.isdigit():
            self.tt_buf += ch
            if len(self.tt_buf) == 3:
                n, self.tt_buf = int(self.tt_buf), ""
                self.teletext_goto(n)
            else:
                self.update_status()
            return "break"
        low = ch.lower()
        if ks in ("Up", "Down"):
            d = -1 if ks == "Up" else 1
            if panes and s in ("story", "list", "home"):
                if s == "story":
                    self.next_story(d)
                else:
                    self.next_story(1)
            elif s == "story":
                p.scroll(d)
            else:
                p.move(d)
        elif ks in ("Prior", "Next"):
            self.reading_page().scroll(-1 if ks == "Prior" else 1, "pages")
        elif ks == "space":
            self.reading_page().scroll(1, "pages")
        elif ks in ("Home", "End"):
            self.reading_page().t.yview_moveto(0 if ks == "Home" else 1)
        elif ks in ("Return", "KP_Enter"):
            if not p.activate() and panes and s in ("list", "home"):
                self.next_story(1)
        elif ks in ("Escape", "BackSpace"):
            if self.filt and s == "list":
                self.set_filter("")
            else:
                self.back()
        elif ks == "Left" and s == "story" and not panes:
            self.back()
        elif s == "story" and low in ("n", "p") or (s == "story" and ks == "Right"):
            self.next_story(-1 if low == "p" else 1)
        elif s in ("list", "story") and low in ("o", "t") or s in ("list", "story", "home") and ch in ("/",):
            {"o": self.open_story, "t": self.toggle_full, "/": self.search}[low]()
        elif s == "list" and low in ("n", "p", "s", "r", "m"):
            {"n": lambda: self.turn(1), "p": lambda: self.turn(-1), "s": self.cycle_sort, "r": self.reload,
             "m": self.mark_page}[low]()
        elif s == "weather" and low in ("r", "l", "u"):
            {"r": self.refresh_weather, "l": self.change_location, "u": self.toggle_units}[low]()
        elif low and low in p.keys:
            p.select(p.keys[low], see=True)
            p.activate()
        elif low == "r":
            self.reload()
        else:
            return None
        return "break"

    # ------------------------------------------------------------------ commands
    def reload(self):
        self.load_feeds(force=True)
        if self.cfg.get("location"):
            self.load_weather(force=True)

    def refresh_weather(self):
        if not self.cfg.get("location"):
            self.change_location()
            return
        self.weather_data, self.weather_err = None, None
        self.render()
        self.load_weather(force=True)

    def open_story(self):
        s = self.screen
        story = None
        if s[0] == "story":
            items, idx = self.story_items()
            story = items[idx] if idx is not None else None
        elif s[0] == "list":
            p = self.active_page()
            items, page, pages, start = self.paged(s[1])
            if p.sel >= 0 and start + p.sel < len(items):
                story = items[start + p.sel]
        if story:
            self.mark_read(story["link"])
            self.say("Opening in your browser…" if open_url(story["link"]) else "Couldn't open a browser.")

    def toggle_full(self):
        self.full = not self.full
        self.render()

    def cycle_sort(self):
        self.sort = SORTS[(SORTS.index(self.sort) + 1) % len(SORTS)]
        self.pages = {}
        self.say(f"Sorted by {self.sort.lower()}.")
        self.render(fresh=True)

    def search(self):
        if self.search_var is not None:
            self.search_entry.focus_set()
            self.search_entry.select_range(0, "end")
            return
        q = ask(self, "Search", "Show stories whose title or source has these words (leave blank to show all):", self.filt)
        if q is not None:
            self.set_filter(q)

    def set_filter(self, q):
        self.filt = q.strip()
        self.pages = {}
        if self.screen[0] not in ("list", "story", "home"):
            self.screen = ("list", None)
        elif self.screen[0] == "story":
            self.screen = ("list", self.screen[1])
        self.render(fresh=True)

    def mark_page(self):
        items, page, pages, start = self.paged(self.screen[1])
        per = self.look.per_page or len(items)
        new = [s["link"] for s in items[start:start + per] if s["link"] not in self.read]
        self.read.update(new)
        self.cfg["read"] = (self.cfg.get("read", []) + new)[-3000:]
        self.save()
        self.render(keep=True)

    def change_location(self):
        q = ask(self, "Weather", "Your city (for example: Portland, Oregon):",
                (self.cfg.get("location") or {}).get("name", "").split(",")[0])
        if not q:
            return
        self.say("Looking up places…")

        def done(res, err):
            if err or not res:
                message(self, "Weather", err and f"Couldn't search for places ({err})." or f"No place called “{q}” found.")
                return
            i = 0
            if len(res) > 1:
                i = choose(self, "Which one?", f"Places called “{q}”:", [place_label(r) for r in res])
                if i is None:
                    return
            self.cfg["location"] = location_from(res[i])
            self.wx.forget()
            self.weather_data = self.weather_err = None
            self.save()
            self.load_weather(force=True)
            self.render()

        self.run_bg(lambda: find_places(q), done)

    def toggle_units(self):
        self.cfg["units"] = "celsius" if self.cfg.get("units") == "fahrenheit" else "fahrenheit"
        self.save()
        self.wx.forget()
        self.weather_data = None
        self.render()
        self.load_weather(force=True)

    def add_feed(self):
        url = ask(self, "Add a Feed", "The feed's address, or just the website's (Phosphor finds the feed):")
        if not url:
            return
        self.say("Looking for a feed…")

        def done(res, err):
            if not res:
                message(self, "Add a Feed", f"No feed found at {url}" + (f" ({err})." if err else "."))
                return
            final, title = res
            if any(f["url"] == final for f in self.cfg["feeds"]):
                self.say("You already have that feed.")
                return
            name = ask(self, "Add a Feed", "Name it:", title or final.split("/")[2])
            if name is None:
                return
            self.cfg["feeds"].append({"title": name or final, "url": final})
            self.save()
            self.say(f"Added {name or final}.")
            self.render(keep=True)
            self.load_feeds()

        self.run_bg(lambda: probe_feed(url), done)

    def import_opml(self):
        path = filedialog.askopenfilename(parent=self.root, title="Import feeds from OPML",
                                          filetypes=[("OPML", "*.opml *.xml"), ("All files", "*")])
        if not path:
            return
        try:
            n = add_feeds(self.cfg, read_opml(path))
        except Exception as e:  # noqa: BLE001 - any unreadable file
            message(self, "Import OPML", f"Couldn't read that file ({short_err(e)}).")
            return
        self.save()
        self.say(f"Imported {n} feed{'s' if n != 1 else ''}.")
        self.render(keep=True)
        self.load_feeds()

    def feed_menu(self, i):
        feeds = self.cfg["feeds"]
        f = feeds[i]
        pick = choose(self, f["title"], f["url"], ["Read it", "Rename", "Move up", "Move down", "Remove"])
        if pick is None:
            return
        if pick == 0:
            self.go(("list", f["url"]))
            return
        if pick == 1:
            name = ask(self, "Rename", "New name:", f["title"])
            if not name:
                return
            f["title"] = name
            self.store.cache.pop(f["url"], None)
            self.load_feeds()
        elif pick in (2, 3):
            j = i - 1 if pick == 2 else i + 1
            if 0 <= j < len(feeds):
                feeds[i], feeds[j] = feeds[j], feeds[i]
        elif pick == 4:
            if not confirm(self, "Remove Feed", f"Remove “{f['title']}”?", "Remove"):
                return
            feeds.pop(i)
        self.save()
        self.render(keep=True)

    def set_era(self, key):
        if key == self.cfg.get("gui_era"):
            return
        self.cfg["gui_era"] = key
        self.tt_size = None
        self.save()
        self.flash = None
        self.apply_era()
        self.say(f"Welcome to {BY_KEY[key].year}.")

    def step_era(self, d):
        keys = [e.key for e in ERAS]
        self.set_era(keys[(keys.index(self.era.key) + d) % len(keys)])

    def set_theme(self, v):
        self.cfg["gui_theme"] = v
        self.save()
        self.apply_era()

    def cycle_phosphor(self):
        names = list(THEME_NAMES)
        self.cfg["theme"] = names[(names.index(self.cfg.get("theme", "green")) + 1) % len(names)]
        self.save()
        self.apply_era()

    def toggle_typewriter(self):
        self.cfg["typewriter"] = not self.cfg.get("typewriter", True)
        self.save()
        self.render(keep=True)

    def cycle_offline(self):
        keep = int(self.cfg.get("offline_keep", 100))
        later = [n for n in OFFLINE_CHOICES if n > keep]
        self.cfg["offline_keep"] = later[0] if later else OFFLINE_CHOICES[0]
        self.save()
        self.render(keep=True)
        self.sync_library()

    def zoom(self, d):
        steps = TEXT_STEPS
        cur = self.cfg.get("gui_text", 0)
        i = steps.index(cur) + d if cur in steps else 2
        if 0 <= i < len(steps):
            self.cfg["gui_text"] = steps[i]
            self.save()
            if self.term:
                self.term.zoom()
            else:
                self.apply_era()

    # ------------------------------------------------------------------ terminal view
    def enter_terminal(self, boot=False):
        if self.term or self.modal:
            return
        self.cfg["gui_mode"] = "terminal"
        self.save()
        from .console import ConsoleView
        self.term = ConsoleView(self)
        try:
            self.term.start(boot)
        except Exception as e:  # noqa: BLE001 - never leave the window empty
            self.term.close()
            self.term = None
            self.cfg["gui_mode"] = "window"
            message(self, "Terminal View", f"The terminal view couldn't start:\n{e}")

    def left_terminal(self, why, crash=None):
        self.term = None
        self.read = set(self.cfg.get("read", []))
        if why == "quit":
            self.quit()
            return
        self.cfg["gui_mode"] = "window"
        self.save()
        self.root.config(menu=self.menubar)
        self.apply_era()  # settings (color, units) may have changed in there
        if crash is not None:
            message(self, "Terminal View", f"The terminal view stopped because of an error:\n{crash}")

    def term_px(self):
        return round(15 * (1 + 0.12 * self.cfg.get("gui_text", 0)) * self.scale)

    # ------------------------------------------------------------------ menus
    def build_menu(self):
        m = self.menubar = tk.Menu(self.root)

        def menu(label):
            sub = tk.Menu(m, tearoff=False)
            m.add_cascade(label=label, menu=sub, underline=0)
            return sub

        f = menu("File")
        f.add_command(label="Reload", accelerator=f"{MOD_LABEL}+R", command=self.reload)
        f.add_command(label="Add a Feed…", command=self.add_feed)
        f.add_command(label="Import Feeds (OPML)…", command=self.import_opml)
        f.add_separator()
        f.add_command(label="Quit", accelerator=f"{MOD_LABEL}+Q", command=self.quit)
        v = menu("View")
        self.era_menu = tk.Menu(v, tearoff=False)
        v.add_cascade(label="Era", menu=self.era_menu)
        v.add_command(label="Earlier Era", accelerator=f"{MOD_LABEL}+[", command=lambda: self.step_era(-1))
        v.add_command(label="Later Era", accelerator=f"{MOD_LABEL}+]", command=lambda: self.step_era(1))
        self.theme_var = tk.StringVar(self.root, self.cfg.get("gui_theme", "system"))
        lt = tk.Menu(v, tearoff=False)
        for val, label in (("system", "Match My Computer"), ("light", "Light"), ("dark", "Dark")):
            lt.add_radiobutton(label=label, value=val, variable=self.theme_var, command=lambda val=val: self.set_theme(val))
        v.add_cascade(label="Light or Dark", menu=lt)
        v.add_separator()
        v.add_command(label="Bigger Text", accelerator=f"{MOD_LABEL}+=", command=lambda: self.zoom(1))
        v.add_command(label="Smaller Text", accelerator=f"{MOD_LABEL}+-", command=lambda: self.zoom(-1))
        v.add_separator()
        v.add_command(label="Terminal View", accelerator=f"{MOD_LABEL}+Shift+W", command=self.enter_terminal)
        g = menu("Go")
        g.add_command(label="Back", accelerator="Alt+Left", command=self.back)
        g.add_command(label="Forward", accelerator="Alt+Right", command=self.forward)
        g.add_command(label="Home", accelerator="Alt+Home", command=lambda: self.go(("home",)))
        g.add_separator()
        g.add_command(label="Weather", command=lambda: self.go(("weather",)))
        g.add_command(label="All Stories", command=lambda: self.go(("list", None)))
        g.add_command(label="Search…", accelerator=f"{MOD_LABEL}+F", command=self.search)
        g.add_command(label="Manage Feeds", command=lambda: self.go(("feeds",)))
        g.add_command(label="Settings", command=lambda: self.go(("settings",)))
        h = menu("Help")
        h.add_command(label="Keyboard Shortcuts", command=self.shortcuts)
        h.add_command(label=f"About {NAME}", command=self.about)
        self.root.config(menu=m)

    def fill_era_menu(self):
        if not hasattr(self, "menubar"):
            self.build_menu()
        self.era_var = getattr(self, "era_var", None) or tk.StringVar(self.root)
        self.era_var.set(self.era.key)
        self.theme_var.set(self.cfg.get("gui_theme", "system"))
        self.era_menu.delete(0, "end")
        for e in ERAS:
            self.era_menu.add_radiobutton(label=e.label, value=e.key, variable=self.era_var,
                                          command=lambda k=e.key: self.set_era(k))

    def shortcuts(self):
        message(self, "Keyboard Shortcuts", "\n".join([
            "Number keys or arrows + Return: pick from a menu or list",
            "Esc or Backspace: back      Alt+Left / Alt+Right: back / forward",
            "N / P: next or previous story (or page of stories)",
            "Space, Page Up/Down: scroll a story",
            "T: full text or the feed's summary      O: open in your browser",
            "S: sort      / or Ctrl+F: search      R: reload      M: mark page read",
            "Weather: R refresh, L change place, U °F/°C",
            "Teletext: key in any three-digit page number (100 = index)",
            f"{MOD_LABEL}+[ and {MOD_LABEL}+]: travel to an earlier or later era",
            f"{MOD_LABEL}+= / {MOD_LABEL}+-: bigger or smaller text",
            f"{MOD_LABEL}+Shift+W: terminal view (and back)",
        ]))

    def about(self):
        stories, texts = self.library.count()
        message(self, f"About {NAME}", f"{NAME} {__version__}\nNews and weather through the eras.\n\n"
                f"Weather: Open-Meteo. News: the feeds you choose.\n"
                f"Saved for offline reading: {stories} stories ({texts} with full text).\n\n"
                f"In a terminal, run  phosphor  for {NAME} Terminal.")

    # ------------------------------------------------------------------ quitting
    def quit(self):
        if self.term:
            self.term.request("quit")
            return
        try:
            if self.root.state() == "normal":
                self.cfg["gui_size"] = f"{self.root.winfo_width()}x{self.root.winfo_height()}"
        except tk.TclError:
            pass
        self.save()
        self.library.save()
        self.root.destroy()


def main():
    ap = argparse.ArgumentParser(prog="phosphor-gui", description="Phosphor: news and weather through the eras")
    ap.add_argument("--no-boot", action="store_true", help="skip the terminal view's boot sequence")
    ap.add_argument("--era", choices=[e.key for e in ERAS], help="start in this era")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    ap.add_argument("--self-test", metavar="REPORT", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if tk is None:
        sys.exit("phosphor-gui needs Tk. On Arch: sudo pacman -S tk   On Debian/Ubuntu: sudo apt install python3-tk")
    if sys.platform == "win32":
        try:  # crisp text on high-DPI screens
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    if args.self_test:
        from ..selftest import window_main
        window_main(args.self_test)
        return
    if args.era:
        cfg = load_config()
        cfg["gui_era"] = args.era
        try:
            save_config(cfg)
        except OSError:
            pass
    Gui(args).root.mainloop()


if __name__ == "__main__":
    main()
