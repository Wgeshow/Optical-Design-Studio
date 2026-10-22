"""Direct, searchable entry points shared by startup and the simulation library."""
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)
from qt_common import COLORS, theme_manager

# Stable destinations; selecting one opens an editor and never starts a job.
SIMULATIONS = (
    ('optical', 'Optical spectrum', 'Optical', 'Reflection, transmission and absorption · S4'),
    ('fdtd', 'Time-domain optics', 'Optical', 'Sources, boundaries and time-domain fields · MEEP'),
    ('tools.index_shift', 'Refractive-index sweep', 'Optical', 'Optical response across editable index changes'),
    ('tools.fields', 'Optical fields & phase', 'Optical', 'Electric and magnetic fields and spectral phase'),
    ('tools.sweep', 'Simulation parameter sweep', 'Optical', 'Every selected parameter combination, raw spectra and Q / R / T / A analysis'),
    ('tools.ai', 'AI optical search', 'Optical', 'Independent editable optical design and model-assisted search'),
    ('photonic_bands', '3D Photonic Bands', 'Photonic crystals', 'Fully 3D editable periodic crystals · MPB'),
    ('photonic_bands.2d', '2D Photonic Bands', 'Photonic crystals', 'Editable two-dimensional periodic crystals · MPB'),
    ('photonic_bands.legume', '2D bands · Legume', 'Photonic crystals', 'Plane-wave bands for an infinite cross-section'),
    ('electrical', 'Electrical device · DC', 'Electrical & heat', 'Device potential, carriers and terminal current'),
    ('electrical.iv', 'Current–voltage sweep', 'Electrical & heat', 'Editable device and terminal bias schedule'),
    ('electrical.cv', 'Capacitance–voltage sweep', 'Electrical & heat', 'Editable device, voltage points and charge derivative'),
    ('coupled', 'Coupled electrical & optical', 'Electrical & heat', 'Bias-dependent carriers and optical response'),
    ('sesame_transport', '1D Semiconductor transport', 'Electrical & heat', 'Editable junction, material regions and contacts'),
    ('sesame_transport.2d', '2D Semiconductor transport', 'Electrical & heat', 'Editable 2D junctions and grain boundaries'),
    ('thermal', 'Temperature & heat flow', 'Electrical & heat', 'Device power, thermal materials and cooling'),
    ('advanced_transport', 'Finite-contact transport', 'Electrical & heat', 'Contacts, interfaces and optional coupled physics'),
    ('high_field_optics', 'High-field optical response', 'Optical', 'Field-dependent absorption and refractive index'),
    ('pcsel.vertical', 'PCSEL vertical modes', 'PCSEL', 'Layer stack, waveguide modes and confinement'),
    ('pcsel.cwt', 'PCSEL coupled-wave modes', 'PCSEL', 'Periodic crystal coupling and band-edge modes'),
    ('pcsel.finite', 'PCSEL finite-area modes', 'PCSEL', 'Finite cavity, boundary conditions and mode selection'),
    ('pcsel.beam', 'PCSEL far-field beam', 'PCSEL', 'Angular emission from a finite optical mode'),
    ('pcsel.aperture', 'PCSEL aperture response', 'PCSEL', 'Source-bound carrier, thermal and rate model'),
    ('pcsel.gme', 'PCSEL guided-mode expansion', 'PCSEL', 'Slab crystal modes and radiation · Legume'),
    ('pcsel.rcwa_poles', 'PCSEL RCWA resonances', 'PCSEL', 'Optical resonances of an editable unit cell · S4'),
    ('pcsel_transport', 'PCSEL periodic transport', 'PCSEL', 'Conformal periodic cell, carriers and current'),
    ('pcsel_unitcell_transport', 'PCSEL representative cell', 'PCSEL', 'Drawn device cell with insulating side faces'),
    ('lumped_laser', 'Laser rate equations', 'PCSEL', 'Threshold, light–current response and modulation'),
    ('papers', 'Paper comparisons', 'Paper library', 'Open any of the 24 references as an editable setup'),
)


