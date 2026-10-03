"""Built-in checks for release builds: `phosphor --self-test` and `phosphor-gui --self-test REPORT`.

They use made-up sample stories and weather (no network), so a build can be tested on any
computer, including the release machines for Windows, macOS, and Linux.
"""

import os
import tempfile
import time
from datetime import datetime, timedelta, timezone

SAMPLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Sample Gazette</title>
<item><title>Town library opens a new reading room</title><link>sample:story-1</link>
<description>&lt;p&gt;The reading room has long tables, good lamps, and a quiet corner for chess.&lt;/p&gt;
&lt;p&gt;Volunteers built the shelves over three weekends.&lt;/p&gt;</description>
<pubDate>Mon, 05 Oct 2026 09:00:00 GMT</pubDate></item>
<item><title>Community garden harvest breaks a record &amp; feeds 200 families</title><link>sample:story-2</link>
<description>Tomatoes, squash, and beans by the bushel.</description>
<pubDate>Sun, 04 Oct 2026 15:30:00 GMT</pubDate></item>
<item><title>Students launch a weather balloon to the edge of space</title><link>sample:story-3</link>
<description>The camera came back with pictures of the curve of the Earth.</description>
<pubDate>Sat, 03 Oct 2026 12:00:00 GMT</pubDate></item>
</channel></rss>"""


def sample_weather():
    """A week of made-up weather in Open-Meteo's shape, starting this hour."""
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    hours = [now + timedelta(hours=i) for i in range(72)]
    days = [now.date() + timedelta(days=i) for i in range(7)]
    return {
        "current": {"time": now.strftime("%Y-%m-%dT%H:%M"), "temperature_2m": 68.4, "apparent_temperature": 70.1,
                    "relative_humidity_2m": 55, "weather_code": 2, "wind_speed_10m": 7.2,
                    "wind_direction_10m": 225, "is_day": 1},
        "hourly": {"time": [h.strftime("%Y-%m-%dT%H:%M") for h in hours],
                   "temperature_2m": [60 + 10 * abs(((i + 6) % 24) - 12) / 12 for i in range(72)],
                   "precipitation_probability": [(i * 7) % 90 for i in range(72)]},
        "daily": {"time": [d.isoformat() for d in days], "weather_code": [2, 61, 3, 0, 1, 80, 95],
                  "temperature_2m_max": [74, 70, 68, 77, 79, 72, 69], "temperature_2m_min": [55, 58, 52, 50, 54, 57, 56],
                  "precipitation_probability_max": [10, 70, 30, 0, 5, 60, 80],
                  "sunrise": [f"{d.isoformat()}T07:20" for d in days], "sunset": [f"{d.isoformat()}T19:05" for d in days]},
    }


def use_temp_home():
    """Point Phosphor's settings and offline library at a throwaway folder."""
    from . import core
    tmp = tempfile.mkdtemp(prefix="phosphor-selftest-")
    core.CONFIG_DIR = tmp
    core.CONFIG_PATH = os.path.join(tmp, "config.json")
    core.LIBRARY_PATH = os.path.join(tmp, "library.json")
    return tmp


def check_core():
    """The engine: feed parsing, sorting, the offline library, weather helpers. Returns notes; raises on failure."""
    from . import core
    title, stories = core.parse_feed(SAMPLE_RSS)
    assert title == "Sample Gazette", title
    assert len(stories) == 3 and stories[1]["title"].startswith("Community garden harvest breaks"), stories
    for s in stories:
        s["source"] = title
    newest = core.arrange(stories, "NEWEST", "", set())
    assert newest[0]["link"] == "sample:story-1"
    assert len(core.arrange(stories, "NEWEST", "balloon", set())) == 1
    lib = core.Library()
    feeds = [{"title": title, "url": "sample:feed"}]
    lib.merge("sample:feed", stories)
    lib.put_article("sample:story-1", [("p", "Full text for reading offline.")])
    lib.dirty = True
    lib.save()
    again = core.Library()
    assert again.count() == (3, 1), again.count()
    assert again.article("sample:story-1") == [("p", "Full text for reading offline.")]
    assert len(again.stories_for("sample:feed")) == 3
    again.prune(2, feeds)
    assert again.count()[0] == 2
    d = sample_weather()
    hours, temps, pops = core.hourly_from_now(d, 24)
    assert len(temps) == 24, len(temps)
    assert core.conditions(95)[2] == "storm" and core.compass(225) == "SW"
    assert core.html_to_paragraphs(stories[0]["summary"])[1][1].startswith("Volunteers")
    return ["engine ok"]


