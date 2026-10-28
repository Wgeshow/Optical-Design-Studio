"""Study discovery and searchable paper cases, without running on selection."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSplitter, QStackedWidget, QTabWidget, QVBoxLayout, QWidget)
from qt_research_common import button, label
from qt_common import COLORS, theme_manager


STUDIES = (
    ('sesame_transport', 'Semiconductor transport', 'J–V curves, carriers and energy bands',
     'Edit a 1D junction or 2D device, its materials, contacts, illumination and grain boundaries.'),
    ('thermal', 'Temperature & heat flow', 'Temperature maps and heat balance',
     'Assign power, thermal materials and cooling boundaries to the device drawn in Structure.'),
    ('pcsel', 'PCSEL optical & aperture studies', 'Vertical modes, unit-cell optics, finite modes and beams',
     'Build an editable layer stack and crystal pattern. Choose the optical or aperture model to calculate.'),
    ('pcsel_transport', 'PCSEL periodic transport', 'Conformal unit-cell current and carrier maps',
     'Edit the periodic cell, layers, circular inclusions, material properties and top/bottom contacts.'),
    ('pcsel_unitcell_transport', 'PCSEL representative cell', 'Transport in the shared device',
     'Use the drawn cell and contacts with insulating side faces, explicit material laws and bias steps.'),
    ('advanced_transport', 'Finite contacts & coupled physics', 'Transport, heating and optical sensitivity',
     'Add explicit contact/interface resistivity and optional recombination, temperature feedback or tunnelling.'),
    ('high_field_optics', 'High-field optical response', 'Absorption and changes in refractive index',
     'Edit the material, electric fields, carrier states and wavelengths for an optical sensitivity study.'),
    ('lumped_laser', 'Steady-state laser estimate', 'Threshold, L–I, heuristic modulation and lumped temperature',
     'Edit supplied mode, gain, recombination and thermal parameters for a steady-state estimate with carrier clamping.'),
)


class StudyLibrary(QWidget):
    engineRequested = pyqtSignal(str)
    simulationRequested = pyqtSignal(str)
    routeRequested = pyqtSignal(dict)

    def __init__(self, benchmarks, duplicate, run_reference, note, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        layout.addWidget(self.tabs)
        from qt_simulation_picker import SimulationPicker
        self.picker = SimulationPicker()
        self.picker.simulationRequested.connect(self._open_choice)
        self.tabs.addTab(self.picker, 'Simulation setups')

        paper = QWidget()
        page = QVBoxLayout(paper)
        page.setContentsMargins(16, 18, 16, 18)
        page.addWidget(label('Start from a paper', 'setupHeading'))
        page.addWidget(label('Open a reference as an editable setup. The original paper case stays available for comparison.'))
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Search paper, figure or simulation…')
        self.search.setAccessibleName('Search paper simulations')
        self.family = QComboBox()
        self.family.setAccessibleName('Paper simulation family')
        filters.addWidget(self.search, 2)
        filters.addWidget(self.family, 1)
        page.addLayout(filters)
        self.benchmarks = benchmarks
        self.benchmarks.setMinimumHeight(34)
        page.addWidget(benchmarks)
        self.count = label('')
        page.addWidget(self.count)
        self.paper_title = label('', 'setupHeading')
        page.addWidget(self.paper_title)
        self.paper_details = label('')
        page.addWidget(self.paper_details)
        self.paper_scope = label('')
        page.addWidget(self.paper_scope)
        actions = QHBoxLayout()
        self.edit_button = button('Open editable setup', duplicate)
        self.reference_button = button('Run original reference', run_reference)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.reference_button)
        actions.addStretch()
        page.addLayout(actions)
        page.addWidget(note)
        page.addStretch()
        self.paper_scroll=QScrollArea();self.paper_scroll.setWidgetResizable(True)
        self.paper_scroll.setFrameShape(QFrame.Shape.NoFrame);self.paper_scroll.setWidget(paper)
        self.tabs.addTab(self.paper_scroll, 'Paper library')
        # Keep the original combo as a stable programmatic selection adapter.
        # Users browse the searchable reference list beside its source details.
        self.benchmarks.hide()
        page.removeWidget(self.benchmarks)
        self.paper_splitter = QSplitter(Qt.Orientation.Horizontal)
        page.insertWidget(3, self.paper_splitter, 1)
        listing = QWidget(); listing.setObjectName('studyCard')
        listing_layout = QVBoxLayout(listing)
        listing_layout.addWidget(label('References', 'setupHeading'))
        self.case_list = QListWidget()
        self.case_list.setObjectName('paperReferenceList')
        self.case_list.setAccessibleName('Paper references')
        self.case_list.setWordWrap(True)
        self.case_list.currentRowChanged.connect(self._paper_selected)
        listing_layout.addWidget(self.case_list)
        page.removeWidget(self.count);listing_layout.addWidget(self.count)
        self.paper_splitter.addWidget(listing)
        source_panel = QWidget(); source_panel.setObjectName('studyCard')
        source_layout = QVBoxLayout(source_panel)
        source_layout.addWidget(label('Selected reference', 'setupHeading'))
        for item in (self.paper_title,self.paper_details,self.paper_scope):
            page.removeWidget(item);source_layout.addWidget(item)
        self.source_link=label('');self.source_link.setOpenExternalLinks(True)
        source_layout.addWidget(self.source_link);source_layout.addStretch()
        source_scroll=QScrollArea();source_scroll.setWidgetResizable(True);source_scroll.setWidget(source_panel)
        self.paper_splitter.addWidget(source_scroll)
        editable = QWidget();editable.setObjectName('studyCard')
        editable_layout=QVBoxLayout(editable)
        editable_layout.addWidget(label('Editable setup', 'setupHeading'))
        from qt_custom_device import DeviceCanvas
        self.paper_preview=DeviceCanvas('3d');self.paper_preview.set_render_quality('flat')
        self.paper_preview.setMinimumSize(0,180)
        self.paper_views=QStackedWidget()
        self.paper_views.addWidget(self.paper_preview)
        from qt_device_builder import GeometryViewport
        self.optical_preview=GeometryViewport();self.optical_preview.setMinimumSize(0,180)
        self.paper_views.addWidget(self.optical_preview)
        from qt_photonic_crystal_3d import PhotonicCrystal3D
        self.crystal_preview=PhotonicCrystal3D();self.crystal_preview.setMinimumSize(0,180)
        self.paper_views.addWidget(self.crystal_preview)
        editable_layout.addWidget(self.paper_views,1)
        self.copy_description=label('')
        editable_layout.addWidget(self.copy_description)
        editable_layout.addStretch(1)
        actions.removeWidget(self.edit_button);actions.removeWidget(self.reference_button)
        editable_layout.addWidget(self.edit_button);editable_layout.addWidget(self.reference_button)
        self.paper_splitter.addWidget(editable)
        self.paper_splitter.setSizes([240,480,330])
        self.paper_splitter.setChildrenCollapsible(False)
        from qt_journey import JourneyBar
        self.paper_journey = JourneyBar([
            dict(title='Find reference', icon='paper', description='Choose the paper and figure you want to reproduce.'),
            dict(title='Inspect scope', icon='info', description='Review source conventions, model limits and the structure before making an editable copy.'),
            dict(title='Open editable setup', icon='cube', description='Continue in the selected simulation’s structure, parameters, checks and run steps. Its source metadata stays attached.')], paper)
        page.insertWidget(0, self.paper_journey)
        self._paper_stage = 0
        self.paper_journey.stageRequested.connect(self._show_paper_stage)
        self.reference_button.setText('Run unchanged reference')
        self.reference_button.setToolTip('Run the original registered inputs. To change the structure or parameters, open the editable setup first.')
        self.paper_journey.set_current(0)
        self._cases = []
        self.search.textChanged.connect(self.filter_cases)
        self.family.currentIndexChanged.connect(self.filter_cases)
        benchmarks.currentIndexChanged.connect(self.describe_case)
        theme_manager().appearance_changed.connect(self.apply_theme)
        theme_manager().changed.connect(self.apply_theme)
        self.apply_theme()
        self.adapt_layout()

    def apply_theme(self):
        colors = COLORS[theme_manager().mode]
        from qt_reference_style import reference_icon
        self.edit_button.setIcon(reference_icon('plus',colors['accent']))
        self.reference_button.setIcon(reference_icon('play',colors['accent']))
        for i in range(self.case_list.count()):self.case_list.item(i).setIcon(reference_icon('paper',colors['accent']))
        self.setStyleSheet('''
            QWidget#studyCard { background: %(panel)s; border: 1px solid %(border)s; border-radius: 8px; }
            QWidget#studyCard QLabel { background: transparent; border: 0; }
            QLabel#studyCardTitle { font-size: 16px; font-weight: 600; color: %(text)s; }
            QLabel#studyCardResult { font-size: 12px; color: %(muted)s; }
            QListWidget#paperReferenceList::item { padding: 8px; }
            QListWidget#paperReferenceList::item:selected { background: %(select)s; color: %(text)s; border-radius: 4px; }
        ''' % colors)

    def set_cases(self, cases):
        self._cases = cases
        old = self.family.currentData()
        self.family.blockSignals(True)
        self.family.clear()
        self.family.addItem('All families', '')
        for value in sorted({row.get('family', 'Other') for row in cases}):
            self.family.addItem(value, value)
        self.family.setCurrentIndex(max(0, self.family.findData(old)))
        self.family.blockSignals(False)
        self.filter_cases()

    def filter_cases(self, *args):
        previous = self.benchmarks.currentData()
        needle = self.search.text().strip().casefold()
        family = self.family.currentData()
        self.benchmarks.blockSignals(True)
        self.benchmarks.clear()
        for row in self._cases:
            source = row.get('source', {})
            text = ' '.join(str(value) for value in (row.get('label', ''), row['id'], row.get('family', ''), source.get('title', ''), source.get('figure', '')))
            if (not family or row.get('family') == family) and (not needle or needle in text.casefold()):
                self.benchmarks.addItem(row.get('label', row['id']).replace('_', ' '), row['id'])
        self.benchmarks.setCurrentIndex(max(0, self.benchmarks.findData(previous)))
        self.benchmarks.blockSignals(False)
        self.count.setText(str(self.benchmarks.count())+' of '+str(len(self._cases))+' paper setups')
        self.edit_button.setEnabled(bool(self.benchmarks.count()))
        self.reference_button.setEnabled(bool(self.benchmarks.count()))
        from qt_reference_style import reference_icon
        self.case_list.blockSignals(True);self.case_list.clear()
        for index in range(self.benchmarks.count()):
            item=QListWidgetItem(reference_icon('paper',COLORS[theme_manager().mode]['accent']),self.benchmarks.itemText(index))
            item.setData(Qt.ItemDataRole.UserRole,self.benchmarks.itemData(index));self.case_list.addItem(item)
        self.case_list.setCurrentRow(self.benchmarks.currentIndex());self.case_list.blockSignals(False)
        self.describe_case()

    def _paper_selected(self,index):
        if index>=0:self.benchmarks.setCurrentIndex(index)

    def describe_case(self, *args):
        row = next((row for row in self._cases if row['id'] == self.benchmarks.currentData()), None)
        if row is None:
            self.paper_title.setText('No matching paper setup')
            self.paper_details.clear()
            self.paper_scope.clear()
            self.source_link.clear();self.copy_description.clear();self.paper_views.hide()
            return
        self.case_list.blockSignals(True);self.case_list.setCurrentRow(self.benchmarks.currentIndex());self.case_list.blockSignals(False)
        source = row.get('source', {})
        self.paper_title.setText(source.get('title', row.get('label', row['id'])))
        self.paper_details.setText(' · '.join(str(value) for value in (row.get('family'), source.get('figure'), source.get('doi')) if value))
        limitations = row.get('limitations', [])
        self.paper_scope.setText('\n'.join(limitations) if limitations else 'Reference inputs and source conventions are retained when you open this setup. Results show agreement and convergence separately.')
        from html import escape
        url=source.get('url') or ('https://doi.org/'+source['doi'] if source.get('doi') else '')
        self.source_link.setText('<a href="'+escape(url,quote=True)+'">Open source paper ↗</a>' if url.startswith(('https://','http://')) else '')
        from benchmark_registry import load_benchmark
        try:
            case=load_benchmark(row['id']);options=case.get('options',{})
            # Each preview uses its owning document, never the unrelated finite
            # device snapshot that may also travel with a paper project.
            device=options.get('device') if case.get('kind')=='electrical' else None
            self.paper_views.hide()
            if device:
                self.paper_preview.set_device(device);self.paper_views.setCurrentIndex(0);self.paper_views.show()
            elif options.get('engine')=='pcsel':
                from qt_pcsel_research_setup import pcsel_preview_device
                cfg=options['settings'];period=cfg['lattice_nm']
                device,_=pcsel_preview_device(cfg['layers'],cfg['shapes'],[period,period])
                self.paper_preview.set_device(device);self.paper_views.setCurrentIndex(0);self.paper_views.show()
            elif case.get('kind')=='simulation':
                from types import SimpleNamespace
                import pandas as pd
                project=case['project']
                model=SimpleNamespace(layers=pd.DataFrame(project['layers']),patterns=pd.DataFrame(project['patterns']),
                    settings=project['settings'],appearance=project.get('appearance',{}))
                self.optical_preview.set_model(model,'',1);self.paper_views.setCurrentIndex(1);self.paper_views.show()
            elif options.get('engine')=='photonic_bands' and options['settings'].get('dimension')==3:
                self.crystal_preview.set_crystal(options['settings']);self.paper_views.setCurrentIndex(2);self.paper_views.show()
            self.copy_description.setText('Source: '+row['id'].replace('_',' ')+'\n\n'
                'Open this reference to edit its structure, materials and calculation parameters. '
                'Its source and comparison metadata stay attached to the editable copy.\n\n'
                'Original reference inputs remain available separately.')
        except (OSError,ValueError,KeyError) as exc:
            self.paper_views.hide();self.copy_description.setText('Reference preview unavailable: '+str(exc))

    def _open_choice(self, target):
        if target == 'papers':
            self.tabs.setCurrentIndex(1)
        else:
            self.simulationRequested.emit(target)

    def _show_paper_stage(self, index):
        self._paper_stage = index
        self.paper_journey.set_current(index)
        self.adapt_layout()

    def adapt_layout(self):
        if hasattr(self, 'picker'):
            self.picker.adapt_layout()
        if hasattr(self,'paper_splitter'):
            compact=self.width()<1050
            stage=getattr(self,'_paper_stage',0)
            self.paper_splitter.widget(0).setVisible(stage==0)
            self.paper_splitter.widget(1).setVisible(stage in (0,1))
            self.paper_splitter.widget(2).setVisible(stage in (1,2))
            self.paper_splitter.setOrientation(Qt.Orientation.Vertical if compact else Qt.Orientation.Horizontal)
            self.case_list.setMaximumHeight(150 if compact else 16777215)
            self.paper_splitter.setMinimumHeight(520 if compact and stage!=2 else 0)
            for index,height in enumerate((190,230,240)):
                self.paper_splitter.widget(index).setMinimumHeight(height if compact else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.adapt_layout()
