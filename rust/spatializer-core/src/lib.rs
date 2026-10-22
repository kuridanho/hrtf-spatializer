//! Native real-time HRTF convolution core.
//!
//! This crate implements the same 21-direction UPOLS processing as the Python
//! package, but without NumPy or the GIL.  It is linked into the SwiftUI app
//! as a static library and called from the Core Audio IOProc.
//!
//! Layouts:
//!   hrirs:   (directions, hrir_length, 2) interleaved f32
//!   pan:     (directions, 2) f32
//!   input:   (frames, 2) interleaved f32
//!   output:  (frames, 2) interleaved f32

use num_complex::Complex32;
use rustfft::{Fft, FftPlanner};
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::Arc;

type C = Complex32;

pub struct SpatializerCore {
    directions: usize,
    block_size: usize,
    partitions: usize,
    bins: usize,
    fft_size: usize,
    sample_rate: u32,

    pan: Vec<f32>,             // S * 2
    filters: Vec<C>,           // S * 2 * K * bins
    fd_buf: Vec<C>,            // S * K * bins
    overlap: Vec<f32>,         // S * 2B
    mixes: Vec<f32>,           // S * B
    time: Vec<C>,              // fft_size scratch
    y_freq: Vec<C>,            // S * 2 * bins
    inverse: Vec<C>,           // fft_size scratch
    fallback_in: Vec<f32>,     // 2B
    fallback_out: Vec<f32>,    // 2B

    fft_forward: Arc<dyn Fft<f32>>,
    fft_inverse: Arc<dyn Fft<f32>>,

    head: usize,
    was_bypassed: bool,

    gain_bits: AtomicU32,
    bypass: AtomicBool,
    meter_left: AtomicU32,
    meter_right: AtomicU32,
}

impl SpatializerCore {
    pub fn new(
        hrirs: &[f32],
        pan: &[f32],
        directions: usize,
        hrir_length: usize,
        sample_rate: u32,
        block_size: usize,
    ) -> Option<Self> {
        if directions == 0
            || hrir_length == 0
            || sample_rate == 0
            || block_size < 8
            || hrirs.len() != directions * hrir_length * 2
            || pan.len() != directions * 2
        {
            return None;
        }

        let partitions = (hrir_length + block_size - 1) / block_size;
        let bins = block_size + 1;
        let fft_size = 2 * block_size;

        let mut planner = FftPlanner::<f32>::new();
        let fft_forward = planner.plan_fft_forward(fft_size);
        let fft_inverse = planner.plan_fft_inverse(fft_size);

        let mut core = Self {
            directions,
            block_size,
            partitions,
            bins,
            fft_size,
            sample_rate,
            pan: pan.to_vec(),
            filters: vec![C::new(0.0, 0.0); directions * 2 * partitions * bins],
            fd_buf: vec![C::new(0.0, 0.0); directions * partitions * bins],
            overlap: vec![0.0; directions * 2 * block_size],
            mixes: vec![0.0; directions * block_size],
            time: vec![C::new(0.0, 0.0); fft_size],
            y_freq: vec![C::new(0.0, 0.0); directions * 2 * bins],
            inverse: vec![C::new(0.0, 0.0); fft_size],
            fallback_in: vec![0.0; 2 * block_size],
            fallback_out: vec![0.0; 2 * block_size],
            fft_forward,
            fft_inverse,
            head: 0,
            was_bypassed: false,
            // 1.0f32.to_bits()
            gain_bits: AtomicU32::new(0x3f80_0000),
            bypass: AtomicBool::new(false),
            meter_left: AtomicU32::new(0),
            meter_right: AtomicU32::new(0),
        };

        core.build_filters(hrirs, hrir_length);
        Some(core)
    }

