#!/usr/bin/env python3
"""
Phosphor Terminal  --  a green-screen terminal for weather and RSS.

Pure Python standard library. No API keys.
Config lives in ~/.config/phosphor/config.json; the offline library in ~/.local/share/phosphor.
"""

import argparse
import os
import sys
import textwrap
import threading
import time
from datetime import datetime

from . import __version__ as VERSION
from .core import (APP, ART, CONFIG_PATH, OFFLINE_CHOICES, SORTS, FeedStore, Library, Weather, add_feeds, ago,
                   arrange, article_text, big, compass, conditions, day_name, find_places, get_article,
                   html_to_paragraphs, hourly_from_now, load_config, location_from, merge_stories,
                   add_feeds, open_url, place_label, probe_feed, read_opml, save_config, short_err, truncate)

try:
    import curses
except ImportError:  # Windows without the windows-curses package
    sys.exit("phosphor needs curses. On Windows run: pip install windows-curses")

# 256-color palette indices: (normal, dim, bright); plus 8-color fallback
THEMES = {
    "green": ((83, 28, 157), curses.COLOR_GREEN),
    "amber": ((214, 130, 222), curses.COLOR_YELLOW),
    "white": ((252, 243, 231), curses.COLOR_WHITE),
}


# ---------------------------------------------------------------------- UI --

def ch(k):
    return k if isinstance(k, str) else None


ENTER = ("\n", "\r", curses.KEY_ENTER)
BACK = ("\x1b", "q", "Q", curses.KEY_BACKSPACE, "\x7f", "\b", curses.KEY_LEFT)
SPIN = "|/-\\"


