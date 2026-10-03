# Phosphor

News and weather through the eras. Pure Python standard library: no API keys, no accounts.

**Phosphor** is the window app. Pick an era and it shows your feeds and forecast the way
people got them then:

| Era | Looks like |
|-----|-----------|
| 1965 Wire Teletype | capitals on newsprint-colored paper, numbered wire slugs, the forecast written out |
| 1979 Green Screen | a glowing home-computer monitor (green, amber, or white) |
| 1983 Teletext | blocky TV pages: key in a three-digit page number (100 is the index, 400 the weather) |
| 1991 Dial-Up BBS | ANSI colors, a message base, and a clock ticking down your time online |
| 1994 Early Web | a page nobody styled: browser-default gray, Times, `<h1>` headings, beveled rules, underlined links |
| 1997 Web Portal | a start page: navy bars, blue links that turn purple once read, a visitor counter |
| 2006 Feed Reader | subscriptions on the left, unread counts, a glossy toolbar |
| Today | clean and quiet, light or dark to match your computer |

Switch with **View › Era**, from Settings, or **Ctrl+[** / **Ctrl+]** (Cmd on a Mac).

**Phosphor Terminal** (`phosphor`) is the real thing: a curses app for any terminal.
The window app can also show it: **View › Terminal View** (Ctrl+Shift+W), and press
`W` in its menu to come back. Both share the same feeds, settings, and offline library.

## Offline reading

Phosphor keeps the newest stories on your computer, with their full text, so you can read
without a connection. The feeds take turns so each gets its share. Choose how many
(off, 50, 100, 200, or 500) in Settings; the default is 100. When a feed can't be reached,
Phosphor shows the saved stories instead, and the last weather report too.

## Install

Needs Python 3.8+. The window app also needs Tk (`sudo pacman -S tk`, `sudo apt install python3-tk`;
Python from python.org includes it).

**Standalone files (Linux/macOS):** copy `phosphor.pyz`, `phosphor-gui.pyz` and `install.sh`
to the machine, then

    sh install.sh       # installs phosphor and phosphor-gui to ~/.local/bin
                        # (on Linux, also a "Phosphor" entry in the app menu)

**As a Python package (any OS, including Windows):**

    pipx install git+https://github.com/themisterdragon/phosphor

On Windows the package pulls in `windows-curses` for the terminal app; use Windows Terminal.

## Keys

| Where      | Keys |
|------------|------|
| Menus      | number keys, or arrows + Return; Esc goes back |
| Story list | `1`-`9`,`0` read · `N`/`P` page · `S` sort · `/` search · `M` mark page read · `O` open in browser · `R` reload |
| Story      | Space/arrows scroll · `N`/`P` next/prev story · `T` full text / summary · `O` browser |
| Weather    | `R` refresh · `L` place · `U` °F/°C |
| Window app | Alt+Left/Right back/forward · Ctrl+=/- text size · Ctrl+Shift+W terminal view |

Settings, feeds, and read history live in `~/.config/phosphor/config.json`; the offline
library in `~/.local/share/phosphor/library.json`.

## Accessibility

Every era's colors meet WCAG 2.1 AA contrast (`python3 scripts/check_contrast.py`), the
text size goes up and down, and everything works from the keyboard. The window app is
drawn with Tk, which screen readers can't read; Phosphor Terminal in a terminal works with
terminal screen readers.

## Build

    python3 scripts/build_pyz.py       # -> dist/phosphor.pyz, dist/phosphor-gui.pyz, dist/install.sh
    python3 scripts/check_contrast.py  # every era passes WCAG AA
    python3 scripts/check_py38.py      # no newer-Python-only syntax

## License

GPL-3.0. See [LICENSE](LICENSE). Weather data comes from [Open-Meteo](https://open-meteo.com/);
stories come from the feeds you subscribe to and belong to their publishers.