    fn build_filters(&mut self, hrirs: &[f32], hrir_length: usize) {
        for direction in 0..self.directions {
            for ear in 0..2 {
                for partition in 0..self.partitions {
                    self.time.fill(C::new(0.0, 0.0));
                    let base = partition * self.block_size;
                    for n in 0..self.block_size {
                        let index = base + n;
                        if index < hrir_length {
                            self.time[n].re =
                                hrirs[(direction * hrir_length + index) * 2 + ear];
                        }
                    }
                    self.fft_forward.process(&mut self.time);
                    for bin in 0..=self.block_size {
                        let target = Self::filter_index(
                            direction,
                            ear,
                            partition,
                            bin,
                            self.partitions,
                            self.bins,
                        );
                        self.filters[target] = self.time[bin];
                    }
                }
            }
        }
    }

    #[inline]
    fn filter_index(
        direction: usize,
        ear: usize,
        partition: usize,
        bin: usize,
        partitions: usize,
        bins: usize,
    ) -> usize {
        ((direction * 2 + ear) * partitions + partition) * bins + bin
    }

    #[inline]
    fn fd_index(direction: usize, slot: usize, bin: usize, partitions: usize, bins: usize) -> usize {
        (direction * partitions + slot) * bins + bin
    }

    #[inline]
    fn y_index(direction: usize, ear: usize, bin: usize, bins: usize) -> usize {
        (direction * 2 + ear) * bins + bin
    }

    pub fn process(&mut self, input: &[f32], output: &mut [f32], frames: usize) {
        let block = self.block_size;
        if frames == block {
            self.process_block(input, output);
            return;
        }

        // Core Audio should give us exactly block_size frames.  If it does
        // not, pad with silence and return the available part without
        // allocating in the audio callback.
        let count = frames.min(block);
        let mut input_buffer = std::mem::take(&mut self.fallback_in);
        let mut output_buffer = std::mem::take(&mut self.fallback_out);
        input_buffer.fill(0.0);
        output_buffer.fill(0.0);
        input_buffer[..count * 2].copy_from_slice(&input[..count * 2]);

        self.process_block(&input_buffer, &mut output_buffer);

        output[..count * 2].copy_from_slice(&output_buffer[..count * 2]);
        self.fallback_in = input_buffer;
        self.fallback_out = output_buffer;
    }

