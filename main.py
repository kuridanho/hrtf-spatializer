#!/usr/bin/env python3
"""
Spatializer — HRTF リアルタイム空間音響アプリ

Usage:
    cd /Users/rikuhonda/Documents/Project/Spatializer
    spatializer_app/.venv/bin/python -m spatializer_app.main
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tkinter as tk
from tkinter import ttk

from spatializer_app.gui.main_window import MainWindow

DATASET_BASE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "dataset")
)


def main() -> None:
    root = tk.Tk()
    root.tk.call("tk", "scaling", 2.0)   # HiDPI / Retina 対応

    # macOS ネイティブ外観に近づける
    style = ttk.Style(root)
    if "aqua" in style.theme_names():
        style.theme_use("aqua")

    MainWindow(root, dataset_base=DATASET_BASE)
    root.mainloop()


if __name__ == "__main__":
    main()
