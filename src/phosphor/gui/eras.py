"""The eras: how people got their news and weather, from the wire-service teletype to today.

Each era is a palette, fonts, and a layout ("page": one screen at a time, like a terminal or a
web page; "panes": a sidebar, a story list and a reading pane). Every text color must reach
WCAG 2.1 AA contrast (4.5:1) on its background: scripts/check_contrast.py tests them all.
Looks are named generically on purpose: no product names or trademarked art.
"""

import os
import shutil
import subprocess
import sys

MAC = sys.platform == "darwin"
WIN = sys.platform == "win32"


class Era:
    def __init__(self, key, year, name, blurb, layout, fonts, colors, dark=None, upper=False, cols=None):
        self.key, self.year, self.name, self.blurb = key, year, name, blurb
        self.layout = layout          # "page" or "panes"
        self.fonts = fonts            # role -> (family candidates, size in pt at text size 0, style)
        self.colors = colors          # light (or only) palette
        self.dark_colors = dark       # None: this era has one look
        self.upper = upper            # ALL CAPS, as the machines of the day printed
        self.cols = cols              # character columns for the screen eras (None: fills the window)

    @property
    def label(self):
        return f"{self.year}  {self.name}"


MONO = ("Liberation Mono", "Courier New", "Courier", "Nimbus Mono PS", "DejaVu Sans Mono", "TkFixedFont")
TERM = ("Menlo", "SF Mono", "Consolas", "Cascadia Mono", "Noto Sans Mono", "DejaVu Sans Mono", "Liberation Mono",
        "TkFixedFont")
SERIF = ("Times New Roman", "Liberation Serif", "Times", "Nimbus Roman", "DejaVu Serif", "TkTextFont")
ARIAL = ("Arial", "Liberation Sans", "Helvetica", "Nimbus Sans", "DejaVu Sans", "TkDefaultFont")
GRANDE = ("Lucida Grande", "Verdana", "DejaVu Sans", "Noto Sans", "Liberation Sans", "TkDefaultFont")
SYSTEM = ("TkDefaultFont",)

# colors every era has: bg, fg (body), dim (secondary text), hi (headings, unread), link, visited,
# bar_bg/bar_fg (heading bars), sel_bg/sel_fg (the highlighted row); "text" lists extra text colors
# drawn on bg; panes eras add side_bg (sidebar) and line (dividers, decoration only).