    fn process_block(&mut self, input: &[f32], output: &mut [f32]) {
        let block = self.block_size;
        let interleaved_len = block * 2;
        let gain = self.gain();

        let bypass = self.bypass.load(Ordering::Relaxed);
        if bypass {
            if !self.was_bypassed {
                self.reset_history();
                self.was_bypassed = true;
            }
            if gain == 1.0 {
                output[..interleaved_len].copy_from_slice(&input[..interleaved_len]);
            } else {
                for (dst, src) in output[..interleaved_len]
                    .iter_mut()
                    .zip(input[..interleaved_len].iter())
                {
                    *dst = *src * gain;
                }
            }
            self.update_meters(output);
            return;
        }

        if self.was_bypassed {
            self.reset_history();
            self.was_bypassed = false;
        }

        output[..interleaved_len].fill(0.0);

        // 1. Pan the stereo input across the measured directions and build
        //    each direction's overlap-save window.
        for direction in 0..self.directions {
            let left_gain = self.pan[direction * 2];
            let right_gain = self.pan[direction * 2 + 1];
            let mix_base = direction * block;
            for n in 0..block {
                self.mixes[mix_base + n] =
                    input[n * 2] * left_gain + input[n * 2 + 1] * right_gain;
            }

            let overlap_base = direction * 2 * block;
            self.overlap
                .copy_within(overlap_base + block..overlap_base + 2 * block, overlap_base);
            self.overlap[overlap_base + block..overlap_base + 2 * block]
                .copy_from_slice(&self.mixes[mix_base..mix_base + block]);

            self.time.fill(C::new(0.0, 0.0));
            for n in 0..2 * block {
                self.time[n].re = self.overlap[overlap_base + n];
            }
            self.fft_forward.process(&mut self.time);

            for bin in 0..=block {
                let target = Self::fd_index(
                    direction,
                    self.head,
                    bin,
                    self.partitions,
                    self.bins,
                );
                self.fd_buf[target] = self.time[bin];
            }
        }

        // 2. Frequency-domain partitioned convolution for both ears.
        for direction in 0..self.directions {
            for ear in 0..2 {
                for bin in 0..=block {
                    let mut acc = C::new(0.0, 0.0);
                    for partition in 0..self.partitions {
                        let slot =
                            (self.head + self.partitions - partition) % self.partitions;
                        let x = self.fd_buf[Self::fd_index(
                            direction,
                            slot,
                            bin,
                            self.partitions,
                            self.bins,
                        )];
                        let h = self.filters[Self::filter_index(
                            direction,
                            ear,
                            partition,
                            bin,
                            self.partitions,
                            self.bins,
                        )];
                        acc += h * x;
                    }
                    self.y_freq[Self::y_index(direction, ear, bin, self.bins)] = acc;
                }
            }
        }

        // 3. Inverse transform per direction/ear, average directions and
        //    accumulate into the interleaved stereo output.
        let inverse_scale = 1.0 / (self.fft_size as f32 * self.directions as f32);
        for direction in 0..self.directions {
            for ear in 0..2 {
                self.inverse.fill(C::new(0.0, 0.0));
                for bin in 0..=block {
                    let value =
                        self.y_freq[Self::y_index(direction, ear, bin, self.bins)];
                    self.inverse[bin] = value;
                    if bin > 0 && bin < block {
                        self.inverse[self.fft_size - bin] = value.conj();
                    }
                }
                self.inverse[0].im = 0.0;
                self.inverse[block].im = 0.0;

                self.fft_inverse.process(&mut self.inverse);

                for n in 0..block {
                    output[n * 2 + ear] += self.inverse[block + n].re * inverse_scale;
                }
            }
        }

        if gain != 1.0 {
            for sample in output[..interleaved_len].iter_mut() {
                *sample *= gain;
            }
        }

        self.head = (self.head + 1) % self.partitions;
        self.update_meters(output);
    }

    fn reset_history(&mut self) {
        self.overlap.fill(0.0);
        self.fd_buf.fill(C::new(0.0, 0.0));
        self.head = 0;
    }

    fn update_meters(&self, output: &[f32]) {
        let block = self.block_size;
        let mut left = 0.0f32;
        let mut right = 0.0f32;
        for n in 0..block {
            left += output[n * 2] * output[n * 2];
            right += output[n * 2 + 1] * output[n * 2 + 1];
        }
        let scale = 1.0 / block as f32;
        self.meter_left
            .store((left * scale).sqrt().to_bits(), Ordering::Relaxed);
        self.meter_right
            .store((right * scale).sqrt().to_bits(), Ordering::Relaxed);
    }

    #[inline]
    fn gain(&self) -> f32 {
        f32::from_bits(self.gain_bits.load(Ordering::Relaxed))
    }

    pub fn set_gain(&self, gain: f32) {
        let clamped = gain.clamp(0.0, 2.0);
        self.gain_bits.store(clamped.to_bits(), Ordering::Relaxed);
    }

    pub fn set_bypass(&self, bypass: bool) {
        self.bypass.store(bypass, Ordering::Relaxed);
    }

    pub fn meters(&self) -> (f32, f32) {
        (
            f32::from_bits(self.meter_left.load(Ordering::Relaxed)),
            f32::from_bits(self.meter_right.load(Ordering::Relaxed)),
        )
    }

    pub fn block_size(&self) -> usize {
        self.block_size
    }

    pub fn partitions(&self) -> usize {
        self.partitions
    }

    pub fn sample_rate(&self) -> u32 {
        self.sample_rate
    }
}

// ---------------------------------------------------------------------------
// C ABI (linked into the Swift app)
// ---------------------------------------------------------------------------

