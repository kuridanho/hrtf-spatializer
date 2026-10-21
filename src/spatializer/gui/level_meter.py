"""Dual-channel vertical RMS/peak level meter."""

from __future__ import annotations

import math
import tkinter as tk
from typing import Protocol


class MeterSource(Protocol):
    def take(self) -> tuple[float, float] | None: ...


class LevelMeterWidget(tk.Canvas):
    """Draw a dB-scaled L/R meter by polling a :class:`MeterSource`."""

    _DECAY = 0.85
    _MIN_DB = -60.0
    _POLL_MS = 33  # ~30 Hz

    def __init__(self, master: tk.Misc, **kwargs: object) -> None:
        kwargs.setdefault("width", 56)
        kwargs.setdefault("height", 140)
        kwargs.setdefault("bg", "#1e1e1e")
        kwargs.setdefault("highlightthickness", 1)
        kwargs.setdefault("highlightbackground", "#444")
        super().__init__(master, **kwargs)

        self._rms = [0.0, 0.0]
        self._peak = [0.0, 0.0]
        self._source: MeterSource | None = None
        self._alive = True

        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Destroy>", self._on_destroy, add="+")
        self.after(self._POLL_MS, self._poll)

    def set_source(self, source: MeterSource | None) -> None:
        self._source = source

    # ------------------------------------------------------------------

    def _on_destroy(self, event: tk.Event) -> None:
        if event.widget is self:
            self._alive = False

    def _poll(self) -> None:
        if not self._alive:
            return

        value = self._source.take() if self._source is not None else None
        if value is not None:
            self._rms[0], self._rms[1] = value
            for channel in range(2):
                self._peak[channel] = max(self._rms[channel], self._peak[channel] * self._DECAY)
        else:
            for channel in range(2):
                self._rms[channel] *= self._DECAY
                self._peak[channel] *= self._DECAY

        self._draw()
        try:
            self.after(self._POLL_MS, self._poll)
        except tk.TclError:
            self._alive = False

    def _draw(self) -> None:
        if not self._alive:
            return
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        if width < 4 or height < 4:
            return

        margin_top = 4
        label_height = 16
        bar_height = height - margin_top - label_height
        gap = 6
        bar_width = max(1, (width - gap) // 2)

        for channel, label in enumerate(("L", "R")):
            x0 = channel * (bar_width + gap)
            x1 = x0 + bar_width

            self.create_rectangle(
                x0,
                margin_top,
                x1,
                margin_top + bar_height,
                fill="#1e1e1e",
                outline="#333",
            )

            rms_db = 20 * math.log10(max(self._rms[channel], 1e-10))
            fraction = max(0.0, min(1.0, (rms_db - self._MIN_DB) / -self._MIN_DB))
            fill_height = int(bar_height * fraction)

            for segment in range(fill_height):
                t = segment / bar_height  # 0 = bottom, 1 = top
                y_bottom = margin_top + bar_height - segment
                self.create_rectangle(
                    x0 + 1,
                    y_bottom - 1,
                    x1 - 1,
                    y_bottom,
                    fill=self._gradient_color(t),
                    outline="",
                )

            peak_db = 20 * math.log10(max(self._peak[channel], 1e-10))
            peak_fraction = max(0.0, min(1.0, (peak_db - self._MIN_DB) / -self._MIN_DB))
            peak_y = margin_top + bar_height - int(bar_height * peak_fraction)
            self.create_line(x0 + 1, peak_y, x1 - 1, peak_y, fill="#ffffff", width=1)

            self.create_text(
                x0 + bar_width // 2,
                height - label_height // 2,
                text=label,
                fill="#cccccc",
                font=("", 9, "bold"),
            )

    @staticmethod
    def _gradient_color(t: float) -> str:
        """Map 0 = bottom (green) through 0.7 (yellow) to 1 = top (red)."""
        if t < 0.7:
            red = int(t / 0.7 * 200)
            green = 180
        else:
            red = 220
            green = int((1.0 - (t - 0.7) / 0.3) * 200)
        return f"#{red:02x}{green:02x}00"
