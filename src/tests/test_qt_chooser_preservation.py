"""All 27 design routes select models while preserving authored input drafts."""
import os
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtTest import QTest
from qt_core import ProjectStore
from data_library import DataLibrary
from qt_app import OpticalStudio
from qt_simulation_picker import SIMULATIONS

APP=QApplication.instance() or QApplication([])


class ChooserPreservationTests(unittest.TestCase):
    def test_all_design_choices_preserve_geometry_raw_drafts_and_reference_identity(self):
        with tempfile.TemporaryDirectory(prefix='ods_27_routes_', dir=Path(__file__).resolve().parents[3]) as temporary:
            store=ProjectStore(DataLibrary(Path(temporary)/'library'),restore=False)
            window=OpticalStudio(store)
            try:
                before_device=copy.deepcopy(store.device)
                bands=window.photonic_bands_page
                bands.primitive_fields['radius'].setText('unfinished radius')
                bands.executable.setText('authored-runtime')
                bands._benchmark_request={'source':'authored-band-reference'}
                original_bands=bands.draft()
                chooser=window.research_studies_page
                chooser.select_engine('sesame_transport')
                sesame=chooser.stack.currentWidget()
                sesame.y_nodes.setText('0, 0.13, 0.49, 1.2')
                sesame.regions.item(0,2).setText('unfinished x range')
                sesame._benchmark_request={'source':'authored-transport-reference'}
                original_sesame=sesame.draft()
                window.setup_state.set('search.electrical.biases_V',[0.,-.123,-.456])
                self.assertEqual(len(SIMULATIONS),27)
                self.assertEqual(len({r[0] for r in SIMULATIONS}),27)
                with patch.object(store,'start_run') as start:
                    for target,_,_,_ in SIMULATIONS:
                        with self.subTest(target=target):
                            window._open_simulation_choice(target)
                            if target.startswith('photonic_bands'):
                                self.assertEqual(window.navigation.currentRow(),10)
                                self.assertEqual(bands.dimension.currentData(),3 if target=='photonic_bands' else 2)
                                self.assertEqual(bands.solver.currentData(),'legume' if target.endswith('.legume') else 'mpb')
                                saved=bands.draft()
                                for key in ('lattice','geometry','object_ids','epsilons','kpoints','benchmark_request'):
                                    self.assertEqual(saved.get(key),original_bands.get(key),key)
                                self.assertEqual(bands.executable.text(),'authored-runtime')
                            elif target.startswith('sesame_transport'):
                                self.assertIs(chooser.stack.currentWidget(),sesame)
                                self.assertEqual(sesame.dimension.currentData(),2 if target.endswith('.2d') else 1)
                                saved=sesame.draft()
                                for key in ('regions','materials','contacts','defects','benchmark_request'):
                                    self.assertEqual(saved.get(key),original_sesame.get(key),key)
                                self.assertEqual(sesame.y_nodes.text(),'0, 0.13, 0.49, 1.2')
                            elif target in ('electrical','electrical.iv','electrical.cv'):
                                self.assertEqual(window.setup_state.get('ui.electrical.study'),{'electrical':'bias','electrical.iv':'iv','electrical.cv':'cv'}[target])
                                self.assertEqual(window.setup_state.get('search.electrical.biases_V'),[0.,-.123,-.456])
                                self.assertEqual(window.electrical_page.current_section,'electrical.study')
                            elif target.startswith('pcsel.'):
                                self.assertEqual(chooser.stack.currentWidget().fields['model'].currentData(),target.split('.')[1])
                                if target=='pcsel.finite':
                                    # Importing a paper opens the new build
                                    # editor, not the emptied legacy Study tab.
                                    from pcsel_research import paper_example
                                    cfg=paper_example('hole','CC',.16);cfg['model']='finite'
                                    page=chooser.stack.currentWidget();page.load_settings(cfg)
                                    self.assertEqual(page.tabs.currentIndex(),page.sections['design'])
                                    self.assertEqual(page.options()['settings']['layers'],cfg['layers'])
                            elif target=='papers':self.assertEqual(chooser.library_page.tabs.currentIndex(),1)
                            elif target in ('optical','coupled','fdtd','tools.fields','tools.index_shift'):
                                self.assertEqual(window.navigation.currentRow(),2)
                            else:self.assertEqual(chooser.selector.currentData(),target)
                            self.assertEqual(store.device,before_device)
                    start.assert_not_called()
                # A direct I-V/C-V choice cannot silently replace the legacy
                # paper model or discard its explicitly authored sweep values.
                from electrical_solver import DEFAULT_OPTIONS
                legacy=copy.deepcopy(DEFAULT_OPTIONS);legacy['biases_V']=[0.,-.37]
                store.save_search('electrical',legacy)
                before=copy.deepcopy(store.search_state['electrical'])
                for target in ('electrical.iv','electrical.cv'):
                    window._open_simulation_choice(target)
                    self.assertEqual(store.search_state['electrical'],before)
                    self.assertEqual(window.electrical_page.current_section,'electrical.study')
                    self.assertIn('editable',window.status.text().lower())
                self.assertEqual(store.device,before_device)
                # On a compact window the paper details and both launch
                # actions remain reachable through the outer page scroll.
                window._open_simulation_choice('papers')
                window.resize(800,760);window.show();window.adapt_interface();QTest.qWait(80)
                library=chooser.library_page;library.adapt_layout();APP.processEvents()
                self.assertEqual(library.paper_scroll.horizontalScrollBar().maximum(),0)
                self.assertGreaterEqual(library.paper_splitter.widget(1).height(),180)
                for action in (library.edit_button,library.reference_button):
                    library.paper_scroll.ensureWidgetVisible(action);APP.processEvents()
                    center=action.mapTo(library.paper_scroll.viewport(),action.rect().center())
                    self.assertTrue(library.paper_scroll.viewport().rect().contains(center))
            finally:
                window._force_close=True;window.hide();window.deleteLater()
                APP.processEvents();QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)


if __name__=='__main__':unittest.main()
