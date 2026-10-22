"""Every start choice reaches its editable model without running a calculation."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtCore import QSettings, QTimer, QObject, QEvent
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout
from qt_workspace_start import (WorkspaceStartDialog, WorkspaceSelection,
    choose_startup_workspace, STARTUP_SIMULATION_KEY)
from qt_simulation_picker import SIMULATIONS, SimulationPicker
from qt_core import ProjectStore
from data_library import DataLibrary
from qt_app import OpticalStudio

APP=QApplication.instance() or QApplication([])


class SimulationPickerTests(unittest.TestCase):
    def test_chooser_cards_never_show_as_separate_windows_even_briefly(self):
        shown=[]
        class WindowObserver(QObject):
            def eventFilter(self,watched,event):
                if event.type()==QEvent.Type.Show and isinstance(watched,QWidget) and watched.isWindow():
                    shown.append((type(watched).__name__,watched.objectName()))
                return False
        observer=WindowObserver()
        APP.installEventFilter(observer)
        host=QWidget();host.setObjectName('expectedChooserHost')
        layout=QVBoxLayout(host)
        try:
            for _ in range(3):
                picker=SimulationPicker(host)
                layout.addWidget(picker)
                host.show()
                for width in (1440,800):
                    host.resize(width,800);APP.processEvents()
                    picker.search.setText('no-matching-simulation-xyz')
                    APP.processEvents()
                    self.assertFalse(picker.empty.isHidden())
                    self.assertFalse(picker.empty.isWindow())
                    picker.search.clear()
                    picker.family.setCurrentIndex(picker.family.findData('PCSEL'))
                    APP.processEvents()
                    picker.family.setCurrentIndex(0)
                    self.assertTrue(all(not card.isWindow() for card in picker.cards.values()))
                picker.hide();picker.deleteLater();APP.processEvents()
            self.assertEqual(shown,[('QWidget','expectedChooserHost')])
        finally:
            APP.removeEventFilter(observer)
            host.hide();host.deleteLater();APP.processEvents()

    def test_start_choices_are_visible_searchable_and_persist_selected_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings=QSettings(str(Path(temporary)/'choice.ini'),QSettings.Format.IniFormat)
            def accept():
                dialog=APP.activeModalWidget()
                self.assertEqual(dialog.choice_tabs.currentIndex(),0)
                self.assertEqual(set(dialog.simulations.buttons),{row[0] for row in SIMULATIONS})
                dialog.simulations.search.setText('RCWA resonances')
                self.assertFalse(dialog.simulations.cards['pcsel.rcwa_poles'].isHidden())
                self.assertTrue(dialog.simulations.cards['pcsel.vertical'].isHidden())
                dialog.remember_check.setChecked(True)
                dialog.simulations.buttons['pcsel.rcwa_poles'].click()
            QTimer.singleShot(0,accept)
            chosen=choose_startup_workspace('ask',settings)
            self.assertEqual(chosen,'device')
            self.assertEqual(chosen.simulation_target,'pcsel.rcwa_poles')
            self.assertEqual(settings.value(STARTUP_SIMULATION_KEY),chosen.simulation_target)
            with patch('qt_workspace_start.WorkspaceStartDialog') as dialog:
                restored=choose_startup_workspace(None,settings)
                dialog.assert_not_called()
            self.assertEqual(restored.simulation_target,chosen.simulation_target)

    def test_all_choices_open_exact_destinations_without_starting_or_replacing_device(self):
        with tempfile.TemporaryDirectory() as temporary:
            store=ProjectStore(DataLibrary(Path(temporary)/'library'),restore=False)
            window=OpticalStudio(store)
            try:
                before=store.portable_project()['device']
                with patch.object(store,'start_run') as start:
                    for target,_,_,_ in SIMULATIONS:
                        with self.subTest(target=target):
                            window._open_simulation_choice(target)
                            if target.startswith('pcsel.'):
                                page=window.research_studies_page._pages['pcsel']
                                self.assertEqual(page.fields['model'].currentData(),target.split('.')[1])
                                self.assertIs(window.research_studies_page.stack.currentWidget(),page)
                            elif target.startswith('photonic_bands'):self.assertEqual(window.navigation.currentRow(),10)
                            elif target.startswith('sesame_transport'):self.assertEqual(window.research_studies_page.selector.currentData(),'sesame_transport')
                            elif target=='papers':self.assertEqual(window.research_studies_page.library_page.tabs.currentIndex(),1)
                            elif target in ('tools.sweep','tools.ai'):self.assertEqual(window.navigation.currentRow(),3 if target=='tools.sweep' else 8)
                            elif target in {'optical','electrical','electrical.iv','electrical.cv','coupled','fdtd','tools.fields','tools.index_shift'}:
                                self.assertEqual(window.navigation.currentRow(),2)
                            else:self.assertEqual(window.research_studies_page.selector.currentData(),target)
                    start.assert_not_called()
                self.assertEqual(store.study_project('optical')['device'],before)
                window.set_workspace_profile(WorkspaceSelection('device','pcsel.gme'))
                self.assertEqual(window.research_studies_page._pages['pcsel'].fields['model'].currentData(),'gme')
            finally:
                window._force_close=True
                window.hide();window.deleteLater();APP.processEvents()

    def test_compact_start_keeps_all_choices_reachable_without_horizontal_scroll(self):
        dialog=WorkspaceStartDialog()
        try:
            dialog.resize(800,760);dialog.show();APP.processEvents()
            scroll=dialog.simulations.scroll
            self.assertEqual(scroll.horizontalScrollBar().maximum(),0)
            for target in ('optical','pcsel.rcwa_poles','lumped_laser','papers'):
                action=dialog.simulations.buttons[target]
                scroll.ensureWidgetVisible(action);APP.processEvents()
                self.assertTrue(scroll.viewport().rect().contains(action.mapTo(scroll.viewport(),action.rect().center())))
        finally:
            dialog.hide();dialog.deleteLater();APP.processEvents()
