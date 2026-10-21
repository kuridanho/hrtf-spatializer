"""HRTF dataset loading and validation.

A dataset is a directory containing one stereo WAV file per measured
direction.  The 21 filenames and their stereo pan coefficients are defined in
:data:`POSITIONS`; the file format is documented in the README.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)


class DatasetError(RuntimeError):
    """Raised when an HRTF dataset is missing, incomplete, or malformed."""


@dataclass(frozen=True, slots=True)
class HRIRPosition:
    """One measured direction and how it is fed from the stereo input."""

    stem: str
    label: str
    left_gain: float
    right_gain: float


#: Directions measured by the original dataset.  ``stem`` is the WAV basename,
#: ``left_gain`` / ``right_gain`` distribute the two input channels across the
#: 21 directions before HRTF convolution.
POSITIONS: tuple[HRIRPosition, ...] = (
    HRIRPosition("100_0", "L100", 1.00, 0.00),
    HRIRPosition("0_100", "R100", 0.00, 1.00),
    HRIRPosition("10_0", "L10", 0.55, 0.45),
    HRIRPosition("0_10", "R10", 0.45, 0.55),
    HRIRPosition("20_0", "L20", 0.60, 0.40),
    HRIRPosition("0_20", "R20", 0.40, 0.60),
    HRIRPosition("30_0", "L30", 0.65, 0.35),
    HRIRPosition("0_30", "R30", 0.35, 0.65),
    HRIRPosition("40_0", "L40", 0.70, 0.30),
    HRIRPosition("0_40", "R40", 0.30, 0.70),
    HRIRPosition("50_0", "L50", 0.75, 0.25),
    HRIRPosition("0_50", "R50", 0.25, 0.75),
    HRIRPosition("60_0", "L60", 0.80, 0.20),
    HRIRPosition("0_60", "R60", 0.20, 0.80),
    HRIRPosition("70_0", "L70", 0.85, 0.15),
    HRIRPosition("0_70", "R70", 0.15, 0.85),
    HRIRPosition("80_0", "L80", 0.90, 0.10),
    HRIRPosition("0_80", "R80", 0.10, 0.90),
    HRIRPosition("90_0", "L90", 0.95, 0.05),
    HRIRPosition("0_90", "R90", 0.05, 0.95),
    HRIRPosition("0_0", "Center", 0.50, 0.50),
)


def _is_dataset_dir(path: Path) -> bool:
    """A directory is a dataset when all 21 primary WAV files exist."""
    try:
        return path.is_dir() and all(
            (path / f"{position.stem}.wav").is_file() for position in POSITIONS
        )
    except OSError:
        return False


def scan_datasets(root: str | Path) -> list[Path]:
    """Find dataset directories under *root*.

    *root* itself may be a dataset.  Otherwise each immediate child directory
    containing all 21 WAV files is returned, sorted by name.
    """
    base = Path(root).expanduser()
    if not base.is_dir():
        return []

    base = base.resolve()
    if _is_dataset_dir(base):
        return [base]

    try:
        children = sorted(path for path in base.iterdir() if path.is_dir())
    except OSError:
        return []

    return [path.resolve() for path in children if _is_dataset_dir(path)]


class HRTFDataset:
    """In-memory representation of one HRTF dataset."""

    def __init__(
        self,
        directory: str | Path | None,
        *,
        average_takes: bool = True,
        positions: tuple[HRIRPosition, ...] = POSITIONS,
    ) -> None:
        self.directory: Path | None = (
            Path(directory).expanduser().resolve() if directory is not None else None
        )
        self.average_takes = average_takes
        self.positions = tuple(positions)
        if not self.positions:
            raise DatasetError("方向定義が空です")

        self.hrirs: np.ndarray = np.empty((0, 0, 2), dtype=np.float32)
        self.sample_rate: int = 0
        self._loaded = False

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_arrays(
        cls,
        hrirs: np.ndarray,
        sample_rate: int,
        *,
        positions: tuple[HRIRPosition, ...] = POSITIONS,
        directory: str | Path | None = None,
    ) -> HRTFDataset:
        """Build a dataset from an existing ``(directions, length, 2)`` array."""
        array = np.asarray(hrirs, dtype=np.float32)
        if array.ndim != 3 or array.shape[2] != 2:
            raise DatasetError(
                f"HRIR 配列は (方向数, 長さ, 2ch) である必要があります: shape={array.shape}"
            )
        if array.shape[0] != len(positions):
            raise DatasetError(
                f"方向数が一致しません: 配列={array.shape[0]}, 定義={len(positions)}"
            )
        if array.shape[1] == 0:
            raise DatasetError("HRIR の長さが 0 です")
        if not np.all(np.isfinite(array)):
            raise DatasetError("HRIR に NaN / Inf が含まれています")
        if int(sample_rate) <= 0:
            raise DatasetError(f"サンプルレートが不正です: {sample_rate}")

        dataset = cls(directory, positions=positions)
        dataset.hrirs = np.ascontiguousarray(array)
        dataset.sample_rate = int(sample_rate)
        dataset._loaded = True
        return dataset

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self) -> HRTFDataset:
        """Read and validate every WAV file, returning ``self`` for chaining."""
        if self.directory is None:
            raise DatasetError("ディレクトリが指定されていないため読み込めません")
        if not self.directory.is_dir():
            raise DatasetError(f"HRTF データセットのディレクトリがありません: {self.directory}")

        missing = [
            f"{position.stem}.wav"
            for position in self.positions
            if not (self.directory / f"{position.stem}.wav").is_file()
        ]
        if missing:
            raise DatasetError(
                f"HRTF データセットが不完全です: {self.directory}\n"
                f"不足しているファイル: {', '.join(missing)}"
            )

        loaded: list[np.ndarray] = []
        sample_rate: int | None = None
        length: int | None = None

        for position in self.positions:
            primary = self.directory / f"{position.stem}.wav"
            data, rate = self._read_wav(primary)

            alternate = self.directory / f"{position.stem}(2).wav"
            if self.average_takes and alternate.is_file():
                second, second_rate = self._read_wav(alternate)
                if second_rate != rate:
                    raise DatasetError(
                        f"テイク間でサンプルレートが異なります: {primary.name}={rate}, "
                        f"{alternate.name}={second_rate}"
                    )
                if second.shape != data.shape:
                    raise DatasetError(
                        f"テイク間で HRIR の長さが異なります: {primary.name}, {alternate.name}"
                    )
                data = (data + second) * 0.5
                logger.info("Averaged take: %s", alternate.name)

            if sample_rate is None:
                sample_rate = rate
            elif rate != sample_rate:
                raise DatasetError(
                    f"データセット内でサンプルレートが異なります: {sample_rate} と {rate} "
                    f"({primary.name})"
                )

            if length is None:
                length = data.shape[0]
            elif data.shape[0] != length:
                raise DatasetError(
                    f"データセット内で HRIR の長さが異なります: {length} と "
                    f"{data.shape[0]} ({primary.name})"
                )

            loaded.append(data)

        self.hrirs = np.ascontiguousarray(np.stack(loaded), dtype=np.float32)
        self.sample_rate = int(sample_rate or 0)
        self._loaded = True
        logger.info(
            "Loaded HRTF dataset %s: %d directions, %d samples, %d Hz",
            self.name,
            self.num_positions,
            self.hrir_len,
            self.sample_rate,
        )
        return self

    def _read_wav(self, path: Path) -> tuple[np.ndarray, int]:
        try:
            data, rate = sf.read(str(path), dtype="float32", always_2d=True)
        except Exception as exc:  # soundfile raises several backend-specific errors
            raise DatasetError(f"HRIR を読み込めません: {path} ({exc})") from exc

        if data.shape[1] != 2:
            raise DatasetError(
                f"HRIR は 2ch ステレオである必要があります: {path} ({data.shape[1]}ch)"
            )
        if data.shape[0] == 0:
            raise DatasetError(f"HRIR が空です: {path}")
        if not np.all(np.isfinite(data)):
            raise DatasetError(f"HRIR に NaN / Inf が含まれています: {path}")
        return np.ascontiguousarray(data), int(rate)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def num_positions(self) -> int:
        return len(self.positions)

    @property
    def hrir_len(self) -> int:
        return int(self.hrirs.shape[1]) if self._loaded else 0

    @property
    def name(self) -> str:
        return self.directory.name if self.directory is not None else "in-memory"

    @property
    def pan_coefs(self) -> np.ndarray:
        """``(directions, 2)`` matrix mapping input L/R to each direction."""
        return np.asarray(
            [(position.left_gain, position.right_gain) for position in self.positions],
            dtype=np.float32,
        )

    def is_compatible_with(self, other: HRTFDataset) -> bool:
        """Whether *other* can be hot-swapped into a running spatializer."""
        return self.num_positions == other.num_positions and self.hrir_len == other.hrir_len

    def require_loaded(self) -> None:
        if not self._loaded or self.hrir_len == 0:
            raise DatasetError(f"HRTF データセットが読み込まれていません: {self.name}")

    @staticmethod
    def scan_datasets(root: str | Path) -> list[Path]:
        """Backward-compatible wrapper around :func:`scan_datasets`."""
        return scan_datasets(root)
