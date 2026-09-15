"""Persistent appearance controls, independent from solver settings."""
from PyQt6.QtCore import Qt, QSignalBlocker
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QComboBox, QSlider, QCheckBox, QLabel
from qt_common import theme_manager, button, note


class AppearancePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = theme_manager()
        layout = QVBoxLayout(self)
        layout.addWidget(note('Customize the interface. Changes apply immediately and are saved on this computer.'))
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.theme = QComboBox()
        self.theme.addItem('Dark mode', 'dark')
        self.theme.addItem('Light mode', 'light')
        self.theme.setAccessibleName('Color theme')
        form.addRow('Theme', self.theme)
        self.scale = QSlider(Qt.Orientation.Horizontal)
        self.scale.setRange(80, 140)
        self.scale.setSingleStep(5)
        self.scale.setAccessibleName('Interface size percentage')
        self.scale.setTracking(False)
        self.value = QLabel()
        form.addRow('Interface size', self.scale)
        form.addRow('', self.value)
        layout.addLayout(form)
        self.adaptive = QCheckBox('Adapt layout and control size to the window')
        layout.addWidget(self.adaptive)
        layout.addWidget(note('Smaller windows use compact navigation and stacked panels. Large tables remain scrollable. Windows display scaling is respected automatically.'))
        layout.addWidget(button('Reset appearance', self.reset))
        layout.addStretch()
        self.theme.currentIndexChanged.connect(lambda: self.manager.apply(self.theme.currentData()))
        self.scale.valueChanged.connect(lambda value: self.manager.set_appearance(scale=value))
        self.adaptive.toggled.connect(lambda value: self.manager.set_appearance(adaptive=value))
        self.manager.changed.connect(self.refresh)
        self.refresh()

    def refresh(self, *_):
        for widget, value in ((self.theme, self.theme.findData(self.manager.mode)),
                              (self.scale, self.manager.scale), (self.adaptive, self.manager.adaptive)):
            with QSignalBlocker(widget):
                if widget is self.theme:
                    widget.setCurrentIndex(value)
                elif widget is self.scale:
                    widget.setValue(value)
                else:
                    widget.setChecked(value)
        self.value.setText(f'{self.manager.scale}% · range 80–140%')

    def reset(self):
        self.manager.set_appearance(scale=100, adaptive=True)
        self.manager.apply('dark')
