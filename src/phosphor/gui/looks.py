"""How each era draws the screens: home, a story list, a story, the weather, feeds, and settings.

Look is the shared design (and the web eras' defaults); each era overrides the pieces it
draws its own way. Screens go into a Page (see page.py).
"""

import time
import tkinter as tk
from datetime import datetime, timezone

from ..core import (ART, NAME, OFFLINE_CHOICES, compass, conditions, day_name, hourly_from_now,
                    truncate)
from .eras import ERAS, mix

SPARK = "▁▂▃▄▅▆▇█"


def human_ago(d):
    if not d:
        return ""
    secs = (datetime.now(timezone.utc) - d).total_seconds()
    if secs < 90:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)} minutes ago"
    if secs < 7200:
        return "1 hour ago"
    if secs < 86400:
        return f"{int(secs // 3600)} hours ago"
    if secs < 172800:
        return "yesterday"
    if secs < 86400 * 7:
        return f"{int(secs // 86400)} days ago"
    return long_date(d.astimezone(), year=True, weekday=False)


def long_date(d, year=False, weekday=True, clock=False):
    """'Friday, October 2' (with the year, a 12-hour time), built by hand: strftime's no-padding flag isn't portable."""
    s = f"{d.strftime('%B')} {d.day}"
    if weekday:
        s = f"{d.strftime('%A')}, {s}"
    if year:
        s += f", {d.year}"
    if clock:
        s += f", {d.hour % 12 or 12}:{d.minute:02d} {'AM' if d.hour < 12 else 'PM'}"
    return s


def short_hour(iso):
    h = datetime.fromisoformat(iso).hour
    return f"{h % 12 or 12}{'am' if h < 12 else 'pm'}"


def plural(n, word):
    if n == 1:
        return f"1 {word}"
    return f"{n:,} " + (word[:-1] + "ies" if word.endswith("y") else word + "s")


def unit_letter(cfg):
    return "F" if cfg.get("units") == "fahrenheit" else "C"


def weather_prose(d, cfg, upper=True):
    """A forecast written out, the way a wire service or a newspaper printed it."""
    cur, daily = d["current"], d["daily"]
    desc = conditions(cur["weather_code"], cur.get("is_day", 1))[0].lower()
    u = unit_letter(cfg)
    wind = "mph" if u == "F" else "km/h"
    lines = [f"Now: {desc}, {round(cur['temperature_2m'])} degrees {u}, feels like "
             f"{round(cur['apparent_temperature'])}. Humidity {cur['relative_humidity_2m']} percent. "
             f"Wind {compass(cur['wind_direction_10m'])} at {round(cur['wind_speed_10m'])} {wind}."]
    for i, day in enumerate(daily["time"]):
        name = "Today" if i == 0 else datetime.fromisoformat(day).strftime("%A")
        short = conditions(daily["weather_code"][i])[0].lower()
        pop = daily["precipitation_probability_max"][i]
        rain = f" Chance of rain {pop} percent." if pop else ""
        lines.append(f"{name}... {short[0].upper() + short[1:]}. High {round(daily['temperature_2m_max'][i])}, "
                     f"low {round(daily['temperature_2m_min'][i])}.{rain}")
    return [l.upper() for l in lines] if upper else lines


