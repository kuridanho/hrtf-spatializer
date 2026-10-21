from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from spatializer.engine.hrtf import (
    POSITIONS,
    DatasetError,
    HRTFDataset,
    scan_datasets,
)


def test_load_dataset(dataset_dir: Path) -> None:
    dataset = HRTFDataset(dataset_dir).load()

    assert dataset.is_loaded
    assert dataset.num_positions == len(POSITIONS) == 21
    assert dataset.hrirs.shape == (21, 256, 2)
    assert dataset.hrirs.dtype == np.float32
    assert dataset.sample_rate == 44_100
    assert dataset.hrir_len == 256
    assert dataset.pan_coefs.shape == (21, 2)
    np.testing.assert_allclose(dataset.pan_coefs.sum(axis=1), 1.0)


def test_scan_datasets_root_and_nested(tmp_path: Path, dataset_dir: Path) -> None:
    assert scan_datasets(tmp_path) == [dataset_dir.resolve()]
    assert scan_datasets(dataset_dir) == [dataset_dir.resolve()]
    assert scan_datasets(tmp_path / "does-not-exist") == []
    assert HRTFDataset.scan_datasets(tmp_path) == [dataset_dir.resolve()]


def test_scan_datasets_ignores_incomplete_directories(tmp_path: Path, dataset_dir: Path) -> None:
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    (incomplete / "0_0.wav").write_bytes(b"not a wav")

    assert scan_datasets(tmp_path) == [dataset_dir.resolve()]


def test_missing_file_is_reported(dataset_dir: Path) -> None:
    (dataset_dir / "30_0.wav").unlink()

    with pytest.raises(DatasetError, match="30_0.wav"):
        HRTFDataset(dataset_dir).load()


def test_mono_hrir_is_rejected(dataset_dir: Path) -> None:
    sf.write(dataset_dir / "0_0.wav", np.zeros(256, dtype=np.float32), 44_100)

    with pytest.raises(DatasetError, match="2ch"):
        HRTFDataset(dataset_dir).load()


def test_inconsistent_length_is_rejected(dataset_dir: Path) -> None:
    sf.write(dataset_dir / "0_0.wav", np.zeros((128, 2), dtype=np.float32), 44_100)

    with pytest.raises(DatasetError, match="長さ"):
        HRTFDataset(dataset_dir).load()


def test_inconsistent_sample_rate_is_rejected(dataset_dir: Path) -> None:
    sf.write(dataset_dir / "0_0.wav", np.zeros((256, 2), dtype=np.float32), 48_000)

    with pytest.raises(DatasetError, match="サンプルレート"):
        HRTFDataset(dataset_dir).load()


def test_alternate_take_is_averaged(dataset_dir: Path) -> None:
    primary, _ = sf.read(dataset_dir / "0_0.wav", dtype="float32", always_2d=True)
    alternate = primary + 0.25
    sf.write(dataset_dir / "0_0(2).wav", alternate, 44_100, subtype="FLOAT")

    averaged = HRTFDataset(dataset_dir, average_takes=True).load()
    raw = HRTFDataset(dataset_dir, average_takes=False).load()

    np.testing.assert_allclose(averaged.hrirs[-1], (primary + alternate) * 0.5, atol=1e-6)
    np.testing.assert_allclose(raw.hrirs[-1], primary, atol=1e-6)


def test_from_arrays_and_compatibility() -> None:
    array = np.zeros((21, 128, 2), dtype=np.float32)
    dataset = HRTFDataset.from_arrays(array, 44_100)
    assert dataset.is_loaded
    assert dataset.hrir_len == 128
    assert dataset.directory is None
    assert dataset.name == "in-memory"

    same_shape = HRTFDataset.from_arrays(array.copy(), 44_100)
    assert dataset.is_compatible_with(same_shape)

    shorter = HRTFDataset.from_arrays(np.zeros((21, 64, 2), dtype=np.float32), 44_100)
    assert not dataset.is_compatible_with(shorter)

    with pytest.raises(DatasetError):
        HRTFDataset.from_arrays(np.zeros((20, 128, 2), dtype=np.float32), 44_100)
    with pytest.raises(DatasetError):
        HRTFDataset.from_arrays(np.zeros((21, 128, 3), dtype=np.float32), 44_100)


def test_unloaded_dataset_cannot_be_required() -> None:
    with pytest.raises(DatasetError, match="読み込まれていません"):
        HRTFDataset(".").require_loaded()
