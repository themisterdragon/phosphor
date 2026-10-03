News and weather through the eras. Pick an era and Phosphor shows your feeds and forecast the
way people got them then: a 1965 wire-service teletype, a 1979 green screen, 1983 teletext,
a 1991 dial-up BBS, the 1994 early web, a 1997 web portal, a 2006 feed reader, or today's clean
look. **Phosphor Terminal** is the same thing as a real terminal app, and the window app can
show it too (View › Terminal View).

No accounts and no API keys. The newest stories are saved on your computer, full text and all,
so you can keep reading when you're offline.

## Download

| Your computer | Get |
|---|---|
| Windows 10 or 11 | `Phosphor-…-windows.exe` (the window app). For the terminal app: `Phosphor-Terminal-…-windows.exe` |
| Mac with Apple silicon (M1 and newer) | `Phosphor-…-macos-apple-silicon.dmg` |
| Mac with an Intel processor | `Phosphor-…-macos-intel.dmg` |
| Linux | `Phosphor-…-linux.tar.gz` (needs Python 3.8+; the window app also needs Tk) |

Not sure which Mac you have? Apple menu › About This Mac: "Chip: Apple M…" means Apple silicon.

### Windows
Run the `.exe`. Windows may say it "protected your PC" because the app isn't signed:
choose **More info › Run anyway**.

### macOS
Open the `.dmg` and drag **Phosphor** to **Applications**. The first time you open it, macOS
will say it can't check the app for malicious software, because it isn't signed. Click **Done**,
then go to **System Settings › Privacy & Security**, scroll down, and click **Open Anyway**.
"Phosphor Terminal" in the disk image is the terminal app: double-click it to run it in Terminal.

### Linux
    tar -xzf Phosphor-*-linux.tar.gz
    cd Phosphor-*/
    sh install.sh        # installs `phosphor` and `phosphor-gui`, plus a "Phosphor" app-menu entry

The window app needs Tk: `sudo apt install python3-tk` (Debian/Ubuntu), `sudo pacman -S tk` (Arch),
`sudo dnf install python3-tkinter` (Fedora).

## Accessibility
Every era meets WCAG 2.1 AA color contrast, text size goes up and down (Ctrl/Cmd + = and -), and
everything works from the keyboard. Screen readers can't read the window app (a limit of the Tk
toolkit it's drawn with); Phosphor Terminal works with terminal screen readers.

Each build here was tested on its own system before release: every era's screens, the keyboard,
and the terminal view.
