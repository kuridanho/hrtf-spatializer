#ifndef SPATIALIZER_CORE_H
#define SPATIALIZER_CORE_H

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct SpatializerCore SpatializerCore;

/// Create a real-time 21-direction HRTF convolver.
///
/// - hrirs: interleaved (direction, sample, ear) float32 array
/// - pan_coefs: interleaved (direction, left/right gain) float32 array
/// - directions: number of measured directions
/// - hrir_length: samples per HRIR
/// - sample_rate: stream sample rate
/// - block_size: fixed processing block size
SpatializerCore *spatializer_core_create(const float *hrirs,
                                         const float *pan_coefs,
                                         int32_t directions,
                                         int32_t hrir_length,
                                         int32_t sample_rate,
                                         int32_t block_size);

void spatializer_core_destroy(SpatializerCore *core);

/// Process `frames` interleaved stereo float32 samples.
/// `frames` should equal the block size passed to create.
void spatializer_core_process(SpatializerCore *core,
                              const float *input,
                              float *output,
                              int32_t frames);

void spatializer_core_set_gain(SpatializerCore *core, float gain);
void spatializer_core_set_bypass(SpatializerCore *core, bool bypass);
void spatializer_core_get_meters(SpatializerCore *core,
                                 float *left,
                                 float *right);

int32_t spatializer_core_block_size(const SpatializerCore *core);
int32_t spatializer_core_partitions(const SpatializerCore *core);

#ifdef __cplusplus
}
#endif

#endif /* SPATIALIZER_CORE_H */
