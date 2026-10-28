"""Automatic-setup controls must never transiently become panel windows."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtCore import QObject, QEvent
from PyQt6.QtWidgets import QApplication, QPushButton, QWidget
from qt_solver_environment import SolverEnvironmentSetup

APP = QApplication.instance() or QApplication([])


class SolverSetupOwnershipTests(unittest.TestCase):
    def check_launcher(self, platform, visible):
        events = []
        class Observer(QObject):
            def eventFilter(self, widget, event):
                if (event.type() == QEvent.Type.Show and isinstance(widget, QPushButton)
                        and widget.isWindow()):
                    events.append(dict(text=widget.text(), parent=widget.parentWidget()))
                return False
        observer = Observer(); APP.installEventFilter(observer)
        host = QWidget()
        try:
            with patch('qt_solver_environment.os.name', platform):
                setup = SolverEnvironmentSetup(lambda: {}, host)
            self.assertEqual(events, [], 'A control was shown before it belonged to its setup panel.')
            self.assertIs(setup.launcher_button.parentWidget(), setup)
            self.assertFalse(setup.launcher_button.isWindow())
            host.show(); setup.show(); APP.processEvents()
            self.assertEqual(setup.launcher_button.isVisible(), visible)
            self.assertEqual(events, [])
        finally:
            APP.removeEventFilter(observer)
            host.close(); host.deleteLater(); APP.processEvents()

    def test_windows_launcher_is_owned_before_visible(self):
        self.check_launcher('nt', True)

    def test_other_platform_launcher_stays_hidden(self):
        self.check_launcher('posix', False)


if __name__ == '__main__':
    unittest.main()
