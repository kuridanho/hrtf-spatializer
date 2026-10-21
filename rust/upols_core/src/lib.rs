//! `upols_core` — Rust extension for the Spatializer UPOLS hot path.
//!
//! The exported function fuses the "gather input history" and
//! "frequency-domain matrix-vector product" steps into a single pass:
//!
//! ```text
//! Y[s, e, b] = Σ_k H_t[s, b, e, k] × fd_buf[s, (head − k + K) % K, b]
//! ```
//!
//! Array layouts (C / row-major):
//!
//! ```text
//! fd_buf : (S, K,  B+1)    complex64   circular history buffer
//! h_t    : (S, B+1, 2, K)  complex64   pre-transposed HRIR filter bank
//! Y      : (S, 2,  B+1)    complex64   per-direction ear spectra
//! ```
//!
//! Parallelism: the outer loop over directions uses rayon.  Each direction
//! is independent, so no synchronization is required.

use num_complex::Complex;
use numpy::{IntoPyArray, PyArray3, PyReadonlyArray3, PyReadonlyArray4};
use pyo3::exceptions::PyValueError;
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

    let s_dim = fd.shape()[0];
    let k_dim = fd.shape()[1];
    let bins = fd.shape()[2];

    if k_dim == 0 {
        return Err(PyValueError::new_err("fd_buf has zero partitions"));
    }
    if h.shape() != [s_dim, bins, 2, k_dim] {
        return Err(PyValueError::new_err(format!(
            "h_t shape mismatch: expected ({s_dim}, {bins}, 2, {k_dim}), got {:?}",
            h.shape()
        )));
    }

    let head = buf_head % k_dim;
    let mut y_flat: Vec<Complex<f32>> = vec![Complex::new(0.0, 0.0); s_dim * 2 * bins];

    // Each direction's output slice has 2 * bins elements:
    // [ear0_bin0, ..., ear0_binN, ear1_bin0, ..., ear1_binN].
    y_flat
        .par_chunks_mut(2 * bins)
        .enumerate()
        .for_each(|(direction, y_s)| {
            for bin in 0..bins {
                let mut acc_left = Complex::<f32>::new(0.0, 0.0);
                let mut acc_right = Complex::<f32>::new(0.0, 0.0);

                for partition in 0..k_dim {
                    let source = (head + k_dim - partition) % k_dim;
                    let x = fd[(direction, source, bin)];
                    acc_left += h[(direction, bin, 0, partition)] * x;
                    acc_right += h[(direction, bin, 1, partition)] * x;
                }

                y_s[bin] = acc_left;
                y_s[bins + bin] = acc_right;
            }
        });

    let y_nd = ndarray::Array3::from_shape_vec((s_dim, 2, bins), y_flat)
        .map_err(|err| PyValueError::new_err(format!("output shape mismatch: {err}")))?;

    Ok(y_nd.into_pyarray(py))
}

#[pymodule]
fn upols_core(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(gather_and_matvec, module)?)?;
    module.add("__doc__", "Rust accelerator for the Spatializer UPOLS hot path")?;
    Ok(())
}