class UI:
    def __init__(self, stdscr, cfg):
        self.s = stdscr
        self.cfg = cfg
        self.buf = []
        self.msg = None
        self.status = ""      # e.g. OFFLINE, shown in the header bar
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        stdscr.keypad(True)
        curses.start_color()
        self.apply_theme()

    def apply_theme(self):
        (fg, dim, hi), basic = THEMES[self.cfg["theme"]]
        if curses.COLORS >= 256:
            bg = 16
            extra_dim = extra_hi = 0
        else:
            fg = dim = hi = basic
            bg = curses.COLOR_BLACK
            extra_dim, extra_hi = curses.A_DIM, curses.A_BOLD
        curses.init_pair(1, fg, bg)
        curses.init_pair(2, bg, fg)
        curses.init_pair(3, dim, bg)
        curses.init_pair(4, hi, bg)
        self.N = curses.color_pair(1)
        self.INV = curses.color_pair(2)
        self.DIM = curses.color_pair(3) | extra_dim
        self.HI = curses.color_pair(4) | curses.A_BOLD | extra_hi
        self.s.bkgd(" ", self.N)

    def dims(self):
        """(rows, content width, left edge): left-justified like any terminal program."""
        rows, cols = self.s.getmaxyx()
        return rows, min(cols, 100), 0

    def tx(self, s):
        return s.upper() if self.cfg.get("uppercase") else s

    # -- buffered drawing (lets us "type" a screen out row by row)
    def begin(self):
        self.buf = []

    def put(self, y, x, text, attr=None, raw=False):
        self.buf.append((y, x, text if raw else self.tx(text), self.N if attr is None else attr))

    def _draw(self, y, x, text, attr):
        rows, cols = self.s.getmaxyx()
        if y < 0 or y >= rows or x >= cols or x < 0:
            return
        try:
            self.s.addstr(y, x, text[: cols - x], attr)
        except curses.error:
            pass  # writing the bottom-right cell always "fails"

    def show(self, animate=False):
        rows, cols = self.s.getmaxyx()
        self.s.erase()
        if rows < 16 or cols < 50:
            self._draw(0, 0, "TERMINAL TOO SMALL (NEED 50X16)", self.HI)
            self.s.refresh()
            return
        anim = animate and self.cfg.get("typewriter", True)
        items = sorted(self.buf, key=lambda b: b[0]) if anim else self.buf
        if anim:
            self.s.nodelay(True)
        last = None
        for y, x, text, attr in items:
            if anim and last is not None and y != last:
                self.s.refresh()
                curses.napms(10)
                k = self.s.getch()
                if k != -1:
                    curses.ungetch(k)  # skip the effect but keep the keypress
                    anim = False
            last = y
            self._draw(y, x, text, attr)
        self.s.nodelay(False)
        self.s.refresh()

    def header(self, title):
        rows, cols = self.s.getmaxyx()  # the bar spans the whole terminal
        self.put(0, 0, " " * cols, self.INV)
        self.put(0, 1, APP, self.INV)
        self.put(0, (cols - len(title)) // 2, title, self.INV)
        clock = datetime.now().strftime("%a %H:%M")
        if self.status:
            clock = self.status + "  " + clock
        self.put(0, cols - len(clock) - 1, clock, self.INV)

    def footer(self, hints):
        rows, w, x0 = self.dims()
        if self.msg:
            self.put(rows - 2, x0, truncate(self.msg, w), self.HI)
            self.msg = None
        else:
            self.put(rows - 2, x0, truncate(hints, w), self.DIM)
        self.put(rows - 1, x0, "]", self.N)

    def rule(self, y, char="-"):
        rows, w, x0 = self.dims()
        self.put(y, x0, char * w, self.DIM)

    def badge(self, y, x, label, selected=False):
        self.put(y, x, f" {label} ", self.INV)

    # -- input
    def key(self):
        """Wait for a key with an Apple-style flashing block cursor at the ] prompt."""
        rows, w, x0 = self.dims()
        self.s.timeout(450)
        on = True
        while True:
            self._draw(rows - 1, x0 + 1, "█" if on else " ", self.N)
            self.s.refresh()
            try:
                k = self.s.get_wch()
            except curses.error:
                on = not on
                continue
            if k == curses.KEY_RESIZE:
                curses.update_lines_cols()
            return k

    def echo(self, c):
        rows, w, x0 = self.dims()
        self._draw(rows - 1, x0 + 1, self.tx(c) + "█", self.N)
        self.s.refresh()
        curses.napms(90)

    def prompt(self, label, initial=""):
        buf = list(initial)
        self.s.timeout(450)
        on = True
        while True:
            rows, w, x0 = self.dims()
            line = "]" + self.tx(label) + "? " + "".join(buf)
            line = line[-(w - 2):]
            self._draw(rows - 1, x0, " " * w, self.N)
            self._draw(rows - 1, x0, line, self.N)
            self._draw(rows - 1, x0 + len(line), "█" if on else " ", self.N)
            self.s.refresh()
            try:
                k = self.s.get_wch()
            except curses.error:
                on = not on
                continue
            on = True
            if k in ENTER:
                return "".join(buf).strip()
            if k == "\x1b":
                return None
            if k in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                if buf:
                    buf.pop()
            elif k == "\x15":
                buf.clear()
            elif isinstance(k, str) and k.isprintable():
                buf.append(k)

    def wait(self, fn, msg="PLEASE WAIT"):
        """Run fn in a thread while showing a spinner. Returns (value, error)."""
        result = {}

        def run():
            try:
                result["v"] = fn()
            except Exception as e:
                result["e"] = e

        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(0.05)
        i = 0
        self.s.timeout(90)
        while t.is_alive():
            rows, w, x0 = self.dims()
            text = f"  {self.tx(msg)} {SPIN[i % 4]}  "
            bw = max(len(text), 26)
            bx = x0 + (w - bw) // 2
            y = rows // 2 - 1
            track = bw - 6
            pos = i % (track * 2 - 2) if track > 1 else 0
            if pos >= track:
                pos = track * 2 - 2 - pos
            bar = "".join("█" if j == pos else "·" for j in range(track))
            self._draw(y - 1, bx, " " * bw, self.INV)
            self._draw(y, bx, text.center(bw), self.INV)
            self._draw(y + 1, bx, ("[" + bar + "]").center(bw), self.INV)
            self._draw(y + 2, bx, "ESC TO CANCEL".center(bw), self.INV)
            self.s.refresh()
            try:
                k = self.s.get_wch()
            except curses.error:
                k = None
            if k == "\x1b":
                return None, "CANCELLED"
            i += 1
        if "e" in result:
            return None, short_err(result["e"])
        return result.get("v"), None


# --------------------------------------------------------------------- app --

class App:
    """The terminal app. The window app's terminal view runs this same class, sharing its state (`shared`)."""

    def __init__(self, stdscr, args, shared=None):
        if shared:
            self.cfg, self.library, self.store, self.wx, self.articles = (
                shared.cfg, shared.library, shared.store, shared.wx, shared.articles)
        else:
            self.cfg = load_config()
            self.library = Library()
            self.store = FeedStore(self.library)
            self.wx = Weather(self.library)
            self.articles = {}
        self.ui = UI(stdscr, self.cfg)
        self.args = args
        self.read = set(self.cfg.get("read", []))
        self.syncing = threading.Event()

    @property
    def weather(self):
        return self.wx.data

    def fetch_weather(self, force=False):
        return self.wx.get(self.cfg, force)

    def save(self):
        try:
            save_config(self.cfg)
        except OSError as e:
            self.ui.msg = f"COULD NOT SAVE CONFIG: {e}"

    def mark_read(self, links):
        new = [l for l in links if l not in self.read]
        if not new:
            return
        self.read.update(new)
        self.cfg["read"] = (self.cfg.get("read", []) + new)[-3000:]
        self.save()

    # -- background
    def prefetch(self):
        def go():
            self.store.get_all(self.cfg["feeds"])
            self.sync_library()
        threading.Thread(target=go, daemon=True).start()
        if self.cfg.get("location"):
            threading.Thread(target=self.quiet_weather, daemon=True).start()

    def quiet_weather(self):
        try:
            self.fetch_weather()
        except Exception:  # noqa: BLE001 - the weather view reports problems
            pass

    def sync_library(self):
        """Save the newest stories' full text for reading offline (one sync at a time)."""
        if self.syncing.is_set():
            return
        self.syncing.set()
        try:
            self.library.sync(int(self.cfg.get("offline_keep", 100)), self.cfg["feeds"])
        finally:
            self.syncing.clear()

    # -- boot
    def boot(self):
        ui = self.ui
        s = ui.s
        rows, w, x0 = ui.dims()
        s.erase()
        s.refresh()
        s.nodelay(True)
        skip = False

        def pause(ms):
            nonlocal skip
            if skip:
                return
            s.refresh()
            curses.napms(ms)
            if s.getch() != -1:
                skip = True

        def typed(y, x, text, attr, delay=22):
            for i, c in enumerate(ui.tx(text)):
                ui._draw(y, x + i, c, attr)
                pause(delay)

        curses.napms(200)
        banner = big(APP, "██" if w >= 84 else "█")
        by = 2
        for i, line in enumerate(banner):
            ui._draw(by + i, x0 + 2, line, ui.HI)
            pause(60)
        y = by + 7
        left = x0 + 2
        typed(y, left, f"{APP} PERSONAL TERMINAL  V{VERSION}", ui.N, 8)
        typed(y + 1, left, "(C) 1979-2026 PHOSPHOR COMPUTER CO.", ui.DIM, 6)
        y += 3
        ui._draw(y, left, ui.tx("MEMORY TEST ........ "), ui.N)
        for kb in range(0, 65, 4):
            ui._draw(y, left + 21, f"{kb:>2}K", ui.N)
            pause(25)
        ui._draw(y, left + 25, " OK", ui.HI)
        for i, (label, val) in enumerate([
            ("CLOCK ..............", datetime.now().strftime("%H:%M:%S")),
            ("FEEDS ..............", f"{len(self.cfg['feeds'])} LOADED"),
            ("WEATHER ............", (self.cfg.get("location") or {}).get("name", "NOT SET")[:22]),
            ("OFFLINE LIBRARY ....", f"{self.library.count()[0]} STORIES"),
        ]):
            pause(140)
            ui._draw(y + 1 + i, left, ui.tx(f"{label} {val}"), ui.N)
        pause(250)
        typed(y + 6, left, "]RUN PHOSPHOR", ui.HI, 70)
        pause(450)
        s.nodelay(False)

    # -- main menu
    def run(self):
        if self.cfg.get("boot", True) and not self.args.no_boot:
            self.boot()
        self.prefetch()
        self.main_menu()

    def main_menu(self):
        ui = self.ui
        items = [
            ("1", "WEATHER REPORT", self.weather_view),
            ("2", "TODAY'S STORIES  (ALL FEEDS)", lambda: self.stories_view("ALL STORIES", self.cfg["feeds"])),
            ("3", "BROWSE BY FEED", self.feeds_view),
            ("4", "MANAGE FEEDS", self.manage_view),
            ("5", "SETTINGS", self.settings_view),
            ("Q", "QUIT", None),
        ]
        leave = getattr(self.args, "leave", None)
        if leave:  # running inside the window app
            items.insert(-1, ("W", "WINDOW VIEW", lambda: leave("switch")))
        sel = 0
        first = True
        while True:
            rows, w, x0 = ui.dims()
            ui.begin()
            ui.header("MAIN MENU")
            y = 2
            if rows >= 24:
                banner = big(APP, "██" if w >= 84 else "█")
                for i, line in enumerate(banner):
                    ui.put(y + i, x0 + 2, line, ui.HI)
                y += 6
            ui.put(y, x0 + 2, "* WEATHER & WIRE SERVICE TERMINAL *", ui.DIM)
            y += 2
            mx = x0 + 2
            for i, (k, label, _) in enumerate(items):
                ui.badge(y, mx, k)
                ui.put(y, mx + 5, label, ui.INV if i == sel else ui.N)
                y += 2
            y += 1
            status = []
            if self.weather and self.cfg.get("location"):
                cur = self.weather["current"]
                unit = "F" if self.cfg["units"] == "fahrenheit" else "C"
                status.append(f"{self.cfg['location']['name'].split(',')[0]}: "
                              f"{round(cur['temperature_2m'])}°{unit} "
                              f"{conditions(cur['weather_code'])[0]}")
            loaded = [self.store.cache.get(f["url"]) for f in self.cfg["feeds"]]
            if loaded and all(loaded):
                unread = sum(1 for c in loaded for s in c["stories"] if s["link"] not in self.read)
                status.append(f"{unread} UNREAD STORIES")
                ui.status = "OFFLINE" if any(c["offline"] for c in loaded) else ""
            if status and y < rows - 3:
                ui.put(y, x0 + 2, "   //   ".join(status), ui.DIM)
            ui.footer("PRESS A NUMBER, OR USE ARROWS + RETURN")
            ui.show(animate=first)
            first = False
            k = ui.key()
            c = (ch(k) or "").upper()
            choice = None
            if k in ENTER:
                choice = items[sel]
            elif k == curses.KEY_UP:
                sel = (sel - 1) % len(items)
            elif k == curses.KEY_DOWN:
                sel = (sel + 1) % len(items)
            elif c == "\x1b":
                choice = items[-1]
            else:
                choice = next((it for it in items if it[0] == c), None)
            if choice:
                ui.echo(choice[0])
                if choice[2] is None:
                    return
                sel = items.index(choice)
                choice[2]()
                first = True

    # -- weather
    def set_location(self):
        ui = self.ui
        q = ui.prompt("ENTER CITY (E.G. PORTLAND, OREGON)")
        if not q:
            return False

        res, err = ui.wait(lambda: find_places(q), "SEARCHING ATLAS")
        if err or not res:
            ui.msg = err or f"NO PLACE CALLED '{q}' FOUND"
            return False
        pick = res[0]
        if len(res) > 1:
            rows, w, x0 = ui.dims()
            ui.begin()
            ui.header("SELECT LOCATION")
            ui.put(2, x0 + 2, f"MATCHES FOR '{q}':", ui.HI)
            for i, r in enumerate(res):
                label = place_label(r)
                ui.badge(4 + i * 2, x0 + 4, str(i + 1))
                ui.put(4 + i * 2, x0 + 9, truncate(label, w - 12))
            ui.footer("PRESS 1-%d  ESC CANCEL" % len(res))
            ui.show(animate=True)
            while True:
                k = ui.key()
                c = ch(k)
                if k in BACK:
                    return False
                if c and c.isdigit() and 1 <= int(c) <= len(res):
                    ui.echo(c)
                    pick = res[int(c) - 1]
                    break
        self.cfg["location"] = location_from(pick)
        self.wx.forget()
        self.save()
        return True

    def weather_view(self):
        ui = self.ui
        if not self.cfg.get("location") and not self.set_location():
            return
        data, err = ui.wait(self.fetch_weather, "DIALING WEATHER SERVICE")
        first = True
        while True:
            ui.begin()
            ui.header("WEATHER REPORT")
            if data:
                self.draw_weather(data)
            else:
                rows, w, x0 = ui.dims()
                ui.put(3, x0 + 2, "?WEATHER SERVICE UNAVAILABLE", ui.HI)
                ui.put(4, x0 + 2, err or "", ui.DIM)
            ui.footer("R REFRESH  L LOCATION  U UNITS  ESC BACK")
            ui.show(animate=first)
            first = False
            k = ui.key()
            c = (ch(k) or "").lower()
            if k in BACK:
                return
            if c in ("r", "l", "u"):
                if c == "l" and not self.set_location():
                    continue
                if c == "u":
                    self.cfg["units"] = "celsius" if self.cfg["units"] == "fahrenheit" else "fahrenheit"
                    self.save()
                data, err = ui.wait(lambda: self.fetch_weather(force=True), "DIALING WEATHER SERVICE")
                first = True

    def draw_weather(self, d):
        ui = self.ui
        rows, w, x0 = ui.dims()
        f = self.cfg["units"] == "fahrenheit"
        unit = "F" if f else "C"
        cur, daily, hourly = d["current"], d["daily"], d["hourly"]
        desc, _, art = conditions(cur["weather_code"], cur.get("is_day", 1))

        ui.put(2, x0 + 2, self.cfg["location"]["name"], ui.HI)
        stamp = "AS OF " + cur["time"][11:16]
        if self.wx.saved_at:
            stamp = "OFFLINE - SAVED " + time.strftime("%a %H:%M", time.localtime(self.wx.saved_at))
        ui.put(2, x0 + w - len(stamp) - 2, stamp, ui.DIM)

        y = 4
        for i, line in enumerate(ART[art]):
            ui.put(y + i, x0 + 2, line, ui.HI)
        temp = f"{round(cur['temperature_2m'])}°"
        bx = x0 + 18
        tbig = big(temp + unit)
        if bx + len(tbig[0]) + 30 > x0 + w:
            tbig = big(temp)
        for i, line in enumerate(tbig):
            ui.put(y + i, bx, line, ui.HI)
        details = [
            (desc, ui.HI),
            (f"FEELS LIKE  {round(cur['apparent_temperature'])}°{unit}", ui.N),
            (f"HUMIDITY    {cur['relative_humidity_2m']}%", ui.N),
            (f"WIND        {round(cur['wind_speed_10m'])} {'MPH' if f else 'KM/H'} "
             f"{compass(cur['wind_direction_10m'])}", ui.N),
            (f"HI / LO     {round(daily['temperature_2m_max'][0])}° / "
             f"{round(daily['temperature_2m_min'][0])}°", ui.N),
            (f"SUN         {daily['sunrise'][0][11:16]} - {daily['sunset'][0][11:16]}", ui.N),
        ]
        dx = bx + len(tbig[0]) + 4
        if dx + 26 > x0 + w:  # narrow: details go under the art
            dx, dy = x0 + 4, y + 6
        else:
            dy = y - 1 if len(details) > 5 else y
        for i, (text, attr) in enumerate(details):
            ui.put(dy + i, dx, text, attr)
        y = max(y + 6, dy + len(details)) + 1
        bottom = rows - 3

        # hourly lo-res chart
        n = min(24, (w - 10) // 3)
        hours, temps, pops = hourly_from_now(d, n)
        daily_rows = 2 + len(daily["time"])
        if temps and y + 8 + 3 <= bottom - min(daily_rows, 5) + 3:
            ui.put(y, x0 + 2, f" NEXT {len(temps)} HOURS ", ui.INV)
            lo, hi = min(temps), max(temps)
            span = (hi - lo) or 1
            height = max(4, min(8, bottom - y - daily_rows - 4))
            levels = [round((t - lo) / span * (height * 2 - 1)) + 1 for t in temps]
            cx = x0 + 9
            for r in range(height):
                fromb = height - 1 - r
                line = ""
                for lv in levels:
                    fill = lv - fromb * 2
                    line += ("██" if fill >= 2 else "▄▄" if fill == 1 else "  ") + " "
                ui.put(y + 1 + r, cx, line, ui.HI)
            ui.put(y + 1, x0 + 2, f"{round(hi):>4}°", ui.DIM)
            ui.put(y + height, x0 + 2, f"{round(lo):>4}°", ui.DIM)
            shade = "".join((" " if p is None or p < 10 else "░" if p < 30 else "▒" if p < 60
                             else "▓" if p < 80 else "█") * 2 + " " for p in pops)
            ui.put(y + height + 1, x0 + 2, "RAIN", ui.DIM)
            ui.put(y + height + 1, cx, shade, ui.N)
            labels = ""
            for i, t in enumerate(hours):
                if i % 3 == 0:
                    lab = "NOW" if i == 0 else t[11:13]
                    labels = labels.ljust(i * 3) + lab
            ui.put(y + height + 2, cx, labels, ui.DIM)
            y += height + 4

        # 7-day
        if y + 2 < bottom:
            ui.put(y, x0 + 2, " 7-DAY FORECAST ", ui.INV)
            y += 1
            glo, ghi = min(daily["temperature_2m_min"]), max(daily["temperature_2m_max"])
            gspan = (ghi - glo) or 1
            bw = max(10, min(30, w - 46))
            for i, day in enumerate(daily["time"]):
                if y >= bottom:
                    break
                lo, hi = daily["temperature_2m_min"][i], daily["temperature_2m_max"][i]
                a = round((lo - glo) / gspan * (bw - 1))
                b = round((hi - glo) / gspan * (bw - 1))
                bar = "".join("█" if a <= j <= b else "·" for j in range(bw))
                name = day_name(day, i)
                short = conditions(daily["weather_code"][i])[1]
                pop = daily["precipitation_probability_max"][i]
                pop = f"{pop:>3}%" if pop is not None else "   -"
                ui.put(y, x0 + 2, f"{name:<6}{short:<14}{round(lo):>4}° ", ui.N)
                ui.put(y, x0 + 28, bar, ui.HI)
                ui.put(y, x0 + 29 + bw, f"{round(hi):>3}°  {pop}", ui.N)
                y += 1

    # -- stories
    def load(self, feeds, force=False):
        res, err = self.ui.wait(lambda: self.store.get_all(feeds, force), "LOADING FEEDS")
        if res is None:
            return [], err
        if force:
            threading.Thread(target=self.sync_library, daemon=True).start()
        stories = merge_stories(res)
        self.ui.status = "OFFLINE" if any(c["offline"] for c in res) else ""
        bad = [f["title"] for f, c in zip(feeds, res) if c["error"] and not c["offline"]]
        if any(c["offline"] for c in res):
            return stories, "OFFLINE - SHOWING SAVED STORIES"
        return stories, ("?FEED ERROR: " + ", ".join(bad)) if bad else None

    def stories_view(self, title, feeds):
        ui = self.ui
        stories, err = self.load(feeds)
        ui.msg = err
        sort_i, page, sel, filt, first = 0, 0, 0, "", True
        while True:
            items = arrange(stories, SORTS[sort_i], filt, self.read)
            rows, w, x0 = ui.dims()
            per = max(1, min(10, (rows - 6) // 2))
            pages = max(1, -(-len(items) // per))
            page = max(0, min(page, pages - 1))
            chunk = items[page * per:(page + 1) * per]
            sel = max(0, min(sel, len(chunk) - 1))

            ui.begin()
            ui.header(title)
            unread = sum(1 for s in items if s["link"] not in self.read)
            info = f"{len(items)} STORIES  {unread} NEW  SORT:{SORTS[sort_i]}"
            if filt:
                info += f"  FILTER:'{filt}'"
            pg = f"PAGE {page + 1}/{pages}"
            ui.put(1, x0 + 1, truncate(info, w - len(pg) - 3), ui.DIM)
            ui.put(1, x0 + w - len(pg) - 1, pg, ui.DIM)
            for i, s in enumerate(chunk):
                y = 3 + i * 2
                new = s["link"] not in self.read
                ui.badge(y, x0 + 1, str((i + 1) % 10))
                line = ("* " if new else "  ") + truncate(s["title"], w - 9)
                attr = ui.INV if i == sel else (ui.HI if new else ui.DIM)
                ui.put(y, x0 + 5, line, attr)
                meta = " - ".join(x for x in (s["source"], ago(s["date"])) if x)
                ui.put(y + 1, x0 + 7, truncate(meta, w - 8), ui.DIM)
            if not chunk:
                ui.put(4, x0 + 2, "NO STORIES." if not filt else "NOTHING MATCHES THAT FILTER.", ui.N)
            ui.footer("1-0 READ  N/P PAGE  S SORT  / FILTER  M MARK READ  O OPEN  R RELOAD  ESC BACK")
            ui.show(animate=first)
            first = False

            k = ui.key()
            c = (ch(k) or "")
            cl = c.lower()
            pick = None
            if k in BACK:
                return
            elif c.isdigit() and len(c) == 1:
                i = (int(c) - 1) % 10
                if i < len(chunk):
                    ui.echo(c)
                    pick = page * per + i
            elif k in ENTER and chunk:
                pick = page * per + sel
            elif k == curses.KEY_DOWN:
                if sel < len(chunk) - 1:
                    sel += 1
                elif page < pages - 1:
                    page, sel = page + 1, 0
            elif k == curses.KEY_UP:
                if sel > 0:
                    sel -= 1
                elif page > 0:
                    page, sel = page - 1, per - 1
            elif cl == "n" or c == " " or k in (curses.KEY_NPAGE, curses.KEY_RIGHT):
                if page < pages - 1:
                    page, sel = page + 1, 0
            elif cl == "p" or k == curses.KEY_PPAGE:
                if page > 0:
                    page, sel = page - 1, 0
            elif cl == "s":
                sort_i = (sort_i + 1) % len(SORTS)
                page = sel = 0
            elif c == "/":
                f = ui.prompt("FILTER (BLANK CLEARS)", filt)
                if f is not None:
                    filt, page, sel = f, 0, 0
            elif cl == "m":
                self.mark_read([s["link"] for s in chunk])
            elif cl == "o" and chunk:
                s = chunk[sel]
                self.mark_read([s["link"]])
                ui.msg = "OPENING IN BROWSER..." if open_url(s["link"]) else "?COULD NOT OPEN BROWSER"
            elif cl == "r":
                stories, err = self.load(feeds, force=True)
                ui.msg = err
                first = True
            if pick is not None:
                end = self.reader(items, pick)
                page, sel = divmod(end, per)
                first = True

    def reader(self, items, idx):
        ui = self.ui
        mode_full = True
        while True:
            story = items[idx]
            link = story["link"]
            self.mark_read([link])
            paras, note = None, None
            if mode_full and link.startswith("http"):
                paras = article_text(self.library, self.articles, link)
                if paras is None:
                    paras, err = ui.wait(lambda: get_article(self.library, self.articles, link),
                                         "RECEIVING TRANSMISSION")
                    if not paras:
                        note = "?FULL TEXT UNAVAILABLE" + (f" ({err})" if err else "") + " - SHOWING FEED SUMMARY"
            if not paras:
                paras = html_to_paragraphs(story["summary"]) or [("p", "(NO TEXT. PRESS O TO OPEN IN BROWSER.)")]
            ui.msg = note
            top, first = 0, True
            while True:
                rows, w, x0 = ui.dims()
                tw = min(w - 4, 78)
                lx = x0 + 2
                lines = [(l, ui.HI, False) for l in textwrap.wrap(story["title"], tw)]
                meta = " - ".join(x for x in (story["source"], story["date"] and
                                  story["date"].astimezone().strftime("%a %b %d %Y %H:%M")) if x)
                lines += [(meta, ui.DIM, False), (truncate(link, tw), ui.DIM, True), ("=" * tw, ui.DIM, False), ("", None, False)]
                for kind, text in paras:
                    for l in textwrap.wrap(text, tw) or [""]:
                        lines.append((l, ui.HI if kind == "h" else ui.N, False))
                    lines.append(("", None, False))
                lines.append(("-- END OF TRANSMISSION --".center(tw), ui.DIM, False))
                body = rows - 4
                maxtop = max(0, len(lines) - body)
                top = max(0, min(top, maxtop))

                ui.begin()
                ui.header(f"STORY {idx + 1} OF {len(items)}")
                for i, (text, attr, raw) in enumerate(lines[top:top + body]):
                    if text:
                        ui.put(2 + i, lx, text, attr, raw)
                pct = 100 if maxtop == 0 else round(top / maxtop * 100)
                ui.footer(f"{pct:>3}%  SPACE/ARROWS SCROLL  N NEXT  P PREV  "
                          f"T {'SUMMARY' if mode_full else 'FULL TEXT'}  O BROWSER  ESC BACK")
                ui.show(animate=first)
                first = False

                k = ui.key()
                c = (ch(k) or "").lower()
                if k in BACK:
                    return idx
                elif k == curses.KEY_DOWN or c == "j":
                    top += 1
                elif k == curses.KEY_UP or c == "k":
                    top -= 1
                elif c == " " or k == curses.KEY_NPAGE:
                    top += body - 2
                elif c == "b" or k == curses.KEY_PPAGE:
                    top -= body - 2
                elif c == "g" or k == curses.KEY_HOME:
                    top = 0
                elif (ch(k) == "G") or k == curses.KEY_END:
                    top = maxtop
                elif c == "o":
                    ui.msg = "OPENING IN BROWSER..." if open_url(link) else "?COULD NOT OPEN BROWSER"
                elif c == "t":
                    mode_full = not mode_full
                    break
                elif c == "n" or k == curses.KEY_RIGHT:
                    if idx < len(items) - 1:
                        idx += 1
                        break
                    ui.msg = "LAST STORY."
                elif c == "p":
                    if idx > 0:
                        idx -= 1
                        break
                    ui.msg = "FIRST STORY."

    # -- feeds
    def feeds_view(self):
        ui = self.ui
        page, first = 0, True
        while True:
            feeds = self.cfg["feeds"]
            rows, w, x0 = ui.dims()
            per = max(1, min(10, (rows - 8) // 2))
            pages = max(1, -(-len(feeds) // per))
            page = max(0, min(page, pages - 1))
            chunk = feeds[page * per:(page + 1) * per]
            ui.begin()
            ui.header("BROWSE BY FEED")
            ui.put(1, x0 + 1, f"{len(feeds)} FEEDS", ui.DIM)
            if pages > 1:
                ui.put(1, x0 + w - 12, f"PAGE {page + 1}/{pages}", ui.DIM)
            for i, f in enumerate(chunk):
                y = 3 + i * 2
                ui.badge(y, x0 + 1, str((i + 1) % 10))
                ui.put(y, x0 + 6, truncate(f["title"], w - 30), ui.HI)
                c = self.store.cache.get(f["url"])
                if c is None:
                    stat = "..."
                elif c["error"]:
                    stat = "?" + c["error"]
                else:
                    new = sum(1 for s in c["stories"] if s["link"] not in self.read)
                    stat = f"{len(c['stories'])} STORIES  {new:>3} NEW"
                stat = truncate(stat, 24)
                ui.put(y, x0 + w - len(stat) - 1, stat, ui.N if c and not c["error"] else ui.DIM)
            y = 3 + len(chunk) * 2
            ui.badge(y, x0 + 1, "A")
            ui.put(y, x0 + 6, "ALL FEEDS COMBINED", ui.N)
            if not feeds:
                ui.put(3, x0 + 2, "NO FEEDS. ADD SOME UNDER MANAGE FEEDS.", ui.N)
            ui.footer("1-0 OPEN FEED  A ALL  N/P PAGE  ESC BACK")
            ui.show(animate=first)
            first = False
            k = ui.key()
            c = ch(k) or ""
            if k in BACK:
                return
            if c.isdigit() and len(c) == 1:
                i = (int(c) - 1) % 10
                if i < len(chunk):
                    ui.echo(c)
                    self.stories_view(chunk[i]["title"].upper(), [chunk[i]])
                    first = True
            elif c.lower() == "a":
                ui.echo("A")
                self.stories_view("ALL STORIES", feeds)
                first = True
            elif c.lower() == "n" or k == curses.KEY_NPAGE:
                page += 1
            elif c.lower() == "p" or k == curses.KEY_PPAGE:
                page -= 1

    def manage_view(self):
        ui = self.ui
        first = True
        while True:
            feeds = self.cfg["feeds"]
            rows, w, x0 = ui.dims()
            ui.begin()
            ui.header("MANAGE FEEDS")
            room = rows - 5
            for i, f in enumerate(feeds[:room]):
                ui.put(2 + i, x0 + 1, f"{i + 1:>2}.", ui.DIM)
                ui.put(2 + i, x0 + 5, truncate(f["title"], 26), ui.HI)
                ui.put(2 + i, x0 + 33, truncate(f["url"], w - 34), ui.DIM, raw=True)
            if len(feeds) > room:
                ui.put(rows - 3, x0 + 5, f"... AND {len(feeds) - room} MORE", ui.DIM)
            if not feeds:
                ui.put(2, x0 + 2, "NO FEEDS YET. PRESS A TO ADD ONE.", ui.N)
            ui.footer("A ADD  D DELETE  E RENAME  M MOVE  I IMPORT OPML  ESC BACK")
            ui.show(animate=first)
            first = False
            k = ui.key()
            c = (ch(k) or "").lower()
            if k in BACK:
                return
            if c == "a":
                self.add_feed()
            elif c in ("d", "e", "m") and feeds:
                n = ui.prompt({"d": "DELETE WHICH #", "e": "RENAME WHICH #", "m": "MOVE WHICH #"}[c])
                if not n or not n.isdigit() or not 1 <= int(n) <= len(feeds):
                    continue
                i = int(n) - 1
                if c == "d":
                    yes = ui.prompt(f"DELETE '{feeds[i]['title']}' (Y/N)")
                    if yes and yes.lower().startswith("y"):
                        feeds.pop(i)
                elif c == "e":
                    name = ui.prompt("NEW NAME", feeds[i]["title"])
                    if name:
                        feeds[i]["title"] = name
                        self.store.cache.pop(feeds[i]["url"], None)
                else:
                    to = ui.prompt(f"MOVE TO POSITION (1-{len(feeds)})")
                    if to and to.isdigit():
                        feeds.insert(max(0, min(len(feeds) - 1, int(to) - 1)), feeds.pop(i))
                self.save()
            elif c == "i":
                self.import_opml()

    def add_feed(self):
        ui = self.ui
        url = ui.prompt("FEED OR SITE URL")
        if not url:
            return
        res, err = ui.wait(lambda: probe_feed(url), "PROBING FEED")
        if not res:
            ui.msg = f"?NO FEED FOUND AT {url} ({err})"
            return
        final, title = res
        if any(f["url"] == final for f in self.cfg["feeds"]):
            ui.msg = "ALREADY SUBSCRIBED."
            return
        name = ui.prompt("NAME", title or final.split("/")[2])
        if name is None:
            return
        self.cfg["feeds"].append({"title": name or final, "url": final})
        self.save()
        threading.Thread(target=self.store.get, args=(self.cfg["feeds"][-1],), daemon=True).start()
        ui.msg = f"ADDED {name or final}."

    def import_opml(self):
        ui = self.ui
        path = ui.prompt("PATH TO OPML FILE")
        if not path:
            return
        try:
            added = add_feeds(self.cfg, read_opml(path))
        except Exception as e:  # noqa: BLE001 - any unreadable file
            ui.msg = f"?CANNOT READ OPML: {short_err(e)}"
            return
        self.save()
        ui.msg = f"IMPORTED {added} FEEDS."

    # -- settings
    def settings_view(self):
        ui = self.ui
        first = True
        while True:
            cfg = self.cfg
            rows, w, x0 = ui.dims()
            opts = [
                ("1", "LOCATION", (cfg.get("location") or {}).get("name", "NOT SET")),
                ("2", "UNITS", cfg["units"]),
                ("3", "PHOSPHOR COLOR", cfg["theme"]),
                ("4", "ALL CAPS", "ON" if cfg["uppercase"] else "OFF"),
                ("5", "TYPEWRITER EFFECT", "ON" if cfg["typewriter"] else "OFF"),
                ("6", "BOOT SEQUENCE", "ON" if cfg["boot"] else "OFF"),
                ("7", "SAVE FOR OFFLINE", self.offline_label()),
            ]
            ui.begin()
            ui.header("SETTINGS")
            for i, (k, label, val) in enumerate(opts):
                y = 3 + i * 2
                ui.badge(y, x0 + 4, k)
                ui.put(y, x0 + 9, f"{label} ".ljust(22, "."), ui.N)
                ui.put(y, x0 + 32, " " + val, ui.HI)
            ui.put(3 + len(opts) * 2 + 1, x0 + 4, f"CONFIG: {CONFIG_PATH}", ui.DIM, raw=True)
            ui.footer("PRESS A NUMBER TO CHANGE  ESC BACK")
            ui.show(animate=first)
            first = False
            k = ui.key()
            c = ch(k) or ""
            if k in BACK:
                return
            if c == "1":
                self.set_location()
            elif c == "2":
                cfg["units"] = "celsius" if cfg["units"] == "fahrenheit" else "fahrenheit"
                self.wx.forget()
            elif c == "3":
                names = list(THEMES)
                cfg["theme"] = names[(names.index(cfg["theme"]) + 1) % len(names)]
                ui.apply_theme()
            elif c == "4":
                cfg["uppercase"] = not cfg["uppercase"]
            elif c == "5":
                cfg["typewriter"] = not cfg["typewriter"]
            elif c == "6":
                cfg["boot"] = not cfg["boot"]
            elif c == "7":
                keep = int(cfg.get("offline_keep", 100))
                later = [n for n in OFFLINE_CHOICES if n > keep]
                cfg["offline_keep"] = later[0] if later else OFFLINE_CHOICES[0]
            else:
                continue
            self.save()
            if c == "2" and cfg.get("location"):
                threading.Thread(target=self.quiet_weather, daemon=True).start()
            if c == "7":
                threading.Thread(target=self.sync_library, daemon=True).start()

    def offline_label(self):
        keep = int(self.cfg.get("offline_keep", 100))
        if not keep:
            return "OFF"
        stories, texts = self.library.count()
        return f"NEWEST {keep} STORIES  ({texts} SAVED)"


def main():
    ap = argparse.ArgumentParser(prog="phosphor", description="Phosphor Terminal -- retro weather & RSS")
    ap.add_argument("--no-boot", action="store_true", help="skip the boot sequence")
    ap.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    ap.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.self_test:
        from .selftest import terminal_main
        terminal_main()
        return
    os.environ.setdefault("ESCDELAY", "25")
    try:
        curses.wrapper(lambda s: App(s, args).run())
        # (the library saves itself after each sync; nothing else is pending)
    except KeyboardInterrupt:
        pass
    print("]BYE.")


if __name__ == "__main__":
    main()
