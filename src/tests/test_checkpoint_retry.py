"""A transient Windows file lock must not discard a completed ML checkpoint."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from data_library import read_json, write_json


class CheckpointRetryTests(unittest.TestCase):
    def test_transient_replace_lock_retries_atomically(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'history.json'
            write_json(path,{'observations':[1]})
            original=os.replace
            attempts=[]
            def locked(source,target):
                attempts.append(1)
                if len(attempts)<3:
                    self.assertEqual(read_json(path),{'observations':[1]})
                    raise PermissionError('Simulated temporary sharing lock')
                return original(source,target)
            with patch('data_library.os.replace',side_effect=locked),patch('data_library.time.sleep'):
                write_json(path,{'observations':[1,2]})
            self.assertEqual(read_json(path),{'observations':[1,2]})
            self.assertEqual(len(attempts),3)
            self.assertEqual(list(Path(temp).glob('*.tmp')),[])

    def test_permanent_error_preserves_previous_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'history.json'
            write_json(path,{'old':True})
            with patch('data_library.os.replace',side_effect=PermissionError('Permanent permission error')) as replaced,patch('data_library.time.sleep'):
                with self.assertRaises(PermissionError): write_json(path,{'old':False})
            self.assertEqual(replaced.call_count,6)
            self.assertEqual(read_json(path),{'old':True})
            self.assertEqual(list(Path(temp).glob('*.tmp')),[])


if __name__=='__main__': unittest.main()