def terminal_main():
    """phosphor --self-test: the engine, plus curses being importable."""
    use_temp_home()
    notes = check_core()
    import curses  # noqa: F401 - the terminal app can't run without it
    notes.append("curses ok")
    print("self-test passed: " + ", ".join(notes))


def window_main(report):
    """phosphor-gui --self-test REPORT: draw every era's screens and run the terminal view, then exit.
    Writes what happened to REPORT (a windowed app has no console) and exits 0 on success."""
    import sys
    import traceback
    log = []

    def finish(ok):
        log.append("PASSED" if ok else "FAILED")
        with open(report, "w", encoding="utf-8") as f:
            f.write("\n".join(log) + "\n")
        os._exit(0 if ok else 1)

    try:
        use_temp_home()
        log += check_core()
        from . import core
        from .gui.eras import ERAS
        from .gui.window import Gui

        class Args:
            no_boot, era, offline = True, None, True

        g = Gui(Args())
        _, stories = core.parse_feed(SAMPLE_RSS)
        g.cfg["feeds"] = [{"title": "Sample Gazette", "url": "sample:feed"}]
        for s in stories:
            s["source"] = "Sample Gazette"
        g.store.cache["sample:feed"] = {"stories": stories, "title": "Sample Gazette", "error": None,
                                        "offline": False}
        g.cfg["location"] = {"name": "Sampleville, US", "lat": 0, "lon": 0}
        g.weather_data = sample_weather()
    except Exception:  # noqa: BLE001
        log.append(traceback.format_exc())
        finish(False)
        return

    screens = [("home",), ("list", None), ("story", None, 0), ("weather",), ("feeds",), ("settings",)]

    def text_of(gui):
        return "".join(p.t.get("1.0", "end") for p in gui.all_pages())

    def eras_pass():
        for era in ERAS:
            g.set_era(era.key)
            for screen in screens:
                g.go(screen)
                g.root.update()
                shown = text_of(g)
                assert len(shown.strip()) > 40, (era.key, screen, shown[:200])
                if screen[0] == "story":
                    assert "reading room" in shown.lower() or "READING ROOM" in shown, (era.key, shown[:300])
            log.append(f"{era.label}: all screens drawn")
        g.set_era("modern")
        g.go(("home",))

    def key(sym, char=""):
        g.on_key(type("Key", (), {"keysym": sym, "char": char, "state": 0, "widget": g.root})())

    def keys_pass():
        key("Down")
        assert g.screen[0] == "story", g.screen
        key("Escape")
        g.set_era("teletext")
        for c in "400":
            key(c, c)
        assert g.screen == ("weather",), g.screen
        log.append("keyboard: ok")

    def terminal_steps():
        g.enter_terminal(boot=False)
        grid = lambda: g.term and g.term.grid  # noqa: E731

        def wait_for(cond, then, tries=100):
            if cond():
                g.root.after(200, then)
            elif tries:
                g.root.after(100, lambda: wait_for(cond, then, tries - 1))
            else:
                log.append("terminal view: timed out; screen shows:\n" + (grid().text.get("1.0", "end") if grid() else "?"))
                finish(False)

        def shown():
            return grid().text.get("1.0", "end") if grid() else ""

        def press(*ks):
            for k in ks:
                grid().queue.append(k)
            grid().signal.set(True)

        def step2():
            press("2")
            wait_for(lambda: "Town library" in shown() or "TOWN LIBRARY" in shown(), step3)

        def step3():
            press("\x1b")
            wait_for(lambda: "WINDOW VIEW" in shown(), step4)

        def step4():
            press("w")
            wait_for(lambda: g.term is None, done)

        def done():
            assert g.cfg.get("gui_mode") == "window"
            log.append("terminal view: menu, story list, back to the window: ok")
            finish(True)

        wait_for(lambda: "MAIN MENU" in shown(), step2)

    def run():
        try:
            eras_pass()
            keys_pass()
            terminal_steps()
        except Exception:  # noqa: BLE001
            log.append(traceback.format_exc())
            finish(False)

    g.root.after(500, run)
    g.root.after(120000, lambda: (log.append("timed out after 2 minutes"), finish(False)))
    try:
        g.root.mainloop()
    except Exception:  # noqa: BLE001
        log.append(traceback.format_exc())
        finish(False)
    finish(False)  # the window closed without the test finishing
    sys.exit(1)
