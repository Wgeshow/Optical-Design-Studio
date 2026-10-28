"""Direct, searchable entry points shared by startup and the simulation library."""
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)
from qt_common import COLORS, theme_manager

# Stable destinations; selecting one opens an editor and never starts a job.
SIMULATIONS = (
    ('optical', 'S4 · optical spectrum', 'Optical', 'Periodic RCWA · wavelength or angle sweeps, R / T / A, phase and fields'),
    ('fdtd', 'Meep · time-domain optics', 'Optical', 'FDTD · broadband pulse, reference normalization, grid, PML and stopping'),
    ('tools.index_shift', 'Refractive-index sweep', 'Optical', 'S4 · optical response across editable index changes'),
    ('tools.fields', 'Optical fields & phase', 'Optical', 'S4 · electric and magnetic fields and spectral phase'),
    ('tools.sweep', 'Simulation parameter sweep', 'Optical', 'S4 · every selected parameter combination, raw spectra and Q / R / T / A analysis'),
    ('tools.ai', 'AI optical search', 'Optical', 'S4 · independent editable optical design and model-assisted search'),
    ('photonic_bands', '3D Photonic Bands', 'Photonic crystals', 'Fully 3D editable periodic crystals · MPB'),
    ('photonic_bands.2d', '2D Photonic Bands', 'Photonic crystals', 'Editable two-dimensional periodic crystals · MPB'),
    ('photonic_bands.legume', '2D bands · Legume', 'Photonic crystals', 'Plane-wave bands for an infinite cross-section'),
    ('electrical', 'Electrical device · DC', 'Electrical & heat', 'Device potential, carriers and terminal current'),
    ('electrical.iv', 'Current–voltage sweep', 'Electrical & heat', 'Editable device and terminal bias schedule'),
    ('electrical.cv', 'Capacitance–voltage sweep', 'Electrical & heat', 'Editable device, voltage points and charge derivative'),
    ('coupled', 'Coupled electrical & optical', 'Electrical & heat', 'Electrical carriers → S4 periodic optical response; independent coupled device'),
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
    ('lumped_laser', 'Steady-state laser estimate', 'PCSEL', 'Threshold, light–current response and heuristic modulation'),
    ('papers', 'Paper comparisons', 'Paper library', 'Open any of the 24 references as an editable setup'),
)


CREATION_PATHS = {
    'optical':'Structure → illumination → spectrum sampling',
    'fdtd':'Domain → pulse → mesh and stopping',
    'tools.index_shift':'Materials and layers → index states → tracking',
    'tools.fields':'Excitation → sampling planes → field display',
    'tools.sweep':'Base design → parameter recipe → all combinations',
    'tools.ai':'Design space → collection → model and verification',
    'photonic_bands':'3D cell → dielectric objects → wavevectors',
    'photonic_bands.2d':'2D cell → inclusions → TE/TM bands',
    'photonic_bands.legume':'2D cell → permittivities → plane-wave modes',
    'electrical':'Device → contacts and charge → DC operating point',
    'electrical.iv':'Device → terminals → voltage schedule',
    'electrical.cv':'Device → electrodes → charge sampling',
    'coupled':'Finite device → S4 optical setup → carrier mapping → bias response',
    'sesame_transport':'1D junction → materials and end contacts → bias',
    'sesame_transport.2d':'2D domain → regions and defects → bias',
    'thermal':'Device → heat sources → cooling faces',
    'advanced_transport':'Finite contacts → interfaces → physical models',
    'high_field_optics':'Material → carrier and field states → spectrum',
    'pcsel.vertical':'Layer stack → waveguide → mode accuracy',
    'pcsel.cwt':'Crystal → coupling → band-edge modes',
    'pcsel.finite':'Crystal source → cavity → outgoing modes',
    'pcsel.beam':'Finite-mode source → angular sampling → beam',
    'pcsel.aperture':'Calibration → aperture and contacts → reduced physics',
    'pcsel.gme':'Slab crystal → guided modes → radiation',
    'pcsel.rcwa_poles':'Unit cell → complex seeds → resonance search',
    'pcsel_transport':'Periodic cell → materials and bias → conformal mesh',
    'pcsel_unitcell_transport':'Drawn cell → contact laws → insulating sides',
    'lumped_laser':'Supplied mode → gain and recombination → operating point',
    'papers':'Find reference → inspect scope → editable simulation',
}


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
        self.match_count=QLabel(self)
        self.match_count.setObjectName('simulationDescription')
        root.addWidget(self.match_count)
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
            path=QLabel(CREATION_PATHS[target],card)
            path.setWordWrap(True)
            path.setObjectName('simulationDescription')
            path.setAccessibleName(title+' setup path: '+CREATION_PATHS[target])
            content.addWidget(path)
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
        self.match_count.setText(f'{len(visible)} of {len(SIMULATIONS)} simulation workspaces · choose one to create or edit its setup')
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