#[no_mangle]
pub unsafe extern "C" fn spatializer_core_create(
    hrirs: *const f32,
    pan_coefs: *const f32,
    directions: i32,
    hrir_length: i32,
    sample_rate: i32,
    block_size: i32,
) -> *mut SpatializerCore {
    if hrirs.is_null() || pan_coefs.is_null() {
        return std::ptr::null_mut();
    }
    if directions <= 0 || hrir_length <= 0 || sample_rate <= 0 || block_size < 8 {
        return std::ptr::null_mut();
    }

    let directions = directions as usize;
    let hrir_length = hrir_length as usize;
    let hrirs = std::slice::from_raw_parts(hrirs, directions * hrir_length * 2);
    let pan = std::slice::from_raw_parts(pan_coefs, directions * 2);

    match SpatializerCore::new(
        hrirs,
        pan,
        directions,
        hrir_length,
        sample_rate as u32,
        block_size as usize,
    ) {
        Some(core) => Box::into_raw(Box::new(core)),
        None => std::ptr::null_mut(),
    }
}

#[no_mangle]
pub unsafe extern "C" fn spatializer_core_destroy(core: *mut SpatializerCore) {
    if !core.is_null() {
        drop(Box::from_raw(core));
    }
}

#[no_mangle]
pub unsafe extern "C" fn spatializer_core_process(
    core: *mut SpatializerCore,
    input: *const f32,
    output: *mut f32,
    frames: i32,
) {
    if core.is_null() || input.is_null() || output.is_null() || frames < 0 {
        return;
    }
    let core = &mut *core;
    let frames = frames as usize;
    let input = std::slice::from_raw_parts(input, frames * 2);
    let output = std::slice::from_raw_parts_mut(output, frames * 2);
    core.process(input, output, frames);
}

#[no_mangle]
pub unsafe extern "C" fn spatializer_core_set_gain(core: *mut SpatializerCore, gain: f32) {
    if let Some(core) = core.as_ref() {
        core.set_gain(gain);
    }
}

#[no_mangle]
pub unsafe extern "C" fn spatializer_core_set_bypass(core: *mut SpatializerCore, bypass: bool) {
    if let Some(core) = core.as_ref() {
        core.set_bypass(bypass);
    }
}

#[no_mangle]
pub unsafe extern "C" fn spatializer_core_get_meters(
    core: *mut SpatializerCore,
    left: *mut f32,
    right: *mut f32,
) {
    if core.is_null() || left.is_null() || right.is_null() {
        return;
    }
    let (l, r) = (*core).meters();
    *left = l;
    *right = r;
}

#[no_mangle]
pub unsafe extern "C" fn spatializer_core_block_size(core: *const SpatializerCore) -> i32 {
    core.as_ref().map(|core| core.block_size() as i32).unwrap_or(0)
}

