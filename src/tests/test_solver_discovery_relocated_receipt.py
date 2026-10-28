"""Discovery can reuse relocated receipts without changing their ownership."""
import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import solver_environment as setup
class RelocatedReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path.cwd());self.root=Path(self.temp.name)
        self.runtime=dict(mode='local',executable=str(self.root/'existing'/'python.exe'),timeout_s=86400.)
        self.file=self.root/'sesame.json'
        self.receipt=dict(schema=1,engine='sesame',root=str(self.root.parent/'old-virtual-root'),runtime=self.runtime)
        self.file.write_text(json.dumps(self.receipt),encoding='utf-8')
    def tearDown(self):self.temp.cleanup()
    def test_strict_reader_retains_root_check_but_discovery_can_probe(self):
        self.assertEqual(setup.saved_runtime('sesame',self.root),{})
        self.assertEqual(setup.saved_runtime('sesame',self.root,discovery_candidate=True),self.runtime)
    def test_relocated_candidate_requires_probe_and_never_rewrites_receipt(self):
        original=self.file.read_bytes()
        with patch.object(setup,'probe',return_value=self.runtime) as probe, patch.object(setup,'_python_install') as install:
            result=setup.discover('sesame',root=self.root)
        self.assertEqual(result,self.runtime);probe.assert_called_once();install.assert_not_called()
        self.assertEqual(self.file.read_bytes(),original)
    def test_failed_probe_and_wrong_engine_are_not_available(self):
        with patch.object(setup,'probe',side_effect=RuntimeError('Missing API')),patch.object(setup.sys,'frozen',True,create=True):
            self.assertEqual(setup.discover('sesame',root=self.root),{})
        self.receipt['engine']='other';self.file.write_text(json.dumps(self.receipt),encoding='utf-8')
        self.assertEqual(setup.saved_runtime('sesame',self.root,discovery_candidate=True),{})
    def test_optional_default_differences_do_not_probe_same_python_twice(self):
        self.file.unlink()
        configured=dict(mode='local',executable=setup.sys.executable,timeout_s='86400')
        with patch.object(setup,'probe',side_effect=RuntimeError('Missing API')) as probe,patch.object(setup.sys,'frozen',False,create=True):
            self.assertEqual(setup.discover('sesame',configured,root=self.root),{})
        self.assertEqual(probe.call_count,1)
if __name__=='__main__':unittest.main()
