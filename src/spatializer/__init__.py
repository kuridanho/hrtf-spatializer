"""Spatializer — real-time HRTF binaural spatializer.

The public API is deliberately small.  GUI and audio-device code is imported
lazily so that the DSP layer can be used headlessly (benchmarks, tests, batch
processing).
"""

from __future__ import annotations

from .engine.hrtf import POSITIONS, DatasetError, HRIRPosition, HRTFDataset
from .engine.upols import RUST_AVAILABLE, UPOLSSpatializer

__version__ = "0.1.0"

__all__ = [
    "POSITIONS",
    "RUST_AVAILABLE",
    "DatasetError",
    "HRIRPosition",
    "HRTFDataset",
    "UPOLSSpatializer",
    "__version__",
]
