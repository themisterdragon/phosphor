"""Phosphor's engine, shared by the terminal app and the window app: settings, feeds,
articles, weather, and the offline library. No curses and no Tk in here.

Pure Python standard library. No API keys.
"""

import html
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.entities import name2codepoint
from html.parser import HTMLParser

APP = "PHOSPHOR"
NAME = "Phosphor"


def _xdg(var, fallback):
    return os.path.join(os.environ.get(var) or os.path.expanduser(fallback), "phosphor")


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", "~/.config")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
DATA_DIR = _xdg("XDG_DATA_HOME", "~/.local/share")
LIBRARY_PATH = os.path.join(DATA_DIR, "library.json")
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
WX_URL = "https://api.open-meteo.com/v1/forecast"
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
OFFLINE_CHOICES = [0, 50, 100, 200, 500]

DEFAULT_CONFIG = {
    "location": None,
    "units": "fahrenheit",
    "theme": "green",
    "uppercase": True,
    "typewriter": True,
    "boot": True,
    "offline_keep": 100,     # stories (with full text) kept on disk for reading offline; 0 = off
    "feeds": [
        {"title": "BBC News - World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
        {"title": "NASA", "url": "https://www.nasa.gov/news-release/feed/"},
        {"title": "Smithsonian Magazine", "url": "https://www.smithsonianmag.com/rss/latest_articles/"},
        {"title": "ScienceDaily", "url": "https://www.sciencedaily.com/rss/top/science.xml"},
        {"title": "Good News Network", "url": "https://www.goodnewsnetwork.org/feed/"},
    ],
    "read": [],
    # the window app
    "gui_era": "modern",
    "gui_theme": "system",   # system / light / dark (eras that have both)
    "gui_text": 0,           # text size step, -2..4
    "gui_mode": "window",    # window / terminal: the view the window app opens in
    "gui_size": None,
}

THEME_NAMES = ("green", "amber", "white")

# ---------------------------------------------------------------- big font --

FONT = {
    "0": ["###", "#.#", "#.#", "#.#", "###"],
    "1": [".#.", "##.", ".#.", ".#.", "###"],
    "2": ["###", "..#", "###", "#..", "###"],
    "3": ["###", "..#", "###", "..#", "###"],
    "4": ["#.#", "#.#", "###", "..#", "..#"],
    "5": ["###", "#..", "###", "..#", "###"],
    "6": ["###", "#..", "###", "#.#", "###"],
    "7": ["###", "..#", "..#", "..#", "..#"],
    "8": ["###", "#.#", "###", "#.#", "###"],
    "9": ["###", "#.#", "###", "..#", "###"],
    "-": ["...", "...", "###", "...", "..."],
    "°": ["##", "##", "..", "..", ".."],
    "C": ["###", "#..", "#..", "#..", "###"],
    "F": ["###", "#..", "##.", "#..", "#.."],
    "H": ["#.#", "#.#", "###", "#.#", "#.#"],
    "O": ["###", "#.#", "#.#", "#.#", "###"],
    "P": ["###", "#.#", "###", "#..", "#.."],
    "R": ["##.", "#.#", "##.", "#.#", "#.#"],
    "S": ["###", "#..", "###", "..#", "###"],
    " ": ["..", "..", "..", "..", ".."],
}


def big(text, px="██"):
    rows = [""] * 5
    blank = " " * len(px)
    for ch in text:
        glyph = FONT.get(ch.upper(), FONT[" "])
        for i in range(5):
            rows[i] += "".join(px if c == "#" else blank for c in glyph[i]) + blank
    return [r.rstrip() for r in rows]


# ----------------------------------------------------------------- weather --

WMO = {
    0: ("CLEAR SKY", "CLEAR", "sun"),
    1: ("MAINLY CLEAR", "MOSTLY CLEAR", "sun"),
    2: ("PARTLY CLOUDY", "PARTLY CLOUDY", "partly"),
    3: ("OVERCAST", "OVERCAST", "cloud"),
    45: ("FOG", "FOG", "fog"),
    48: ("FREEZING FOG", "FOG", "fog"),
    51: ("LIGHT DRIZZLE", "DRIZZLE", "drizzle"),
    53: ("DRIZZLE", "DRIZZLE", "drizzle"),
    55: ("HEAVY DRIZZLE", "DRIZZLE", "drizzle"),
    56: ("FREEZING DRIZZLE", "FRZ DRIZZLE", "sleet"),
    57: ("FREEZING DRIZZLE", "FRZ DRIZZLE", "sleet"),
    61: ("LIGHT RAIN", "LIGHT RAIN", "rain"),
    63: ("RAIN", "RAIN", "rain"),
    65: ("HEAVY RAIN", "HEAVY RAIN", "rain"),
    66: ("FREEZING RAIN", "FRZ RAIN", "sleet"),
    67: ("FREEZING RAIN", "FRZ RAIN", "sleet"),
    71: ("LIGHT SNOW", "LIGHT SNOW", "snow"),
    73: ("SNOW", "SNOW", "snow"),
    75: ("HEAVY SNOW", "HEAVY SNOW", "snow"),
    77: ("SNOW GRAINS", "SNOW", "snow"),
    80: ("LIGHT SHOWERS", "SHOWERS", "rain"),
    81: ("SHOWERS", "SHOWERS", "rain"),
    82: ("VIOLENT SHOWERS", "HVY SHOWERS", "rain"),
    85: ("SNOW SHOWERS", "SNOW SHWRS", "snow"),
    86: ("HEAVY SNOW SHOWERS", "SNOW SHWRS", "snow"),
    95: ("THUNDERSTORM", "T-STORMS", "storm"),
    96: ("T-STORM WITH HAIL", "T-STORMS", "storm"),
    99: ("T-STORM WITH HAIL", "T-STORMS", "storm"),
}

ART = {
    "sun": [
        "    \\   /    ",
        "     .-.     ",
        "  - (   ) -  ",
        "     `-'     ",
        "    /   \\    ",
    ],
    "moon": [
        "     _..   * ",
        "   .' .'     ",
        "  :  :    *  ",
        "   '. '.     ",
        "     `''  *  ",
    ],
    "partly": [
        "   \\  /      ",
        " _ /\"\".-.    ",
        "   \\_(   ).  ",
        "   /(___(__) ",
        "             ",
    ],
    "cloud": [
        "             ",
        "     .--.    ",
        "  .-(    ).  ",
        " (___.__)__) ",
        "             ",
    ],
    "fog": [
        "             ",
        " _ - _ - _ - ",
        "  _ - _ - _  ",
        " _ - _ - _ - ",
        "             ",
    ],
    "drizzle": [
        "     .-.     ",
        "    (   ).   ",
        "   (___(__)  ",
        "    ' ' ' '  ",
        "   ' ' ' '   ",
    ],
    "rain": [
        "     .-.     ",
        "    (   ).   ",
        "   (___(__)  ",
        "   ,',',','  ",
        "  ,',',','   ",
    ],
    "snow": [
        "     .-.     ",
        "    (   ).   ",
        "   (___(__)  ",
        "    *  *  *  ",
        "   *  *  *   ",
    ],
    "sleet": [
        "     .-.     ",
        "    (   ).   ",
        "   (___(__)  ",
        "    ' * ' *  ",
        "   * ' * '   ",
    ],
    "storm": [
        "     .-.     ",
        "    (   ).   ",
        "   (___(__)  ",
        "    ,/_,'/_  ",
        "     /   /   ",
    ],
}

COMPASS = "N NNE NE ENE E ESE SE SSE S SSW SW WSW W WNW NW NNW".split()


def compass(deg):
    return COMPASS[int(deg / 22.5 + 0.5) % 16]


def conditions(code, is_day=1):
    """(long description, short description, art key) for a weather code."""
    desc, short, art = WMO.get(code, ("UNKNOWN", "?", "cloud"))
    if art == "sun" and not is_day:
        art = "moon"
    return desc, short, art


def fetch_weather(loc, units):
    f = units == "fahrenheit"
    q = urllib.parse.urlencode({
        "latitude": loc["lat"], "longitude": loc["lon"],
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,"
                   "weather_code,wind_speed_10m,wind_direction_10m,is_day",
        "hourly": "temperature_2m,precipitation_probability",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                 "precipitation_probability_max,sunrise,sunset",
        "temperature_unit": "fahrenheit" if f else "celsius",
        "wind_speed_unit": "mph" if f else "kmh",
        "timezone": "auto", "forecast_days": 7,
    })
    data, _, _ = http_get(f"{WX_URL}?{q}")
    return json.loads(data)


def find_places(query):
    """Up to 9 places matching 'City' or 'City, State/Country'."""
    name, _, rest = query.partition(",")
    p = urllib.parse.urlencode({"name": name.strip(), "count": 10, "language": "en", "format": "json"})
    data, _, _ = http_get(f"{GEO_URL}?{p}")
    res = json.loads(data).get("results") or []
    rest = rest.strip().lower()
    if rest:
        filt = [r for r in res if any(rest in (r.get(k) or "").lower()
                for k in ("admin1", "country", "country_code", "admin2"))]
        res = filt or res
    return res[:9]


def place_label(r, short=False):
    return ", ".join(x for x in (r.get("name"), r.get("admin1"),
                                 r.get("country_code") if short else r.get("country")) if x)


def location_from(place):
    return {"name": place_label(place, short=True), "lat": place["latitude"], "lon": place["longitude"]}


def hourly_from_now(d, n=24):
    """(times, temps, rain chances) for the next n hours."""
    hourly = d["hourly"]
    now = d["current"]["time"][:13]
    start = next((i for i, t in enumerate(hourly["time"]) if t[:13] >= now), 0)
    sl = slice(start, start + n)
    return hourly["time"][sl], hourly["temperature_2m"][sl], hourly["precipitation_probability"][sl]


def day_name(iso, i):
    return "TODAY" if i == 0 else datetime.fromisoformat(iso).strftime("%a").upper()


# ------------------------------------------------------------------ config --

def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(CONFIG_PATH) as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        # don't clobber a config we couldn't parse
        try:
            os.replace(CONFIG_PATH, CONFIG_PATH + ".bad")
        except OSError:
            pass
    if cfg.get("theme") not in THEME_NAMES:
        cfg["theme"] = "green"
    return cfg


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_PATH)


