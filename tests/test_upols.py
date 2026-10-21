from __future__ import annotations

import numpy as np
import pytest

from spatializer.engine import upols as upols_module
from spatializer.engine.hrtf import POSITIONS, DatasetError, HRTFDataset
from spatializer.engine.upols import UPOLSSpatializer


def make_dataset(*, length: int = 192, directions: int = 5, seed: int = 0) -> HRTFDataset:
    rng = np.random.default_rng(seed)
    hrirs = np.zeros((directions, length, 2), dtype=np.float32)
    for index in range(directions):
        delay = index % 4
        hrirs[index, delay, 0] = 1.0
        hrirs[index, delay + 1, 1] = 0.8
        hrirs[index] += rng.normal(0.0, 1e-3, size=(length, 2)).astype(np.float32)
    return HRTFDataset.from_arrays(hrirs, 44_100, positions=POSITIONS[:directions])


def reference_output(x: np.ndarray, dataset: HRTFDataset) -> np.ndarray:
    """Direct time-domain convolution with pan mixing and direction averaging."""
    mixes = x @ dataset.pan_coefs.T
    output = np.zeros((len(x), 2), dtype=np.float64)
    for direction in range(dataset.num_positions):
        for ear in range(2):
            convolved = np.convolve(
                mixes[:, direction],
                dataset.hrirs[direction, :, ear],
                mode="full",
            )
            output[:, ear] += convolved[: len(x)]
    return output / dataset.num_positions


def test_matches_direct_convolution() -> None:
    dataset = make_dataset()
    rng = np.random.default_rng(123)
    audio = rng.uniform(-1.0, 1.0, size=(640, 2)).astype(np.float32)

    spatializer = UPOLSSpatializer(dataset, block_size=64)
    actual = spatializer.process(audio)
    expected = reference_output(audio.astype(np.float64), dataset)

    np.testing.assert_allclose(actual, expected, atol=1e-4, rtol=1e-4)


def test_impulse_alignment() -> None:
    dataset = HRTFDataset.from_arrays(
        np.array([[[1.0, 1.0]] + [[0.0, 0.0]] * 63], dtype=np.float32),
        44_100,
        positions=(POSITIONS[-1],),
    )
    spatializer = UPOLSSpatializer(dataset, block_size=64)

    audio = np.zeros((128, 2), dtype=np.float32)
    audio[0, 0] = 1.0  # left input only → 0.5 to each ear via the center pan
    output = spatializer.process(audio)

    np.testing.assert_allclose(output[0], [0.5, 0.5], atol=1e-6)
    np.testing.assert_allclose(output[1:], 0.0, atol=1e-6)


def test_update_dataset_swaps_filters() -> None:
    first = make_dataset(seed=0)
    second = make_dataset(seed=1)
    rng = np.random.default_rng(5)
    audio = rng.uniform(-0.5, 0.5, size=(320, 2)).astype(np.float32)

    spatializer = UPOLSSpatializer(first, block_size=64)
    spatializer.update_dataset(second)
    actual = spatializer.process(audio)

    expected = reference_output(audio.astype(np.float64), second)
    np.testing.assert_allclose(actual, expected, atol=1e-4, rtol=1e-4)


def test_incompatible_dataset_is_rejected() -> None:
    spatializer = UPOLSSpatializer(make_dataset(directions=5), block_size=64)

    with pytest.raises(DatasetError, match="方向数"):
        spatializer.update_dataset(make_dataset(directions=4))
    with pytest.raises(DatasetError, match="方向数"):
        spatializer.update_dataset(make_dataset(length=256, directions=5))


def test_sample_rate_mismatch_is_rejected() -> None:
    spatializer = UPOLSSpatializer(make_dataset(), block_size=64)
    other = HRTFDataset.from_arrays(make_dataset().hrirs, 48_000, positions=POSITIONS[:5])

    with pytest.raises(DatasetError, match="サンプルレート"):
        spatializer.update_dataset(other)


def test_reset_clears_history() -> None:
    spatializer = UPOLSSpatializer(make_dataset(), block_size=64)
    audio = np.ones((128, 2), dtype=np.float32) * 0.25
    spatializer.process(audio)

    spatializer.reset()
    silence = np.zeros((128, 2), dtype=np.float32)
    output = spatializer.process(silence)

    np.testing.assert_allclose(output, 0.0, atol=1e-8)


def test_invalid_block_shape() -> None:
    spatializer = UPOLSSpatializer(make_dataset(), block_size=64)

    with pytest.raises(ValueError, match="入力"):
        spatializer.process_block(np.zeros((32, 2), dtype=np.float32))
    with pytest.raises(ValueError):
        spatializer.process_block(np.zeros((64, 1), dtype=np.float32))


def test_numpy_fallback_matches_accelerator(monkeypatch) -> None:
    dataset = make_dataset()
    rng = np.random.default_rng(7)
    audio = rng.uniform(-0.5, 0.5, size=(320, 2)).astype(np.float32)

    accelerated = UPOLSSpatializer(dataset, block_size=64)
    accelerated_output = accelerated.process(audio)
    accelerated_backend = accelerated.backend

    monkeypatch.setattr(upols_module, "_ACCELERATOR", None)
    fallback = UPOLSSpatializer(dataset, block_size=64)
    fallback_output = fallback.process(audio)
    fallback_backend = fallback.backend

    if accelerated_backend == "rust":
        np.testing.assert_allclose(accelerated_output, fallback_output, atol=1e-5)
    assert accelerated_backend in {"rust", "numpy"}
    assert fallback_backend == "numpy"


def test_repr_contains_backend() -> None:
    spatializer = UPOLSSpatializer(make_dataset(), block_size=64)
    text = repr(spatializer)
    assert "directions=5" in text
    assert "block_size=64" in text
    assert spatializer.backend in text
