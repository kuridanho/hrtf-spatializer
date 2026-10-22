use spatializer_core::SpatializerCore;
use std::time::Instant;

fn main() {
    let directions = 21usize;
    let length = 16_384usize;
    let sample_rate = 48_000u32;
    let mut hrirs = vec![0.0f32; directions * length * 2];
    for direction in 0..directions {
        for ear in 0..2 {
            for n in 0..length {
                let value = ((direction * 131 + ear * 17 + n) as f32 * 0.017).sin()
                    * (-(n as f32) / 4_000.0).exp()
                    * 0.05;
                hrirs[(direction * length + n) * 2 + ear] = value;
            }
        }
    }
    let pan: Vec<f32> = (0..directions)
        .flat_map(|_| [0.5f32, 0.5f32])
        .collect();

    println!("HRIR {directions} x {length}, {sample_rate} Hz");
    for block_size in [64usize, 128, 256, 512] {
        let mut core = SpatializerCore::new(
            &hrirs,
            &pan,
            directions,
            length,
            sample_rate,
            block_size,
        )
        .expect("create");

        let frames = sample_rate as usize * 2;
        let mut input = vec![0.0f32; block_size * 2];
        let mut output = vec![0.0f32; block_size * 2];
        for n in 0..block_size {
            input[n * 2] = ((n as f32) * 0.1).sin() * 0.1;
            input[n * 2 + 1] = ((n as f32) * 0.13).cos() * 0.1;
        }

        let blocks = frames / block_size;
        let mut times = Vec::with_capacity(blocks);
        for _ in 0..blocks {
            let start = Instant::now();
            core.process(&input, &mut output, block_size);
            times.push(start.elapsed().as_secs_f64() * 1000.0);
        }
        times.sort_by(|a, b| a.partial_cmp(b).unwrap());
        let mean = times.iter().sum::<f64>() / times.len() as f64;
        let p95 = times[(times.len() as f64 * 0.95) as usize];
        let budget = block_size as f64 / sample_rate as f64 * 1000.0;
        println!(
            "B={block_size:3} K={:3} mean={mean:.3} ms p95={p95:.3} ms budget={budget:.2} ms headroom={:.1}x",
            core.partitions(),
            budget / mean
        );
    }
}
