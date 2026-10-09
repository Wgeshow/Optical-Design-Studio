from pathlib import Path
import sys, tempfile, unittest
from types import SimpleNamespace
from unittest.mock import patch
import backend, ml_optimizer

class PlatformTests(unittest.TestCase):
    def test_linux_native_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            native=Path(temp)/'pcs_s4_runtime'/'linux'
            native.mkdir(parents=True)
            extension=SimpleNamespace(__file__=str(native/'S4.so'),AccelerationInfo=lambda:{})
            proxy=SimpleNamespace(_MEIPASS=temp,platform='linux',path=[])
            helper=SimpleNamespace(configure=lambda **kw:None)
            with patch.object(backend,'sys',proxy),patch.dict(sys.modules,{'S4':extension,'s4_runtime':helper}):
                self.assertIs(backend.load_runtime(dict(threads=1,gpu_block=256,gpu_device=0,gpu_min_n=1024)),extension)
            self.assertEqual(proxy.path[0],str(native))
    def test_linux_does_not_add_windows_wheels(self):
        proxy=SimpleNamespace(platform='linux',path=[])
        with patch.object(ml_optimizer,'sys',proxy):
            try: ml_optimizer.dependencies()
            except RuntimeError: pass
        self.assertEqual(proxy.path,[])
