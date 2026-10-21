from __future__ import annotations
import tkinter as tk
from tkinter import ttk
from typing import Optional

import sounddevice as sd


def _build_device_list(require_input: bool) -> list[tuple[int, str]]:
    key = "max_input_channels" if require_input else "max_output_channels"
    items: list[tuple[int, str]] = []
    for i, dev in enumerate(sd.query_devices()):
        if dev[key] > 0:
            sr = int(dev["default_samplerate"])
            ch = int(dev[key])
            items.append((i, f"{dev['name']}  [{ch}ch, {sr // 1000}kHz]"))
    return items


class DevicePanel(ttk.LabelFrame):
    """Input / output audio device selectors."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, text="オーディオデバイス", padding=8)

        self._input_items = _build_device_list(require_input=True)
        self._output_items = _build_device_list(require_input=False)

        self._input_var = tk.StringVar()
        self._output_var = tk.StringVar()

        ttk.Label(self, text="入力 (BlackHole):").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self._input_cb = ttk.Combobox(
            self, textvariable=self._input_var, state="readonly", width=38,
            values=[label for _, label in self._input_items],
        )
        self._input_cb.grid(row=0, column=1, sticky="ew", pady=3)

        ttk.Label(self, text="出力 (ヘッドホン):").grid(row=1, column=0, sticky="w", padx=(0, 8))
        self._output_cb = ttk.Combobox(
            self, textvariable=self._output_var, state="readonly", width=38,
            values=[label for _, label in self._output_items],
        )
        self._output_cb.grid(row=1, column=1, sticky="ew", pady=3)

        self.columnconfigure(1, weight=1)
        self._auto_select()

    # ------------------------------------------------------------------

    def selected_input_device(self) -> Optional[int]:
        idx = self._input_cb.current()
        if idx < 0 or idx >= len(self._input_items):
            return None
        return self._input_items[idx][0]

    def selected_output_device(self) -> Optional[int]:
        idx = self._output_cb.current()
        if idx < 0 or idx >= len(self._output_items):
            return None
        return self._output_items[idx][0]

    def set_enabled(self, enabled: bool) -> None:
        state = "readonly" if enabled else "disabled"
        self._input_cb.configure(state=state)
        self._output_cb.configure(state=state)

    # ------------------------------------------------------------------

    def _auto_select(self) -> None:
        for i, (_, label) in enumerate(self._input_items):
            if "blackhole" in label.lower():
                self._input_cb.current(i)
                break
        else:
            if self._input_items:
                self._input_cb.current(0)

        for i, (_, label) in enumerate(self._output_items):
            if "airpods" in label.lower():
                self._output_cb.current(i)
                break
        else:
            if self._output_items:
                self._output_cb.current(0)
