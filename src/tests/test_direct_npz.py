"""Interleaved direct writes, reader compatibility and interrupted publication."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np

from direct_npz import DirectNPZWriter


class DirectNPZTests(unittest.TestCase):
    def test_interleaved_noncontiguous_blocks_roundtrip_and_crc(self):
        e = (np.arange(90).reshape(15, 6)[:, ::2] + 3j).astype(np.complex128)
        h = e * (2 + 1j)
        xyz = np.arange(90, dtype=np.float64).reshape(15, 6)[:, ::2]
        values = dict(E=e, H=h, xyz=xyz, names=np.asarray(['film', 'air']),
                      version=np.asarray(1, np.int32), empty=np.empty((0, 3)))
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / 'fields.npz'
            with DirectNPZWriter(destination, {k: (v.shape, v.dtype) for k, v in values.items()}) as writer:
                for first in range(0, 15, 4):
                    for name in ('E', 'H', 'xyz'):
                        writer.append(name, values[name][first:first + 4])
                for name in ('names', 'version', 'empty'):
                    writer.append(name, values[name])
                self.assertFalse(destination.exists())
            with zipfile.ZipFile(destination) as archive:
                self.assertIsNone(archive.testzip())
            with np.load(destination, allow_pickle=False) as archive:
                for key, value in values.items():
                    np.testing.assert_array_equal(archive[key], value)
            self.assertEqual(list(Path(tmp).iterdir()), [destination])

    def test_incomplete_or_failed_write_preserves_old_result_and_cleans_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / 'fields.npz'
            destination.write_bytes(b'existing result')
            for deliberate_error in (False, True):
                with self.assertRaises((ValueError, RuntimeError)):
                    with DirectNPZWriter(destination, {'E': ((10, 3), np.complex128)}) as writer:
                        writer.append('E', np.ones((2, 3), np.complex128))
                        if deliberate_error:
                            raise RuntimeError('cancelled')
                self.assertEqual(destination.read_bytes(), b'existing result')
                self.assertEqual(list(Path(tmp).iterdir()), [destination])

    def test_reject_wrong_dtype_shape_and_overflow_without_corrupting_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / 'fields.npz'
            with DirectNPZWriter(destination, {'E': ((2, 3), np.complex128)}) as writer:
                for bad in (np.ones((2, 3)), np.ones((2, 2), np.complex128),
                            np.ones((3, 3), np.complex128)):
                    with self.assertRaises(ValueError):
                        writer.append('E', bad)
                writer.append('E', np.ones((2, 3), np.complex128))
            with zipfile.ZipFile(destination) as archive:
                self.assertIsNone(archive.testzip())

    def test_invalid_declarations_leave_no_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            for specification in ({'../E': ((2, 3), np.complex128)},
                                  {'E': ((-1, 3), np.complex128)},
                                  {'E': ((2,), object)}, {}):
                with self.assertRaises(ValueError):
                    DirectNPZWriter(Path(tmp) / 'fields.npz', specification)
                self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_failed_durable_flush_does_not_publish_or_leave_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / 'fields.npz'
            destination.write_bytes(b'previous complete result')
            with patch('direct_npz.os.fsync', side_effect=OSError('flush failed')):
                with self.assertRaisesRegex(OSError, 'flush failed'):
                    with DirectNPZWriter(destination, {'E': ((2, 3), np.complex128)}) as writer:
                        writer.append('E', np.ones((2, 3), np.complex128))
            self.assertEqual(destination.read_bytes(), b'previous complete result')
            self.assertEqual(list(Path(tmp).iterdir()), [destination])


if __name__ == '__main__':
    unittest.main()
