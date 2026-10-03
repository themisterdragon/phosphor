#!/bin/sh
# Install phosphor.pyz as the `phosphor` command (Phosphor Terminal) and phosphor-gui.pyz as
# `phosphor-gui` (the window app, "Phosphor"), on Linux/macOS. On Linux the window app also
# gets a "Phosphor" entry in the app menu.
set -e
here=$(cd "$(dirname "$0")" && pwd)
src="$here/phosphor.pyz"
[ -f "$src" ] || src="$here/dist/phosphor.pyz"
[ -f "$src" ] || { echo "phosphor.pyz not found next to install.sh or in dist/"; exit 1; }
gui="$(dirname "$src")/phosphor-gui.pyz"
command -v python3 >/dev/null || { echo "Phosphor needs Python 3 (3.8 or newer)."; exit 1; }

if [ -f "$gui" ] && ! python3 -c 'import tkinter' 2>/dev/null; then
    echo "note: the window app needs Tk, which this Python doesn't have."
    if command -v pacman >/dev/null; then echo "      install it with:  sudo pacman -S tk"
    elif command -v apt-get >/dev/null; then echo "      install it with:  sudo apt install python3-tk"
    elif command -v dnf >/dev/null; then echo "      install it with:  sudo dnf install python3-tkinter"
    elif command -v zypper >/dev/null; then echo "      install it with:  sudo zypper install python3-tk"
    elif [ "$(uname)" = Darwin ]; then echo "      Python from python.org includes it."
    fi
fi

dest="${PREFIX:-$HOME/.local}/bin"
mkdir -p "$dest"
cp "$src" "$dest/phosphor"
chmod +x "$dest/phosphor"
echo "installed $dest/phosphor"
if [ -f "$gui" ]; then
    cp "$gui" "$dest/phosphor-gui"
    chmod +x "$dest/phosphor-gui"
    echo "installed $dest/phosphor-gui"
    if [ "$(uname)" = Linux ]; then
        share="${XDG_DATA_HOME:-$HOME/.local/share}"
        mkdir -p "$share/applications" "$share/icons"
        python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); from phosphor.icon import png; sys.stdout.buffer.write(png(8))' \
            "$gui" > "$share/icons/phosphor-gui.png"
        cat > "$share/applications/phosphor-gui.desktop" <<EOD
[Desktop Entry]
Version=1.0
Name=Phosphor
Comment=News and weather through the eras
Exec=$dest/phosphor-gui
Terminal=false
Type=Application
Icon=$share/icons/phosphor-gui.png
StartupWMClass=Phosphor
Categories=Network;News;
EOD
        echo "installed $share/applications/phosphor-gui.desktop"
    fi
fi
case ":$PATH:" in *":$dest:"*) ;; *) echo "note: add $dest to your PATH";; esac
