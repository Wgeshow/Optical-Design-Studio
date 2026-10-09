import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from crash_reporting import install_crash_reporting

class CrashReportingTests(unittest.TestCase):
    def test_uncaught_callback_is_logged_and_reported_without_exiting(self):
        messages=[]
        with tempfile.TemporaryDirectory() as directory, patch('crash_reporting.faulthandler.enable'):
            log, previous=install_crash_reporting(directory,messages.append)
            try:
                try:
                    raise ValueError('test optimization callback failure')
                except ValueError:
                    sys.excepthook(*sys.exc_info())
                self.assertIn('test optimization callback failure', messages[0])
                self.assertIn('Traceback', Path(log.name).read_text())
            finally:
                sys.excepthook=previous
                log.close()

    def test_reporting_failure_does_not_raise_from_exception_hook(self):
        def broken(message):
            raise RuntimeError('UI unavailable')
        with tempfile.TemporaryDirectory() as directory, patch('crash_reporting.faulthandler.enable'):
            log, previous=install_crash_reporting(directory,broken)
            try:
                sys.excepthook(ValueError,ValueError('failed'),None)
                self.assertIn('failed',Path(log.name).read_text())
            finally:
                sys.excepthook=previous
                log.close()
