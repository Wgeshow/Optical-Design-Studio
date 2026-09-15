"""Public update UI tests: fake clients only, with no login or credential access."""
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_import_library = tempfile.TemporaryDirectory(prefix='s4_about_import_')
os.environ.setdefault('S4_LIBRARY_ROOT', _import_library.name)

from PyQt6.QtCore import QCoreApplication, QEvent, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QLabel

import qt_about
from qt_about import AboutPage
from qt_common import theme_manager
from update_client import CheckResult, ReleaseInfo, UpdateCancelled, UpdateError


INFO = {'version': '1.0.3', 'last_updated': 'Not recorded',
        'platform': 'Windows · 64-bit', 'platform_id': 'windows-x64'}
RELEASE = ReleaseInfo('1.0.4', 'v1.0.4', '2026-09-14T12:00:00Z',
    '<script>Untrusted release notes remain text</script>',
    'https://github.com/Wgeshow/optical-design-studio-downloads/releases/tag/v1.0.4',
    7, 'OpticalDesignStudio-Setup-1.0.4-Windows-x64.exe', 12, 'a' * 64)


class FakeService:
    def __init__(self):
        self.calls = []
        self.status = 'available'
        self.error = None
        self.block = False
        self.entered = threading.Event()
        self.completed_path = None

    def factory(self):
        service = self

        class Client:
            def check(self, installed_version, platform_id, cancel):
                service.calls.append(('check', installed_version, platform_id))
                service.wait(cancel)
                return CheckResult(service.status, '',
                    RELEASE if service.status == 'available' else None, '2026-09-14T12:34:00Z')

            def download(self, release, directory, progress, cancel):
                service.calls.append(('download', release, directory))
                service.wait(cancel)
                progress(6, 12)
                progress(12, 12)
                path = Path(directory) / release.asset_name
                path.write_bytes(b'verified fake package')
                service.completed_path = path
                return path
        return Client()

    def wait(self, cancel):
        self.entered.set()
        while self.block and not cancel.is_set():
            cancel.wait(0.01)
        if cancel.is_set():
            raise UpdateCancelled()
        if self.error:
            raise self.error


class AboutPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.previous_quit = cls.app.quitOnLastWindowClosed()
        cls.app.setQuitOnLastWindowClosed(False)

    @classmethod
    def tearDownClass(cls):
        cls.app.setQuitOnLastWindowClosed(cls.previous_quit)

    def setUp(self):
        self.service = FakeService()
        self.store = Mock()
        self.pages = []
        self.old_theme = theme_manager().mode
        theme_manager().apply('dark', persist=False)
        self.info_patch = patch.object(qt_about, 'installation_info', return_value=INFO.copy())
        self.info_patch.start()

    def tearDown(self):
        self.service.block = False
        for page in self.pages:
            page.shutdown()
            self.wait_idle(page)
            page.hide()
            page.deleteLater()
        self.settle()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.info_patch.stop()
        theme_manager().apply(self.old_theme, persist=False)

    def settle(self):
        for _ in range(3):
            self.app.processEvents()

    def wait_idle(self, page):
        deadline = time.monotonic() + 5
        while page.busy and time.monotonic() < deadline:
            QTest.qWait(5)
        self.settle()
        self.assertFalse(page.busy, 'The request worker did not become idle')

    def make_page(self):
        page = AboutPage(self.store, self.service.factory)
        self.pages.append(page)
        page.resize(760, 950)
        page.show()
        self.settle()
        return page

    def check(self, page, status='available'):
        self.service.status = status
        page.check_for_updates()
        self.wait_idle(page)

    def test_creation_uses_real_metadata_without_automatic_network_requests(self):
        page = self.make_page()
        self.assertEqual(page.state, 'not_checked')
        self.assertEqual(self.service.calls, [])
        self.assertEqual(page.metadata_labels['Installed version'].text(), '1.0.3')
        self.assertEqual(page.metadata_labels['Last updated'].text(), 'Not recorded')
        self.assertTrue(page.check_button.isVisible())
        self.assertTrue(page.check_button.isEnabled())
        self.assertFalse(page.download_button.isVisible())
        self.assertFalse(hasattr(page, 'account_button'))
        self.assertFalse(hasattr(page, 'disconnect_button'))
        self.assertFalse(hasattr(page, '_token'))
        self.assertEqual(page.findChild(QLabel, 'publicBadge').text(), 'PUBLIC UPDATES')

    def test_available_current_empty_and_incompatible_states_do_not_claim_false_currency(self):
        page = self.make_page()
        self.check(page)
        self.assertEqual(page.state, 'available')
        self.assertTrue(page.download_button.isVisible())
        self.assertTrue(page.notes_button.isVisible())
        self.assertIn('1.0.4', page.status_detail.text())
        self.assertNotIn('Never', page.last_checked.text())
        for state in ('current', 'no_releases', 'no_compatible'):
            self.check(page, state)
            self.assertEqual(page.state, state)
            self.assertFalse(page.download_button.isVisible())
            self.assertFalse(page.notes_button.isVisible())
            if state != 'current':
                self.assertNotIn('up to date', page.status_title.text())
        self.store.assert_not_called()
        self.assertEqual(self.store.mock_calls, [])

    def test_failed_check_hides_old_download_and_unexpected_errors_do_not_expose_secrets(self):
        page = self.make_page()
        self.check(page)
        self.service.error = UpdateError('network', 'Cannot reach GitHub.')
        self.check(page)
        self.assertEqual(page.state, 'error')
        self.assertIsNone(page._release)
        self.assertFalse(page.download_button.isVisible())
        self.assertEqual(page.status_detail.text(), 'Cannot reach GitHub.')
        self.service.error = RuntimeError('Authorization: secret-not-for-display')
        self.check(page)
        self.assertNotIn('secret-not-for-display', page.status_detail.text())

    def test_check_button_works_directly_without_dialog_or_credentials(self):
        forbidden_store = Mock(side_effect=AssertionError('Credential access is forbidden'))
        with patch.dict(sys.modules, {'update_credentials': SimpleNamespace(CredentialStore=forbidden_store)}), \
                patch.object(QDialog, 'exec', side_effect=AssertionError('No sign-in dialog is allowed')):
            page = self.make_page()
            QTest.mouseClick(page.check_button, Qt.MouseButton.LeftButton)
            self.wait_idle(page)
        forbidden_store.assert_not_called()
        self.assertFalse(hasattr(qt_about, 'CredentialStore'))
        self.assertFalse(hasattr(qt_about, 'ConnectionDialog'))
        self.assertFalse(hasattr(page, '_credentials'))
        self.assertEqual(page.state, 'available')
        self.assertEqual(self.service.calls, [('check', '1.0.3', 'windows-x64')])

    def test_busy_check_cancel_and_host_shutdown_wait_for_worker(self):
        self.service.block = True
        page = self.make_page()
        became_idle = Mock()
        page.idle.connect(became_idle)
        page.check_for_updates()
        self.assertTrue(page.busy)
        self.assertEqual(page.state, 'checking')
        self.assertFalse(page.check_button.isEnabled())
        self.assertTrue(page.cancel_button.isVisible())
        page.check_for_updates()  # A second click cannot create a concurrent request.
        self.assertFalse(page.shutdown())
        self.wait_idle(page)
        self.assertTrue(page.shutdown())
        self.assertEqual(page.state, 'cancelled')
        self.assertTrue(page.check_button.isEnabled())
        became_idle.assert_called_once()
        self.assertEqual(len(self.service.calls), 1)
        self.assertEqual(self.store.mock_calls, [])

    def test_download_is_explicit_verified_and_only_opens_containing_folder(self):
        page = self.make_page()
        self.check(page)
        with tempfile.TemporaryDirectory(prefix='s4_about_download_') as folder:
            with patch.object(qt_about.QFileDialog, 'getExistingDirectory', return_value=folder), \
                    patch.object(qt_about.QDesktopServices, 'openUrl', return_value=True) as open_url:
                page.download_update()
                self.wait_idle(page)
                self.assertEqual(page.state, 'downloaded')
                self.assertTrue(self.service.completed_path.is_file())
                self.assertEqual(page.progress_bar.value(), 1000)
                open_url.assert_not_called()
                page.download_update()
                open_url.assert_called_once()
                self.assertEqual(Path(open_url.call_args.args[0].toLocalFile()), Path(folder))
                self.assertNotIn('.exe', open_url.call_args.args[0].toString())

    def test_cancelled_or_failed_download_never_exposes_a_downloaded_action(self):
        page = self.make_page()
        self.check(page)
        with tempfile.TemporaryDirectory(prefix='s4_about_cancel_') as folder:
            with patch.object(qt_about.QFileDialog, 'getExistingDirectory', return_value=folder):
                self.service.block = True
                page.download_update()
                self.assertEqual(page.state, 'downloading')
                page.cancel_request()
                self.wait_idle(page)
                self.assertEqual(page.state, 'cancelled')
                self.assertFalse(page.download_button.isVisible())
                self.assertEqual(list(Path(folder).iterdir()), [])
                self.service.block = False
                self.check(page)
                self.service.error = UpdateError('integrity', 'The package checksum did not match.')
                page.download_update()
                self.wait_idle(page)
                self.assertEqual(page.state, 'error')
                self.assertEqual(page.status_title.text(), 'Could not download update')
                self.assertFalse(page.download_button.isVisible())
                self.assertIsNone(page._downloaded_path)

    def test_controls_fit_at_compact_width_in_both_themes_and_statuses(self):
        page = self.make_page()
        for mode in ('dark', 'light'):
            theme_manager().apply(mode, persist=False)
            for state in ('available', 'current', 'no_releases', 'no_compatible'):
                self.check(page, state)
                self.assertLessEqual(page.minimumSizeHint().width(), 760)
                self.assertEqual(page.width(), 760)
                self.assertTrue(page.rect().contains(page.update_card.geometry()))
                if state == 'available':
                    self.assertTrue(page.download_button.isVisible())
                    self.assertFalse(page.check_button.geometry().intersects(page.download_button.geometry()))
                    self.assertFalse(page.download_button.geometry().intersects(page.notes_button.geometry()))
                for control in (page.check_button,):
                    self.assertGreaterEqual(control.width(), control.minimumSizeHint().width())
                self.assertFalse(page.grab().isNull())

    def test_cancelled_destination_dialog_does_not_start_download(self):
        page = self.make_page()
        self.check(page)
        with patch.object(qt_about.QFileDialog, 'getExistingDirectory', return_value=''):
            page.download_update()
        self.assertEqual(page.state, 'available')
        self.assertEqual(len(self.service.calls), 1)
        self.assertFalse(page.busy)
        self.assertIsNone(self.service.completed_path)


if __name__ == '__main__':
    unittest.main()
