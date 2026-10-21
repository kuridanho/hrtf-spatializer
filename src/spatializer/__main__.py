"""Command-line entry point: ``python -m spatializer`` / ``spatializer``."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__
from .config import (
    DATASET_ENV_VAR,
    DEFAULT_BLOCK_SIZE,
    DEFAULT_SAMPLE_RATE,
    SUPPORTED_BLOCK_SIZES,
    AppConfig,
    ConfigError,
    resolve_dataset_root,
)
from .engine.hrtf import scan_datasets


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spatializer",
        description="Real-time HRTF binaural spatializer for macOS system audio.",
    )
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "HRTF dataset directory (or a folder containing datasets). "
            f"Defaults to ${DATASET_ENV_VAR} or ./dataset."
        ),
    )
    parser.add_argument(
        "--block-size",
        type=int,
        choices=SUPPORTED_BLOCK_SIZES,
        default=DEFAULT_BLOCK_SIZE,
        help=f"samples per audio block (default: {DEFAULT_BLOCK_SIZE})",
    )
    parser.add_argument(
        "--sample-rate",
        type=int,
        default=DEFAULT_SAMPLE_RATE,
        metavar="HZ",
        help=(f"stream sample rate; must match the HRTF dataset (default: {DEFAULT_SAMPLE_RATE})"),
    )
    parser.add_argument(
        "--list-datasets",
        action="store_true",
        help="list detected datasets and exit",
    )
    parser.add_argument("--debug", action="store_true", help="enable debug logging")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _configure_tk(root) -> None:
    """Apply Retina scaling and the native macOS look when available."""
    from tkinter import ttk

    try:
        scaling = root.winfo_fpixels("1i") / 72.0
        if scaling > 0:
            root.tk.call("tk", "scaling", scaling)
    except Exception:
        logging.getLogger(__name__).debug("Could not configure Tk scaling", exc_info=True)

    style = ttk.Style(root)
    if "aqua" in style.theme_names():
        style.theme_use("aqua")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    dataset_root = resolve_dataset_root(args.dataset_dir)
    if args.list_datasets:
        datasets = scan_datasets(dataset_root)
        if not datasets:
            print(f"No datasets found under {dataset_root}", file=sys.stderr)
            return 1
        for path in datasets:
            print(path)
        return 0

    try:
        config = AppConfig(
            dataset_root=dataset_root,
            block_size=args.block_size,
            sample_rate=args.sample_rate,
        )
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        import tkinter as tk

        from .gui.main_window import MainWindow
    except ImportError as exc:
        print(
            "error: tkinter が見つかりません。macOS では "
            "`brew install python-tk` を実行してください。\n"
            f"({exc})",
            file=sys.stderr,
        )
        return 2

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"error: GUI を起動できません: {exc}", file=sys.stderr)
        return 2

    _configure_tk(root)
    MainWindow(root, config)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
