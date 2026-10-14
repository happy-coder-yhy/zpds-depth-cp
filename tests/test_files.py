import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import zarr

from zpds_depth_cp import (
    DEPTH_STORAGE_ALPHA, DepthLogSZ3, DepthZarrWriter,
    compress, decompress, inspect, open_depth, verify,
)


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def source(self, shape=(3, 64, 80), dtype="<f4"):
        data = np.random.default_rng(9).uniform(0.01, 10, shape).astype(dtype)
        path = self.root / "source.npy"
        np.save(path, data)
        return path, data

    def test_defaults_are_s1_t1_and_source_unchanged(self):
        source, data = self.source()
        before = source.read_bytes()
        target = self.root / "depth.zarr"
        details = compress(source, target)
        self.assertEqual(DEPTH_STORAGE_ALPHA, 0.001)
        self.assertEqual(details["compressor"]["alpha"], 0.001)
        self.assertEqual(details["chunks"], [1, 64, 80])
        self.assertTrue(verify(source, target)["passed"])
        self.assertEqual(source.read_bytes(), before)
        output = self.root / "decoded.npy"
        decompress(target, output)
        restored = np.load(output)
        self.assertEqual(restored.dtype, np.dtype("<f4"))
        self.assertEqual(restored.shape, data.shape)
        self.assertTrue((np.abs(restored.astype("f8") - data) <= .001 * np.maximum(1, data.astype("f8"))).all())

    def test_single_frame_and_big_endian(self):
        for dtype in ("<f4", ">f4"):
            source, data = self.source((32, 40), dtype)
            target = self.root / (dtype[0].replace("<", "little").replace(">", "big") + ".zarr")
            compress(source, target)
            output = target.with_suffix(".npy")
            decompress(target, output)
            self.assertEqual(np.load(output).shape, data.shape)
            self.assertTrue(verify(source, target)["passed"])

    def test_exception_payloads_survive_file_roundtrip(self):
        bits = np.array([0, 0x80000000, 0x7fc01234, 0x7fa01234, 0x7f800000,
                         0xff800000, 0xbf800000, 0x7f7fffff, 0x41200001], dtype="<u4")
        data = np.tile(bits, 128).reshape(1, 32, 36).view("<f4")
        source = self.root / "bits.npy"
        np.save(source, data)
        target, output = self.root / "bits.zarr", self.root / "out.npy"
        compress(source, target)
        decompress(target, output)
        np.testing.assert_array_equal(np.load(output).view("<u4"), data.view("<u4"))
        self.assertTrue(verify(source, target)["passed"])

    def test_preserves_metadata_but_replaces_storage_parameters(self):
        source = self.root / "old.zarr"
        root = zarr.open_group(str(source), mode="w")
        root.create_dataset("depth", data=np.ones((2, 8, 10), dtype="f4"))
        root.attrs.update({"fps": 30, "alpha": .003, "depth_unit": "meter"})
        target = self.root / "new.zarr"
        details = compress(source, target)
        self.assertEqual(details["metadata"]["fps"], 30)
        self.assertEqual(details["metadata"]["alpha"], .001)
        self.assertEqual(details["metadata"]["n_frames"], 2)

    def test_rejects_bad_dtype_shape_units_and_overwrite(self):
        source, _ = self.source(dtype="f8")
        with self.assertRaisesRegex(ValueError, "float32"):
            compress(source, self.root / "bad.zarr")
        np.save(source, np.ones((2, 0), dtype="f4"))
        with self.assertRaises(ValueError):
            open_depth(source)
        source, _ = self.source()
        with self.assertRaises(ValueError):
            compress(source, source)
        with self.assertRaises(ValueError):
            compress(source, source / "child.zarr")
        target = self.root / "target.zarr"
        compress(source, target)
        with self.assertRaises(FileExistsError):
            compress(source, target)
        with self.assertRaises(ValueError):
            decompress(target, self.root / "bad.bin")
        with self.assertRaises(ValueError):
            decompress(target, target / "inside.npy")
        zarr.open_group(str(target), mode="a").attrs["depth_unit"] = "mm"
        with self.assertRaisesRegex(ValueError, "meters"):
            open_depth(target)

    def test_empty_sequence(self):
        source, _ = self.source((0, 4, 5))
        target, output = self.root / "empty.zarr", self.root / "empty.npy"
        compress(source, target)
        decompress(target, output)
        self.assertEqual(np.load(output).shape, (0, 4, 5))
        self.assertTrue(verify(source, target)["passed"])

    def test_failed_compression_cleans_staging_and_leaves_source(self):
        source, _ = self.source()
        before = source.read_bytes()
        target = self.root / "failed.zarr"
        with patch.object(DepthLogSZ3, "encode", side_effect=RuntimeError("codec failed")):
            with self.assertRaisesRegex(RuntimeError, "codec failed"):
                compress(source, target)
        self.assertFalse(target.exists())
        self.assertFalse(list(self.root.glob(".zpds-depth-cp-*")))
        self.assertEqual(source.read_bytes(), before)

    def test_verify_uses_codec_not_group_metadata(self):
        source, _ = self.source()
        target = self.root / "target.zarr"
        compress(source, target)
        zarr.open_group(str(target), mode="a").attrs["alpha"] = 1
        self.assertEqual(verify(source, target)["alpha"], .001)
        with self.assertRaises(ValueError):
            verify(source, source)

    def test_cli_fresh_process_and_failure_exit_codes(self):
        source, _ = self.source((2, 8, 10))
        target = self.root / "cli.zarr"
        def run(*args):
            return subprocess.run([sys.executable, "-m", "zpds_depth_cp", *map(str, args)],
                                  capture_output=True, text=True)
        result = run("compress", source, target)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["chunks"], [1, 8, 10])
        result = run("verify", source, target)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["passed"])
        result = run("decompress", target, self.root / "cli.npy")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(run("compress", source, target).returncode, 1)
        np.save(source, np.full((2, 8, 10), 9, dtype="f4"))
        result = run("verify", source, target)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertGreater(json.loads(result.stdout)["bound_violations"], 0)


class WriterTests(unittest.TestCase):
    def test_tail_chunks_and_read_slices(self):
        frames = np.random.default_rng(7).uniform(.1, 10, (5, 32, 40)).astype("f4")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "depth.zarr"
            with DepthZarrWriter(path, 32, 40, chunk_frames=2) as writer:
                for frame in frames:
                    writer.append(frame)
                self.assertEqual(writer.n_frames, 5)
            writer.close()
            with self.assertRaises(RuntimeError):
                writer.append(frames[0])
            result = open_depth(path)[1:5:2, 2:8, 3:9]
            source = frames[1:5:2, 2:8, 3:9]
            self.assertTrue((np.abs(result.astype("f8")-source) <= .001*np.maximum(1, source)).all())
            self.assertEqual(inspect(path)["metadata"]["n_frames"], 5)

    def test_dimension_validation_before_filesystem_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.zarr"
            for height, width in ((True, 3), (1.5, 2), (0, 1), (2, -1)):
                with self.assertRaises(ValueError):
                    DepthZarrWriter(path, height, width)
                self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