ERAS = [
    Era("teletype", "1965", "Wire Teletype",
        "News clatters in over the wire service printer, one line at a time, in capitals.",
        "page",
        {"body": (MONO, 12, ""), "head": (MONO, 12, "bold"), "big": (MONO, 15, "bold")},
        {"bg": "#F3EBD3", "fg": "#26221C", "dim": "#5E5547", "hi": "#000000", "link": "#26221C",
         "visited": "#5E5547", "bar_bg": "#26221C", "bar_fg": "#F3EBD3", "sel_bg": "#26221C", "sel_fg": "#F3EBD3",
         "text": {"red": "#A1261C"}},
        dark={"bg": "#1D1A15", "fg": "#E8DFC6", "dim": "#B3A88F", "hi": "#FFFFFF", "link": "#E8DFC6",
              "visited": "#B3A88F", "bar_bg": "#E8DFC6", "bar_fg": "#1D1A15", "sel_bg": "#E8DFC6",
              "sel_fg": "#1D1A15", "text": {"red": "#F08A7E"}},
        upper=True, cols=72),
    Era("phosphor", "1979", "Green Screen",
        "A home computer and a modem: glowing capitals on a dark tube. (Phosphor Terminal is this, for real.)",
        "page",
        {"body": (TERM, 13, ""), "head": (TERM, 13, "bold"), "big": (TERM, 13, "bold")},
        None,  # follows the terminal's Phosphor Color setting: see phosphor_colors()
        upper=True, cols=80),
    Era("teletext", "1983", "Teletext",
        "Pages of news on the family TV: key in a three-digit page number and wait for it to come round.",
        "page",
        {"body": (TERM, 15, "bold"), "head": (TERM, 15, "bold"), "big": (TERM, 26, "bold")},
        {"bg": "#000000", "fg": "#FFFFFF", "dim": "#00FFFF", "hi": "#FFFF00", "link": "#FFFFFF",
         "visited": "#00FFFF", "bar_bg": "#0000FF", "bar_fg": "#FFFF00", "sel_bg": "#FFFF00", "sel_fg": "#000000",
         "text": {"red": "#FF0000", "green": "#00FF00", "yellow": "#FFFF00", "cyan": "#00FFFF",
                  "magenta": "#FF00FF", "white": "#FFFFFF"}},
        cols=40),
    Era("bbs", "1991", "Dial-Up BBS",
        "Dial in to the local bulletin board after school: ANSI colors, message bases, and a time limit.",
        "page",
        {"body": (TERM, 13, ""), "head": (TERM, 13, "bold"), "big": (TERM, 13, "bold")},
        {"bg": "#000000", "fg": "#AAAAAA", "dim": "#00AAAA", "hi": "#FFFFFF", "link": "#55FFFF",
         "visited": "#00AAAA", "bar_bg": "#0000AA", "bar_fg": "#FFFF55", "sel_bg": "#00AAAA", "sel_fg": "#000000",
         "text": {"yellow": "#FFFF55", "green": "#55FF55", "magenta": "#FF55FF", "cyan": "#55FFFF",
                  "red": "#FF5555", "blue": "#7777FF"}},
        cols=80),
    Era("earlyweb", "1994", "Early Web",
        "Before anyone styled a page: gray background, Times, blue underlined links, and horizontal rules.",
        "page",
        {"body": (SERIF, 13, ""), "head": (SERIF, 17, "bold"), "big": (SERIF, 26, "bold"), "small": (SERIF, 11, ""),
         "ui": (ARIAL, 10, ""), "mono": (MONO, 12, "")},
        {"bg": "#C0C0C0", "fg": "#000000", "dim": "#2E2E2E", "hi": "#000000", "link": "#0000EE",
         "visited": "#551A8B", "bar_bg": "#000000", "bar_fg": "#C0C0C0", "sel_bg": "#0000EE", "sel_fg": "#FFFFFF",
         "face": "#B4B4B4", "face_fg": "#000000", "field": "#FFFFFF", "text": {"red": "#8B0000"}},
        dark={"bg": "#000000", "fg": "#D8D8D8", "dim": "#B0B0B0", "hi": "#FFFFFF", "link": "#8C9CFF",
              "visited": "#C99CFF", "bar_bg": "#D8D8D8", "bar_fg": "#000000", "sel_bg": "#8C9CFF", "sel_fg": "#000000",
              "face": "#303030", "face_fg": "#E0E0E0", "field": "#1A1A1A", "text": {"red": "#FF8080"}}),
    Era("portal", "1997", "Web Portal",
        "Your start page on the World Wide Web: blue links, gray buttons, and a visitor counter.",
        "page",
        {"body": (SERIF, 13, ""), "head": (ARIAL, 12, "bold"), "big": (SERIF, 22, "bold"), "small": (ARIAL, 9, ""),
         "ui": (ARIAL, 10, "")},
        {"bg": "#FFFFFF", "fg": "#000000", "dim": "#555555", "hi": "#000000", "link": "#0000EE",
         "visited": "#551A8B", "bar_bg": "#000080", "bar_fg": "#FFFFFF", "sel_bg": "#000080", "sel_fg": "#FFFFFF",
         "face": "#C0C0C0", "face_fg": "#000000", "field": "#FFFFFF",
         "text": {"red": "#CC0000", "green": "#006600"}},
        dark={"bg": "#1B1B1F", "fg": "#E6E6E6", "dim": "#A8A8A8", "hi": "#FFFFFF", "link": "#8AB4FF",
              "visited": "#C8A2FF", "bar_bg": "#2B3A80", "bar_fg": "#FFFFFF", "sel_bg": "#3A4FA8", "sel_fg": "#FFFFFF",
              "face": "#3A3A40", "face_fg": "#E6E6E6", "field": "#26262B",
              "text": {"red": "#FF7B7B", "green": "#7BD88F"}}),
    Era("reader", "2006", "Feed Reader",
        "Every site's feed in one inbox: subscriptions on the left, unread counts in bold, glossy buttons.",
        "panes",
        {"body": (GRANDE, 11, ""), "head": (GRANDE, 11, "bold"), "big": (GRANDE, 17, "bold"),
         "small": (GRANDE, 9, ""), "ui": (GRANDE, 10, "")},
        {"bg": "#FFFFFF", "fg": "#222222", "dim": "#5F6B7A", "hi": "#000000", "link": "#1A4AA8",
         "visited": "#5F6B7A", "bar_bg": "#C3D9FF", "bar_fg": "#0B2A66", "sel_bg": "#E1ECFE", "sel_fg": "#000000",
         "side_bg": "#EEF3FB", "line": "#B8C7E0", "gloss": ("#F4F8FF", "#C3D9FF"), "text": {"orange": "#B34700"}},
        dark={"bg": "#16191F", "fg": "#E3E7EE", "dim": "#9AA6B8", "hi": "#FFFFFF", "link": "#8DB6FF",
              "visited": "#9AA6B8", "bar_bg": "#24324D", "bar_fg": "#DCE8FF", "sel_bg": "#2A3B5C", "sel_fg": "#FFFFFF",
              "side_bg": "#1D222B", "line": "#3A4660", "gloss": ("#2E3E60", "#1C2741"), "text": {"orange": "#FFA060"}}),
    Era("modern", "Today", "Modern",
        "Clean and quiet: your computer's own fonts, light or dark to match it.",
        "panes",
        {"body": (SYSTEM, 12, ""), "head": (SYSTEM, 12, "bold"), "big": (SYSTEM, 20, "bold"),
         "small": (SYSTEM, 10, ""), "ui": (SYSTEM, 11, "")},
        {"bg": "#FFFFFF", "fg": "#1F2328", "dim": "#59636E", "hi": "#000000", "link": "#0B5CD5",
         "visited": "#59636E", "bar_bg": "#F3F4F6", "bar_fg": "#1F2328", "sel_bg": "#DCE8FB", "sel_fg": "#000000",
         "side_bg": "#F6F7F9", "line": "#D8DCE2", "text": {"orange": "#A84B00"}},
        dark={"bg": "#17191C", "fg": "#E6E8EB", "dim": "#A0A7B1", "hi": "#FFFFFF", "link": "#7AB0FF",
              "visited": "#A0A7B1", "bar_bg": "#212429", "bar_fg": "#E6E8EB", "sel_bg": "#27406A", "sel_fg": "#FFFFFF",
              "side_bg": "#1E2125", "line": "#353A41", "text": {"orange": "#FFB070"}}),
]
BY_KEY = {e.key: e for e in ERAS}

