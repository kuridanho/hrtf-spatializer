from __future__ import annotations
import os
import numpy as np
import soundfile as sf

# (filename_stem, L_channel_coef, R_channel_coef)
# Order and coefficients replicate bedroom_20ch.py averaging formula.
# Bug in original (R90 loaded from 0_10.wav) is corrected here.
POSITION_MAP: list[tuple[str, float, float]] = [
    ("100_0", 1.00, 0.00),  # L100
    ("0_100", 0.00, 1.00),  # R100
    ("10_0",  0.55, 0.45),  # L10
    ("0_10",  0.45, 0.55),  # R10
    ("20_0",  0.60, 0.40),  # L20
    ("0_20",  0.40, 0.60),  # R20
    ("30_0",  0.65, 0.35),  # L30
    ("0_30",  0.35, 0.65),  # R30
    ("40_0",  0.70, 0.30),  # L40
    ("0_40",  0.30, 0.70),  # R40
    ("50_0",  0.75, 0.25),  # L50
    ("0_50",  0.25, 0.75),  # R50
    ("60_0",  0.80, 0.20),  # L60
    ("0_60",  0.20, 0.80),  # R60
    ("70_0",  0.85, 0.15),  # L70
    ("0_70",  0.15, 0.85),  # R70
    ("80_0",  0.90, 0.10),  # L80
    ("0_80",  0.10, 0.90),  # R80
    ("90_0",  0.95, 0.05),  # L90
    ("0_90",  0.05, 0.95),  # R90
    ("0_0",   0.50, 0.50),  # Center
]


class HRTFDataset:
    """Loads and manages HRIR measurements for one dataset directory."""

    def __init__(self, dataset_dir: str, average_takes: bool = True) -> None:
        self.dataset_dir = dataset_dir
        self.average_takes = average_takes
        self.hrirs: list[np.ndarray] = []       # each shape (hrir_len, 2), float64
        self.pan_coefs: np.ndarray = np.array(  # (21, 2)
            [[L, R] for _, L, R in POSITION_MAP], dtype=np.float64
        )
        self.sample_rate: int = 44100
        self.hrir_len: int = 16384

    def load(self) -> None:
        self.hrirs = []
        for stem, _, _ in POSITION_MAP:
            path = os.path.join(self.dataset_dir, f"{stem}.wav")
            hrir, sr = sf.read(path, dtype="float64")

            alt = os.path.join(self.dataset_dir, f"{stem}(2).wav")
            if self.average_takes and os.path.exists(alt):
                hrir2, _ = sf.read(alt, dtype="float64")
                hrir = (hrir + hrir2) * 0.5

            self.hrirs.append(hrir)
            self.sample_rate = sr
            self.hrir_len = hrir.shape[0]

    def name(self) -> str:
        return os.path.basename(self.dataset_dir)

    @staticmethod
    def scan_datasets(base_dir: str) -> list[str]:
        """Return sorted list of home_impulse_* directories under base_dir."""
        results: list[str] = []
        try:
            for entry in sorted(os.listdir(base_dir)):
                full = os.path.join(base_dir, entry)
                if os.path.isdir(full) and "home_impulse" in entry:
                    results.append(full)
        except OSError:
            pass
        return results
