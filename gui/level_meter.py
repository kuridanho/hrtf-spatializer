from __future__ import annotations
import math
import queue
import tkinter as tk
from tkinter import ttk


class LevelMeterWidget(tk.Canvas):
    """
    Dual-channel vertical level meter (L / R).

    Polls engine.meter_queue at ~30 Hz and draws dB-scaled gradient bars.
    """

    _DECAY = 0.85
    _MIN_DB = -60.0
    _POLL_MS = 33  # ~30 Hz

    def __init__(self, master: tk.Misc, **kwargs) -> None:
        kwargs.setdefault("width", 56)
        kwargs.setdefault("height", 140)
        kwargs.setdefault("bg", "#1e1e1e")
        kwargs.setdefault("highlightthickness", 1)
        kwargs.setdefault("highlightbackground", "#444")
        super().__init__(master, **kwargs)

        self._rms = [0.0, 0.0]
        self._peak = [0.0, 0.0]
        self._meter_queue: queue.SimpleQueue | None = None

        self.bind("<Configure>", lambda _: self._draw())
        self._poll()

    def set_meter_queue(self, q: queue.SimpleQueue) -> None:
        self._meter_queue = q

    # ------------------------------------------------------------------

    def _poll(self) -> None:
        if self._meter_queue is not None:
            latest = None
            while True:
                try:
                    latest = self._meter_queue.get_nowait()
                except Exception:
                    break
            if latest is not None:
                self._rms[0], self._rms[1] = latest
                for i in range(2):
                    self._peak[i] = max(self._rms[i], self._peak[i] * self._DECAY)
            else:
                for i in range(2):
                    self._rms[i] *= self._DECAY
                    self._peak[i] *= self._DECAY
            self._draw()
        self.after(self._POLL_MS, self._poll)

    def _draw(self) -> None:
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 4 or h < 4:
            return

        margin_top = 4
        label_h = 16
        bar_h = h - margin_top - label_h
        gap = 6
        bar_w = (w - gap) // 2

        for ch, label in enumerate(("L", "R")):
            x0 = ch * (bar_w + gap)
            x1 = x0 + bar_w

            # Background
            self.create_rectangle(x0, margin_top, x1, margin_top + bar_h,
                                   fill="#1e1e1e", outline="#333")

            # RMS bar (segmented gradient)
            rms = self._rms[ch]
            db = 20 * math.log10(max(rms, 1e-10))
            frac = max(0.0, min(1.0, (db - self._MIN_DB) / (-self._MIN_DB)))
            fill_h = int(bar_h * frac)

            if fill_h > 0:
                # Draw gradient as stacked thin rectangles
                segs = max(fill_h, 1)
                for s in range(segs):
                    t = s / bar_h  # 0 = bottom, 1 = top
                    color = self._gradient_color(t)
                    y_bot = margin_top + bar_h - s
                    y_top = y_bot - 1
                    self.create_rectangle(x0 + 1, y_top, x1 - 1, y_bot,
                                           fill=color, outline="")

            # Peak tick
            pk_db = 20 * math.log10(max(self._peak[ch], 1e-10))
            pk_frac = max(0.0, min(1.0, (pk_db - self._MIN_DB) / (-self._MIN_DB)))
            pk_y = margin_top + bar_h - int(bar_h * pk_frac)
            self.create_line(x0 + 1, pk_y, x1 - 1, pk_y, fill="#ffffff", width=1)

            # Channel label
            self.create_text(
                x0 + bar_w // 2, h - label_h // 2,
                text=label, fill="#cccccc", font=("", 9, "bold"),
            )

    @staticmethod
    def _gradient_color(t: float) -> str:
        """Map 0=bottom(green) → 0.7(yellow) → 1=top(red)."""
        if t < 0.7:
            r = int(t / 0.7 * 200)
            g = 180
        else:
            r = 220
            g = int((1.0 - (t - 0.7) / 0.3) * 200)
        return f"#{r:02x}{g:02x}00"
