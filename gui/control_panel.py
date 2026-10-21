from __future__ import annotations
import os
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional


class ControlPanel(ttk.LabelFrame):
    """
    Stream controls and HRTF parameter selectors.

    Callbacks (all optional):
        on_start()
        on_stop()
        on_bypass(bool)
        on_dataset(str)   ← dataset directory path
        on_block_size(int)
    """

    _BLOCK_SIZES = [256, 512, 1024]

    def __init__(
        self,
        master: tk.Misc,
        dataset_base: str,
        on_start: Optional[Callable] = None,
        on_stop: Optional[Callable] = None,
        on_bypass: Optional[Callable[[bool], None]] = None,
        on_dataset: Optional[Callable[[str], None]] = None,
        on_block_size: Optional[Callable[[int], None]] = None,
        on_volume: Optional[Callable[[float], None]] = None,
    ) -> None:
        super().__init__(master, text="コントロール", padding=8)
        self._dataset_dirs: list[str] = []
        self._cb_start = on_start
        self._cb_stop = on_stop
        self._cb_bypass = on_bypass
        self._cb_dataset = on_dataset
        self._cb_block_size = on_block_size
        self._cb_volume = on_volume
        self._bypass_state = False

        # --- Stream buttons ---
        btn_row = ttk.Frame(self)
        btn_row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        self._start_btn = ttk.Button(btn_row, text="▶ 開始", command=self._on_start)
        self._start_btn.pack(side="left", padx=(0, 4))
        self._stop_btn = ttk.Button(btn_row, text="■ 停止", command=self._on_stop,
                                    state="disabled")
        self._stop_btn.pack(side="left", padx=(0, 4))
        self._bypass_btn = ttk.Button(btn_row, text="BYPASS: OFF",
                                      command=self._on_bypass_toggle)
        self._bypass_btn.pack(side="left")

        # --- Dataset selector ---
        ttk.Label(self, text="HRTF データセット:").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=3)
        self._dataset_var = tk.StringVar()
        self._dataset_cb = ttk.Combobox(self, textvariable=self._dataset_var,
                                         state="readonly", width=30)
        self._dataset_cb.grid(row=1, column=1, sticky="ew", pady=3)
        self._dataset_cb.bind("<<ComboboxSelected>>", self._on_dataset_changed)
        self._populate_datasets(dataset_base)

        # --- Block size selector ---
        ttk.Label(self, text="ブロックサイズ:").grid(
            row=2, column=0, sticky="w", padx=(0, 8), pady=3)
        self._block_var = tk.StringVar()
        block_labels = [
            f"{bs} samples  ({bs / 44100 * 1000:.1f} ms)"
            for bs in self._BLOCK_SIZES
        ]
        self._block_cb = ttk.Combobox(self, textvariable=self._block_var,
                                       state="readonly", width=30,
                                       values=block_labels)
        self._block_cb.current(1)  # default 512
        self._block_cb.grid(row=2, column=1, sticky="ew", pady=3)
        self._block_cb.bind("<<ComboboxSelected>>", self._on_block_changed)

        # --- Volume slider ---
        ttk.Label(self, text="音量:").grid(
            row=3, column=0, sticky="w", padx=(0, 8), pady=3)
        vol_frame = ttk.Frame(self)
        vol_frame.grid(row=3, column=1, sticky="ew", pady=3)

        self._vol_var = tk.DoubleVar(value=100.0)
        self._vol_slider = ttk.Scale(
            vol_frame,
            from_=0.0, to=150.0,
            orient="horizontal",
            variable=self._vol_var,
            command=self._on_volume_changed,
        )
        self._vol_slider.pack(side="left", fill="x", expand=True)
        self._vol_label = ttk.Label(vol_frame, text="100%", width=5, anchor="e")
        self._vol_label.pack(side="left", padx=(4, 0))

        # --- Info label ---
        self._info_var = tk.StringVar(value="遅延: 11.6 ms  |  SR: 44100 Hz  |  停止中")
        info_lbl = ttk.Label(self, textvariable=self._info_var,
                              foreground="gray", font=("", 10))
        info_lbl.grid(row=4, column=0, columnspan=2, pady=(6, 0))

        self.columnconfigure(1, weight=1)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def selected_dataset_dir(self) -> str:
        idx = self._dataset_cb.current()
        if 0 <= idx < len(self._dataset_dirs):
            return self._dataset_dirs[idx]
        return ""

    def selected_block_size(self) -> int:
        idx = self._block_cb.current()
        if 0 <= idx < len(self._BLOCK_SIZES):
            return self._BLOCK_SIZES[idx]
        return 512

    def set_running(self, running: bool) -> None:
        self._start_btn.configure(state="disabled" if running else "normal",
                                   text="▶ 開始")
        self._stop_btn.configure(state="normal" if running else "disabled")
        self._dataset_cb.configure(state="disabled" if running else "readonly")
        self._block_cb.configure(state="disabled" if running else "readonly")
        self._update_info("処理中" if running else "停止中")

    def set_loading(self) -> None:
        self._start_btn.configure(state="disabled", text="読み込み中…")

    # ------------------------------------------------------------------
    # Internal callbacks
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        if self._cb_start:
            self._cb_start()

    def _on_stop(self) -> None:
        if self._cb_stop:
            self._cb_stop()

    def _on_bypass_toggle(self) -> None:
        self._bypass_state = not self._bypass_state
        label = "BYPASS: ON" if self._bypass_state else "BYPASS: OFF"
        self._bypass_btn.configure(text=label)
        if self._cb_bypass:
            self._cb_bypass(self._bypass_state)

    def _on_dataset_changed(self, _event=None) -> None:
        path = self.selected_dataset_dir()
        if path and self._cb_dataset:
            self._cb_dataset(path)

    def _on_block_changed(self, _event=None) -> None:
        if self._cb_block_size:
            self._cb_block_size(self.selected_block_size())
        self._update_info()

    def _on_volume_changed(self, _val=None) -> None:
        pct = self._vol_var.get()
        self._vol_label.configure(text=f"{pct:.0f}%")
        if self._cb_volume:
            self._cb_volume(pct / 100.0)

    def _update_info(self, status: str = "") -> None:
        bs = self.selected_block_size()
        lat = bs / 44100 * 1000
        self._info_var.set(f"遅延: {lat:.1f} ms  |  SR: 44100 Hz  |  {status}")

    def _populate_datasets(self, base: str) -> None:
        from spatializer_app.engine.hrtf_loader import HRTFDataset
        self._dataset_dirs = HRTFDataset.scan_datasets(base)
        labels = [os.path.basename(d) for d in self._dataset_dirs]
        self._dataset_cb["values"] = labels
        # Default to the latest version (_6)
        default = next(
            (i for i, d in enumerate(self._dataset_dirs) if d.endswith("_6")),
            len(self._dataset_dirs) - 1,
        )
        if labels:
            self._dataset_cb.current(default)
