#!/usr/bin/env python3
"""Write the app icon as a PNG (build/icon.png by default) for the Windows and macOS builds."""
import pathlib
import sys

root = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / "src"))
from phosphor.icon import png  # noqa: E402

out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else root / "build" / "icon.png")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(png(32))  # 512 x 512
print(f"wrote {out}")
