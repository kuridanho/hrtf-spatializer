/// upols_core — Rust extension for the UPOLS hot path
///
/// Exported function:
///   gather_and_matvec(fd_buf, h_t, buf_head) -> Y
///
/// Fuses the "gather input history" and "frequency-domain matrix-vector
/// product" steps into one pass, eliminating the intermediate fd_work array.
///
/// Math (per-block):
///   Y[s, e, b] = Σ_{k=0}^{K-1}  H_t[s, b, e, k]  ×  fd_buf[s, (head−k+K)%K, b]
///
/// where head is the slot that was just written (= partition 0 of the HRIR).
///
/// Array layouts (C / row-major):
///   fd_buf : (S, K,  B+1)    complex64   input  (circular ring buffer)
///   h_t    : (S, B+1, 2, K)  complex64   input  (HRIR filter bank, pre-transposed)
///   Y      : (S, 2,  B+1)    complex64   output
///
/// Parallelism: outer loop over S speakers uses rayon — each speaker is
/// independent, so no synchronisation needed.
use num_complex::Complex;
use numpy::{IntoPyArray, PyArray3, PyReadonlyArray3, PyReadonlyArray4};
use pyo3::prelude::*;
use rayon::prelude::*;

#[pyfunction]
fn gather_and_matvec<'py>(
    py: Python<'py>,
    fd_buf: PyReadonlyArray3<'_, Complex<f32>>,
    h_t: PyReadonlyArray4<'_, Complex<f32>>,
    buf_head: usize,
) -> PyResult<Bound<'py, PyArray3<Complex<f32>>>> {
    let fd = fd_buf.as_array();
    let h = h_t.as_array();

    let s_dim = fd.shape()[0]; // speakers
    let k_dim = fd.shape()[1]; // HRIR partitions
    let bh = fd.shape()[2];    // FFT bins (B+1)

    // Output: flat Vec in (S, 2, B+1) C-order
    let mut y_flat: Vec<Complex<f32>> = vec![Complex::new(0.0, 0.0); s_dim * 2 * bh];

    // Each speaker's output slice has 2*bh elements.
    y_flat
        .par_chunks_mut(2 * bh)
        .enumerate()
        .for_each(|(si, y_s)| {
            // y_s layout: [ear0_bin0, ear0_bin1, ..., ear1_bin0, ear1_bin1, ...]
            for bi in 0..bh {
                let mut acc0 = Complex::<f32>::new(0.0, 0.0);
                let mut acc1 = Complex::<f32>::new(0.0, 0.0);

                for ki in 0..k_dim {
                    // Gather: walk backwards through the circular ring buffer.
                    // slot (buf_head - ki + K) % K holds the input from ki blocks ago.
                    let src_k = (buf_head + k_dim - ki) % k_dim;
                    let x = fd[(si, src_k, bi)];

                    // Accumulate for each ear.
                    acc0 += h[(si, bi, 0, ki)] * x;
                    acc1 += h[(si, bi, 1, ki)] * x;
                }

                y_s[bi]       = acc0; // ear 0
                y_s[bh + bi]  = acc1; // ear 1
            }
        });

    // Wrap as ndarray then convert to numpy PyArray3
    let y_nd = ndarray::Array3::from_shape_vec((s_dim, 2, bh), y_flat)
        .expect("shape mismatch — this is a bug");

    Ok(y_nd.into_pyarray(py))
}

#[pymodule]
fn upols_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(gather_and_matvec, m)?)?;
    Ok(())
}
