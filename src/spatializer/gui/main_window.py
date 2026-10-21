"""Top-level application window and thread orchestration."""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from ..config import AppConfig
from ..engine.audio import AudioEngine, detect_blackhole
from ..engine.hrtf import HRTFDataset, scan_datasets
from .control_panel import ControlPanel
from .device_panel import DevicePanel
from .level_meter import LevelMeterWidget
from .setup_dialog import show_setup_dialog

logger = logging.getLogger(__name__)


class MainWindow:
    """Build the tkinter UI and connect it to the audio engine."""

    def __init__(self, root: tk.Tk, config: AppConfig) -> None:
        self._root = root
        self._config = config
        self._engine = AudioEngine()
        self._result_queue: queue.SimpleQueue[tuple[str, str]] = queue.SimpleQueue()
        self._closing = False

        root.title("Spatializer — HRTF リアルタイム空間音響")
        root.resizable(False, False)

        outer = ttk.Frame(root, padding=14)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer,
            text="🎧  Spatializer",
            font=("", 18, "bold"),
            anchor="center",
        ).pack(fill="x", pady=(0, 8))

        top = ttk.Frame(outer)
        top.pack(fill="x", pady=(0, 8))

        self._device_panel = DevicePanel(top)
        self._device_panel.pack(side="left", fill="both", expand=True, padx=(0, 8))

        self._meter = LevelMeterWidget(top, width=56, height=130)
        self._meter.pack(side="right", fill="y")
        self._meter.set_source(self._engine.level)

        self._control = ControlPanel(
            outer,
            block_size=config.block_size,
            sample_rate=config.sample_rate,
            on_start=self._on_start,
            on_stop=self._on_stop,
            on_bypass=self._on_bypass,
            on_volume=self._on_volume,
            on_rescan=self._refresh_datasets,
            on_dataset=self._on_dataset_selected,
        )
        self._control.pack(fill="x")
        self._control.set_datasets(scan_datasets(config.dataset_root))

        ttk.Label(
            outer,
            text=(
                "⚠️  システム出力を BlackHole のみに設定してください"
                "（AirPods との同時出力はエコーの原因になります）"
            ),
            foreground="#b05000",
            font=("", 10),
            wraplength=480,
            justify="center",
        ).pack(pady=(8, 0))

        ttk.Label(
            outer,
            text=f"データセット: {config.dataset_root}",
            foreground="#777777",
            font=("", 9),
            wraplength=480,
            justify="center",
        ).pack(pady=(4, 0))

        root.update_idletasks()
        root.after(250, self._startup_check)
        root.after(500, self._sync_engine_state)

        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.bind_all("<Command-q>", lambda _event: self._on_close())
        root.bind_all("<Control-q>", lambda _event: self._on_close())

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def _startup_check(self) -> None:
        if self._closing:
            return
        if detect_blackhole() is None:
            show_setup_dialog(self._root)
        if not self._control.has_datasets():
            self._control.set_status("データセット未検出 — dataset/ に HRTF を配置してください")

    def _sync_engine_state(self) -> None:
        """Reflect automatic bypass (DSP fault) in the button state."""
        if self._closing:
            return
        if self._engine.bypass != self._control.bypass_state:
            self._control.set_bypass(self._engine.bypass)
        self._root.after(500, self._sync_engine_state)

    # ------------------------------------------------------------------
    # Stream control
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        if self._engine.is_running():
            return

        input_device = self._device_panel.selected_input_device()
        output_device = self._device_panel.selected_output_device()
        if input_device is None or output_device is None:
            messagebox.showwarning("デバイスエラー", "入出力デバイスを選択してください。")
            return

        dataset_path = self._control.selected_dataset_path()
        if dataset_path is None:
            messagebox.showwarning(
                "データセットエラー",
                "HRTF データセットが見つかりません。\n"
                "README の形式で dataset/ に配置し、「再スキャン」を押してください。",
            )
            return

        block_size = self._control.selected_block_size()
        sample_rate = self._config.sample_rate
        self._control.set_loading()
        self._device_panel.set_enabled(False)

        def worker() -> None:
            try:
                dataset = HRTFDataset(dataset_path).load()
                self._engine.start(
                    dataset,
                    input_device,
                    output_device,
                    block_size=block_size,
                    sample_rate=sample_rate,
                )
            except Exception as exc:
                logger.exception("Failed to start the audio stream")
                self._result_queue.put(("error", str(exc)))
            else:
                self._result_queue.put(("ok", dataset.name))

        threading.Thread(target=worker, name="spatializer-start", daemon=True).start()
        self._root.after(100, self._poll_start_result)

    def _poll_start_result(self) -> None:
        if self._closing:
            return
        try:
            kind, payload = self._result_queue.get_nowait()
        except queue.Empty:
            self._root.after(100, self._poll_start_result)
            return

        if kind == "ok":
            self._control.set_running(True)
            backend = self._engine.backend or "numpy"
            self._control.set_status(f"{payload}  |  {backend}")
        else:
            self._control.set_running(False)
            self._device_panel.set_enabled(True)
            self._control.set_status("起動エラー")
            messagebox.showerror(
                "起動エラー",
                "ストリームを開けませんでした。\n\n"
                f"{payload}\n\n"
                "BlackHole と出力デバイスの設定を確認してください。",
            )

    def _on_stop(self) -> None:
        self._engine.stop()
        self._control.set_running(False)
        self._device_panel.set_enabled(True)

    def _on_bypass(self, bypass: bool) -> None:
        self._engine.set_bypass(bypass)

    def _on_volume(self, gain: float) -> None:
        self._engine.set_volume(gain)

    # ------------------------------------------------------------------
    # Dataset handling
    # ------------------------------------------------------------------

    def _on_dataset_selected(self, path: Path) -> None:
        if not self._engine.is_running():
            self._control.set_status(f"停止中 — {path.name}")

    def _refresh_datasets(self) -> None:
        paths = scan_datasets(self._config.dataset_root)
        self._control.set_datasets(paths)

        if not paths:
            self._control.set_status("データセット未検出")
            messagebox.showinfo(
                "HRTF データセット",
                "データセットが見つかりませんでした。\n\n"
                f"配置場所: {self._config.dataset_root}\n\n"
                "必要なファイル形式は README を参照してください。",
            )
        else:
            self._control.set_status(f"{len(paths)} 件のデータセットを検出")

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def _on_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._engine.stop()
        self._root.destroy()
