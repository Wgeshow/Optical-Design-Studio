"""All 28 study/tool documents and the paper library preserve independent setups."""
import os
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtWidgets import QApplication, QDialog
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtTest import QTest
from qt_core import ProjectStore
from data_library import DataLibrary
from qt_app import OpticalStudio
from qt_simulation_picker import SIMULATIONS
from qt_study_transfer import StudyTransferDialog
from simulation_documents import STUDY_IDS

APP=QApplication.instance() or QApplication([])


class ChooserPreservationTests(unittest.TestCase):
    def test_choices_restore_own_geometry_incomplete_drafts_and_reference_identity(self):
        with tempfile.TemporaryDirectory(prefix='ods_29_routes_', dir=Path(__file__).resolve().parents[3]) as temporary:
            with patch.dict(os.environ,S4_LIBRARY_ROOT=str(Path(temporary)/'preferences')):
                store=ProjectStore(DataLibrary(Path(temporary)/'library'),restore=False)
                window=OpticalStudio(store)
            try:
                chooser=window.research_studies_page
                original_width=store.device['width_um']
                authored={};pages={};diagnostics={};widths={}
                self.assertEqual(len(STUDY_IDS),28)
                self.assertEqual(len(SIMULATIONS),29)
                self.assertEqual({row[0] for row in SIMULATIONS},set(STUDY_IDS)|{'papers'})

                def open_study(target):
                    window._open_simulation_choice(target);APP.processEvents()
                    self.assertEqual(store.active_study,target)
                    if target.startswith('photonic_bands'):return window.photonic_bands_page
                    if target.startswith('electrical'):return window.electrical_page
                    if target.startswith(('sesame_transport','pcsel.')):return chooser.stack.currentWidget()
                    return None

                def raw_inputs(target,page):
                    draft=page.draft()
                    keys=(('lattice','geometry','object_ids','epsilons','kpoints','benchmark_request')
                        if target.startswith('photonic_bands') else
                        ('regions','materials','contacts','defects','benchmark_request')
                        if target.startswith('sesame_transport') else ('structured','benchmark_request'))
                    return {**{key:copy.deepcopy(draft.get(key)) for key in keys},
                        'fields':copy.deepcopy(draft['fields'])}

                with patch.object(store,'start_run') as start:
                    for index,target in enumerate(STUDY_IDS):
                        with self.subTest(first_visit=target):
                            page=open_study(target)
                            # A new choice does not receive the preceding edited device.
                            self.assertEqual(store.device['width_um'],original_width)
                            widths[target]=20.+index
                            store.update_settings(dict(ax_um=widths[target],wl_start_nm=1300.+index))
                            if page is not None:
                                self.assertNotIn(page,pages.values())
                                pages[target]=page
                                self.assertEqual(page.diagnostics.list.count(),0)
                                diagnostics[target]=page.diagnostics
                                self.assertEqual(len({id(value) for value in diagnostics.values()}),len(diagnostics))
                            if target.startswith('photonic_bands'):
                                self.assertEqual(window.navigation.currentRow(),10)
                                self.assertEqual(page.dimension.currentData(),3 if target=='photonic_bands' else 2)
                                self.assertEqual(page.solver.currentData(),'legume' if target.endswith('.legume') else 'mpb')
                                page.primitive_fields['radius'].setText('unfinished radius '+target)
                                page.executable.setText('authored-runtime-'+target)
                            elif target.startswith('sesame_transport'):
                                self.assertEqual(page.dimension.currentData(),2 if target.endswith('.2d') else 1)
                                page.y_nodes.setText('0, 0.13, 0.49, '+str(1.2+index))
                                page.regions.item(0,2).setText('unfinished x range '+target)
                            elif target.startswith('pcsel.'):
                                self.assertEqual(page.fields['model'].currentData(),target.split('.')[1])
                                page.fields['lattice_nm'].setText(str(400+index))
                                page.fields['harmonics'].setText('unfinished harmonics '+target)
                            elif target.startswith('electrical'):
                                self.assertEqual(window.setup_state.get('ui.electrical.study'),
                                    {'electrical':'bias','electrical.iv':'iv','electrical.cv':'cv'}[target])
                                page.drafts['ui.electrical.bias_list_text']='0, unfinished '+target
                                page.flush_draft()
                                authored[target]=copy.deepcopy(page.drafts)
                            if page is not None and not target.startswith('electrical'):
                                page._benchmark_request={'source':'authored-reference-'+target}
                                page.flush_draft()
                                authored[target]=raw_inputs(target,page)
                                page.diagnostics.set_diagnostics([dict(code='private',severity='error',
                                    message='Only '+target,workspace=page.workspace_id)])

                    for target in STUDY_IDS:
                        with self.subTest(return_visit=target):
                            page=open_study(target)
                            self.assertEqual(store.device['width_um'],widths[target])
                            if page is not None:
                                self.assertIs(page,pages[target])
                                if target.startswith('electrical'):
                                    self.assertEqual(page.drafts,authored[target])
                                else:
                                    self.assertEqual(raw_inputs(target,page),authored[target])
                                    self.assertEqual(page.diagnostics.list.count(),1)
                                    self.assertIn('Only '+target,page.diagnostics.list.item(0).text())

                    # Only explicit Transfer inputs copies a compatible structure.
                    open_study('electrical.iv')
                    store.update_settings(dict(wl_start_nm=1661.))
                    window.setup_state.set('device.mesh.nx',17)
                    dialog=StudyTransferDialog(store,window)
                    self.assertGreaterEqual(dialog.source.findData('optical'),0)
                    self.assertEqual(dialog.source.findData('photonic_bands'),-1)
                    dialog.source.setCurrentIndex(dialog.source.findData('optical'))
                    with patch('qt_study_transfer.StudyTransferDialog',return_value=dialog):
                        with patch.object(dialog,'exec',return_value=QDialog.DialogCode.Accepted):
                            window.transfer_inputs_button.click()
                    self.assertEqual(store.device['width_um'],widths['optical'])
                    self.assertEqual(store.settings['wl_start_nm'],1661.)
                    self.assertEqual(store.device['mesh']['nx'],17)
                    self.assertEqual(store.study_project('optical')['device']['width_um'],widths['optical'])
                    current=copy.deepcopy(store.project())
                    with self.assertRaisesRegex(ValueError,'compatible structure'):
                        store.transfer_study_inputs('photonic_bands')
                    self.assertEqual(store.project(),current)
                    dialog.deleteLater()
                    store.update_settings(dict(ax_um=99.))
                    self.assertEqual(store.study_project('optical')['device']['width_um'],widths['optical'])
                    start.assert_not_called()
                # Papers is a library destination, not another simulation document.
                active=store.active_study
                window._open_simulation_choice('papers')
                self.assertEqual(store.active_study,active)
                self.assertEqual(chooser.library_page.tabs.currentIndex(),1)
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
