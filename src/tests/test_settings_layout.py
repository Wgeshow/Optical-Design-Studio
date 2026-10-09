"""Settings navigation and native project preview integration."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication, QBoxLayout
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_common import theme_manager
from qt_compute import SettingsPage
from qt_device_builder import GeometryViewport

APP=QApplication.instance() or QApplication([])


class SettingsLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.manager=theme_manager()
        self.old=(self.manager.settings,self.manager.look,copy.deepcopy(self.manager.custom_colors),self.manager.scale,self.manager.adaptive,self.manager.glass_opacity)
        self.manager.settings=QSettings(str(Path(self.temp.name)/'appearance.ini'),QSettings.Format.IniFormat)
        self.manager.custom_colors={}
        self.manager.set_appearance(scale=100,adaptive=True)
        self.manager.apply_look('glass_dark',persist=False)
        self.store=ProjectStore(DataLibrary(Path(self.temp.name)/'library'),restore=False)
        self.page=SettingsPage(self.store)
        self.page.resize(1536,920)
        self.page.show()
        self.process()

    def process(self):
        for _ in range(12):APP.processEvents()

    def tearDown(self):
        self.page.close()
        self.page.deleteLater()
        self.process()
        self.manager.settings,self.manager.custom_colors,self.manager.glass_opacity=self.old[0],self.old[2],self.old[5]
        self.manager.set_appearance(scale=self.old[3],adaptive=self.old[4])
        self.manager.apply_look(self.old[1],persist=False)
        self.temp.cleanup()

    def test_vertical_navigation_preserves_settings_stack_api(self):
        self.assertTrue(self.page.settings_tabs.tabBar().isHidden())
        for index,control in enumerate(self.page.settings_navigation):
            control.click()
            self.process()
            self.assertEqual(self.page.settings_tabs.currentIndex(),index)
            self.assertTrue(control.isChecked())
            self.assertEqual(sum(button.isChecked() for button in self.page.settings_navigation),1)
        self.page.settings_tabs.setCurrentIndex(0)
        self.assertTrue(self.page.settings_navigation[0].isChecked())
        self.assertEqual(self.page.appearance_page.theme.currentData(),'glass_dark')

    def test_native_preview_tracks_shared_model_without_mutating_optical_inputs(self):
        appearance=self.page.appearance_page
        self.assertIsInstance(appearance.viewport,GeometryViewport)
        before=self.store.project()
        for mode,button in appearance.view_buttons.items():
            button.click()
            self.assertEqual(appearance.viewport.mode,mode)
        for key,control in appearance.display_controls.items():
            control.setChecked(not control.isChecked())
            self.assertEqual(getattr(appearance.viewport,key),control.isChecked())
        appearance.theme_cards['light'].click()
        appearance.color_fields['accent'].setText('#476bc1')
        appearance.color_fields['accent'].editingFinished.emit()
        self.assertEqual(self.store.project(),before)
        name=str(self.store.layers.iloc[1]['Name'])
        self.store.appearance={'layer_colors':{name:'#65a9c8'}}
        self.store.layers.loc[1,'Thickness_um']=.375
        self.store.changed.emit('structure')
        self.assertEqual(appearance.viewport.layer_colors[name],'#65a9c8')
        self.assertEqual(appearance.viewport.layers[1]['Thickness_um'],.375)
        self.assertFalse(appearance.viewport.grab().isNull())

    def test_compact_layout_scrolls_and_keeps_theme_cards_separate(self):
        self.page.resize(640,760)
        self.process()
        appearance=self.page.appearance_page
        self.assertEqual(self.page.width(),640)
        self.assertEqual(appearance.content_layout.direction(),QBoxLayout.Direction.TopToBottom)
        self.assertGreater(self.page.settings_scroll.verticalScrollBar().maximum(),0)
        cards=list(appearance.theme_cards.values())
        self.assertEqual(cards[0].y(),cards[1].y())
        self.assertGreater(cards[2].y(),cards[0].geometry().bottom())
        for index,card in enumerate(cards):
            for other in cards[index+1:]:
                self.assertFalse(card.geometry().intersects(other.geometry()))
        self.page.settings_scroll.verticalScrollBar().setValue(self.page.settings_scroll.verticalScrollBar().maximum())
        self.process()
        self.assertTrue(appearance.preview_panel.isVisible())
        self.assertEqual(self.page.settings_scroll.horizontalScrollBar().maximum(),0)


if __name__=='__main__':unittest.main()