# Green Screen takes Phosphor Terminal's color (green / amber / white)
PHOSPHOR = {
    "green": ("#33FF66", "#1FB84A", "#B8FFC8"),
    "amber": ("#FFB000", "#C88400", "#FFE0A0"),
    "white": ("#E8E8E8", "#A8A8A8", "#FFFFFF"),
}


def phosphor_colors(theme):
    fg, dim, hi = PHOSPHOR.get(theme, PHOSPHOR["green"])
    bg = "#0A0F0A" if theme == "green" else "#0F0C06" if theme == "amber" else "#0C0C0C"
    return {"bg": bg, "fg": fg, "dim": dim, "hi": hi, "link": fg, "visited": dim, "bar_bg": fg, "bar_fg": bg,
            "sel_bg": fg, "sel_fg": bg, "text": {}}


def colors_for(era, dark, theme="green"):
    if era.key == "phosphor":
        return phosphor_colors(theme)
    return era.dark_colors if dark and era.dark_colors else era.colors


# ------------------------------------------------------------------ color math (WCAG 2.1 contrast)
def channels(color):
    """'#rrggbb' -> (r, g, b) as 0-255."""
    n = int(color[1:], 16)
    return n >> 16, (n >> 8) & 0xFF, n & 0xFF


def brightness(color):
    """Relative luminance, 0 (black) to 1 (white), as WCAG 2.1 defines it."""
    weights = (0.2126, 0.7152, 0.0722)
    total = 0.0
    for value, weight in zip(channels(color), weights):
        s = value / 255
        linear = s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4
        total += weight * linear
    return total


def contrast(a, b):
    """The WCAG contrast ratio of two colors, 1 to 21."""
    hi, lo = max(brightness(a), brightness(b)), min(brightness(a), brightness(b))
    return (hi + 0.05) / (lo + 0.05)


def mix(a, b, t):
    """The color t of the way from a to b."""
    return "#" + "".join("%02X" % round(x + (y - x) * t) for x, y in zip(channels(a), channels(b)))


def contrast_problems(c):
    """Text/background pairs in palette c that miss WCAG AA (4.5:1). [] means it passes."""
    pairs = [(k, "bg") for k in ("fg", "dim", "hi", "link", "visited")]
    pairs += [("bar_fg", "bar_bg"), ("sel_fg", "sel_bg")]
    if "side_bg" in c:
        pairs += [(k, "side_bg") for k in ("fg", "dim", "hi", "link")]
    if "face" in c:
        pairs += [("face_fg", "face"), ("fg", "field")]
    out = []
    for a, b in pairs:
        r = contrast(c[a], c[b])
        if r < 4.5:
            out.append(f"{a} {c[a]} on {b} {c[b]}: {r:.2f}:1")
    for name, col in c.get("text", {}).items():
        r = contrast(col, c["bg"])
        if r < 4.5:
            out.append(f"text.{name} {col} on bg {c['bg']}: {r:.2f}:1")
    return out


# ------------------------------------------------------------------ is the computer in dark mode?
def _ask(*cmd):
    """A command's output, or "" if it isn't there or fails."""
    if not shutil.which(cmd[0]):
        return ""
    try:
        done = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=2)
        return done.stdout.decode(errors="replace").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def system_dark():
    if MAC:
        return "dark" in _ask("defaults", "read", "-g", "AppleInterfaceStyle").lower()
    if WIN:
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 "Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize")
            light, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return light == 0
        except OSError:
            return False
    # Linux: the desktop's color-scheme preference (GNOME, and most others follow it), then the GTK theme name
    scheme = _ask("gsettings", "get", "org.gnome.desktop.interface", "color-scheme")
    if "dark" in scheme:
        return True
    if "light" in scheme:
        return False
    theme = os.environ.get("GTK_THEME", "") or _ask("gsettings", "get", "org.gnome.desktop.interface", "gtk-theme")
    return "dark" in theme.lower()
