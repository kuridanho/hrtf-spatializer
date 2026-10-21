from __future__ import annotations
import queue
import threading
from typing import Optional

import numpy as np
import sounddevice as sd

from .hrtf_loader import HRTFDataset
from .upols import VectorizedSpatializer


class AudioEngine:
    """
    Manages the real-time sounddevice duplex stream.

    Flow:
        BlackHole (input) → HRTF convolution → AirPods Pro (output)

    The audio callback must complete within one block period (~11.6 ms at
    512 samples / 44100 Hz). Heavy work (filter-bank rebuilding) is done
    on a background thread via update_dataset().
    """

    def __init__(self) -> None:
        self._stream: Optional[sd.Stream] = None
        self._spatializer: Optional[VectorizedSpatializer] = None
        self._bypass = False
        self._gain: float = 1.0   # linear volume (0.0 – 2.0)
        self._block_size = 512
        self._sample_rate = 44100
        self._lock = threading.Lock()

        # Level meter: callback pushes (rms_L, rms_R); GUI polls this queue
        self.meter_queue: queue.SimpleQueue[tuple[float, float]] = queue.SimpleQueue()

    # ------------------------------------------------------------------
    # Stream lifecycle
    # ------------------------------------------------------------------

    def start(
        self,
        dataset: HRTFDataset,
        input_device: int,
        output_device: int,
        block_size: int = 512,
        sample_rate: int = 44100,
    ) -> None:
        self.stop()
        self._block_size = block_size
        self._sample_rate = sample_rate
        self._spatializer = VectorizedSpatializer(dataset, block_size)

        self._stream = sd.Stream(
            samplerate=sample_rate,
            blocksize=block_size,
            device=(input_device, output_device),
            channels=(2, 2),
            dtype="float32",
            callback=self._callback,
            latency="low",
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if self._spatializer is not None:
            self._spatializer.reset()

    def is_running(self) -> bool:
        return self._stream is not None and self._stream.active

    # ------------------------------------------------------------------
    # Runtime controls (thread-safe)
    # ------------------------------------------------------------------

    def set_bypass(self, bypass: bool) -> None:
        self._bypass = bypass

    def set_volume(self, gain: float) -> None:
        """Set output gain (0.0 = mute, 1.0 = unity, 2.0 = double).
        Thread-safe: float assignment is atomic in CPython."""
        self._gain = max(0.0, min(2.0, gain))

    def update_dataset(self, dataset: HRTFDataset) -> None:
        """Rebuild filter banks on the calling thread, then schedule atomic swap."""
        if self._spatializer is not None:
            self._spatializer.update_dataset(dataset)

    # ------------------------------------------------------------------
    # Audio callback (called from PortAudio real-time thread)
    # ------------------------------------------------------------------

    def _callback(
        self,
        indata: np.ndarray,
        outdata: np.ndarray,
        frames: int,
        time: sd.CallbackTimeInfo,
        status: sd.CallbackFlags,
    ) -> None:
        if self._bypass or self._spatializer is None:
            outdata[:] = indata
        else:
            outdata[:] = self._spatializer.process_block(indata)

        # Apply output volume gain
        gain = self._gain
        if gain != 1.0:
            outdata *= gain

        # Push RMS to meter queue (non-blocking; drop if full)
        rms_L = float(np.sqrt(np.mean(outdata[:, 0] ** 2)))
        rms_R = float(np.sqrt(np.mean(outdata[:, 1] ** 2)))
        try:
            self.meter_queue.put_nowait((rms_L, rms_R))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Device discovery helpers
    # ------------------------------------------------------------------

    @staticmethod
    def list_devices() -> list[dict]:
        return list(sd.query_devices())

    @staticmethod
    def detect_blackhole() -> Optional[int]:
        for i, dev in enumerate(sd.query_devices()):
            if "blackhole" in dev["name"].lower() and dev["max_input_channels"] > 0:
                return i
        return None

    @staticmethod
    def detect_airpods() -> Optional[int]:
        for i, dev in enumerate(sd.query_devices()):
            name = dev["name"].lower()
            if "airpods" in name and dev["max_output_channels"] > 0:
                return i
        return None

    @staticmethod
    def default_output_device() -> int:
        return int(sd.default.device[1])

    @staticmethod
    def default_input_device() -> int:
        return int(sd.default.device[0])
