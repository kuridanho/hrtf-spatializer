from __future__ import annotations

import numpy as np
import pytest

from spatializer.engine import audio as audio_module
from spatializer.engine.audio import (
    AudioDevice,
    AudioEngine,
    LatestValue,
    find_device,
    list_devices,
)
from spatializer.engine.hrtf import HRTFDataset
from spatializer.engine.upols import UPOLSSpatializer


def test_latest_value_keeps_only_the_newest() -> None:
    mailbox = LatestValue()
    assert mailbox.take() is None

    mailbox.set(1)
    mailbox.set(2)
    assert mailbox.take() == 2
    assert mailbox.take() is None


def test_volume_is_clamped() -> None:
    engine = AudioEngine()

    engine.set_volume(-1.0)
    assert engine.volume == 0.0
    engine.set_volume(99.0)
    assert engine.volume == 2.0
    engine.set_volume(0.5)
    assert engine.volume == 0.5


def test_update_dataset_requires_running_stream() -> None:
    engine = AudioEngine()
    dataset = HRTFDataset.from_arrays(np.zeros((21, 64, 2), np.float32), 44_100)

    with pytest.raises(RuntimeError, match="開始"):
        engine.update_dataset(dataset)


def test_bypass_callback_copies_input_and_updates_meter() -> None:
    engine = AudioEngine()
    input_block = np.full((8, 2), 0.1, dtype=np.float32)
    output_block = np.zeros_like(input_block)

    engine._callback(input_block, output_block, 8, None, None)

    np.testing.assert_allclose(output_block, input_block)
    level = engine.level.take()
    assert level is not None
    assert level == pytest.approx((0.1, 0.1), abs=1e-6)


def test_callback_applies_gain_to_bypass_signal() -> None:
    engine = AudioEngine()
    engine.set_volume(0.5)
    input_block = np.full((4, 2), 0.2, dtype=np.float32)
    output_block = np.zeros_like(input_block)

    engine._callback(input_block, output_block, 4, None, None)

    np.testing.assert_allclose(output_block, 0.1)


def test_callback_runs_spatializer() -> None:
    engine = AudioEngine()
    dataset = HRTFDataset.from_arrays(np.zeros((21, 64, 2), dtype=np.float32), 44_100)
    dataset.hrirs[:, 0, 0] = 1.0
    dataset.hrirs[:, 0, 1] = 1.0
    engine._spatializer = UPOLSSpatializer(dataset, block_size=16)

    input_block = np.zeros((16, 2), dtype=np.float32)
    input_block[0, :] = 0.5
    output_block = np.zeros_like(input_block)

    engine._callback(input_block, output_block, 16, None, None)

    assert np.all(np.isfinite(output_block))
    assert np.any(output_block != 0.0)
    assert engine.level.take() is not None


def test_device_finders(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_devices = [
        {
            "name": "BlackHole 2ch",
            "max_input_channels": 2,
            "max_output_channels": 2,
            "default_samplerate": 44_100.0,
        },
        {
            "name": "AirPods Pro",
            "max_input_channels": 0,
            "max_output_channels": 2,
            "default_samplerate": 48_000.0,
        },
        {
            "name": "Built-in Microphone",
            "max_input_channels": 1,
            "max_output_channels": 0,
            "default_samplerate": 48_000.0,
        },
    ]
    monkeypatch.setattr(audio_module.sd, "query_devices", lambda: fake_devices)

    devices = list_devices()
    assert [device.index for device in devices] == [0, 1, 2]
    assert find_device("blackhole", require_input=True) == 0
    assert find_device("airpods", require_input=False) == 1
    assert find_device("airpods", require_input=True) is None
    assert audio_module.detect_blackhole() == 0
    assert audio_module.detect_airpods() == 1


def test_audio_device_label() -> None:
    device = AudioDevice(
        index=3,
        name="BlackHole 2ch",
        max_input_channels=2,
        max_output_channels=2,
        default_samplerate=44_100.0,
    )
    assert device.supports_input
    assert device.supports_output
    assert device.label(input_side=True) == "BlackHole 2ch  [2ch, 44.1 kHz]"
