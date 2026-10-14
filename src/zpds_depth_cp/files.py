"""Frame-wise NPY/Zarr conversion and storage-error verification."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import tempfile

import numpy as np
import zarr

from .codecs import DepthLogSZ3
from .storage import DEPTH_STORAGE_ALPHA, DepthZarrWriter


def _validate_array(array):
    if array.ndim not in (2, 3) or min(array.shape[-2:]) < 1:
        raise ValueError("Depth must have shape (H,W) or (T,H,W), with positive H/W")
    if array.dtype.kind != "f" or array.dtype.itemsize != 4:
        raise ValueError("Depth must be float32 in meters; integer/float64 input is not converted implicitly")
    return array


def open_depth(path: str | Path):
    """Open an NPY array or a local Zarr v2 array/group without loading all frames.

    A group must contain a `depth` array. Values must be float32 meters.
    Missing unit metadata is treated as the caller's declaration of meters.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    if path.is_file():
        if path.suffix.lower() != ".npy":
            raise ValueError("Only .npy files and local Zarr directories are supported")
        return _validate_array(np.load(path, mmap_mode="r", allow_pickle=False))
    node = zarr.open(str(path), mode="r")
    array = node["depth"] if isinstance(node, zarr.hierarchy.Group) else node
    for attrs in (node.attrs, array.attrs):
        if attrs.get("depth_unit", "meter") not in ("meter", "meters", "m"):
            raise ValueError("Depth units must be meters")
    return _validate_array(array)


def _frames(array):
    if array.ndim == 2:
        yield np.asarray(array[:], dtype="<f4")
    else:
        for i in range(array.shape[0]):
            yield np.asarray(array[i], dtype="<f4")


def _sequence_shape(array):
    return (1, *array.shape) if array.ndim == 2 else tuple(array.shape)


@contextmanager
def _destination(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination == source or source in destination.parents or destination in source.parents:
        raise ValueError("Input and output paths must not overlap")
    if destination.exists():
        raise FileExistsError(f"Output already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Stage alongside the target: errors leave no half-written output behind.
    with tempfile.TemporaryDirectory(prefix=".zpds-depth-cp-", dir=destination.parent) as temp:
        staged = Path(temp) / destination.name
        yield staged
        if destination.exists():
            raise FileExistsError(f"Output already exists: {destination}")
        staged.rename(destination)


def compress(source: str | Path, destination: str | Path) -> dict:
    """Write S1/T1 Zarr from float32 metric NPY or Zarr. Never overwrite input.

    Recompressing already lossy data bounds the *additional* perturbation, not
    the error relative to the original pre-compression depth.
    """
    array = open_depth(source)
    shape = _sequence_shape(array)
    metadata = {}
    if Path(source).is_dir():
        metadata = dict(zarr.open(str(source), mode="r").attrs)
    metadata["source_array_shape"] = list(array.shape)
    with _destination(source, destination) as staged:
        with DepthZarrWriter(staged, *shape[1:], metadata=metadata) as writer:
            for frame in _frames(array):
                writer.append(frame)
    return inspect(destination)


def decompress(source: str | Path, destination: str | Path) -> dict:
    """Export decoded metric float32 to NPY, streaming one frame at a time.

    A single-frame (H,W) input compressed by this tool retains its original
    dimensionality. Other depth sequences decode to (T,H,W).
    """
    if Path(destination).suffix.lower() != ".npy":
        raise ValueError("Decompression output must end in .npy")
    array = open_depth(source)
    shape = tuple(array.shape)
    if Path(source).is_dir():
        attrs = zarr.open(str(source), mode="r").attrs
        original = attrs.get("source_array_shape")
        if shape[0] == 1 and array.ndim == 3 and original == list(shape[1:]):
            shape = shape[1:]
    with _destination(source, destination) as staged:
        if array.ndim == 3 and array.shape[0] == 0:
            np.save(staged, np.empty(shape, dtype="<f4"), allow_pickle=False)
        else:
            output = np.lib.format.open_memmap(staged, mode="w+", dtype="<f4", shape=shape)
            try:
                for i, frame in enumerate(_frames(array)):
                    if len(shape) == 2:
                        output[:] = frame
                    else:
                        output[i] = frame
                output.flush()
            finally:
                del output
    return inspect(destination)


def inspect(path: str | Path) -> dict:
    """Return shape, dtype, codec configuration, attributes and logical bytes."""
    path = Path(path)
    array = open_depth(path)
    size = path.stat().st_size if path.is_file() else sum(
        file.stat().st_size for file in path.rglob("*") if file.is_file()
    )
    result = {"shape": list(array.shape), "dtype": str(array.dtype),
              "depth_unit": "meter", "file_bytes": size,
              "array_bytes": int(np.prod(array.shape)) * 4}
    if path.is_dir():
        result.update(chunks=list(array.chunks),
                      compressor=array.compressor.get_config() if array.compressor else None,
                      metadata=dict(zarr.open(str(path), mode="r").attrs))
    return result


def verify(source: str | Path, compressed: str | Path) -> dict:
    """Audit decoded error against source; this is not model accuracy testing.

    The tolerance is taken from the actual S codec, not mutable group attrs.
    Exceptional values must preserve all float32 bits, including NaN payloads.
    """
    original, restored = open_depth(source), open_depth(compressed)
    if _sequence_shape(original) != _sequence_shape(restored):
        raise ValueError("Source and compressed shapes differ")
    codec = getattr(restored, "compressor", None)
    if not isinstance(codec, DepthLogSZ3):
        raise ValueError("Verification requires an S-format compressed Zarr array")
    count = violations = mismatches = 0
    total = maximum = 0.0
    for raw, decoded in zip(_frames(original), _frames(restored)):
        normal = np.isfinite(raw) & (raw > 0) & (raw <= 10)
        reference = raw[normal].astype("f8")
        error = np.abs(decoded[normal].astype("f8") - reference)
        bound = codec.alpha * np.maximum(1, reference)
        violations += int(np.count_nonzero(~np.isfinite(error) | (error > bound)))
        mismatches += int(np.count_nonzero(raw.view("<u4")[~normal] != decoded.view("<u4")[~normal]))
        count += error.size
        total += float(error.sum())
        if error.size:
            maximum = max(maximum, float(np.max(np.where(np.isfinite(error), error, np.inf))))
    return {"passed": violations == 0 and mismatches == 0, "alpha": codec.alpha,
            "s1": codec.alpha == DEPTH_STORAGE_ALPHA, "bounded_pixels": count,
            "bound_violations": violations, "exception_bit_mismatches": mismatches,
            "mean_abs_error_m": total / count if count and np.isfinite(total) else None,
            "max_abs_error_m": maximum if np.isfinite(maximum) else None}
