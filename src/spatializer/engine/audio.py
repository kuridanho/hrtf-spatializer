"""Real-time audio stream management and device discovery."""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np
import sounddevice as sd

from ..config import DEFAULT_SAMPLE_RATE, MAX_GAIN, MIN_GAIN
from .hrtf import DatasetError, HRTFDataset
from .upols import UPOLSSpatializer

logger = logging.getLogger(__name__)


class LatestValue:
    """A lock-free single-slot mailbox where the newest value wins.

    Used by the audio callback to publish level-meter values without ever
    blocking the real-time thread or growing an unbounded queue.
    """

    def __init__(self) -> None:
        self._items: deque[Any] = deque(maxlen=1)

    def set(self, value: Any) -> None:
        self._items.append(value)

    def take(self) -> Any | None:
        try:
            return self._items.popleft()
        except IndexError:
            return None


@dataclass(frozen=True, slots=True)
class AudioDevice:
    """A snapshot of one PortAudio device."""

    index: int
    name: str
    max_input_channels: int
    max_output_channels: int
    default_samplerate: float

    @property
    def supports_input(self) -> bool:
        return self.max_input_channels > 0

    @property
    def supports_output(self) -> bool:
        return self.max_output_channels > 0

    def label(self, *, input_side: bool) -> str:
        channels = self.max_input_channels if input_side else self.max_output_channels
        rate = self.default_samplerate / 1000.0
        return f"{self.name}  [{channels}ch, {rate:.1f} kHz]"


