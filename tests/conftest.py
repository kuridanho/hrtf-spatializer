from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from spatializer.engine.hrtf import POSITIONS


def write_dataset(
    directory: Path,
    *,
    length: int = 256,
    sample_rate: int = 44_100,
    seed: int = 0,
) -> Path:
    """Write a complete synthetic 21-direction dataset to *directory*."""
    directory.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)

    for index, position in enumerate(POSITIONS):
        hrir = np.zeros((length, 2), dtype=np.float32)
        delay = index % 8
        hrir[delay, 0] = 1.0
        hrir[min(delay + 2, length - 1), 1] = 0.7
        hrir += rng.normal(0.0, 1e-4, size=hrir.shape).astype(np.float32)
        sf.write(directory / f"{position.stem}.wav", hrir, sample_rate, subtype="FLOAT")

    return directory


@pytest.fixture
def dataset_dir(tmp_path: Path) -> Path:
    return write_dataset(tmp_path / "home_impulse_test")