# -------------------------------------------------------------------- text --

PUNCT = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "“": '"', "”": '"',
    "–": "-", "—": "--", "…": "...", " ": " ", "•": "*",
    "​": "", "′": "'", "″": '"', "﻿": "",
})


def clean(s):
    return " ".join((s or "").translate(PUNCT).split())


def truncate(s, n):
    if n <= 0:
        return ""
    return s if len(s) <= n else s[: max(0, n - 3)] + "..."


def html_to_paragraphs(s):
    if not s:
        return []
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</(p|div|li|h[1-6]|blockquote|tr|ul|ol)>", "\n\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "\n\n* ", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    paras = [clean(p) for p in re.split(r"\n\s*\n", s)]
    return [("p", p) for p in paras if p]


def ago(d):
    if not d:
        return ""
    secs = (datetime.now(timezone.utc) - d).total_seconds()
    if secs < 60:
        return "JUST NOW"
    if secs < 3600:
        return f"{int(secs // 60)}M AGO"
    if secs < 86400:
        return f"{int(secs // 3600)}H AGO"
    if secs < 86400 * 7:
        return f"{int(secs // 86400)}D AGO"
    return d.astimezone().strftime("%b %d %Y")


def short_err(e):
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    if isinstance(e, urllib.error.URLError):
        return f"NETWORK: {e.reason}"
    if isinstance(e, ET.ParseError):
        return "NOT A VALID FEED"
    if isinstance(e, TimeoutError):
        return "TIMED OUT"
    return f"{type(e).__name__}: {e}"[:60]