def list_devices() -> list[AudioDevice]:
    """Return all PortAudio devices, or an empty list if the backend fails."""
    try:
        raw_devices = sd.query_devices()
    except Exception as exc:  # PortAudioError and host-API specific failures
        logger.warning("オーディオデバイスを取得できません: %s", exc)
        return []

    devices: list[AudioDevice] = []
    for index, device in enumerate(raw_devices):
        try:
            devices.append(
                AudioDevice(
                    index=int(index),
                    name=str(device["name"]),
                    max_input_channels=int(device["max_input_channels"]),
                    max_output_channels=int(device["max_output_channels"]),
                    default_samplerate=float(device["default_samplerate"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            logger.debug("デバイス %s を解釈できませんでした: %r", index, device)
    return devices


def find_device(name_fragment: str, *, require_input: bool) -> int | None:
    """Find the first device whose name contains *name_fragment*."""
    needle = name_fragment.lower()
    for device in list_devices():
        channel_ok = device.supports_input if require_input else device.supports_output
        if channel_ok and needle in device.name.lower():
            return device.index
    return None


def detect_blackhole() -> int | None:
    """Return the input index of BlackHole, if installed."""
    return find_device("blackhole", require_input=True)


def detect_airpods() -> int | None:
    """Return the output index of AirPods, if connected."""
    return find_device("airpods", require_input=False)


def _default_device(index: int) -> int | None:
    try:
        value = int(sd.default.device[index])
    except (TypeError, ValueError, IndexError):
        return None
    return value if value >= 0 else None


def default_input_device() -> int | None:
    return _default_device(0)


def default_output_device() -> int | None:
    return _default_device(1)


class AudioEngine:
    """Owns the duplex PortAudio stream and the HRTF spatializer.

    Signal flow::

        input device (BlackHole) → UPOLS HRTF → output device (headphones)

    The callback does no allocation-heavy setup: the filter bank is built
    before the stream starts (or on the thread calling
    :meth:`update_dataset`).
    """

    def __init__(self) -> None:
        self._stream: sd.Stream | None = None
        self._spatializer: UPOLSSpatializer | None = None
        self._bypass = False
        self._gain = 1.0
        self._faulted = False
        self._lock = threading.RLock()
        self._sample_rate = DEFAULT_SAMPLE_RATE

        #: Last ``(rms_left, rms_right)`` pair, polled by the GUI.
        self.level = LatestValue()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(
        self,
        dataset: HRTFDataset,
        input_device: int,
        output_device: int,
        *,
        block_size: int = 512,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ) -> None:
        """Open and start the duplex stream."""
        with self._lock:
            self.stop()
            dataset.require_loaded()
            if dataset.sample_rate != sample_rate:
                raise DatasetError(
                    "HRTF データセットとストリームのサンプルレートが一致しません: "
                    f"dataset={dataset.sample_rate} Hz, stream={sample_rate} Hz"
                )

            spatializer = UPOLSSpatializer(dataset, block_size=block_size)
            stream = sd.Stream(
                samplerate=sample_rate,
                blocksize=block_size,
                device=(input_device, output_device),
                channels=(2, 2),
                dtype="float32",
                callback=self._callback,
                latency="low",
            )

            self._spatializer = spatializer
            self._stream = stream
            self._sample_rate = sample_rate
            self._faulted = False

            try:
                stream.start()
            except Exception:
                self._stream = None
                self._spatializer = None
                try:
                    stream.close()
                except Exception:
                    logger.debug("Failed to close stream after start error", exc_info=True)
                raise

            logger.info(
                "Stream started: %d Hz, %d samples/block, backend=%s",
                sample_rate,
                block_size,
                spatializer.backend,
            )

    def stop(self) -> None:
        """Stop and close the stream, if running."""
        with self._lock:
            stream, self._stream = self._stream, None
            spatializer, self._spatializer = self._spatializer, None

            if stream is not None:
                try:
                    stream.stop()
                except Exception:
                    logger.debug("Failed to stop stream", exc_info=True)
                try:
                    stream.close()
                except Exception:
                    logger.debug("Failed to close stream", exc_info=True)

            if spatializer is not None:
                spatializer.reset()

    def is_running(self) -> bool:
        stream = self._stream
        return stream is not None and bool(stream.active)

    @property
    def backend(self) -> str | None:
        spatializer = self._spatializer
        return spatializer.backend if spatializer is not None else None

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    # ------------------------------------------------------------------
    # Runtime controls (thread-safe)
    # ------------------------------------------------------------------

    def set_bypass(self, bypass: bool) -> None:
        self._bypass = bool(bypass)

    @property
    def bypass(self) -> bool:
        return self._bypass

    def set_volume(self, gain: float) -> None:
        """Set output gain; ``0.0`` mutes, ``1.0`` is unity, ``2.0`` doubles."""
        self._gain = float(np.clip(gain, MIN_GAIN, MAX_GAIN))

    @property
    def volume(self) -> float:
        return self._gain

    def update_dataset(self, dataset: HRTFDataset) -> None:
        """Build new filters and schedule them for the next audio block."""
        spatializer = self._spatializer
        if spatializer is None:
            raise RuntimeError("ストリームが開始されていません")
        if dataset.sample_rate != self._sample_rate:
            raise DatasetError(
                "実行中に切り替えるには、同じサンプルレートのデータセットが必要です: "
                f"現在={self._sample_rate} Hz, 新規={dataset.sample_rate} Hz"
            )
        spatializer.update_dataset(dataset)

    # ------------------------------------------------------------------
    # Audio callback (PortAudio real-time thread)
    # ------------------------------------------------------------------

    def _callback(
        self,
        indata: np.ndarray,
        outdata: np.ndarray,
        frames: int,
        time_info: Any,
        status: Any,
    ) -> None:
        if status:
            logger.debug("PortAudio status: %s", status)

        spatializer = self._spatializer
        if self._bypass or spatializer is None:
            outdata[:] = indata
        else:
            try:
                outdata[:] = spatializer.process_block(indata)
            except Exception:
                if not self._faulted:
                    logger.exception("HRTF 処理に失敗したため BYPASS に切り替えます")
                    self._faulted = True
                self._bypass = True
                outdata[:] = indata

        gain = self._gain
        if gain != 1.0:
            outdata *= gain

        if frames:
            left = outdata[:, 0]
            right = outdata[:, 1]
            self.level.set(
                (
                    float(np.sqrt(np.dot(left, left) / frames)),
                    float(np.sqrt(np.dot(right, right) / frames)),
                )
            )

    # ------------------------------------------------------------------
    # Context manager convenience
    # ------------------------------------------------------------------

    def __enter__(self) -> AudioEngine:
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.stop()