class SimulationPicker(QWidget):
    simulationRequested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('simulationPicker')
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Find a simulation…')
        self.search.setAccessibleName('Find a simulation')
        self.family = QComboBox()
        self.family.setAccessibleName('Simulation family')
        self.family.addItem('All simulations', '')
        for family in dict.fromkeys(row[2] for row in SIMULATIONS):
            self.family.addItem(family, family)
        filters.addWidget(self.search, 3)
        filters.addWidget(self.family, 1)
        root.addLayout(filters)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        self.grid = QGridLayout(body)
        self.grid.setContentsMargins(0, 6, 6, 6)
        self.grid.setSpacing(10)
        self.buttons = {}
        self.cards = {}
        for target, title, family, description in SIMULATIONS:
            # Filtering sets visibility before the first grid insertion. Own
            # cards immediately so Qt cannot briefly show each as a window.
            card = QFrame(body)
            card.setObjectName('simulationCard')
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            content = QVBoxLayout(card)
            content.setContentsMargins(14, 12, 14, 12)
            action = QPushButton(title.replace('&', '&&'))
            action.setObjectName('simulationChoice')
            action.setAccessibleName('Open '+title)
            action.setAutoDefault(False)
            action.setCursor(Qt.CursorShape.PointingHandCursor)
            action.clicked.connect(lambda checked=False, value=target: self.simulationRequested.emit(value))
            caption = QLabel(description)
            caption.setObjectName('simulationDescription')
            caption.setWordWrap(True)
            content.addWidget(action)
            content.addWidget(caption)
            content.addStretch()
            self.cards[target] = card
            self.buttons[target] = action
        self.empty = QLabel('No matching simulations. Try another name or family.', body)
        self.empty.setWordWrap(True)
        self.scroll.setWidget(body)
        root.addWidget(self.scroll, 1)
        self.search.textChanged.connect(self.adapt_layout)
        self.family.currentIndexChanged.connect(self.adapt_layout)
        theme_manager().appearance_changed.connect(self.apply_theme)
        theme_manager().changed.connect(self.apply_theme)
        self.apply_theme()
        self.adapt_layout()

    def apply_theme(self):
        colors = COLORS[theme_manager().mode]
        from qt_reference_style import reference_icon
        for target, action in self.buttons.items():
            icon=('paper' if target=='papers' else 'bands' if target.startswith('photonic_bands')
                  else 'thermal' if target=='thermal' else 'transport' if 'transport' in target or target.startswith('electrical') or target=='coupled'
                  else 'pattern' if target.startswith('pcsel.') else 'field' if 'fields' in target
                  else 'mesh' if target=='fdtd' else 'spectrum')
            action.setIcon(reference_icon(icon, colors['accent']))
            action.setIconSize(QSize(28, 28))
        self.setStyleSheet('''
            QFrame#simulationCard { background: %(panel)s; border: 1px solid %(border)s; border-radius: 8px; }
            QFrame#simulationCard QLabel { background: transparent; color: %(muted)s; }
            QPushButton#simulationChoice { text-align: left; background: transparent; border: 0;
                padding: 3px 0; color: %(text)s; font-size: 15px; font-weight: 600; }
            QPushButton#simulationChoice:hover { color: %(accent)s; }
            QPushButton#simulationChoice:focus { border: 1px solid %(accent)s; border-radius: 4px; }
            QLabel#simulationDescription { font-size: 12px; }
        ''' % colors)

    def adapt_layout(self, *args):
        needle = self.search.text().strip().casefold()
        family = self.family.currentData()
        visible = [row[0] for row in SIMULATIONS if (not family or family == row[2])
                   and (not needle or needle in ' '.join(row).casefold())]
        columns = 3 if self.width() >= 1250 else 2 if self.width() >= 880 else 1
        while self.grid.count():
            self.grid.takeAt(0)
        for row in range(self.grid.rowCount()):
            self.grid.setRowStretch(row, 0)
        for target, card in self.cards.items():
            card.setVisible(target in visible)
        for i, target in enumerate(visible):
            self.grid.addWidget(self.cards[target], i//columns, i%columns)
        self.empty.setVisible(not visible)
        if not visible:
            self.grid.addWidget(self.empty, 0, 0, 1, columns)
        for column in range(3):
            self.grid.setColumnStretch(column, int(column < columns))
        self.grid.setRowStretch((len(visible)+columns-1)//columns, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.adapt_layout()
