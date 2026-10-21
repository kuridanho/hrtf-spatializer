#!/usr/bin/env python3
"""Generate a synthetic 21-direction HRTF dataset for smoke testing.

The generated HRIRs are *not* real measurements.  They only provide
plausible interaural time/level differences so that the audio path and GUI
can be exercised before a real dataset is available.

Usage::

    python scripts/generate_dummy_dataset.py --out dataset/demo
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spatializer.engine.hrtf import POSITIONS  # noqa: E402

MAX_ITD_SECONDS = 0.00065  # ~0.65 ms at the extreme left/right


def _azimuth_degrees(stem: str) -> float:
    """Convert a dataset stem such as ``30_0`` / ``0_30`` to signed degrees.

    Negative values are to the left, positive to the right, matching the
    pan coefficients in :data:`spatializer.engine.hrtf.POSITIONS`.
    """
    left, right = stem.split("_")
    left_angle, right_angle = int(left), int(right)
    if left_angle:
        return float(-left_angle)
    if right_angle:
        return float(right_angle)
    return 0.0


def _windowed_sinc(length: int, delay: float, gain: float, half_width: int = 16) -> np.ndarray:
    """A short fractional-delay kernel at *delay* samples."""
    t = np.arange(length, dtype=np.float64) - delay
    window = np.where(np.abs(t) <= half_width, 0.5 + 0.5 * np.cos(np.pi * t / half_width), 0.0)
    return gain * np.sinc(t) * window


def _one_pole_lowpass(signal: np.ndarray, alpha: float) -> np.ndarray:
    """Causal one-pole low-pass, used to fake head-shadow darkening."""
    if alpha <= 0.0:
        return signal
    output = np.empty_like(signal)
    previous = 0.0
    for index, sample in enumerate(signal):
        previous = alpha * previous + (1.0 - alpha) * sample
        output[index] = previous
    return output


def make_hrir(azimuth: float, sample_rate: int, length: int) -> np.ndarray:
    """Build one stereo HRIR with ITD, ILD and a little head shadow."""
    lateral = np.sin(np.radians(azimuth))  # -1 = left, +1 = right
    max_itd = MAX_ITD_SECONDS * sample_rate

    left_delay = max(0.0, lateral) * max_itd
    right_delay = max(0.0, -lateral) * max_itd

    left_gain = 1.0 - 0.35 * max(0.0, lateral)
    right_gain = 1.0 - 0.35 * max(0.0, -lateral)

    left = _windowed_sinc(length, left_delay, left_gain)
    right = _windowed_sinc(length, right_delay, right_gain)

    left = _one_pole_lowpass(left, 0.65 * max(0.0, lateral))
    right = _one_pole_lowpass(right, 0.65 * max(0.0, -lateral))

    hrir = np.column_stack([left, right]).astype(np.float32)
    peak = float(np.max(np.abs(hrir)))
    if peak > 0:
        hrir *= 0.9 / peak
    return hrir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("dataset/demo"),
        help="output dataset directory (default: dataset/demo)",
    )
    parser.add_argument("--length", type=int, default=4096, help="HRIR length in samples")
    parser.add_argument("--sample-rate", type=int, default=44_100)
    args = parser.parse_args()

    if args.length <= 0:
        parser.error("--length must be positive")

    args.out.mkdir(parents=True, exist_ok=True)
    for position in POSITIONS:
        hrir = make_hrir(_azimuth_degrees(position.stem), args.sample_rate, args.length)
        sf.write(args.out / f"{position.stem}.wav", hrir, args.sample_rate, subtype="FLOAT")

    print(f"Wrote {len(POSITIONS)} synthetic HRIRs to {args.out.resolve()}")
    print("This dataset is for smoke testing only; replace it with real measurements.")
    print(f"Run: spatializer --dataset-dir {args.out.parent.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
