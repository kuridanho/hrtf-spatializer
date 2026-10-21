"""Stream controls and HRTF dataset selection."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk

from ..config import (
    DEFAULT_BLOCK_SIZE,
    DEFAULT_SAMPLE_RATE,
    SUPPORTED_BLOCK_SIZES,
    VOLUME_SLIDER_MAX,
)


class ControlPanel(ttk.LabelFrame):
    """Start/stop, dataset, block-size and volume controls."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        block_size: int = DEFAULT_BLOCK_SIZE,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        on_start: Callable[[], None] | None = None,
        on_stop: Callable[[], None] | None = None,
        on_bypass: Callable[[bool], None] | None = None,
        on_volume: Callable[[float], None] | None = None,
        on_rescan: Callable[[], None] | None = None,
        on_dataset: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(master, text="コントロール", padding=8)

        self._on_start = on_start
        self._on_stop = on_stop
        self._on_bypass = on_bypass
        self._on_volume = on_volume
        self._on_rescan = on_rescan
        self._on_dataset = on_dataset

        self._dataset_paths: list[Path] = []
        self._sample_rate = int(sample_rate)
        self._running = False
        self._loading = False
        self._bypass_state = False
        self._status_text = "停止中"

        # --- Stream buttons ---
        buttons = ttk.Frame(self)
        buttons.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        self._start_btn = ttk.Button(buttons, text="▶ 開始", command=self._handle_start)
        self._start_btn.pack(side="left", padx=(0, 4))
        self._stop_btn = ttk.Button(
            buttons, text="■ 停止", command=self._handle_stop, state="disabled"
        )
        self._stop_btn.pack(side="left", padx=(0, 4))
        self._bypass_btn = ttk.Button(buttons, text="BYPASS: OFF", command=self._toggle_bypass)
        self._bypass_btn.pack(side="left")

        # --- Dataset selector ---
        ttk.Label(self, text="HRTF データセット:").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=3
        )
        dataset_row = ttk.Frame(self)
        dataset_row.grid(row=1, column=1, sticky="ew", pady=3)

        self._dataset_var = tk.StringVar()
        self._dataset_cb = ttk.Combobox(
            dataset_row,
            textvariable=self._dataset_var,
            state="readonly",
            width=28,
        )
        self._dataset_cb.pack(side="left", fill="x", expand=True)
        self._dataset_cb.bind("<<ComboboxSelected>>", self._dataset_changed)

        self._rescan_btn = ttk.Button(dataset_row, text="再スキャン", command=self._rescan, width=9)
        self._rescan_btn.pack(side="left", padx=(4, 0))

        # --- Block size selector ---
        ttk.Label(self, text="ブロックサイズ:").grid(
            row=2, column=0, sticky="w", padx=(0, 8), pady=3
        )
        self._block_var = tk.StringVar()
        self._block_labels = [
            f"{size} samples  ({size / self._sample_rate * 1000:.1f} ms)"
            for size in SUPPORTED_BLOCK_SIZES
        ]
        self._block_cb = ttk.Combobox(
            self,
            textvariable=self._block_var,
            state="readonly",
            width=28,
            values=self._block_labels,
        )
        default_index = (
            SUPPORTED_BLOCK_SIZES.index(block_size)
            if block_size in SUPPORTED_BLOCK_SIZES
            else SUPPORTED_BLOCK_SIZES.index(DEFAULT_BLOCK_SIZE)
        )
        self._block_cb.current(default_index)
        self._block_cb.grid(row=2, column=1, sticky="ew", pady=3)
        self._block_cb.bind("<<ComboboxSelected>>", self._block_changed)

        # --- Volume slider ---
        ttk.Label(self, text="音量:").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=3)
        volume_row = ttk.Frame(self)
        volume_row.grid(row=3, column=1, sticky="ew", pady=3)

        self._volume_var = tk.DoubleVar(value=100.0)
        self._volume_slider = ttk.Scale(
            volume_row,
            from_=0.0,
            to=VOLUME_SLIDER_MAX,
            orient="horizontal",
            variable=self._volume_var,
            command=self._volume_changed,
        )
        self._volume_slider.pack(side="left", fill="x", expand=True)
        self._volume_label = ttk.Label(volume_row, text="100%", width=5, anchor="e")
        self._volume_label.pack(side="left", padx=(4, 0))

        # --- Info label ---
        self._info_var = tk.StringVar()
        ttk.Label(
            self,
            textvariable=self._info_var,
            foreground="gray",
            font=("", 10),
        ).grid(row=4, column=0, columnspan=2, pady=(6, 0))

        self.columnconfigure(1, weight=1)
        self._update_info()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_datasets(self, paths: list[Path]) -> None:
        """Replace the dataset list, preserving the current selection if possible."""
        current = self.selected_dataset_path()
        self._dataset_paths = [Path(path) for path in paths]

        self._dataset_cb["values"] = [path.name for path in self._dataset_paths]
        if current is not None and current in self._dataset_paths:
            self._dataset_cb.current(self._dataset_paths.index(current))
        elif self._dataset_paths:
            self._dataset_cb.current(0)
        else:
            self._dataset_cb.set("")

        self._update_start_state()

    def selected_dataset_path(self) -> Path | None:
        index = self._dataset_cb.current()
        if 0 <= index < len(self._dataset_paths):
            return self._dataset_paths[index]
        return None

    def selected_block_size(self) -> int:
        index = self._block_cb.current()
        if 0 <= index < len(SUPPORTED_BLOCK_SIZES):
            return SUPPORTED_BLOCK_SIZES[index]
        return DEFAULT_BLOCK_SIZE

    def has_datasets(self) -> bool:
        return bool(self._dataset_paths)

    @property
    def bypass_state(self) -> bool:
        return self._bypass_state

    def set_running(self, running: bool) -> None:
        self._running = running
        self._loading = False
        self._start_btn.configure(text="▶ 開始")
        self._stop_btn.configure(state="normal" if running else "disabled")

        state = "disabled" if running else "readonly"
        self._dataset_cb.configure(state=state)
        self._block_cb.configure(state=state)
        self._rescan_btn.configure(state="disabled" if running else "normal")
        self._update_start_state()

        self._status_text = "処理中" if running else "停止中"
        self._update_info()

    def set_loading(self) -> None:
        self._loading = True
        self._start_btn.configure(text="読み込み中…")
        self._update_start_state()

    def set_status(self, text: str) -> None:
        self._status_text = text
        self._update_info()

    def set_bypass(self, enabled: bool) -> None:
        """Keep the button in sync when bypass is changed programmatically."""
        self._bypass_state = enabled
        self._bypass_btn.configure(text=f"BYPASS: {'ON' if enabled else 'OFF'}")

    # ------------------------------------------------------------------
    # Internal callbacks
    # ------------------------------------------------------------------

    def _handle_start(self) -> None:
        if self._on_start is not None:
            self._on_start()

    def _handle_stop(self) -> None:
        if self._on_stop is not None:
            self._on_stop()

    def _toggle_bypass(self) -> None:
        self.set_bypass(not self._bypass_state)
        if self._on_bypass is not None:
            self._on_bypass(self._bypass_state)

    def _rescan(self) -> None:
        if self._on_rescan is not None:
            self._on_rescan()

    def _dataset_changed(self, _event: tk.Event | None = None) -> None:
        path = self.selected_dataset_path()
        if path is not None and self._on_dataset is not None:
            self._on_dataset(path)

    def _block_changed(self, _event: tk.Event | None = None) -> None:
        self._update_info()

    def _volume_changed(self, _value: str | None = None) -> None:
        percent = self._volume_var.get()
        self._volume_label.configure(text=f"{percent:.0f}%")
        if self._on_volume is not None:
            self._on_volume(percent / 100.0)

    def _update_start_state(self) -> None:
        can_start = not self._running and not self._loading and self.has_datasets()
        self._start_btn.configure(state="normal" if can_start else "disabled")

    def _update_info(self) -> None:
        block_size = self.selected_block_size()
        latency = block_size / self._sample_rate * 1000.0
        self._info_var.set(
            f"遅延: {latency:.1f} ms  |  {self._sample_rate} Hz  |  {self._status_text}"
        )
