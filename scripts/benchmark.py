#!/usr/bin/env python3
"""Offline HRTF processing benchmark.

Processes a WAV file (or a generated stereo test tone) through the same
block-based UPOLS engine used in real time, reports the per-block timing, and
optionally writes the binaural result.

Usage::

    python scripts/benchmark.py --dataset-dir dataset/demo --input music.wav
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spatializer.config import DEFAULT_BLOCK_SIZE, SUPPORTED_BLOCK_SIZES  # noqa: E402
from spatializer.engine.hrtf import HRTFDataset, scan_datasets  # noqa: E402
from spatializer.engine.upols import UPOLSSpatializer  # noqa: E402


def _resolve_dataset(path: Path) -> HRTFDataset:
    candidates = scan_datasets(path)
    if not candidates:
        raise SystemExit(
            f"No HRTF dataset found under {path}. "
            "Generate one with scripts/generate_dummy_dataset.py."
        )
    dataset = HRTFDataset(candidates[0]).load()
    print(f"Dataset: {candidates[0]}  ({dataset.hrir_len} samples, {dataset.sample_rate} Hz)")
    return dataset


def _load_audio(path: Path | None, sample_rate: int, seconds: float) -> np.ndarray:
    if path is None:
        length = int(sample_rate * seconds)
        t = np.arange(length, dtype=np.float32) / sample_rate
        left = 0.2 * np.sin(2 * np.pi * 220.0 * t)
        right = 0.2 * np.sin(2 * np.pi * 330.0 * t)
        print(f"Input: generated {seconds:.1f}s stereo test tone")
        return np.column_stack([left, right]).astype(np.float32)

    audio, rate = sf.read(str(path), dtype="float32", always_2d=True)
    if rate != sample_rate:
        raise SystemExit(
            f"Input sample rate ({rate} Hz) does not match the dataset ({sample_rate} Hz)."
        )
    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
    elif audio.shape[1] > 2:
        audio = audio[:, :2]
    print(f"Input: {path}  ({len(audio) / rate:.1f}s)")
    return np.ascontiguousarray(audio, dtype=np.float32)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--input", type=Path, default=None, help="input WAV (2ch preferred)")
    parser.add_argument("--output", type=Path, default=None, help="write binaural WAV here")
    parser.add_argument(
        "--block-size",
        type=int,
        choices=SUPPORTED_BLOCK_SIZES,
        default=DEFAULT_BLOCK_SIZE,
    )
    parser.add_argument("--seconds", type=float, default=3.0, help="test tone length")
    args = parser.parse_args()

    dataset = _resolve_dataset(args.dataset_dir)
    audio = _load_audio(args.input, dataset.sample_rate, args.seconds)
    if len(audio) == 0:
        raise SystemExit("Input audio is empty.")

    started = time.perf_counter()
    spatializer = UPOLSSpatializer(dataset, block_size=args.block_size)
    build_ms = (time.perf_counter() - started) * 1000.0
    print(f"Engine: {spatializer!r}  (filter bank built in {build_ms:.1f} ms)")

    block = args.block_size
    num_blocks = (len(audio) + block - 1) // block
    padded = np.zeros((num_blocks * block, 2), dtype=np.float32)
    padded[: len(audio)] = audio
    output = np.empty_like(padded)
    timings = np.empty(num_blocks, dtype=np.float64)

    for index in range(num_blocks):
        chunk = padded[index * block : (index + 1) * block]
        begin = time.perf_counter()
        output[index * block : (index + 1) * block] = spatializer.process_block(chunk)
        timings[index] = (time.perf_counter() - begin) * 1000.0

    output = output[: len(audio)]
    budget_ms = block / dataset.sample_rate * 1000.0
    measured = timings[1:] if num_blocks > 1 else timings

    print(f"Block budget: {budget_ms:.2f} ms")
    print(
        f"Processing: mean={measured.mean():.3f} ms  "
        f"p95={np.percentile(measured, 95):.3f} ms  "
        f"max={measured.max():.3f} ms"
    )
    print(f"Real-time headroom: {budget_ms / measured.mean():.2f}x")

    if args.output is not None:
        peak = float(np.max(np.abs(output)))
        if peak > 1.0:
            output /= peak
            print(f"Normalized output by {peak:.3f}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        sf.write(args.output, output, dataset.sample_rate)
        print(f"Wrote {args.output}")

    if measured.mean() > budget_ms * 0.8:
        print(
            "WARNING: close to the real-time budget; try a larger block size or the Rust backend."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