# ----------------------------------------------------------------- network --

def http_get(url, timeout=12, limit=4_000_000):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limit), r.headers.get_content_charset(), r.geturl()


def decode_html(data, charset):
    if not charset:
        m = re.search(rb"""<meta[^>]+charset=["']?([\w-]+)""", data[:4096], re.I)
        charset = m.group(1).decode() if m else "utf-8"
    try:
        return data.decode(charset, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def open_url(url):
    if not url.startswith(("http://", "https://")):
        return False
    try:
        if sys.platform == "win32":
            os.startfile(url)
            return True
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([opener, url], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except OSError:
        return webbrowser.open(url)


# -------------------------------------------------------------------- feeds --

def _tag(el):
    return el.tag.rsplit("}", 1)[-1].lower() if isinstance(el.tag, str) else ""


def _child(el, *names):
    for name in names:
        for c in el:
            if _tag(c) == name:
                return c
    return None


def _text(el):
    if el is None:
        return ""
    if len(el):  # xhtml content
        return "".join(el.itertext()).strip()
    return (el.text or "").strip()


def parse_date(s):
    if not s:
        return None
    d = None
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        try:
            d = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


XML_ENTS = {"amp", "lt", "gt", "quot", "apos"}


def _fix_entities(data):
    def sub(m):
        name = m.group(1).decode()
        if name in XML_ENTS or name not in name2codepoint:
            return m.group(0)
        return f"&#{name2codepoint[name]};".encode()
    return re.sub(rb"&([A-Za-z][A-Za-z0-9]*);", sub, data)


def parse_feed(data):
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        root = ET.fromstring(_fix_entities(data))
    if _tag(root) not in ("rss", "feed", "rdf"):
        raise ET.ParseError("not a feed")

    chan = _child(root, "channel")
    feed_title = clean(_text(_child(chan if chan is not None else root, "title")))

    stories = []
    for el in root.iter():
        if _tag(el) not in ("item", "entry"):
            continue
        title = clean(html.unescape(_text(_child(el, "title")))) or "(UNTITLED)"
        link = ""
        for c in el:
            if _tag(c) == "link":
                href = c.get("href")
                if href and c.get("rel", "alternate") == "alternate":
                    link = href
                    break
                if not href and (c.text or "").strip():
                    link = c.text.strip()
                    break
        if not link:
            guid = _child(el, "guid", "id")
            if guid is not None and (guid.text or "").startswith("http"):
                link = guid.text.strip()
        summary = _text(_child(el, "encoded", "content", "description", "summary"))
        date = parse_date(_text(_child(el, "pubdate", "published", "updated", "date", "issued")))
        stories.append({"title": title, "link": link or title, "summary": summary, "date": date})
    return feed_title, stories


def discover_feed(page_html, base):
    for m in re.finditer(r"<link\b[^>]*>", page_html, re.I):
        tag = m.group(0)
        if re.search(r"application/(rss|atom)\+xml", tag, re.I):
            href = re.search(r"""href=["']([^"']+)""", tag, re.I)
            if href:
                return urllib.parse.urljoin(base, html.unescape(href.group(1)))
    return None


def probe_feed(url):
    """Fetch a URL; if it's a web page, try to autodiscover its feed. -> (url, title)"""
    if "://" not in url:
        url = "https://" + url
    data, charset, final = http_get(url)
    try:
        title, _ = parse_feed(data)
        return final, title
    except ET.ParseError:
        found = discover_feed(decode_html(data, charset), final)
        if not found:
            raise ET.ParseError("no feed found")
        data, _, final = http_get(found)
        title, _ = parse_feed(data)
        return final, title


def read_opml(path):
    """[(title, url)] of the feeds in an OPML file."""
    root = ET.parse(os.path.expanduser(path)).getroot()
    return [(o.get("title") or o.get("text") or o.get("xmlUrl"), o.get("xmlUrl"))
            for o in root.iter("outline") if o.get("xmlUrl")]


def add_feeds(cfg, pairs):
    """Subscribe to (title, url) pairs not already in the list; returns how many were added."""
    have = {f["url"] for f in cfg["feeds"]}
    added = 0
    for title, url in pairs:
        if url and url not in have:
            cfg["feeds"].append({"title": title or url, "url": url})
            have.add(url)
            added += 1
    return added


def merge_stories(results):
    """One list from several feeds' results, without repeats."""
    seen, stories = set(), []
    for c in results:
        for s in c["stories"]:
            if s["link"] not in seen:
                seen.add(s["link"])
                stories.append(s)
    return stories


SORTS = ["NEWEST", "OLDEST", "SOURCE", "UNREAD"]


def arrange(stories, sort, filt, read):
    if filt:
        f = filt.lower()
        stories = [s for s in stories if f in s["title"].lower() or f in s["source"].lower()]
    newest = sorted(stories, key=lambda s: s["date"] or EPOCH, reverse=True)
    if sort == "OLDEST":
        return newest[::-1]
    if sort == "SOURCE":
        return sorted(newest, key=lambda s: s["source"].lower())
    if sort == "UNREAD":
        return sorted(newest, key=lambda s: s["link"] in read)
    return newest


class FeedStore:
    """Feeds fetched this session, falling back to the offline library when a feed can't be reached."""

    def __init__(self, library=None):
        self.cache = {}
        self.locks = {}
        self.glock = threading.Lock()
        self.library = library

    def _lock(self, url):
        with self.glock:
            return self.locks.setdefault(url, threading.Lock())

    def get(self, feed, force=False):
        url = feed["url"]
        with self._lock(url):
            c = self.cache.get(url)
            if c and not force:
                return c
            try:
                data, _, _ = http_get(url)
                title, stories = parse_feed(data)
                for s in stories:
                    s["source"] = feed.get("title") or title or url
                c = {"stories": stories, "title": title, "error": None, "offline": False}
                if self.library:
                    self.library.merge(url, stories)
            except Exception as e:
                old = (c or {}).get("stories") or []
                offline = not old and self.library is not None
                if offline:
                    old = self.library.stories_for(url, feed.get("title"))
                c = {"stories": old, "title": None, "error": short_err(e), "offline": offline and bool(old)}
            self.cache[url] = c
            return c

    def get_all(self, feeds, force=False):
        if not feeds:
            return []
        with ThreadPoolExecutor(max_workers=8) as ex:
            return list(ex.map(lambda f: self.get(f, force), feeds))

    def stories(self, feeds):
        """Whatever is already here for these feeds, without fetching."""
        return merge_stories([c for c in (self.cache.get(f["url"]) for f in feeds) if c])


# ------------------------------------------------------------------ articles --

class ArticleParser(HTMLParser):
    SKIP = {"script", "style", "nav", "header", "footer", "aside", "form", "noscript",
            "svg", "button", "figcaption", "iframe", "select", "template", "dialog"}
    BLOCK = {"p", "h1", "h2", "h3", "h4", "li", "blockquote", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.in_article = 0
        self.cur = None
        self.blocks = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
            return
        if tag in ("article", "main"):
            self.in_article += 1
        if tag in self.BLOCK and not self.skip:
            self.flush()
            self.cur = [tag, []]

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if tag in self.BLOCK:
            self.flush()
        if tag in ("article", "main"):
            self.in_article = max(0, self.in_article - 1)

    def handle_data(self, d):
        if not self.skip and self.cur is not None:
            self.cur[1].append(d)

    def flush(self):
        if self.cur:
            t = clean("".join(self.cur[1]))
            if t:
                self.blocks.append((self.cur[0], t, self.in_article > 0))
        self.cur = None


def extract_article(page):
    p = ArticleParser()
    p.feed(page)
    p.close()
    p.flush()
    inside = [b for b in p.blocks if b[2]]
    pool = inside if sum(len(t) for tag, t, _ in inside if tag == "p") > 400 else p.blocks
    out = []
    for tag, t, _ in pool:
        if tag[0] == "h":
            if len(t) < 120:
                out.append(("h", t))
        elif tag == "li":
            if len(t) > 60:
                out.append(("p", "* " + t))
        elif len(t) > 40 or t[-1:] in '.?!"':
            out.append(("p", t))
    while out and out[-1][0] == "h":
        out.pop()
    if sum(len(t) for k, t in out if k == "p") < 300:
        return None
    return out


def fetch_article(url):
    data, charset, _ = http_get(url)
    return extract_article(decode_html(data, charset))


# ------------------------------------------------------------ offline library --

def _iso(d):
    return d.isoformat() if d else None


class Library:
    """The newest stories (and their full text) kept on disk so Phosphor works without a connection.

    Keeps `keep` stories in all, shared fairly among the feeds (newest first, taking turns),
    plus the last weather report. Saved to LIBRARY_PATH.
    """

    RETRY = 6 * 3600   # seconds before trying again to save the full text of a story that failed

    def __init__(self, path=None):
        self.path = path or LIBRARY_PATH
        self.lock = threading.RLock()
        self.items = {}      # link -> stored story
        self.weather = None
        self.dirty = False
        try:
            with open(self.path) as f:
                data = json.load(f)
            self.items = data.get("stories") or {}
            self.weather = data.get("weather")
        except (OSError, ValueError, AttributeError):
            pass

    # -- stories
    def merge(self, feed_url, stories):
        now = time.time()
        with self.lock:
            for s in stories:
                old = self.items.get(s["link"], {})
                self.items[s["link"]] = {
                    "title": s["title"], "link": s["link"], "summary": s["summary"][:20000],
                    "date": _iso(s["date"]), "source": s.get("source", ""), "feed": feed_url,
                    "seen": now, "text": old.get("text"), "tried": old.get("tried", 0),
                }
            self.dirty = True

    def _story(self, it, title=None):
        return {"title": it["title"], "link": it["link"], "summary": it.get("summary", ""),
                "date": parse_date(it.get("date")), "source": title or it.get("source", ""), "saved": True}

    def stories_for(self, feed_url, title=None):
        with self.lock:
            return [self._story(it, title) for it in self.items.values() if it.get("feed") == feed_url]

    def article(self, link):
        with self.lock:
            it = self.items.get(link)
            return [tuple(p) for p in it["text"]] if it and it.get("text") else None

    def count(self):
        with self.lock:
            return len(self.items), sum(1 for it in self.items.values() if it.get("text"))

    def chosen(self, keep, feeds):
        """The links to keep: newest first, the feeds taking turns, `keep` in all."""
        with self.lock:
            per = {}
            urls = [f["url"] for f in feeds]
            for it in self.items.values():
                if it.get("feed") in urls:
                    per.setdefault(it["feed"], []).append(it)
            for lst in per.values():
                lst.sort(key=lambda it: (it.get("date") or "", it.get("seen", 0)), reverse=True)
            out, i = [], 0
            queues = [per[u] for u in urls if u in per]
            while len(out) < keep and any(i < len(q) for q in queues):
                for q in queues:
                    if i < len(q) and len(out) < keep:
                        out.append(q[i]["link"])
                i += 1
            return out

    def prune(self, keep, feeds):
        with self.lock:
            links = set(self.chosen(keep, feeds))
            for link in [k for k in self.items if k not in links]:
                del self.items[link]
            self.dirty = True

    def sync(self, keep, feeds, stop=None):
        """Download the full text of the stories being kept (a few at a time), then save."""
        if keep <= 0:
            self.clear()
            return
        self.prune(keep, feeds)
        now = time.time()
        with self.lock:
            todo = [link for link in self.chosen(keep, feeds)
                    if link.startswith("http") and not self.items[link].get("text")
                    and now - self.items[link].get("tried", 0) > self.RETRY]

        def one(link):
            if stop and stop.is_set():
                return
            try:
                paras = fetch_article(link)
            except Exception:  # noqa: BLE001 - one bad page shouldn't stop the rest
                paras = None
            with self.lock:
                it = self.items.get(link)
                if it is not None:
                    it["tried"] = time.time()
                    if paras:
                        it["text"] = [list(p) for p in paras]
                    self.dirty = True

        if todo:
            with ThreadPoolExecutor(max_workers=4) as ex:
                list(ex.map(one, todo))
        self.save()

    def put_article(self, link, paras):
        with self.lock:
            it = self.items.get(link)
            if it is not None and paras:
                it["text"] = [list(p) for p in paras]
                self.dirty = True

    def clear(self):
        with self.lock:
            self.items = {}
            self.dirty = True
        self.save()

    # -- weather
    def save_weather(self, loc, units, data):
        with self.lock:
            self.weather = {"name": loc["name"], "units": units, "at": time.time(), "data": data}
            self.dirty = True

    def last_weather(self, loc, units):
        with self.lock:
            w = self.weather
            if w and loc and w.get("name") == loc.get("name") and w.get("units") == units:
                return w["data"], w["at"]
            return None, None

    def save(self):
        with self.lock:
            if not self.dirty:
                return
            data = {"version": 1, "stories": self.items, "weather": self.weather}
            self.dirty = False
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, self.path)
        except (OSError, TypeError, ValueError):
            pass


class Weather:
    """The weather report for the configured place, kept between views, saved for offline use."""

    def __init__(self, library):
        self.library = library
        self.lock = threading.Lock()
        self.data = None
        self.saved_at = None   # set when the report came from the offline library

    def get(self, cfg, force=False):
        loc = cfg.get("location")
        if not loc:
            return None
        with self.lock:
            if self.data and not force:
                return self.data
            try:
                self.data = fetch_weather(loc, cfg.get("units"))
                self.saved_at = None
                self.library.save_weather(loc, cfg.get("units"), self.data)
                self.library.save()
            except Exception:
                data, at = self.library.last_weather(loc, cfg.get("units"))
                if data is None:
                    raise
                self.data, self.saved_at = data, at
            return self.data

    def forget(self):
        with self.lock:
            self.data = None


def article_text(library, articles, link):
    """Full text already on hand (this session or the offline library), or None."""
    return articles.get(link) or (library.article(link) if library else None)


def get_article(library, articles, link):
    """Full text: from memory, the offline library, or the web (saved for next time)."""
    paras = article_text(library, articles, link)
    if paras:
        return paras
    paras = fetch_article(link)
    if paras:
        articles[link] = paras
        if library:
            library.put_article(link, paras)
    return paras
