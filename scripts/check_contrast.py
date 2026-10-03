#!/usr/bin/env python3
"""Every era's palette (light and dark, and each Green Screen color) must pass WCAG 2.1 AA."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from phosphor.gui.eras import ERAS, PHOSPHOR, colors_for, contrast_problems  # noqa: E402

bad = 0
for era in ERAS:
    variants = [(t, colors_for(era, False, t)) for t in PHOSPHOR] if era.key == "phosphor" else \
        [("light", era.colors)] + ([("dark", era.dark_colors)] if era.dark_colors else [])
    for name, c in variants:
        for p in contrast_problems(c):
            print(f"{era.name} ({name}): {p}")
            bad += 1
print("all eras pass WCAG AA" if not bad else f"{bad} problem(s)")
sys.exit(1 if bad else 0)
