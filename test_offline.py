"""
Offline correctness test for VectorizedSpatializer.

Reads a short WAV file, processes it block by block through the UPOLS
engine, writes the binaural output to a WAV file, and benchmarks the
per-block processing time.

Usage:
    cd spatializer_app
    python test_offline.py
"""

import sys
import time
import os

import numpy as np
import soundfile as sf

# Allow running from the spatializer_app directory or from Spatializer/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spatializer_app.engine.hrtf_loader import HRTFDataset
from spatializer_app.engine.upols import VectorizedSpatializer

DATASET_DIR = os.path.join(
    os.path.dirname(__file__), "..", "dataset", "home_impulse_bedroom_441_6"
)
INPUT_WAV = os.path.join(os.path.dirname(__file__), "..", "music_data", "abc.wav")
OUTPUT_WAV = os.path.join(os.path.dirname(__file__), "test_output.wav")
BLOCK_SIZE = 512


def main() -> None:
    print("Loading HRTF dataset…")
    dataset = HRTFDataset(os.path.abspath(DATASET_DIR))
    dataset.load()
    print(f"  Loaded {len(dataset.hrirs)} HRIRs, "
          f"len={dataset.hrir_len}, sr={dataset.sample_rate}")

    print(f"Building filter banks (B={BLOCK_SIZE}, K={dataset.hrir_len // BLOCK_SIZE})…")
    t0 = time.perf_counter()
    spatializer = VectorizedSpatializer(dataset, block_size=BLOCK_SIZE)
    build_ms = (time.perf_counter() - t0) * 1000
    print(f"  Filter bank built in {build_ms:.1f} ms")

    print(f"Reading input: {INPUT_WAV}")
    audio, sr = sf.read(INPUT_WAV, dtype="float32", always_2d=True)
    if sr != dataset.sample_rate:
        print(f"  WARNING: input sr={sr} != HRIR sr={dataset.sample_rate}")

    # Pad to multiple of BLOCK_SIZE
    n_blocks = (len(audio) + BLOCK_SIZE - 1) // BLOCK_SIZE
    padded_len = n_blocks * BLOCK_SIZE
    audio_padded = np.zeros((padded_len, 2), dtype=np.float32)
    audio_padded[: len(audio)] = audio[:, :2] if audio.shape[1] >= 2 else np.column_stack([audio[:, 0]] * 2)

    output = np.zeros((padded_len, 2), dtype=np.float32)
    block_times: list[float] = []

    print(f"Processing {n_blocks} blocks…")
    for i in range(n_blocks):
        block_in = audio_padded[i * BLOCK_SIZE : (i + 1) * BLOCK_SIZE]
        t0 = time.perf_counter()
        block_out = spatializer.process_block(block_in)
        block_times.append((time.perf_counter() - t0) * 1000)
        output[i * BLOCK_SIZE : (i + 1) * BLOCK_SIZE] = block_out

    # Trim back to original length
    output = output[: len(audio)]

    budget_ms = BLOCK_SIZE / dataset.sample_rate * 1000
    mean_ms = np.mean(block_times[1:])   # skip first (JIT warm-up)
    max_ms = np.max(block_times[1:])
    print(f"\nBlock size: {BLOCK_SIZE} samples = {budget_ms:.2f} ms budget")
    print(f"Avg process_block(): {mean_ms:.3f} ms  ({mean_ms/budget_ms*100:.1f}% of budget)")
    print(f"Max process_block(): {max_ms:.3f} ms  ({max_ms/budget_ms*100:.1f}% of budget)")

    # Normalize to prevent clipping
    peak = np.max(np.abs(output))
    if peak > 1.0:
        output /= peak
        print(f"Normalized output by {peak:.3f}")

    sf.write(OUTPUT_WAV, output, dataset.sample_rate)
    print(f"\nOutput written to: {OUTPUT_WAV}")
    print("Listen to test_output.wav to verify spatial effect.")
    print("Tip: toggle between original and processed to hear the HRTF difference.")

    if mean_ms > budget_ms * 0.8:
        print("\nWARNING: Processing is close to real-time budget. "
              "Consider increasing block size to 1024.")
    else:
        print("\nReal-time processing is feasible on this machine.")


if __name__ == "__main__":
    main()
