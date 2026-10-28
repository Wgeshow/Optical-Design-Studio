"""AI page scrolling cannot silently change unfocused simulation parameters."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6 import sip
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import (QAbstractSpinBox, QApplication, QComboBox, QLineEdit,
                            QScrollArea, QVBoxLayout, QWidget)
from data_library import DataLibrary
from qt_ai_search import AISearchPage
from qt_common import guard_unfocused_wheel, integer, number
from qt_core import ProjectStore


class AIUnfocusedWheelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        assert cls.app.platformName() == 'offscreen'

    @staticmethod
    def wheel(control, delta=-120):
        position = QPointF(control.rect().center())
        event = QWheelEvent(position, QPointF(control.mapToGlobal(position.toPoint())),
                            QPoint(), QPoint(0, delta), Qt.MouseButton.NoButton,
                            Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(control, event)
        return event

    def test_all_ai_numeric_and_combo_controls_ignore_unfocused_wheel_without_saving(self):
        with tempfile.TemporaryDirectory(prefix='ai-wheel-') as directory:
            store = ProjectStore(DataLibrary(Path(directory) / 'library'), restore=False)
            store.study_navigation_enabled = True
            store.activate_study('tools.ai')
            page = AISearchPage(store)
            try:
                before = copy.deepcopy(page.options())
                draft = copy.deepcopy(store.search_state)
                controls = page.findChildren(QAbstractSpinBox) + page.findChildren(QComboBox)
                self.assertGreater(len(controls), 20)
                with patch.object(store, 'start_run', side_effect=AssertionError('No solver')):
                    for control in controls:
                        with self.subTest(control=control.objectName() or type(control).__name__):
                            self.assertTrue(hasattr(control, '_unfocused_wheel_guard'))
                            self.assertEqual(control.focusPolicy(), Qt.FocusPolicy.StrongFocus)
                            control.clearFocus()
                            original = control.currentIndex() if isinstance(control, QComboBox) else control.value()
                            self.wheel(control)
                            self.wheel(control, 120)
                            current = control.currentIndex() if isinstance(control, QComboBox) else control.value()
                            self.assertEqual(current, original)
                    self.assertEqual(page.controls['rta_step'].value(), .5)
                    self.assertEqual(page.options(), before)
                    self.assertEqual(store.search_state, draft)
            finally:
                sip.delete(page)

    def test_unfocused_wheel_reaches_parent_scroll_area_for_spinboxes_and_combos(self):
        controls = [number(.5, .001, 100, 3), integer(10, 0, 100), QComboBox()]
        controls[-1].addItems(['First', 'Second', 'Third'])
        for control in controls:
            with self.subTest(control=type(control).__name__):
                area = QScrollArea()
                body = QWidget()
                layout = QVBoxLayout(body)
                focus = QLineEdit('Focus belongs here')
                layout.addWidget(focus)
                layout.addWidget(guard_unfocused_wheel(control))
                layout.addStretch()
                body.setMinimumHeight(1400)
                area.setWidget(body)
                area.setWidgetResizable(True)
                area.resize(400, 180)
                area.show()  # Offscreen-only test window; never a native desktop surface.
                self.app.processEvents()
                try:
                    focus.setFocus()
                    self.app.processEvents()
                    self.assertFalse(control.hasFocus())
                    area.verticalScrollBar().setValue(100)
                    before = control.currentIndex() if isinstance(control, QComboBox) else control.value()
                    self.wheel(control)
                    self.assertGreater(area.verticalScrollBar().value(), 100)
                    after = control.currentIndex() if isinstance(control, QComboBox) else control.value()
                    self.assertEqual(after, before)
                finally:
                    sip.delete(area)

    def test_focused_wheel_and_explicit_value_changes_remain_available(self):
        control = guard_unfocused_wheel(number(.5, .001, 100, 3))
        self.assertIs(guard_unfocused_wheel(control), control)
        try:
            with patch.object(control, 'hasFocus', return_value=True):
                self.wheel(control, 120)
            self.assertEqual(control.value(), 1.5)
            control.setValue(.75)
            self.assertEqual(control.value(), .75)
            combo = guard_unfocused_wheel(QComboBox())
            try:
                combo.addItems(['First', 'Second'])
                with patch.object(combo, 'hasFocus', return_value=True):
                    self.wheel(combo)
                self.assertEqual(combo.currentIndex(), 1)
                combo.setCurrentIndex(0)
                self.assertEqual(combo.currentIndex(), 0)
            finally:
                sip.delete(combo)
        finally:
            sip.delete(control)


if __name__ == '__main__':
    unittest.main()
