from __future__ import annotations
import numpy as np
from .hrtf_loader import HRTFDataset

# ── Rust extension (optional fast path) ────────────────────────────────────
# Built with maturin from engine/upols_core/.  Falls back to numpy if the
# .so is not present (e.g. after a clean checkout before `maturin develop`).
try:
    import upols_core as _rust  # type: ignore
    _RUST_AVAILABLE = True
except ModuleNotFoundError:
    _RUST_AVAILABLE = False


class VectorizedSpatializer:
    """
    Uniform Partitioned Overlap-Save (UPOLS) spatializer.

    Processes all 21 HRIR positions simultaneously.

    Hot path:
      - If the Rust extension is available (`upols_core`): gather + matvec
        are fused in one Rust/rayon call → ~10x faster than numpy einsum.
      - Otherwise: falls back to numpy einsum.

    All internal arrays use float32 / complex64 to halve memory bandwidth
    compared with the previous float64 implementation.

    Thread safety: update_dataset() may be called from a background thread.
    The CPython GIL makes a single attribute assignment atomic.
    """

    def __init__(self, dataset: HRTFDataset, block_size: int = 512) -> None:
        self.B = block_size
        self.S = len(dataset.hrirs)
        self.K = dataset.hrir_len // block_size  # partitions per HRIR

        self._pan_coefs = dataset.pan_coefs.astype(np.float32)  # (S, 2)
        self._H, self._H_t = self._build_filter_bank(dataset)
        # _H   : (S, 2, K, B+1) complex64  — numpy fallback layout
        # _H_t : (S, B+1, 2, K) complex64  — Rust layout (pre-transposed)
        self._pending: tuple[np.ndarray, np.ndarray] | None = None

        # Overlap-save input history per speaker: (S, 2B) float32
        self._overlap = np.zeros((self.S, 2 * self.B), dtype=np.float32)

        # Circular frequency-domain input history: (S, K, B+1) complex64
        self._fd_buf = np.zeros((self.S, self.K, self.B + 1), dtype=np.complex64)
        self._buf_head = 0
        self._k_indices = np.arange(self.K, dtype=np.intp)  # reused every block

        # numpy fallback only: fd_work scratch buffer
        self._fd_work = np.zeros((self.S, self.K, self.B + 1), dtype=np.complex64)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_dataset(self, dataset: HRTFDataset) -> None:
        """Schedule a filter-bank swap (safe to call from any thread)."""
        self._pending = self._build_filter_bank(dataset)

    def process_block(self, indata: np.ndarray) -> np.ndarray:
        """
        Apply HRTF to one audio block.

        Parameters
        ----------
        indata : (B, 2) float32
            Raw stereo input from sounddevice.

        Returns
        -------
        (B, 2) float32
            Binaural HRTF-processed output.
        """
        # Atomic filter-bank swap (CPython GIL guarantees atomicity)
        if self._pending is not None:
            self._H, self._H_t = self._pending
            self._pending = None

        x = indata  # already float32 from sounddevice

        # 1. Compute 21 pan mixes: (B, 2) @ (2, S) → (B, S) → (S, B) float32
        mixes = (x @ self._pan_coefs.T).T

        # 2. Shift overlap buffers and append new mixes
        self._overlap[:, : self.B] = self._overlap[:, self.B :]
        self._overlap[:, self.B :] = mixes

        # 3. rfft of each speaker's 2B overlap window → (S, B+1) complex64
        X = np.fft.rfft(self._overlap, axis=1).astype(np.complex64)

        # 4. Write to circular freq-domain buffer at current head
        self._fd_buf[:, self._buf_head, :] = X

        # 5 & 6. Gather history + multiply-accumulate → Y (S, 2, B+1)
        if _RUST_AVAILABLE:
            # Rust fuses steps 5 & 6 in one rayon-parallel pass
            Y = _rust.gather_and_matvec(self._fd_buf, self._H_t, self._buf_head)
        else:
            # numpy fallback: explicit gather then einsum
            idx = (self._buf_head - self._k_indices + self.K) % self.K
            np.copyto(self._fd_work, self._fd_buf[:, idx, :])
            Y = np.einsum("skb,sekb->seb", self._fd_work, self._H)

        # 7. irfft → (S, 2, 2B); take last B samples (overlap-save valid region)
        y_time = np.fft.irfft(Y, n=2 * self.B, axis=2)

        # 8. Average over 21 speakers → (2, B), then transpose → (B, 2)
        out = y_time[:, :, self.B :].mean(axis=0).T

        # 9. Advance circular buffer head
        self._buf_head = (self._buf_head + 1) % self.K

        return out.astype(np.float32)

    def reset(self) -> None:
        """Clear all internal state (call when stream restarts)."""
        self._overlap[:] = 0.0
        self._fd_buf[:] = 0.0
        self._fd_work[:] = 0.0
        self._buf_head = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_filter_bank(
        self, dataset: HRTFDataset
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Pre-compute FFTs of HRIR partitions for all speakers.

        Returns
        -------
        H   : (S, 2, K, B+1) complex64  — numpy einsum layout
        H_t : (S, B+1, 2, K) complex64  — Rust gather_and_matvec layout
        """
        S = len(dataset.hrirs)
        B = self.B
        K = dataset.hrir_len // B

        # Stack HRIRs: (S, hrir_len, 2) float32
        hrirs_arr = np.array(dataset.hrirs, dtype=np.float32)

        # Trim to K*B samples and reshape into partitions: (S, K, B, 2)
        hrirs_partitioned = hrirs_arr[:, : K * B, :].reshape(S, K, B, 2)

        # Zero-pad each partition to 2B: (S, K, 2B, 2)
        pad = np.zeros((S, K, B, 2), dtype=np.float32)
        padded = np.concatenate([hrirs_partitioned, pad], axis=2)

        # rfft along the 2B axis: (S, K, B+1, 2) complex64
        H_raw = np.fft.rfft(padded, axis=2).astype(np.complex64)

        # numpy layout: (S, 2, K, B+1)
        H = np.ascontiguousarray(H_raw.transpose(0, 3, 1, 2))

        # Rust layout: (S, B+1, 2, K)
        H_t = np.ascontiguousarray(H_raw.transpose(0, 2, 3, 1))

        return H, H_t