#[no_mangle]
pub unsafe extern "C" fn spatializer_core_partitions(core: *const SpatializerCore) -> i32 {
    core.as_ref().map(|core| core.partitions() as i32).unwrap_or(0)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE_RATE: u32 = 48_000;

    fn reference(
        input: &[f32],
        hrirs: &[f32],
        pan: &[f32],
        directions: usize,
        hrir_length: usize,
    ) -> Vec<f32> {
        let frames = input.len() / 2;
        let mut out = vec![0.0f64; frames * 2];

        for direction in 0..directions {
            let left_gain = pan[direction * 2] as f64;
            let right_gain = pan[direction * 2 + 1] as f64;
            let mut mix = vec![0.0f64; frames];
            for n in 0..frames {
                mix[n] = input[n * 2] as f64 * left_gain
                    + input[n * 2 + 1] as f64 * right_gain;
            }

            for ear in 0..2 {
                for n in 0..frames {
                    let mut acc = 0.0f64;
                    for k in 0..hrir_length {
                        if n >= k {
                            let h = hrirs[(direction * hrir_length + k) * 2 + ear] as f64;
                            acc += h * mix[n - k];
                        }
                    }
                    out[n * 2 + ear] += acc / directions as f64;
                }
            }
        }

        out.iter().map(|v| *v as f32).collect()
    }

    fn test_data() -> (Vec<f32>, Vec<f32>, Vec<f32>) {
        let directions = 2usize;
        let length = 8usize;
        let mut hrirs = vec![0.0f32; directions * length * 2];
        // Left-facing direction: left ear early, right ear delayed.
        hrirs[(0 * length + 0) * 2 + 0] = 1.0;
        hrirs[(0 * length + 2) * 2 + 1] = 0.7;
        // Right-facing direction.
        hrirs[(1 * length + 1) * 2 + 0] = 0.6;
        hrirs[(1 * length + 0) * 2 + 1] = 1.0;

        let pan = vec![1.0, 0.0, 0.0, 1.0];
        let input: Vec<f32> = (0..32)
            .map(|i| ((i as f32 * 0.37).sin() * 0.2) as f32)
            .collect();
        (hrirs, pan, input)
    }

    #[test]
    fn matches_direct_convolution() {
        let (hrirs, pan, input) = test_data();
        let mut core =
            SpatializerCore::new(&hrirs, &pan, 2, 8, SAMPLE_RATE, 8).expect("create");
        let mut output = vec![0.0f32; input.len()];

        for frame_start in (0..input.len() / 2).step_by(8) {
            core.process(
                &input[frame_start * 2..(frame_start + 8) * 2],
                &mut output[frame_start * 2..(frame_start + 8) * 2],
                8,
            );
        }

        let expected = reference(&input, &hrirs, &pan, 2, 8);
        for (actual, wanted) in output.iter().zip(expected.iter()) {
            assert!(
                (actual - wanted).abs() < 2e-4,
                "actual={actual}, expected={wanted}"
            );
        }
    }

    #[test]
    fn bypass_copies_input_and_applies_gain() {
        let (hrirs, pan, input) = test_data();
        let mut core =
            SpatializerCore::new(&hrirs, &pan, 2, 8, SAMPLE_RATE, 8).expect("create");
        core.set_bypass(true);
        core.set_gain(0.5);

        let mut output = vec![0.0f32; 16];
        core.process(&input[..16], &mut output, 8);

        for (actual, wanted) in output.iter().zip(input[..16].iter()) {
            assert!((actual - wanted * 0.5).abs() < 1e-6);
        }
    }

    #[test]
    fn invalid_arguments_return_none() {
        assert!(SpatializerCore::new(&[], &[], 0, 0, 0, 0).is_none());
        let (hrirs, pan, _) = test_data();
        assert!(SpatializerCore::new(&hrirs, &pan, 2, 8, SAMPLE_RATE, 4).is_none());
    }

    #[test]
    fn block_partition_count() {
        let (hrirs, pan, _) = test_data();
        let core =
            SpatializerCore::new(&hrirs, &pan, 2, 8, SAMPLE_RATE, 8).expect("create");
        assert_eq!(core.partitions(), 1);
        assert_eq!(core.block_size(), 8);
    }

    #[test]
    fn impulse_alignment() {
        let directions = 1usize;
        let length = 8usize;
        let mut hrirs = vec![0.0f32; length * 2];
        hrirs[0] = 1.0;
        hrirs[1] = 1.0;
        let pan = vec![0.5, 0.5];
        let mut core =
            SpatializerCore::new(&hrirs, &pan, directions, length, SAMPLE_RATE, 8)
                .expect("create");
        let mut input = vec![0.0f32; 16];
        input[0] = 1.0;
        let mut output = vec![0.0f32; 16];
        core.process(&input, &mut output, 8);
        assert!((output[0] - 0.5).abs() < 1e-5);
        assert!((output[1] - 0.5).abs() < 1e-5);
    }
}
