"""Application-wide constants and dataset-path resolution."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "Spatializer"
DEFAULT_SAMPLE_RATE = 44_100
DEFAULT_BLOCK_SIZE = 512
SUPPORTED_BLOCK_SIZES = (256, 512, 1024)

MIN_GAIN = 0.0
MAX_GAIN = 2.0
#: Upper end of the GUI volume slider (percent).
VOLUME_SLIDER_MAX = 150.0

DATASET_ENV_VAR = "SPATIALIZER_DATASET_DIR"


class ConfigError(ValueError):
    """Raised when application configuration is invalid."""


def repository_root() -> Path:
    """Return the checkout root when running from a source tree.

    Falls back to the site-packages parent when installed as a wheel; this is
    only used as a convenience default for the bundled ``dataset/`` folder.
    """
    return Path(__file__).resolve().parents[2]


def default_dataset_root() -> Path:
    """Resolve the dataset directory from the environment or conventional paths."""
    env_value = os.environ.get(DATASET_ENV_VAR)
    if env_value:
        return Path(env_value).expanduser().resolve()

    repo_dataset = repository_root() / "dataset"
    if repo_dataset.is_dir():
        return repo_dataset.resolve()

    return (Path.cwd() / "dataset").resolve()


def resolve_dataset_root(value: str | Path | None) -> Path:
    """Normalize a user-supplied dataset path.

    Relative paths are resolved against the current working directory.  The
    path is *not* required to exist: the dataset may be supplied later.
    """
    if value is None:
        return default_dataset_root()

    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def validate_block_size(block_size: int) -> int:
    """Return a validated block size or raise :class:`ConfigError`."""
    try:
        value = int(block_size)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"ブロックサイズが不正です: {block_size!r}") from exc

    if value not in SUPPORTED_BLOCK_SIZES:
        allowed = ", ".join(str(size) for size in SUPPORTED_BLOCK_SIZES)
        raise ConfigError(f"ブロックサイズは {allowed} のいずれかです: {value}")
    return value


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Immutable configuration shared by the CLI and GUI."""

    dataset_root: Path
    block_size: int = DEFAULT_BLOCK_SIZE
    sample_rate: int = DEFAULT_SAMPLE_RATE

    def __post_init__(self) -> None:
        object.__setattr__(self, "dataset_root", Path(self.dataset_root).expanduser().resolve())
        object.__setattr__(self, "block_size", validate_block_size(self.block_size))
        if self.sample_rate <= 0:
            raise ConfigError(f"サンプルレートが不正です: {self.sample_rate}")

    @property
    def latency_ms(self) -> float:
        """One-block latency in milliseconds (excluding device buffers)."""
        return self.block_size / self.sample_rate * 1000.0