def weather_text(d, cfg, width, upper=True):
    """The terminal-style report: art + big temperature, an hourly chart, the week. [(text, tag)] lines."""
    cur, daily = d["current"], d["daily"]
    u = unit_letter(cfg)
    desc, _, art = conditions(cur["weather_code"], cur.get("is_day", 1))
    out = [[(f"{round(cur['temperature_2m'])}°{u}", "huge"), ("  " + desc, "hi")]]
    details = [
        (f"FEELS LIKE {round(cur['apparent_temperature'])}°{u}", "body"),
        (f"HUMIDITY   {cur['relative_humidity_2m']}%", "body"),
        (f"WIND       {round(cur['wind_speed_10m'])} {'MPH' if u == 'F' else 'KM/H'} "
         f"{compass(cur['wind_direction_10m'])}", "body"),
        (f"HI / LO    {round(daily['temperature_2m_max'][0])}° / {round(daily['temperature_2m_min'][0])}°", "body"),
        (f"SUN        {daily['sunrise'][0][11:16]} - {daily['sunset'][0][11:16]}", "body"),
    ]
    if width >= 50:
        for i in range(5):
            text, tag = details[i]
            out.append([(ART[art][i] + "    ", "hi"), (text, tag)])
    else:
        out += [[(ART[art][i], "hi")] for i in range(5)]
        out.append([("", "body")])
        out += [[(t, tag)] for t, tag in details]
    out.append([("", "body")])
    n = min(24, max(8, (width - 8) // 2))
    hours, temps, pops = hourly_from_now(d, n)
    if temps:
        lo, hi = min(temps), max(temps)
        span = (hi - lo) or 1
        out.append([(f" NEXT {len(temps)} HOURS ", "bar")])
        out.append([(f"{round(hi):>4}° ", "dim"), ("".join(SPARK[round((t - lo) / span * 7)] * 2 for t in temps), "hi")])
        out.append([(f"{round(lo):>4}° ", "dim"),
                    ("".join(("  " if p is None or p < 10 else "░░" if p < 30 else "▒▒" if p < 60 else "▓▓" if p < 80
                              else "██") for p in pops), "body"), ("  RAIN", "dim")])
        labels = ""
        for i, t in enumerate(hours):
            if i % 3 == 0:
                labels = labels.ljust(i * 2) + ("NOW" if i == 0 else t[11:13])
        out.append([("      " + labels, "dim")])
        out.append([("", "body")])
    out.append([(" 7-DAY FORECAST ", "bar")])
    glo, ghi = min(daily["temperature_2m_min"]), max(daily["temperature_2m_max"])
    gspan = (ghi - glo) or 1
    bw = max(8, min(24, width - 40))
    for i, day in enumerate(daily["time"]):
        lo, hi = daily["temperature_2m_min"][i], daily["temperature_2m_max"][i]
        a, b = round((lo - glo) / gspan * (bw - 1)), round((hi - glo) / gspan * (bw - 1))
        bar = "".join("█" if a <= j <= b else "·" for j in range(bw))
        short = conditions(daily["weather_code"][i])[1]
        pop = daily["precipitation_probability_max"][i]
        pop = f"{pop:>3}%" if pop is not None else "   -"
        if width < 50:
            out.append([(f"{day_name(day, i)[:3]:<4}{short[:11]:<12}{round(lo):>3}°/{round(hi):>3}° {pop}", "body")])
        else:
            out.append([(f"{day_name(day, i):<6}{short:<14}{round(lo):>4}° ", "body"), (bar, "hi"),
                        (f"{round(hi):>4}°  {pop}", "body")])
    return out


def chart(gui, parent, d, width):
    """The next 24 hours (temperature line, chance of rain bars) and the week, drawn on a canvas."""
    c, f = gui.colors, gui.fonts
    hours, temps, pops = hourly_from_now(d, 24)
    daily = d["daily"]
    s = gui.px(1)
    width = max(gui.px(320), width)
    ch = gui.px(150)
    week_h = gui.px(26) * len(daily["time"])
    cv = tk.Canvas(parent, width=width, height=ch + gui.px(40) + week_h, bg=c["bg"], highlightthickness=0, bd=0)
    if not temps:
        return cv
    left, right, top = gui.px(44), width - gui.px(12), gui.px(24)
    lo, hi = min(temps), max(temps)
    span = (hi - lo) or 1
    step = (right - left) / max(1, len(temps) - 1)
    soft = mix(c["link"], c["bg"], 0.75)
    cv.create_text(left - gui.px(6), top, text=f"{round(hi)}°", anchor="e", fill=c["dim"], font=f["small"])
    cv.create_text(left - gui.px(6), top + ch - gui.px(30), text=f"{round(lo)}°", anchor="e", fill=c["dim"],
                   font=f["small"])
    cv.create_text(left, gui.px(4), text="Next 24 hours", anchor="nw", fill=c["fg"], font=f["head"])
    base = top + ch - gui.px(30)
    for i, p in enumerate(pops):
        if p:
            x = left + i * step
            h = (ch - gui.px(30)) * p / 100 * 0.5
            cv.create_rectangle(x - step * 0.35, base - h, x + step * 0.35, base, fill=soft, outline="")
    pts = []
    for i, t in enumerate(temps):
        pts += [left + i * step, top + (hi - t) / span * (ch - gui.px(30))]
    if len(pts) >= 4:
        cv.create_line(*pts, fill=c["link"], width=max(2, 2 * s), joinstyle="round")
    for i, t in enumerate(hours):
        if i % 3 == 0:
            x = left + i * step
            cv.create_text(x, base + gui.px(6), text="Now" if i == 0 else short_hour(t),
                           anchor="n", fill=c["dim"], font=f["small"])
            cv.create_text(x, top + (hi - temps[i]) / span * (ch - gui.px(30)) - gui.px(6), text=f"{round(temps[i])}°",
                           anchor="s", fill=c["fg"], font=f["small"])
    cv.create_text(right, gui.px(4), text="bars: chance of rain", anchor="ne", fill=c["dim"], font=f["small"])
    # the week
    y = ch + gui.px(34)
    glo, ghi = min(daily["temperature_2m_min"]), max(daily["temperature_2m_max"])
    gspan = (ghi - glo) or 1
    bx0, bx1 = left + gui.px(190), right - gui.px(60)
    for i, day in enumerate(daily["time"]):
        lo_, hi_ = daily["temperature_2m_min"][i], daily["temperature_2m_max"][i]
        name = "Today" if i == 0 else datetime.fromisoformat(day).strftime("%a")
        short = conditions(daily["weather_code"][i])[1].title()
        cv.create_text(left - gui.px(36), y, text=name, anchor="w", fill=c["fg"], font=f["body"])
        cv.create_text(left + gui.px(28), y, text=short, anchor="w", fill=c["dim"], font=f["small"])
        cv.create_text(bx0 - gui.px(8), y, text=f"{round(lo_)}°", anchor="e", fill=c["dim"], font=f["body"])
        a = bx0 + (lo_ - glo) / gspan * (bx1 - bx0)
        b = bx0 + (hi_ - glo) / gspan * (bx1 - bx0)
        cv.create_line(bx0, y, bx1, y, fill=mix(c["dim"], c["bg"], 0.7), width=max(4, 4 * s), capstyle="round")
        cv.create_line(a, y, max(b, a + 1), y, fill=c["link"], width=max(4, 4 * s), capstyle="round")
        cv.create_text(bx1 + gui.px(8), y, text=f"{round(hi_)}°", anchor="w", fill=c["fg"], font=f["body"])
        pop = daily["precipitation_probability_max"][i]
        if pop:
            cv.create_text(right, y, text=f"{pop}%", anchor="e", fill=c["dim"], font=f["small"])
        y += gui.px(26)
    return cv


# ------------------------------------------------------------------ the shared design
class Look:
    per_page = None          # stories per page in a list (None: one long list)
    numbered = True          # number keys pick menu items and stories

    def __init__(self, gui):
        self.gui = gui
        self.era = gui.era
        self.cfg = gui.cfg

    def tx(self, s):
        return self.gui.tx(s)

    def ago(self, d):
        return human_ago(d)

    # -- pieces
    def masthead(self, p, title):
        p.w(self.tx(title), "big").nl(2)

    def section(self, p, title):
        p.w(" " + self.tx(title) + " ", "bar").nl()

    def row(self, p, key, label, detail, action):
        """A menu line."""
        p.item(action, key=key)
        if key and self.numbered:
            p.w(f"{key}. ", "dim")
        p.w(self.tx(label), "link")
        p.end_item()
        if detail:
            p.w("  " + self.tx(detail), "dim")
        p.nl()

    def entry(self, p, n, s, items_key, idx):
        unread = s["link"] not in self.gui.read
        p.item(lambda: self.gui.go(("story", items_key, idx)), key=(n % 10) if n <= 10 and self.numbered else None)
        p.w(self.tx(s["title"]), "link" if unread else "visited", "head" if unread else "body")
        p.end_item()
        p.nl().w("   " + self.tx(" · ".join(x for x in (s["source"], self.ago(s["date"])) if x)), "dim", "small").nl()

    def foot(self, p):
        pass

    def rule(self, p):
        p.w("—" * 30, "dim").nl()

    def links(self, p, pairs, sep="   "):
        for i, (label, action) in enumerate(pairs):
            if i:
                p.w(sep, "dim")
            p.item(action, self.tx(label), "link")
        p.nl()

    # -- screens
    def home(self, p):
        g = self.gui
        self.masthead(p, "Main Menu")
        rows = self.home_rows()
        self.section(p, "Today")
        for key, label, detail, action in rows:
            self.row(p, key, label, detail, action)
        p.nl()
        self.foot(p)

    def home_rows(self):
        g = self.gui
        rows = [("1", "Weather report", g.weather_line(), lambda: g.go(("weather",)))]
        total, new = g.counts(None)
        rows.append(("2", "All stories", f"{plural(total, 'story')}, {new} new" if total else g.loading_line(),
                     lambda: g.go(("list", None))))
        for i, f in enumerate(g.cfg["feeds"][:6]):
            t, n = g.counts(f["url"])
            rows.append((str(i + 3), f["title"], f"{plural(t, 'story')}, {n} new" if t else "",
                         lambda u=f["url"]: g.go(("list", u))))
        rows.append(("F", "Manage feeds", "", lambda: g.go(("feeds",))))
        rows.append(("S", "Settings", "", lambda: g.go(("settings",))))
        return rows

    def list_info(self, items, page, pages):
        new = sum(1 for s in items if s["link"] not in self.gui.read)
        info = f"{plural(len(items), 'story')} · {new} new · sorted by {self.gui.sort.lower()}"
        if self.gui.filt:
            info += f" · showing “{self.gui.filt}”"
        if pages > 1:
            info += f" · page {page + 1} of {pages}"
        return info

    def story_list(self, p, key, items, page, pages, start):
        g = self.gui
        self.masthead(p, g.list_title(key))
        p.w(self.tx(self.list_info(items, page, pages)), "dim").nl(2)
        chunk = items[start:start + self.per_page] if self.per_page else items
        for i, s in enumerate(chunk):
            self.entry(p, i + 1, s, key, start + i)
        if not chunk:
            p.w(self.tx(g.empty_line()), "body").nl()
        p.nl()
        self.pager(p, key, page, pages)
        self.foot(p)

    def pager(self, p, key, page, pages):
        g = self.gui
        pairs = []
        if page > 0:
            pairs.append(("« Previous", lambda: g.turn(-1)))
        if page < pages - 1:
            pairs.append(("Next »", lambda: g.turn(1)))
        pairs += [("Sort", g.cycle_sort), ("Search", g.search), ("Reload", g.reload), ("Back", g.back)]
        self.links(p, pairs, " | ")

    def story(self, p, key, items, idx, paras, note):
        g = self.gui
        s = items[idx]
        self.article(p, s, paras, note, idx, len(items))
        p.nl()
        self.links(p, self.story_links(), " | ")
        self.foot(p)

    def story_links(self):
        g = self.gui
        return [("« Previous", lambda: g.next_story(-1)), ("Next »", lambda: g.next_story(1)),
                ("Summary" if g.full else "Full text", g.toggle_full), ("Open in browser", g.open_story),
                ("Back", g.back)]

    def byline(self, s):
        when = long_date(s["date"].astimezone(), year=True, clock=True) if s["date"] else ""
        return " · ".join(x for x in (s["source"], when) if x)

    def article(self, p, s, paras, note, idx, count):
        p.w(self.tx(s["title"]), "big").nl()
        p.w(self.tx(self.byline(s)), "dim", "small").nl()
        if note:
            p.w(self.tx(note), "note").nl()
        p.nl()
        for kind, text in paras:
            p.w(self.tx(text), "head" if kind == "h" else "body", "para").nl()

    def weather(self, p, d, err):
        g = self.gui
        self.masthead(p, "Weather")
        if d is None:
            p.w(self.tx(err or "Loading the forecast…"), "body").nl(2)
        else:
            self.weather_body(p, d)
        p.nl()
        self.links(p, self.weather_links(), " | ")
        self.foot(p)

    def weather_links(self):
        g = self.gui
        return [("Refresh", g.refresh_weather), ("Change place", g.change_location),
                ("°C" if g.cfg.get("units") == "fahrenheit" else "°F", g.toggle_units), ("Back", g.back)]

    def weather_body(self, p, d):
        g = self.gui
        cur = d["current"]
        u = unit_letter(self.cfg)
        desc = conditions(cur["weather_code"], cur.get("is_day", 1))[0].capitalize()
        p.w(self.tx(g.cfg["location"]["name"]), "head").w("   " + self.tx(g.weather_stamp()), "dim", "small").nl()
        p.w(f"{round(cur['temperature_2m'])}°{u}", "big").w("  " + self.tx(desc), "head").nl()
        daily = d["daily"]
        p.w(self.tx(f"Feels like {round(cur['apparent_temperature'])}°  ·  Humidity {cur['relative_humidity_2m']}%  ·  "
                    f"Wind {round(cur['wind_speed_10m'])} {'mph' if u == 'F' else 'km/h'} "
                    f"{compass(cur['wind_direction_10m'])}  ·  Sunrise {daily['sunrise'][0][11:16]}, "
                    f"sunset {daily['sunset'][0][11:16]}"), "dim").nl(2)
        p.embed(chart(g, p.t, d, g.content_width() - g.px(40)))
        p.nl()

    def feeds(self, p):
        g = self.gui
        self.masthead(p, "Manage Feeds")
        self.section(p, "Your feeds")
        for i, f in enumerate(g.cfg["feeds"]):
            p.item(lambda i=i: g.feed_menu(i), key=(i + 1) % 10 if i < 10 and self.numbered else None)
            if self.numbered and i < 10:
                p.w(f"{(i + 1) % 10}. ", "dim")
            p.w(self.tx(f["title"]), "link")
            p.end_item()
            p.w("  " + truncate(f["url"], 70), "dim", "small").nl()
        if not g.cfg["feeds"]:
            p.w(self.tx("No feeds yet."), "body").nl()
        p.nl()
        self.links(p, [("Add a feed…", g.add_feed), ("Import OPML…", g.import_opml), ("Back", g.back)], " | ")
        p.nl()
        p.w(self.tx("Pick a feed to rename, move, or remove it. You can paste a site's address; "
                    "Phosphor finds its feed."), "dim", "small").nl()
        self.foot(p)

    def settings(self, p):
        g = self.gui
        cfg = g.cfg
        self.masthead(p, "Settings")
        self.section(p, "Era")
        for e in ERAS:
            mark = "(•)" if e.key == g.era.key else "( )"
            p.item(lambda k=e.key: g.set_era(k))
            p.w(f"{mark} ", "body").w(self.tx(e.label), "link")
            p.end_item()
            p.nl()
            p.w(self.tx(e.blurb), "dim", "small", "indent").nl()
        p.nl()
        self.section(p, "Look")
        if g.era.dark_colors:
            for v, label in (("system", "Match my computer"), ("light", "Light"), ("dark", "Dark")):
                mark = "(•)" if cfg.get("gui_theme", "system") == v else "( )"
                p.item(lambda v=v: g.set_theme(v), f"{mark} {self.tx(label)}", "link").nl()
        if g.era.key == "phosphor":
            p.item(g.cycle_phosphor, self.tx(f"Screen color: {cfg['theme']}"), "link").nl()
        p.item(lambda: g.zoom(1), self.tx("Bigger text"), "link").w("   ").item(lambda: g.zoom(-1), self.tx("Smaller text"), "link").nl()
        p.item(g.toggle_typewriter, self.tx(f"Typewriter effect (old screens): {'on' if cfg.get('typewriter', True) else 'off'}"),
               "link").nl()
        p.nl()
        self.section(p, "Weather")
        p.item(g.change_location, self.tx(f"Place: {(cfg.get('location') or {}).get('name', 'not set')}"), "link").nl()
        p.item(g.toggle_units, self.tx(f"Units: {'Fahrenheit' if cfg.get('units') == 'fahrenheit' else 'Celsius'}"),
               "link").nl()
        p.nl()
        self.section(p, "Offline reading")
        stories, texts = g.library.count()
        keep = int(cfg.get("offline_keep", 100))
        p.item(g.cycle_offline, self.tx(f"Keep the newest {keep} stories" if keep else "Off"), "link").nl()
        p.w(self.tx(f"Saved now: {plural(stories, 'story')}, {texts} with full text. Phosphor keeps them on this "
                    f"computer so you can read without a connection; the feeds take turns so each gets its share. "
                    f"Choices: {', '.join(str(n) if n else 'off' for n in OFFLINE_CHOICES)}."), "dim", "small").nl(2)
        self.section(p, "Terminal")
        p.item(g.enter_terminal, self.tx("Switch to the terminal view"), "link").nl()
        p.w(self.tx(f"The real {NAME} Terminal, inside this window ({g.mod_label}+Shift+W). "
                    f"In a terminal, run: phosphor"), "dim", "small").nl()
        p.nl()
        self.links(p, [("Back", g.back)])
        self.foot(p)


# ------------------------------------------------------------------ the character-screen eras
class CharLook(Look):
    per_page = 10

    def section(self, p, title):
        p.w(f" {self.tx(title)} ", "bar").nl(2)

    def ago(self, d):
        from ..core import ago
        return ago(d)

    def width(self):
        return min(self.era.cols or 80, self.gui.page_chars())

    def masthead(self, p, title):
        w = self.width()
        clock = datetime.now().strftime("%a %H:%M").upper()
        left, mid = " " + NAME.upper(), self.tx(title)
        line = left + " " * max(1, (w - len(mid)) // 2 - len(left)) + mid
        line = line + " " * max(1, w - len(line) - len(clock) - 1) + clock + " "
        p.w(line[:w], "bar").nl(2)

    def row(self, p, key, label, detail, action):
        p.item(action, key=key)
        p.w(f" {key} ", "bar").w("  " + self.tx(label), "body")
        p.end_item()
        if detail:
            p.w("  " + self.tx(detail), "dim")
        p.nl(2)

    def entry(self, p, n, s, items_key, idx):
        unread = s["link"] not in self.gui.read
        w = self.width()
        p.item(lambda: self.gui.go(("story", items_key, idx)), key=n % 10 if n <= 10 else None)
        p.w(f" {n % 10} ", "bar").w(" " + ("* " if unread else "  ") + self.tx(s["title"]),
                                    "hi" if unread else "dim", "hang6")
        p.end_item()
        p.nl().w("       " + truncate(self.tx(" - ".join(x for x in (s["source"], self.ago(s["date"])) if x)), w - 8),
                 "dim").nl()

    def list_info(self, items, page, pages):
        new = sum(1 for s in items if s["link"] not in self.gui.read)
        info = f"{len(items)} STORIES  {new} NEW  SORT:{self.gui.sort}"
        if self.gui.filt:
            info += f"  FILTER:'{self.gui.filt}'"
        return info + f"  PAGE {page + 1}/{pages}"

    def links(self, p, pairs, sep="  "):
        for i, (label, action) in enumerate(pairs):
            if i:
                p.w("  ")
            p.item(action, f"[{self.tx(label)}]", "link")
        p.nl()

    def pager(self, p, key, page, pages):
        g = self.gui
        self.links(p, [("N next page", lambda: g.turn(1)), ("P prev", lambda: g.turn(-1)), ("S sort", g.cycle_sort),
                       ("/ search", g.search), ("R reload", g.reload), ("Esc back", g.back)])

    def story_links(self):
        g = self.gui
        return [("P prev", lambda: g.next_story(-1)), ("N next", lambda: g.next_story(1)),
                ("T " + ("summary" if g.full else "full text"), g.toggle_full), ("O browser", g.open_story),
                ("Esc back", g.back)]

    def byline(self, s):
        when = s["date"].astimezone().strftime("%a %b %d %Y %H:%M") if s["date"] else ""
        return " - ".join(x for x in (s["source"], when) if x)

    def article(self, p, s, paras, note, idx, count):
        w = self.width()
        p.w(self.tx(s["title"]), "hi").nl()
        p.w(self.tx(self.byline(s)), "dim").nl()
        p.w(truncate(s["link"], w), "dim").nl()
        if note:
            p.w(self.tx(note), "note").nl()
        p.w("=" * w, "dim").nl(2)
        for kind, text in paras:
            p.w(self.tx(text), "hi" if kind == "h" else "body").nl(2)
        p.w("-- END OF TRANSMISSION --".center(w), "dim").nl()

    def weather_body(self, p, d):
        g = self.gui
        p.w(self.tx(g.cfg["location"]["name"]), "hi").w("   " + self.tx(g.weather_stamp()), "dim").nl(2)
        for line in weather_text(d, g.cfg, self.width(), self.era.upper):
            for text, tag in line:
                p.w(self.tx(text) if tag != "bar" else text, tag)
            p.nl()

    def weather_links(self):
        g = self.gui
        return [("R refresh", g.refresh_weather), ("L place", g.change_location), ("U units", g.toggle_units),
                ("Esc back", g.back)]

    def rule(self, p):
        p.w("-" * self.width(), "dim").nl()


class GreenScreen(CharLook):
    def foot(self, p):
        pass   # the window's bottom line is the "]" prompt


class Teletype(CharLook):
    """1965: the wire-service printer. Stories come in as numbered slugs; weather as a written forecast."""

    def masthead(self, p, title):
        w = self.width()
        stamp = datetime.now().strftime("%a %b %d %Y  %H%M").upper()
        p.w(f"{NAME.upper()} WIRE SERVICE".ljust(w - len(stamp)) + stamp, "hi").nl()
        p.w("=" * w, "dim").nl()
        p.w(self.tx(title), "head").nl(2)

    def section(self, p, title):
        p.w(f"--- {self.tx(title)} ".ljust(self.width(), "-"), "dim").nl()

    def row(self, p, key, label, detail, action):
        p.item(action, key=key)
        p.w(f"{key:>2}) ", "dim").w(self.tx(label), "hi")
        p.end_item()
        if detail:
            p.w("  ... " + self.tx(detail), "dim")
        p.nl()

    def entry(self, p, n, s, items_key, idx):
        unread = s["link"] not in self.gui.read
        w = self.width()
        when = s["date"].astimezone().strftime("%H%M") if s["date"] else "----"
        slug = f"A{idx + 1:03d}  {truncate(s['source'], 30).upper()}  {when}ET"
        p.item(lambda: self.gui.go(("story", items_key, idx)), key=n % 10 if n <= 10 else None)
        p.w(f"{n % 10}  ", "dim").w(slug, "dim").w("   URGENT" if unread and self.fresh(s) else "", "red")
        p.nl().w("   " + self.tx(s["title"]), "hi" if unread else "body", "hang3")
        p.end_item()
        p.nl(2)

    def fresh(self, s):
        return s["date"] and (datetime.now(timezone.utc) - s["date"]).total_seconds() < 3 * 3600

    def article(self, p, s, paras, note, idx, count):
        w = self.width()
        when = s["date"].astimezone().strftime("%H%M") if s["date"] else "----"
        p.w(f"A{idx + 1:03d}", "dim").w("   BC-" + "".join(ch for ch in s["source"].upper() if ch.isalnum())[:10], "dim").nl()
        p.w(self.tx(s["title"]), "hi").nl()
        if note:
            p.w(self.tx(note), "note").nl()
        p.nl()
        first = True
        for kind, text in paras:
            if first and kind == "p":
                text = f"({s['source']}) -- " + text
                first = False
            p.w(self.tx(text), "hi" if kind == "h" else "body").nl(2)
        p.w(f"-0- {when}ET", "dim").nl()

    def weather_body(self, p, d):
        g = self.gui
        p.w(self.tx(f"WEATHER BULLETIN FOR {g.cfg['location']['name']}"), "hi").nl()
        p.w(self.tx(g.weather_stamp()), "dim").nl(2)
        for line in weather_prose(d, g.cfg):
            p.w(line, "body").nl(2)
        p.w("-0-", "dim").nl()

    def foot(self, p):
        p.nl().w("NNNN", "dim").nl()


class Teletext(CharLook):
    """1983: forty columns of blocky color on the TV. Every screen has a page number to key in."""
    per_page = 8

    def masthead(self, p, title):
        g = self.gui
        num = g.teletext_number()
        clock = datetime.now().strftime("%a %d %b %H:%M")
        p.w(f"P{num:<4}", "white").w(f"{NAME.upper()} {num}".ljust(18), "yellow").w(clock, "white").nl()
        p.w(" " + self.tx(title).upper()[:38].ljust(39), "bar", "big").nl(2)

    def section(self, p, title):
        p.w(self.tx(title).upper(), "cyan").nl()

    def row(self, p, key, label, detail, action):
        p.item(action, key=key)
        p.w(self.tx(label)[:30].ljust(31), "white").w(key, "yellow")
        p.end_item()
        p.nl()
        if detail:
            p.w(" " + truncate(self.tx(detail), 38), "cyan").nl()

    def home_rows(self):
        g = self.gui
        total, new = g.counts(None)
        rows = [("400", "Weather", g.weather_line(), lambda: g.go(("weather",))),
                ("101", "Headlines", f"{total} stories, {new} new" if total else g.loading_line(),
                 lambda: g.go(("list", None)))]
        for i, f in enumerate(g.cfg["feeds"][:8]):
            rows.append((f"{301 + i}", f["title"], "", lambda u=f["url"]: g.go(("list", u))))
        rows += [("701", "Manage feeds", "", lambda: g.go(("feeds",))),
                 ("700", "Settings", "", lambda: g.go(("settings",)))]
        return rows

    def home(self, p):
        self.masthead(p, "Index")
        for key, label, detail, action in self.home_rows():
            self.row(p, key, label, detail, action)
        p.nl()
        self.foot(p)

    def entry(self, p, n, s, items_key, idx):
        unread = s["link"] not in self.gui.read
        num = 102 + idx if idx < 98 else None
        p.item(lambda: self.gui.go(("story", items_key, idx)), key=n % 10 if n <= 10 else None)
        p.w(f"{num or '   '} ", "yellow").w(truncate(s["title"], 35), "white" if unread else "cyan")
        p.end_item()
        p.nl()

    def list_info(self, items, page, pages):
        return f"{len(items)} stories      {page + 1}/{pages}"

    def pager(self, p, key, page, pages):
        pass  # the colored links at the foot of every page do this job

    def article(self, p, s, paras, note, idx, count):
        p.w(self.tx(s["title"]), "yellow").nl()
        p.w(truncate(s["source"], 38), "cyan").nl()
        if note:
            p.w(self.tx(note), "note").nl()
        p.nl()
        for kind, text in paras:
            p.w(text, "cyan" if kind == "h" else "white").nl(2)

    def story(self, p, key, items, idx, paras, note):
        self.article(p, items[idx], paras, note, idx, len(items))
        self.foot(p)

    def weather_body(self, p, d):
        g = self.gui
        p.w(truncate(g.cfg["location"]["name"], 38), "yellow").nl()
        for line in weather_text(d, g.cfg, 40, False):
            for text, tag in line:
                p.w(text, {"hi": "yellow", "body": "white", "dim": "cyan"}.get(tag, tag))
            p.nl()

    def weather(self, p, d, err):
        self.masthead(p, "Weather")
        if d is None:
            p.w(err or "Page coming...", "white").nl()
        else:
            self.weather_body(p, d)
        p.nl()
        self.foot(p)

    def foot(self, p):
        g = self.gui
        p.nl()
        for label, tag, action in (("Headlines", "red", lambda: g.go(("list", None))),
                                   ("Weather", "green", lambda: g.go(("weather",))),
                                   ("Feeds", "yellow", lambda: g.go(("feeds",))),
                                   ("Index", "cyan", lambda: g.go(("home",)))):
            p.item(action, label.ljust(10), tag)


class Bbs(CharLook):
    """1991: a dial-up bulletin board. Boxes, ANSI color, a message base, and a clock ticking down."""

    def masthead(self, p, title):
        w = self.width()
        clock = datetime.now().strftime("%H:%M")
        inner = w - 2
        label = f"  {NAME} BBS  ·  Node 1  ·  {title}"
        p.w("╔" + "═" * inner + "╗", "blue").nl()
        p.w("║", "blue").w(label.ljust(inner - len(clock) - 2), "cyan").w(clock + "  ", "yellow").w("║", "blue").nl()
        p.w("╚" + "═" * inner + "╝", "blue").nl(2)

    def section(self, p, title):
        p.w(f"─── {title} ".ljust(self.width(), "─"), "magenta").nl()

    def row(self, p, key, label, detail, action):
        p.item(action, key=key)
        p.w("[", "blue").w(key, "yellow").w("] ", "blue").w(label, "cyan")
        p.end_item()
        if detail:
            p.w("  " + detail, "dim")
        p.nl()

    def entry(self, p, n, s, items_key, idx):
        unread = s["link"] not in self.gui.read
        w = self.width()
        when = s["date"].astimezone().strftime("%m/%d %H:%M") if s["date"] else ""
        p.item(lambda: self.gui.go(("story", items_key, idx)), key=n % 10 if n <= 10 else None)
        p.w(f"{idx + 1:>4} ", "yellow").w("*" if unread else " ", "magenta")
        p.w(" " + truncate(s["title"], w - 36).ljust(w - 35), "hi" if unread else "fg")
        p.w(truncate(s["source"], 15).ljust(16), "green").w(when, "dim")
        p.end_item()
        p.nl()

    def story_list(self, p, key, items, page, pages, start):
        g = self.gui
        w = self.width()
        self.masthead(p, f"Message Base: {g.list_title(key)}")
        p.w(self.list_info(items, page, pages), "dim").nl(2)
        p.w("   # ", "yellow").w("  Subject".ljust(w - 34), "yellow").w("From".ljust(16), "yellow").w("Date", "yellow").nl()
        p.w("─" * w, "blue").nl()
        chunk = items[start:start + self.per_page]
        for i, s in enumerate(chunk):
            self.entry(p, i + 1, s, key, start + i)
        if not chunk:
            p.w(g.empty_line(), "body").nl()
        p.nl()
        self.pager(p, key, page, pages)

    def article(self, p, s, paras, note, idx, count):
        w = self.width()
        when = s["date"].astimezone().strftime("%m/%d/%y %H:%M") if s["date"] else "?"
        p.w(f"Msg #{idx + 1} of {count}", "yellow").nl()
        p.w("From: ", "cyan").w(s["source"], "green").nl()
        p.w("Date: ", "cyan").w(when, "body").nl()
        p.w("Subj: ", "cyan").w(s["title"], "hi").nl()
        p.w("─" * w, "blue").nl()
        if note:
            p.w(note, "note").nl()
        p.nl()
        for kind, text in paras:
            p.w(text, "hi" if kind == "h" else "body").nl(2)
        p.w("─" * w, "blue").nl()

    def links(self, p, pairs, sep="  "):
        for i, (label, action) in enumerate(pairs):
            if i:
                p.w("  ")
            key, _, rest = label.partition(" ")
            p.item(action)
            p.w("[", "blue").w(key, "yellow").w("] " + rest, "cyan")
            p.end_item()
        p.nl()


class EarlyWeb(Look):
    """1994: a page nobody styled. Browser-default gray, Times, <h1>, <hr>, <ul>, blue underlined links."""

    def hr(self, p):
        """<hr>: the browser's sunken, beveled rule, as wide as the text."""
        g = self.gui
        t = p.t
        width = min(t.winfo_width() - 2 * int(str(t.cget("padx"))), g.px(1000)) if t.winfo_width() > 50 else g.px(900)
        bevel = tk.Frame(t, height=2, width=max(g.px(200), width), bd=1, relief="sunken", bg=g.colors["bg"])
        p.nl()
        p.embed(bevel, pady=g.px(6))
        p.nl()

    def masthead(self, p, title):
        p.w(title if title != "Main Menu" else f"{NAME} News Page", "big").nl()

    def section(self, p, title):
        p.w(title, "h2").nl()

    def row(self, p, key, label, detail, action):
        p.w("  •  ", "fg")
        p.item(action, label, "link", key=key)
        if detail:
            p.w(f" ({detail})", "fg")
        p.nl()

    def entry(self, p, n, s, items_key, idx):
        unread = s["link"] not in self.gui.read
        p.w("  •  ", "fg")
        p.item(lambda: self.gui.go(("story", items_key, idx)), s["title"], "link" if unread else "visited",
               key=n % 10 if n <= 10 else None)
        meta = ", ".join(x for x in (s["source"], self.ago(s["date"])) if x)
        p.w(f" ({meta})" if meta else "", "fg").nl()

    def links(self, p, pairs, sep=" | "):
        p.w("[ ", "fg")
        for i, (label, action) in enumerate(pairs):
            if i:
                p.w(" | ", "fg")
            p.item(action, label, "link")
        p.w(" ]", "fg").nl()

    def pager(self, p, key, page, pages):
        g = self.gui
        self.links(p, [("Sort", g.cycle_sort), ("Search", g.search), ("Reload", g.reload), ("Back", g.back)])

    def home(self, p):
        g = self.gui
        self.masthead(p, "Main Menu")
        p.w(f"Welcome! This page collects the news from {plural(len(g.cfg['feeds']), 'feed')} and the "
            f"weather for {(g.cfg.get('location') or {}).get('name', 'your town')}. It updates itself.", "body").nl()
        self.hr(p)
        self.section(p, "Weather")
        p.w("  •  ", "fg")
        p.item(lambda: g.go(("weather",)), g.weather_line(), "link").nl()
        self.section(p, "Headlines")
        items = g.items_for(None)
        for i, s in enumerate(items[:12]):
            self.entry(p, i + 1, s, None, i)
        p.w("  •  ", "fg")
        p.item(lambda: g.go(("list", None)), f"All {len(items)} stories", "link").nl()
        self.section(p, "Sources")
        for f in g.cfg["feeds"]:
            t, n = g.counts(f["url"])
            p.w("  •  ", "fg")
            p.item(lambda u=f["url"]: g.go(("list", u)), f["title"], "link")
            p.w(f" ({n} new)" if t else "", "fg").nl()
        self.section(p, "This Page")
        p.w("  •  ", "fg")
        p.item(lambda: g.go(("feeds",)), "Change the list of sources", "link").nl()
        p.w("  •  ", "fg")
        p.item(lambda: g.go(("settings",)), "Settings", "link").nl()
        self.foot(p)

    def story_list(self, p, key, items, page, pages, start):
        g = self.gui
        self.masthead(p, g.list_title(key))
        p.w(self.list_info(items, page, pages) + ".", "fg").nl()
        self.hr(p)
        for i, s in enumerate(items):
            self.entry(p, i + 1, s, key, i)
        if not items:
            p.w(g.empty_line(), "body").nl()
        self.hr(p)
        self.pager(p, key, page, pages)
        self.foot(p)

    def article(self, p, s, paras, note, idx, count):
        p.w(s["title"], "big").nl()
        p.w(self.byline(s), "fg").nl()
        if note:
            p.w(note, "note").nl()
        self.hr(p)
        for kind, text in paras:
            p.w(text, "h2" if kind == "h" else "body", "para").nl()

    def story(self, p, key, items, idx, paras, note):
        self.article(p, items[idx], paras, note, idx, len(items))
        self.hr(p)
        self.links(p, self.story_links())
        self.foot(p)

    def weather_body(self, p, d):
        g = self.gui
        p.w(f"Forecast for {g.cfg['location']['name']}", "h2").nl()
        p.w(g.weather_stamp() + ".", "fg").nl(2)
        for line in weather_prose(d, g.cfg, upper=False):
            p.w(line, "body", "para").nl()
        self.section(p, "The Week")
        daily = d["daily"]
        u = unit_letter(g.cfg)
        rows = [f"{'Day':<10}{'Sky':<20}{'Low':>5}{'High':>6}{'Rain':>6}", "-" * 47]
        for i, day in enumerate(daily["time"]):
            pop = daily["precipitation_probability_max"][i]
            rows.append(f"{day_name(day, i).title():<10}{conditions(daily['weather_code'][i])[1].title():<20}"
                        f"{round(daily['temperature_2m_min'][i]):>4}{u}{round(daily['temperature_2m_max'][i]):>5}{u}"
                        f"{(str(pop) + '%') if pop is not None else '-':>6}")
        p.w("\n".join(rows), "mono").nl()

    def weather(self, p, d, err):
        self.masthead(p, "Weather")
        self.hr(p)
        if d is None:
            p.w(err or "Loading the forecast…", "body").nl()
        else:
            self.weather_body(p, d)
        self.hr(p)
        self.links(p, self.weather_links())
        self.foot(p)

    def foot(self, p):
        self.hr(p)
        p.w(f"Last modified: {datetime.now().strftime('%a %b %d %H:%M:%S %Y')}", "fg").nl()
        p.w(f"{NAME} {self.gui.version}", "fg").nl()


class Portal(Look):
    """1997: a start page on the web. Navy section bars, blue links that turn purple once read."""
    per_page = 25

    def masthead(self, p, title):
        p.w(f"{NAME} Net", "big", "center").nl()
        p.w("Your window on the world: news, weather & more", "dim", "center", "small").nl()
        p.w("—" * 3, "dim", "center").nl()
        if title not in ("Main Menu",):
            p.w(title, "headline").nl()
        p.nl()

    def section(self, p, title):
        p.w("  " + title + "  ", "bar", "barfont").nl()

    def row(self, p, key, label, detail, action):
        p.w("  • ", "fg")
        p.item(action, label, "link", key=key)
        if detail:
            p.w("  " + detail, "dim", "small")
        p.nl()

    def entry(self, p, n, s, items_key, idx):
        unread = s["link"] not in self.gui.read
        p.w("  • ", "fg")
        p.item(lambda: self.gui.go(("story", items_key, idx)), s["title"], "link" if unread else "visited",
               key=n % 10 if n <= 10 else None)
        if unread and s["date"] and (datetime.now(timezone.utc) - s["date"]).total_seconds() < 3 * 3600:
            p.w(" NEW!", "red", "barfont")
        p.nl().w("     " + " · ".join(x for x in (s["source"], self.ago(s["date"])) if x), "dim", "small").nl()

    def home(self, p):
        g = self.gui
        self.masthead(p, "Main Menu")
        self.section(p, "Weather")
        d = g.weather_data
        if d and g.cfg.get("location"):
            cur = d["current"]
            p.w("  ")
            p.item(lambda: g.go(("weather",)), f"{g.cfg['location']['name']}: {round(cur['temperature_2m'])}°"
                   f"{unit_letter(g.cfg)}, {conditions(cur['weather_code'])[0].capitalize()}", "link")
            p.w("  (5-day forecast inside)", "dim", "small").nl()
        else:
            p.w("  ")
            p.item(lambda: g.go(("weather",)), g.weather_line() or "Set your city", "link").nl()
        p.nl()
        self.section(p, "Top Stories")
        items = g.items_for(None)
        for i, s in enumerate(items[:10]):
            self.entry(p, i + 1, s, None, i)
        p.w("  ")
        p.item(lambda: g.go(("list", None)), f"More headlines ({len(items)})…", "link").nl(2)
        self.section(p, "Channels")
        for i, f in enumerate(g.cfg["feeds"]):
            t, n = g.counts(f["url"])
            p.w("  • ", "fg")
            p.item(lambda u=f["url"]: g.go(("list", u)), f["title"], "link")
            p.w(f"  ({n} new)" if t else "", "dim", "small").nl()
        p.nl()
        self.links(p, [("Manage feeds", lambda: g.go(("feeds",))), ("Settings", lambda: g.go(("settings",)))], " | ")
        self.foot(p)

    def foot(self, p):
        g = self.gui
        p.nl().w("—" * 3, "dim", "center").nl()
        p.w(f"© 1997–{datetime.now().year} {NAME} Net · Best viewed at 800×600 or higher\n", "dim", "small", "center")
        p.w(f"You are visitor No. {len(g.read) + 1:06d}", "dim", "small", "center").nl()

    def weather_links(self):
        g = self.gui
        return [("Refresh", g.refresh_weather), ("Change city", g.change_location),
                ("Show °C" if g.cfg.get("units") == "fahrenheit" else "Show °F", g.toggle_units), ("Back", g.back)]


class Panes(Look):
    """2006 and today: subscriptions on the left, the story list, and a reading pane."""
    numbered = False

    def sidebar(self, p):
        g = self.gui
        cur = g.screen
        rows = [("Today", ("home",), ""), ("Weather", ("weather",), g.weather_short())]
        total, new = g.counts(None)
        rows.append(("All stories", ("list", None), str(new) if new else ""))
        for f in g.cfg["feeds"]:
            t, n = g.counts(f["url"])
            rows.append((f["title"], ("list", f["url"]), str(n) if n else ""))
        p.w(self.side_head("Reading"), "sidehead").nl()
        for i, (label, screen, badge) in enumerate(rows):
            if i == 3:
                p.w(self.side_head("Subscriptions"), "sidehead").nl()
            here = cur[:2] == screen[:2] or (screen[0] == "list" and cur[0] == "story" and cur[1] == screen[1])
            p.item(lambda s=screen: g.go(s))
            p.w("  " + label, "sidehi" if (badge and screen[0] == "list") or here else "side")
            if badge:
                p.w(f"  ({badge})" if self.era.key == "reader" else f"  {badge}", "sidedim")
            p.end_item()
            if here:
                p.select(len(p.items) - 1, see=False)
            p.nl()
        p.nl()
        p.item(lambda: g.go(("feeds",)), "  Manage feeds", "side").nl()
        p.item(lambda: g.go(("settings",)), "  Settings", "side").nl()

    def side_head(self, text):
        return ("  " + text.upper()) if self.era.key == "reader" else ("  " + text)

    def list_rows(self, p, key, items, current):
        g = self.gui
        for i, s in enumerate(items):
            unread = s["link"] not in g.read
            p.item(lambda i=i: g.go(("story", key, i)))  # (the newlines too, so a highlight spans the pane)
            p.w(s["title"] + "\n", "listhi" if unread else "listread", "row")
            p.w(" · ".join(x for x in (s["source"], self.ago(s["date"])) if x) + "\n", "listdim", "row")
            p.end_item()
            p.w(" ", "gap").nl()
        if not items:
            p.w("  " + g.empty_line(), "dim").nl()
        if current is not None:
            p.select(current, see=True)

    def article(self, p, s, paras, note, idx, count):
        p.item(self.gui.open_story, s["title"], "big", "titlelink").nl()
        p.w(self.byline(s), "dim", "small").nl()
        if note:
            p.w(note, "note").nl()
        p.nl()
        for kind, text in paras:
            p.w(text, "head" if kind == "h" else "body", "para").nl()
        p.nl()
        self.links(p, self.story_links()[:-1], "   ·   ")

    def today(self, p):
        """The reading pane before a story is picked: the day at a glance."""
        g = self.gui
        p.w(long_date(datetime.now()), "big").nl(2)
        d = g.weather_data
        if d and g.cfg.get("location"):
            cur = d["current"]
            p.item(lambda: g.go(("weather",)))
            p.w(f"{round(cur['temperature_2m'])}°{unit_letter(g.cfg)}  ", "big")
            p.w(conditions(cur["weather_code"], cur.get("is_day", 1))[0].capitalize(), "head")
            p.end_item()
            p.nl().w(g.cfg["location"]["name"] + "   " + g.weather_stamp(), "dim", "small").nl(2)
        else:
            p.item(lambda: g.go(("weather",)), g.weather_line() or "Set your city for the weather", "link").nl(2)
        total, new = g.counts(None)
        p.w(f"{plural(total, 'story')}, {new} new" if total else g.loading_line(), "head").nl()
        stories, texts = g.library.count()
        p.w(f"{texts} saved on this computer for reading offline.", "dim", "small").nl(2)
        p.w("Pick a story on the left. Up and Down move through the list, Return opens, "
            "N and P go to the next or previous story, Space scrolls.", "dim", "small").nl()


LOOKS = {"teletype": Teletype, "phosphor": GreenScreen, "teletext": Teletext, "bbs": Bbs, "earlyweb": EarlyWeb, "portal": Portal,
         "reader": Panes, "modern": Panes}


def stamp_saved(at):
    t = time.localtime(at)
    return f"saved {time.strftime('%a', t)} {t.tm_hour % 12 or 12}:{t.tm_min:02d} {'AM' if t.tm_hour < 12 else 'PM'}"
