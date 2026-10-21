from __future__ import annotations

from pathlib import Path

import pytest

from spatializer.config import (
    DATASET_ENV_VAR,
    AppConfig,
    ConfigError,
    default_dataset_root,
    resolve_dataset_root,
    validate_block_size,
)


def test_validate_block_size() -> None:
    assert validate_block_size(256) == 256
    assert validate_block_size("512") == 512

    with pytest.raises(ConfigError):
        validate_block_size(123)
    with pytest.raises(ConfigError):
        validate_block_size("nope")


def test_resolve_dataset_root_relative(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()

    assert resolve_dataset_root("data") == (tmp_path / "data").resolve()
    assert resolve_dataset_root(tmp_path / "data") == (tmp_path / "data").resolve()


def test_dataset_root_from_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_path = tmp_path / "from-env"
    monkeypatch.setenv(DATASET_ENV_VAR, str(env_path))

    assert default_dataset_root() == env_path.resolve()
    assert resolve_dataset_root(None) == env_path.resolve()


def test_app_config_latency_and_validation(tmp_path: Path) -> None:
    config = AppConfig(dataset_root=tmp_path, block_size=512)

    assert config.latency_ms == pytest.approx(512 / 44_100 * 1000)
    assert config.dataset_root == tmp_path.resolve()

    with pytest.raises(ConfigError):
        AppConfig(dataset_root=tmp_path, block_size=999)
    with pytest.raises(ConfigError):
        AppConfig(dataset_root=tmp_path, sample_rate=0)
