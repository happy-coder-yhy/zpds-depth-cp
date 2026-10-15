import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import zarr

from zpds_depth_cp import DepthLogSZ3, DepthZarrWriter, compress, decompress, inspect, verify


class PrecisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.npy"
        self.raw = np.random.default_rng(73).uniform(0.001, 12, (3, 64, 80)).astype("<f4")
        self.raw.ravel()[:8] = [0, -0.0, -1, np.nan, np.inf, -np.inf, 1, 10]
        self.raw.view("<u4").ravel()[3] = 0x7fc01234
        np.save(self.source, self.raw)

    def assert_roundtrip(self, result, alpha):
        normal = np.isfinite(self.raw) & (self.raw > 0) & (self.raw <= 10)
        error = np.abs(result[normal].astype("f8") - self.raw[normal])
        self.assertTrue((error <= alpha * np.maximum(1, self.raw[normal].astype("f8"))).all())
        np.testing.assert_array_equal(result.view("<u4")[~normal], self.raw.view("<u4")[~normal])

    def test_file_api_all_presets(self):
        for preset, alpha in (("S1", .001), ("S2", .002), ("S3", .003)):
            with self.subTest(preset=preset):
                target = self.root / f"{preset}.zarr"
                details = compress(self.source, target, preset=preset)
                self.assertEqual(details["preset"], preset)
                self.assertEqual(details["compressor"]["alpha"], alpha)
                self.assertEqual(details["metadata"]["preset"], preset)
                self.assertEqual(details["chunks"], [1, 64, 80])
                report = verify(self.source, target)
                self.assertTrue(report["passed"])
                self.assertEqual(report["preset"], preset)
                self.assertEqual(report["s1"], preset == "S1")
                output = self.root / f"{preset}.npy"
                decompress(target, output)
                self.assert_roundtrip(np.load(output), alpha)

    def test_cli_all_presets_and_automatic_decode(self):
        for preset, alpha in (("S1", .001), ("s2", .002), ("S3", .003)):
            with self.subTest(preset=preset):
                target, output = self.root / f"{preset}.zarr", self.root / f"{preset}.npy"
                def run(*args):
                    return subprocess.run([sys.executable, "-m", "zpds_depth_cp", *map(str, args)],
                                          text=True, capture_output=True, check=True)
                details = json.loads(run("compress", self.source, target, "--preset", preset).stdout)
                self.assertEqual(details["preset"], preset.upper())
                report = json.loads(run("verify", self.source, target).stdout)
                self.assertTrue(report["passed"])
                self.assertEqual(report["alpha"], alpha)
                self.assertEqual(json.loads(run("inspect", target).stdout)["preset"], preset.upper())
                run("decompress", target, output)
                self.assert_roundtrip(np.load(output), alpha)

    def test_streaming_presets_match_existing_alpha_codec(self):
        for preset, alpha in (("S1", .001), ("S2", .002), ("S3", .003)):
            with self.subTest(preset=preset):
                target = self.root / f"{preset}.zarr"
                with DepthZarrWriter(target, 64, 80, preset=preset.lower()) as writer:
                    writer.append(self.raw[0])
                array = zarr.open_group(str(target), mode="r")["depth"]
                expected = DepthLogSZ3((1, 64, 80), alpha)
                self.assertEqual(array.compressor.get_config(), expected.get_config())
                self.assertEqual(array.compressor.encode(self.raw[:1]), expected.encode(self.raw[:1]))

    def test_default_matches_s2_encoding(self):
        target = self.root / "default.zarr"
        compress(self.source, target)
        array = zarr.open_group(str(target), mode="r")["depth"]
        expected = DepthLogSZ3((1, 64, 80), .002)
        self.assertEqual(array.compressor.encode(self.raw[:1]), expected.encode(self.raw[:1]))

    def test_invalid_preset_creates_no_output(self):
        target = self.root / "bad.zarr"
        for preset in ("S0", "S4", "", None, 2):
            with self.subTest(preset=preset):
                with self.assertRaisesRegex(ValueError, "preset"):
                    compress(self.source, target, preset=preset)
                self.assertFalse(target.exists())
        result = subprocess.run([sys.executable, "-m", "zpds_depth_cp", "compress",
                                 str(self.source), str(target), "--preset", "S4"],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(target.exists())

    def test_writer_rejects_conflicting_options(self):
        target = self.root / "bad.zarr"
        with self.assertRaisesRegex(ValueError, "either preset or alpha"):
            DepthZarrWriter(target, 64, 80, preset="S2", alpha=.002)
        with self.assertRaisesRegex(ValueError, "preset"):
            DepthZarrWriter(target, 64, 80, preset="S4")
        self.assertFalse(target.exists())

    def test_inspect_and_verify_use_actual_codec_for_old_files(self):
        target = self.root / "old.zarr"
        with DepthZarrWriter(target, 64, 80, alpha=.002) as writer:
            for frame in self.raw:
                writer.append(frame)
        group = zarr.open_group(str(target), mode="a")
        del group.attrs["preset"]
        self.assertEqual(inspect(target)["preset"], "S2")
        group.attrs.update({"preset": "S1", "alpha": .001})
        self.assertEqual(inspect(target)["preset"], "S2")
        self.assertEqual(verify(self.source, target)["preset"], "S2")

    def test_custom_alpha_remains_supported(self):
        target = self.root / "custom.zarr"
        with DepthZarrWriter(target, 64, 80, alpha=.0005) as writer:
            for frame in self.raw:
                writer.append(frame)
        self.assertEqual(inspect(target)["preset"], "custom")
        self.assertTrue(verify(self.source, target)["passed"])


if __name__ == "__main__":
    unittest.main()
