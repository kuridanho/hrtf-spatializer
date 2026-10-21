from __future__ import annotations
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional

from spatializer_app.engine.hrtf_loader import HRTFDataset
from spatializer_app.engine.audio_engine import AudioEngine
from .device_panel import DevicePanel
from .control_panel import ControlPanel
from .level_meter import LevelMeterWidget
from .setup_dialog import show_setup_dialog


class MainWindow:
    """
    Top-level application window built with tkinter.

    Threading model:
        Heavy work (dataset load + engine start) runs in a daemon thread.
        Results are put in _result_queue and picked up by _poll_result()
        which runs on the main thread via root.after().
    """

    def __init__(self, root: tk.Tk, dataset_base: str) -> None:
        self._root = root
        self._dataset_base = dataset_base
        self._engine = AudioEngine()
        self._result_queue: queue.SimpleQueue = queue.SimpleQueue()

        root.title("Spatializer — HRTF リアルタイム空間音響")
        root.resizable(False, False)

        # ---- Layout ----
        outer = ttk.Frame(root, padding=14)
        outer.pack(fill="both", expand=True)

        # Title
        ttk.Label(
            outer,
            text="🎧  Spatializer",
            font=("", 18, "bold"),
            anchor="center",
        ).pack(fill="x", pady=(0, 8))

        # Top row: device panel + level meter
        top = ttk.Frame(outer)
        top.pack(fill="x", pady=(0, 8))

        self._device_panel = DevicePanel(top)
        self._device_panel.pack(side="left", fill="both", expand=True, padx=(0, 8))

        self._meter = LevelMeterWidget(top, width=56, height=130)
        self._meter.pack(side="right", fill="y")
        self._meter.set_meter_queue(self._engine.meter_queue)

        # Control panel
        self._control = ControlPanel(
            outer,
            dataset_base=dataset_base,
            on_start=self._on_start,
            on_stop=self._on_stop,
            on_bypass=self._engine.set_bypass,
            on_dataset=self._on_dataset_changed,
            on_volume=self._engine.set_volume,
        )
        self._control.pack(fill="x")

        # Routing hint — always visible to prevent double-audio mistake
        hint = ttk.Label(
            outer,
            text="⚠️  システム出力 → BlackHole のみ に設定してください（AirPods Pro との同時出力はエコーの原因になります）",
            foreground="#b05000",
            font=("", 10),
            wraplength=480,
            justify="center",
        )
        hint.pack(pady=(8, 0))

        # ---- Startup: BlackHole check ----
        root.update_idletasks()
        if AudioEngine.detect_blackhole() is None:
            root.after(200, lambda: show_setup_dialog(root))

        # Proper termination: red-X button and macOS Cmd+Q both call _on_close
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.bind_all("<Command-q>", lambda _e: self._on_close())

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        in_dev = self._device_panel.selected_input_device()
        out_dev = self._device_panel.selected_output_device()
        if in_dev is None or out_dev is None:
            messagebox.showwarning("デバイスエラー", "入出力デバイスを選択してください。")
            return

        dataset_dir = self._control.selected_dataset_dir()
        if not dataset_dir:
            messagebox.showwarning("データセットエラー", "HRTFデータセットが見つかりません。")
            return

        self._control.set_loading()
        bs = self._control.selected_block_size()

        def _worker() -> None:
            try:
                dataset = HRTFDataset(dataset_dir)
                dataset.load()
                self._engine.start(
                    dataset=dataset,
                    input_device=in_dev,
                    output_device=out_dev,
                    block_size=bs,
                )
                self._result_queue.put(("ok", None))
            except Exception as exc:
                self._result_queue.put(("error", str(exc)))

        threading.Thread(target=_worker, daemon=True).start()
        self._root.after(100, self._poll_result)

    def _poll_result(self) -> None:
        try:
            kind, data = self._result_queue.get_nowait()
        except queue.Empty:
            self._root.after(100, self._poll_result)
            return

        if kind == "ok":
            self._control.set_running(True)
        else:
            self._control.set_running(False)
            messagebox.showerror("起動エラー", f"ストリームを開けませんでした:\n{data}")

    def _on_stop(self) -> None:
        self._engine.stop()
        self._control.set_running(False)

    def _on_dataset_changed(self, dataset_dir: str) -> None:
        if not self._engine.is_running():
            return

        def _rebuild() -> None:
            try:
                dataset = HRTFDataset(dataset_dir)
                dataset.load()
                self._engine.update_dataset(dataset)
            except Exception:
                pass

        threading.Thread(target=_rebuild, daemon=True).start()

    def _on_close(self) -> None:
        self._engine.stop()
        self._root.destroy()
