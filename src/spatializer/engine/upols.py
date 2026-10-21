"""Uniform Partitioned Overlap-Save (UPOLS) HRTF convolution.

The spatializer convolves the stereo input with all 21 measured HRIRs at once.
The input channels are first distributed across the directions using the
dataset's pan coefficients, then each direction is filtered by its own HRIR,
and the left/right ear outputs are averaged across directions.

Two implementations of the frequency-domain matrix-vector product are
available:

* ``upols_core`` — an optional Rust/PyO3 extension (rayon-parallel).
* NumPy ``einsum`` — the always-available fallback.
"""

from __future__ import annotations

import importlib
import logging

import numpy as np

from .hrtf import DatasetError, HRTFDataset

logger = logging.getLogger(__name__)


def _load_accelerator():
    """Import the optional native extension, if it has been built."""
    for module_name in ("spatializer._upols_core", "upols_core"):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        logger.info("UPOLS accelerator enabled: %s", module_name)
        return module
    logger.info("UPOLS accelerator not available; using the NumPy fallback")
    return None


_ACCELERATOR = _load_accelerator()

#: Kept as a module-level flag for callers that want to report the backend.
RUST_AVAILABLE = _ACCELERATOR is not None


class UPOLSSpatializer:
    """Real-time 21-direction HRTF convolver.

    Parameters
    ----------
    dataset:
        A loaded :class:`~spatializer.engine.hrtf.HRTFDataset`.
    block_size:
        Number of samples processed per :meth:`process_block` call.  Must be
        positive.  The HRIR is zero-padded to a whole number of blocks.

    Notes
    -----
    :meth:`update_dataset` may be called from a background thread.  The new
    filter bank is swapped at the beginning of the next block; the swap is a
    single attribute assignment and therefore atomic under the GIL.
    """

    def __init__(self, dataset: HRTFDataset, block_size: int = 512) -> None:
        if not isinstance(block_size, int) or block_size <= 0:
            raise ValueError(f"block_size は正の整数である必要があります: {block_size!r}")
        dataset.require_loaded()

        self.block_size = block_size
        self.sample_rate = dataset.sample_rate
        self.num_positions = dataset.num_positions
        self.num_partitions = max(1, (dataset.hrir_len + block_size - 1) // block_size)

        self._pan_coefs = np.ascontiguousarray(dataset.pan_coefs, dtype=np.float32)  # (S, 2)
        self._H, self._H_t = self._build_filter_bank(dataset)
        self._pending: tuple[np.ndarray, np.ndarray] | None = None

        block = self.block_size
        partitions = self.num_partitions
        self._mixes = np.empty((block, self.num_positions), dtype=np.float32)
        self._overlap = np.zeros((self.num_positions, 2 * block), dtype=np.float32)
        self._fd_buf = np.zeros((self.num_positions, partitions, block + 1), dtype=np.complex64)
        self._fd_work = np.zeros_like(self._fd_buf)
        self._head = 0
        self._k_indices = np.arange(partitions, dtype=np.intp)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def backend(self) -> str:
        return "rust" if _ACCELERATOR is not None else "numpy"

    @property
    def latency_ms(self) -> float:
        """Algorithmic latency of one block in milliseconds."""
        return self.block_size / self.sample_rate * 1000.0

    def process_block(self, indata: np.ndarray) -> np.ndarray:
        """Filter one block of stereo audio.

        Parameters
        ----------
        indata:
            ``(block_size, 2)`` float array.

        Returns
        -------
        ``(block_size, 2)`` float32 binaural output.
        """
        if self._pending is not None:
            pending, self._pending = self._pending, None
            self._H, self._H_t = pending

        x = np.asarray(indata, dtype=np.float32)
        block = self.block_size
        if x.ndim != 2 or x.shape != (block, 2):
            raise ValueError(f"入力は ({block}, 2) である必要があります: shape={x.shape}")

        # 1. Distribute the stereo input across all measured directions.
        np.matmul(x, self._pan_coefs.T, out=self._mixes)

        # 2. Slide the overlap-save window and append the new samples.
        self._overlap[:, :block] = self._overlap[:, block:]
        self._overlap[:, block:] = self._mixes.T

        # 3. Transform each direction's 2B window.
        spectrum = np.fft.rfft(self._overlap, axis=1).astype(np.complex64)

        # 4. Store it in the circular frequency-domain history.
        self._fd_buf[:, self._head, :] = spectrum

        # 5. Gather history and multiply-accumulate the filter partitions.
        if _ACCELERATOR is not None:
            y_freq = _ACCELERATOR.gather_and_matvec(self._fd_buf, self._H_t, self._head)
        else:
            indices = (self._head - self._k_indices + self.num_partitions) % self.num_partitions
            np.take(self._fd_buf, indices, axis=1, out=self._fd_work)
            y_freq = np.einsum("skb,sekb->seb", self._fd_work, self._H)

        # 6. Back to time domain and keep the valid (second) half.
        y_time = np.fft.irfft(y_freq, n=2 * block, axis=2)

        # 7. Average the 21 directions into a stereo binaural signal.
        out = y_time[:, :, block:].mean(axis=0).T

        self._head = (self._head + 1) % self.num_partitions
        return np.ascontiguousarray(out, dtype=np.float32)

    def process(self, audio: np.ndarray) -> np.ndarray:
        """Convenience wrapper that filters a whole ``(samples, 2)`` array."""
        samples = np.asarray(audio, dtype=np.float32)
        if samples.ndim != 2 or samples.shape[1] != 2:
            raise ValueError(f"入力は (サンプル数, 2) である必要があります: shape={samples.shape}")
        if len(samples) == 0:
            return samples.copy()

        padded_length = ((len(samples) + self.block_size - 1) // self.block_size) * self.block_size
        padded = np.zeros((padded_length, 2), dtype=np.float32)
        padded[: len(samples)] = samples

        output = np.empty_like(padded)
        for start in range(0, padded_length, self.block_size):
            output[start : start + self.block_size] = self.process_block(
                padded[start : start + self.block_size]
            )
        return output[: len(samples)]

    def update_dataset(self, dataset: HRTFDataset) -> None:
        """Schedule a new filter bank for the next block.

        The replacement must have the same number of directions and the same
        HRIR length, because the internal buffers are pre-allocated.  To use a
        structurally different dataset, restart the stream.
        """
        dataset.require_loaded()
        new_partitions = max(1, (dataset.hrir_len + self.block_size - 1) // self.block_size)
        if dataset.num_positions != self.num_positions or new_partitions != self.num_partitions:
            raise DatasetError(
                "実行中に切り替えるには、方向数と HRIR 長が同じデータセットが必要です: "
                f"現在={self.num_positions}方向 / {self.num_partitions * self.block_size}サンプル, "
                f"新規={dataset.num_positions}方向 / {dataset.hrir_len}サンプル"
            )
        if dataset.sample_rate != self.sample_rate:
            raise DatasetError(
                "実行中に切り替えるには、同じサンプルレートのデータセットが必要です: "
                f"現在={self.sample_rate}Hz, 新規={dataset.sample_rate}Hz"
            )

        self._pending = self._build_filter_bank(dataset)

    def reset(self) -> None:
        """Clear overlap and history buffers (call after a stream restart)."""
        self._overlap[:] = 0.0
        self._fd_buf[:] = 0.0
        self._fd_work[:] = 0.0
        self._head = 0

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_filter_bank(self, dataset: HRTFDataset) -> tuple[np.ndarray, np.ndarray]:
        """Return pre-transposed frequency-domain HRIR partitions.

        ``H`` has shape ``(directions, 2, K, B+1)`` (NumPy layout) and ``H_t``
        has shape ``(directions, B+1, 2, K)`` (Rust layout).
        """
        dataset.require_loaded()
        num_directions = dataset.num_positions
        block = self.block_size
        partitions = max(1, (dataset.hrir_len + block - 1) // block)
        padded_length = partitions * block

        hrirs = dataset.hrirs.astype(np.float32, copy=False)
        if hrirs.shape[1] != padded_length:
            padded_hrirs = np.zeros((num_directions, padded_length, 2), dtype=np.float32)
            padded_hrirs[:, : hrirs.shape[1], :] = hrirs
            hrirs = padded_hrirs

        partitioned = hrirs.reshape(num_directions, partitions, block, 2)

        # Zero-pad each B-sample partition to 2B for overlap-save.
        padded = np.zeros((num_directions, partitions, 2 * block, 2), dtype=np.float32)
        padded[:, :, :block, :] = partitioned

        raw = np.fft.rfft(padded, axis=2).astype(np.complex64)
        filt = np.ascontiguousarray(raw.transpose(0, 3, 1, 2))  # (S, 2, K, B+1)
        filt_t = np.ascontiguousarray(raw.transpose(0, 2, 3, 1))  # (S, B+1, 2, K)
        return filt, filt_t

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(directions={self.num_positions}, "
            f"block_size={self.block_size}, partitions={self.num_partitions}, "
            f"backend={self.backend!r})"
        )
