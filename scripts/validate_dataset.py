#!/usr/bin/env python3
"""Validate one or more HRTF datasets without starting the GUI.

Usage::

    python scripts/validate_dataset.py dataset/my_room
    python scripts/validate_dataset.py dataset          # validate all children
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spatializer.engine.hrtf import DatasetError, HRTFDataset, scan_datasets  # noqa: E402


def validate(path: Path, *, average_takes: bool) -> bool:
    print(f"\n== {path} ==")
    try:
        dataset = HRTFDataset(path, average_takes=average_takes).load()
    except DatasetError as exc:
        print(f"  ERROR: {exc}")
        return False

    peak = float(np.max(np.abs(dataset.hrirs)))
    rms = float(np.sqrt(np.mean(np.square(dataset.hrirs))))
    print(f"  directions : {dataset.num_positions}")
    print(f"  length     : {dataset.hrir_len} samples")
    print(f"  sample rate: {dataset.sample_rate} Hz")
    print(f"  peak       : {peak:.4f}")
    print(f"  rms        : {rms:.6f}")

    ok = True
    if peak < 1e-6:
        print("  WARNING: dataset is silent")
        ok = False
    if dataset.hrir_len < dataset.sample_rate // 100:
        print("  WARNING: HRIR is shorter than 10 ms; low-frequency response may be poor")
    if dataset.sample_rate not in (44_100, 48_000):
        print(f"  WARNING: unusual sample rate {dataset.sample_rate} Hz")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="dataset directory or parent directory")
    parser.add_argument(
        "--no-average-takes",
        action="store_true",
        help="ignore optional (2).wav alternate takes",
    )
    args = parser.parse_args()

    datasets = scan_datasets(args.path)
    if not datasets:
        print(
            f"No complete dataset found under {args.path}. "
            "Expected 21 WAV files per dataset; see docs/dataset.md.",
            file=sys.stderr,
        )
        return 1

    results = [validate(path, average_takes=not args.no_average_takes) for path in datasets]
    failures = sum(not result for result in results)
    print(f"\n{len(results) - failures}/{len(results)} dataset(s) valid")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
