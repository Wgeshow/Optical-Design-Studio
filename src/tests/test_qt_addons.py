import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox
from qt_addons import AddonsPage, AddonWorker
from addon_runtime import AddonClient, asset_name, APP_VERSION
from update_client import ReleaseInfo


class Store(QObject):
    busy_changed = pyqtSignal(bool)
    def __init__(self):
        super().__init__()
        self.busy, self._worker, self.saved = False, None, 0
    def _set_busy(self, value):
        self.busy = value
        self.busy_changed.emit(value)
    def _autosave(self):
        self.saved += 1
    def cancel(self):
        self._worker.cancel()


class Worker(QObject):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)
    finished = pyqtSignal()
    progress = pyqtSignal(int)
    stage = pyqtSignal(str)
    def __init__(self, identifier, release=None, parent=None, install=True):
        super().__init__(parent)
        self.cancelled = False
    def start(self):
        pass
    def cancel(self):
        self.cancelled = True
    def isRunning(self):
        return False


class AddonsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.page = None
        self.store = Store()
        for name, value in [('bundled', False), ('available', False), ('pending_addons', [])]:
            patcher = patch('addon_runtime.'+name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        if self.page is not None:
            self.page.deleteLater()
        self.app.processEvents()

    def test_constructing_settings_never_contacts_github(self):
        with patch.object(AddonClient, '_json') as metadata, patch.object(AddonClient, 'download') as download:
            self.page = AddonsPage()
            self.page.show()
            self.app.processEvents()
            metadata.assert_not_called()
            download.assert_not_called()
            self.assertTrue(self.page.shutdown())

    def test_bundled_libraries_do_not_offer_download(self):
        with patch('addon_runtime.bundled', return_value=True):
            self.page = AddonsPage()
            for status, button in self.page.cards.values():
                self.assertIn('Included', status.text())
                self.assertFalse(button.isEnabled())

    def test_install_starts_on_first_click_without_second_confirmation(self):
        self.page = AddonsPage(store=self.store)
        with patch.object(QMessageBox, 'question') as confirm, patch('qt_addons.AddonWorker', Worker):
            self.page.action('gpu')
        confirm.assert_not_called()
        self.assertTrue(self.page.is_busy)
        self.assertTrue(self.store.busy)
        self.assertEqual(self.store.saved, 1)
        self.store.cancel()
        self.assertTrue(self.page.worker.cancelled)
        self.page.worker.finished.emit()
        self.assertFalse(self.store.busy)
        self.assertIsNone(self.store._worker)

    def test_restart_only_after_worker_finishes_and_lock_released(self):
        self.page = AddonsPage(store=self.store)
        observed = []
        self.page.restart_requested.connect(lambda: observed.append((self.store.busy, self.page.is_busy)))
        with patch('qt_addons.AddonWorker', Worker):
            self.page.action('gpu')
        self.page.worker.completed.emit(Path('fake-staged-pack'))
        self.assertEqual(observed, [])
        self.page.worker.finished.emit()
        self.app.processEvents()
        self.assertEqual(observed, [(False, False)])

    def test_failure_releases_lock_without_restart(self):
        self.page = AddonsPage(store=self.store)
        restarts = []
        self.page.restart_requested.connect(lambda: restarts.append(True))
        with patch('qt_addons.AddonWorker', Worker):
            self.page.action('gpu')
        self.page.worker.failed.emit('Download failed')
        self.page.worker.finished.emit()
        self.app.processEvents()
        self.assertFalse(self.store.busy)
        self.assertEqual(restarts, [])

    def test_active_calculation_blocks_native_and_meep_installs(self):
        self.store.busy, self.store._worker = True, object()
        self.page = AddonsPage(store=self.store)
        with patch('qt_addons.AddonWorker') as native, patch('qt_fdtd._ManagedRuntimeTask') as meep:
            self.page.action('gpu')
            self.page.meep_settings.start_managed(True)
            native.assert_not_called()
            meep.assert_not_called()
        self.assertTrue(self.store.busy)

    def test_new_meep_operation_cannot_overlap_native_install(self):
        self.page = AddonsPage(store=self.store)
        with patch('qt_addons.AddonWorker', Worker):
            self.page.action('gpu')
        with patch('qt_fdtd._ManagedRuntimeTask') as meep:
            self.page.meep_settings.start_managed(True)
            meep.assert_not_called()
        self.page.worker.finished.emit()

    def test_preflight_failure_does_not_start_install(self):
        def blocked():
            raise RuntimeError('Updater is busy')
        self.page = AddonsPage(store=self.store, preflight=blocked)
        with patch('qt_addons.AddonWorker') as worker:
            self.page.action('gpu')
            worker.assert_not_called()
        self.assertFalse(self.store.busy)
        self.assertIn('Updater is busy', self.page.status.text())


class WorkerTests(unittest.TestCase):
    def test_single_worker_checks_downloads_and_installs(self):
        release = ReleaseInfo(APP_VERSION, 'v'+APP_VERSION, '', '', '', 1, asset_name('gpu'), 5, 'a'*64)
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp)/'pack.zip'
            package.write_bytes(b'hello')
            worker = AddonWorker('gpu')
            results = []
            worker.completed.connect(results.append)
            with patch.object(AddonClient, 'check_addon', return_value=release) as check, \
                 patch.object(AddonClient, 'download', return_value=package) as download, \
                 patch('addon_runtime.install_archive', return_value=Path(tmp)/'staged') as install:
                worker.run()
                check.assert_called_once()
                download.assert_called_once()
                install.assert_called_once()
            self.assertEqual(results, [Path(tmp)/'staged'])


if __name__ == '__main__':
    unittest.main()
