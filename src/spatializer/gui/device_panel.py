"""Input / output audio device selectors."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..engine.audio import AudioDevice, list_devices


class DevicePanel(ttk.LabelFrame):
    """Two comboboxes listing usable input and output devices."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, text="オーディオデバイス", padding=8)

        self._input_items: list[AudioDevice] = []
        self._output_items: list[AudioDevice] = []

        self._input_var = tk.StringVar()
        self._output_var = tk.StringVar()

        ttk.Label(self, text="入力 (BlackHole):").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self._input_cb = ttk.Combobox(
            self,
            textvariable=self._input_var,
            state="readonly",
            width=38,
        )
        self._input_cb.grid(row=0, column=1, sticky="ew", pady=3)

        ttk.Label(self, text="出力 (ヘッドホン):").grid(row=1, column=0, sticky="w", padx=(0, 8))
        self._output_cb = ttk.Combobox(
            self,
            textvariable=self._output_var,
            state="readonly",
            width=38,
        )
        self._output_cb.grid(row=1, column=1, sticky="ew", pady=3)

        self._refresh_button = ttk.Button(self, text="再読込", command=self.refresh, width=7)
        self._refresh_button.grid(row=2, column=1, sticky="e", pady=(4, 0))

        self.columnconfigure(1, weight=1)
        self.refresh()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def selected_input_device(self) -> int | None:
        index = self._input_cb.current()
        if 0 <= index < len(self._input_items):
            return self._input_items[index].index
        return None

    def selected_output_device(self) -> int | None:
        index = self._output_cb.current()
        if 0 <= index < len(self._output_items):
            return self._output_items[index].index
        return None

    def set_enabled(self, enabled: bool) -> None:
        state = "readonly" if enabled else "disabled"
        self._input_cb.configure(state=state)
        self._output_cb.configure(state=state)
        self._refresh_button.configure(state="normal" if enabled else "disabled")

    def refresh(self) -> None:
        """Rescan PortAudio devices, keeping the current selection if possible."""
        previous_input = self.selected_input_device()
        previous_output = self.selected_output_device()

        devices = list_devices()
        self._input_items = [device for device in devices if device.supports_input]
        self._output_items = [device for device in devices if device.supports_output]

        self._input_cb["values"] = [device.label(input_side=True) for device in self._input_items]
        self._output_cb["values"] = [
            device.label(input_side=False) for device in self._output_items
        ]

        if not self._select_by_index(self._input_cb, self._input_items, previous_input):
            self._auto_select(self._input_cb, self._input_items, ("blackhole",))

        if not self._select_by_index(self._output_cb, self._output_items, previous_output):
            self._auto_select(self._output_cb, self._output_items, ("airpods", "headphone"))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _select_by_index(
        combo: ttk.Combobox, items: list[AudioDevice], device_index: int | None
    ) -> bool:
        if device_index is None:
            return False
        for position, device in enumerate(items):
            if device.index == device_index:
                combo.current(position)
                return True
        return False

    @staticmethod
    def _auto_select(
        combo: ttk.Combobox, items: list[AudioDevice], preferred_names: tuple[str, ...]
    ) -> None:
        for needle in preferred_names:
            for position, device in enumerate(items):
                if needle in device.name.lower():
                    combo.current(position)
                    return
        if items:
            combo.current(0)
