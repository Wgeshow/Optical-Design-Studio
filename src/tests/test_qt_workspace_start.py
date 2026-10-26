"""Startup workspace choices, cancellation and keyboard behavior are explicit."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

from PyQt6.QtCore import QCoreApplication,QEvent,QSettings,QTimer,Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication,QBoxLayout,QDialog,QScrollArea,QWidget
from qt_workspace_start import (STARTUP_WORKSPACE_KEY,WorkspaceLoadingWindow,WorkspaceStartDialog,
    choose_startup_workspace,normalize_workspace_profile)

APP=QApplication.instance() or QApplication([])


class WorkspaceStartTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'startup.ini'
        self.settings=QSettings(str(self.path),QSettings.Format.IniFormat)

    def tearDown(self):
        for widget in APP.topLevelWidgets():
            if isinstance(widget,WorkspaceStartDialog):widget.close();widget.deleteLater()
            elif isinstance(widget,WorkspaceLoadingWindow):widget.shutdown_without_cancel()
        APP.processEvents();self.temp.cleanup()

    def act(self,callback):
        def invoke():
            dialog=APP.activeModalWidget();self.assertIsInstance(dialog,WorkspaceStartDialog)
            callback(dialog)
        QTimer.singleShot(0,invoke)

    def remember(self,profile):
        self.settings.setValue(STARTUP_WORKSPACE_KEY,profile);self.settings.sync()

    def test_profile_aliases_and_unknown_explicit_values(self):
        self.assertEqual(normalize_workspace_profile('Device Studio'),'device')
        self.assertEqual(normalize_workspace_profile('multiphysics'),'device')
        self.assertEqual(normalize_workspace_profile('Original Optical Studio'),'original')
        self.assertEqual(normalize_workspace_profile('legacy'),'original')
        self.assertEqual(normalize_workspace_profile('choose'),'ask')
        self.assertIsNone(normalize_workspace_profile(None))
        for value in ('unknown',True,42):
            with self.assertRaises(ValueError):normalize_workspace_profile(value)

    def test_explicit_profiles_skip_dialog_without_changing_remembered_choice(self):
        self.remember('original');before=self.path.read_bytes()
        with patch('qt_workspace_start.WorkspaceStartDialog') as dialog:
            self.assertEqual(choose_startup_workspace('device',self.settings),'device')
            self.assertEqual(choose_startup_workspace('legacy',self.settings),'original')
            dialog.assert_not_called()
        self.assertEqual(self.path.read_bytes(),before)

    def test_unset_launch_honors_saved_profile_without_showing_dialog(self):
        self.remember('original')
        with patch('qt_workspace_start.WorkspaceStartDialog') as dialog:
            self.assertEqual(choose_startup_workspace(None,self.settings),'original');dialog.assert_not_called()

    def test_ask_shows_real_dialog_even_when_choice_was_remembered(self):
        self.remember('device')
        self.act(lambda dialog:dialog.open_buttons['original'].click())
        self.assertEqual(choose_startup_workspace('ask',self.settings),'original')
        self.assertFalse(self.settings.contains(STARTUP_WORKSPACE_KEY))

    def test_remember_checkbox_persists_only_accepted_choice(self):
        def accept(dialog):
            self.assertFalse(dialog.remember_check.isChecked())
            dialog.remember_check.setChecked(True);dialog.open_buttons['original'].click()
        self.act(accept)
        self.assertEqual(choose_startup_workspace(None,self.settings),'original')
        self.assertEqual(self.settings.value(STARTUP_WORKSPACE_KEY),'original')

    def test_escape_cancel_keeps_existing_choice_and_preference_bytes(self):
        self.remember('original');before=self.path.read_bytes()
        def cancel(dialog):
            dialog.remember_check.setChecked(True);QTest.keyClick(dialog,Qt.Key.Key_Escape)
        self.act(cancel)
        self.assertIsNone(choose_startup_workspace('ask',self.settings,current='device'))
        self.assertEqual(self.settings.value(STARTUP_WORKSPACE_KEY),'original')
        self.assertEqual(self.path.read_bytes(),before)

    def test_return_opens_current_workspace_and_accepts_immediately(self):
        self.act(lambda dialog:QTest.keyClick(dialog,Qt.Key.Key_Return))
        self.assertEqual(choose_startup_workspace('ask',self.settings,current='original'),'original')

    def test_first_choice_commits_once_and_ignores_repeated_other_action(self):
        dialog=WorkspaceStartDialog();finished=[];dialog.finished.connect(finished.append)
        dialog.show();APP.processEvents()
        QTest.mouseClick(dialog.open_buttons['device'],Qt.MouseButton.LeftButton)
        dialog.open_buttons['original'].click();dialog.choose_profile('original')
        self.assertEqual(dialog.selected_profile,'device')
        self.assertEqual(finished,[QDialog.DialogCode.Accepted])
        self.assertTrue(all(not action.isEnabled() for action in dialog.open_buttons.values()))
        self.assertFalse(dialog.remember_check.isEnabled())

    def test_return_auto_repeat_cannot_emit_a_second_accepted_choice(self):
        dialog=WorkspaceStartDialog(current='original');finished=[];dialog.finished.connect(finished.append)
        dialog.show();APP.processEvents()
        QTest.keyClick(dialog,Qt.Key.Key_Return)
        repeat=QKeyEvent(QEvent.Type.KeyPress,Qt.Key.Key_Return,Qt.KeyboardModifier.NoModifier,'',True,3)
        QApplication.sendEvent(dialog,repeat)
        self.assertEqual(dialog.selected_profile,'original')
        self.assertEqual(finished,[QDialog.DialogCode.Accepted])

    def test_parented_dialog_is_released_after_accept_and_cancel(self):
        parent=QWidget()
        try:
            for accepted in (True,False):
                self.act(lambda dialog,accept=accepted:dialog.choose_profile('device') if accept else dialog.reject())
                self.assertEqual(choose_startup_workspace('ask',self.settings,parent),'device' if accepted else None)
                QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
                self.assertEqual(parent.findChildren(WorkspaceStartDialog),[])
        finally:
            parent.deleteLater()

    def test_accessible_close_button_cancels_without_changing_preferences(self):
        self.remember('original');before=self.path.read_bytes()
        def cancel(dialog):
            self.assertTrue(dialog.windowFlags()&Qt.WindowType.FramelessWindowHint)
            self.assertEqual(dialog.close_button.accessibleName(),'Close workspace chooser')
            dialog.remember_check.setChecked(True)
            QTest.mouseClick(dialog.close_button,Qt.MouseButton.LeftButton)
        self.act(cancel)
        self.assertIsNone(choose_startup_workspace('ask',self.settings))
        self.assertEqual(self.path.read_bytes(),before)

    def test_compact_window_scrolls_to_both_actions_and_keeps_resize_control(self):
        dialog=WorkspaceStartDialog();dialog.resize(640,620);dialog.show();APP.processEvents()
        self.assertEqual(dialog.card_layout.direction(),QBoxLayout.Direction.TopToBottom)
        scroll=dialog.findChild(QScrollArea)
        self.assertGreater(scroll.verticalScrollBar().maximum(),0)
        self.assertTrue(dialog.resize_grip.isVisible())
        for profile in ('device','original'):
            button=dialog.open_buttons[profile]
            scroll.ensureWidgetVisible(button,0,0);APP.processEvents()
            center=button.mapTo(scroll.viewport(),button.rect().center())
            self.assertTrue(scroll.viewport().rect().contains(center),profile)
            self.assertGreaterEqual(button.height(),40)
        QTest.mouseClick(dialog.open_buttons['original'],Qt.MouseButton.LeftButton)
        self.assertEqual(dialog.result(),QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.selected_profile,'original')

    def test_invalid_remembered_value_prompts_instead_of_guessing(self):
        self.remember('obsolete-workspace')
        self.act(lambda dialog:dialog.open_buttons['device'].click())
        self.assertEqual(choose_startup_workspace(None,self.settings),'device')
        self.assertFalse(self.settings.contains(STARTUP_WORKSPACE_KEY))

    def test_full_dialog_has_two_native_previews_exact_actions_and_nine_holes(self):
        dialog=WorkspaceStartDialog();dialog.resize(1586,992);dialog.show();APP.processEvents()
        self.assertEqual(dialog.heading.text(),'Choose your workspace')
        self.assertEqual(dialog.subtitle.text(),'Two workspaces. One project library.')
        self.assertEqual(dialog.open_buttons['device'].text(),'Open Device Studio')
        self.assertEqual(dialog.open_buttons['original'].text(),'Open Original Optical Studio')
        self.assertEqual(len(dialog.previews['device'].device['shapes']),9)
        self.assertTrue(dialog.previews['device'].hits)
        self.assertFalse(dialog.grab().isNull())
        dialog.open_buttons['device'].click();self.assertEqual(dialog.result(),QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.selected_profile,'device')

    def test_loading_surface_paints_opaque_without_modality_or_stay_on_top(self):
        from qt_common import COLORS,theme_manager
        theme_manager().apply('dark',persist=False)
        loading=WorkspaceLoadingWindow('original');loading.set_stage('Building original optical controls')
        loading.show();APP.processEvents()
        self.assertTrue(loading.isVisible());self.assertIsNone(APP.activeModalWidget())
        self.assertEqual(loading.windowModality(),Qt.WindowModality.NonModal)
        self.assertFalse(loading.windowFlags()&Qt.WindowType.WindowStaysOnTopHint)
        self.assertFalse(loading.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        self.assertEqual((loading.width(),loading.height()),(680,330))
        self.assertEqual(loading.heading.text(),'Opening Original Optical Studio')
        self.assertEqual(loading.stage_line.text(),'Building original optical controls')
        self.assertEqual((loading.progress.minimum(),loading.progress.maximum()),(0,0))
        pixel=loading.grab().toImage().pixelColor(15,loading.height()-15)
        self.assertEqual(pixel.alpha(),255);self.assertEqual(pixel.name(),COLORS['dark']['bg'])

    def test_loading_cancel_emits_once_across_button_escape_and_close(self):
        loading=WorkspaceLoadingWindow();signals=[];loading.cancelled.connect(lambda:signals.append('cancelled'))
        loading.show();APP.processEvents()
        QTest.mouseClick(loading.cancel_button,Qt.MouseButton.LeftButton)
        loading.cancel_button.click();QTest.keyClick(loading,Qt.Key.Key_Escape);loading.close()
        self.assertEqual(signals,['cancelled'])
        self.assertFalse(loading.cancel_button.isEnabled());self.assertFalse(loading.close_button.isEnabled())
        self.assertTrue(loading.isVisible())
        loading.set_stage('A late construction callback')
        self.assertEqual(loading.stage_line.text(),'Cancelling workspace startup…')

    def test_loading_window_close_requests_cancellation(self):
        loading=WorkspaceLoadingWindow('device');signals=[];loading.cancelled.connect(lambda:signals.append('cancelled'))
        loading.show();APP.processEvents();loading.close()
        self.assertEqual(signals,['cancelled']);self.assertTrue(loading.isVisible())

    def test_loading_shutdown_hides_and_deletes_without_cancellation(self):
        loading=WorkspaceLoadingWindow();signals=[];destroyed=[]
        loading.cancelled.connect(lambda:signals.append('cancelled'));loading.destroyed.connect(lambda:destroyed.append(True))
        loading.show();APP.processEvents();loading.shutdown_without_cancel();loading.shutdown_without_cancel()
        self.assertFalse(loading.isVisible());self.assertEqual(signals,[])
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.assertEqual(destroyed,[True])


if __name__=='__main__':unittest.main()
