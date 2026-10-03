#!/usr/bin/env python3
"""Build dist/phosphor.pyz (terminal, needs curses) and dist/phosphor-gui.pyz (window, needs Tk)."""
import pathlib
import shutil
import tempfile
import zipapp

root = pathlib.Path(__file__).resolve().parent.parent
dist = root / "dist"
dist.mkdir(exist_ok=True)
for name, module in (("phosphor", "app"), ("phosphor-gui", "gui")):
    with tempfile.TemporaryDirectory() as tmp:
        stage = pathlib.Path(tmp)
        shutil.copytree(root / "src" / "phosphor", stage / "phosphor",
                        ignore=shutil.ignore_patterns("__pycache__"))
        (stage / "__main__.py").write_text(f"from phosphor.{module} import main\n\nmain()\n")
        out = dist / f"{name}.pyz"
        zipapp.create_archive(stage, out, interpreter="/usr/bin/env python3", compressed=True)
    print(f"built {out}")
shutil.copy2(root / "install.sh", dist / "install.sh")
