"""Metric depth compression without model or GPU dependencies.

Importing this package registers the current and legacy Numcodecs IDs.
"""

from .codecs import DepthLogSZ3, DepthSZ3
from .storage import DEPTH_CHUNK_FRAMES, DEPTH_STORAGE_ALPHA, PRECISION_PRESETS, DepthZarrWriter
from .files import compress, decompress, inspect, open_depth, verify

__version__ = "0.2.0"
__all__ = [
    "DEPTH_CHUNK_FRAMES", "DEPTH_STORAGE_ALPHA", "DepthLogSZ3", "DepthSZ3",
    "DepthZarrWriter", "compress", "decompress", "inspect", "open_depth", "verify",
    "PRECISION_PRESETS",
]
