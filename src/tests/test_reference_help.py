"""Searchable guidance must preserve scientific distinctions and real illustrations."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import json
import hashlib
import tempfile
import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QApplication,QWidget,QVBoxLayout,QLabel
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QImage
from qt_help import HelpGuide,GUIDES,TOPIC_IMAGES,ASSET_ROOT,DOCUMENTS,EXAMPLE_PROJECT,FIRST_STEPS,REAL_EXAMPLE_TOPIC,REAL_EXAMPLE_ROOT,RESULT_LINKS,add_help_tabs

APP=QApplication.instance() or QApplication([])

class ReferenceHelpTests(unittest.TestCase):
    def setUp(self):self.guide=HelpGuide()
    def tearDown(self):self.guide.deleteLater();APP.processEvents()
    def test_control_search_finds_semantics_and_no_match(self):
        for term,topic in [('cm⁻³','Δn sweep and carrier density'),('checkpoint','AI checkpoints and reference fields'),('incident-normalized','MEEP FDTD'),('threshold','Performance and convergence'),('CSV','Import CSV and manual materials')]:
            self.guide.query.setText(term)
            entries=[self.guide.topics.item(i).text() for i in range(self.guide.topics.count())]
            self.assertIn(topic,entries)
        self.guide.query.setText('zzzz-no-guide')
        self.assertEqual(self.guide.topics.count(),0)
        self.assertIn('No matching',self.guide.reader.toPlainText())
    def test_topics_render_real_images_and_native_tabs(self):
        self.assertGreaterEqual(len(GUIDES),24)
        self.assertEqual(self.guide.center_tabs.tabText(0),'User guide')
        self.assertEqual(self.guide.center_tabs.tabText(1),'Shortcuts')
        for topic,(filename,_) in TOPIC_IMAGES.items():
            self.assertFalse(QImage(str(ASSET_ROOT/filename)).isNull(),filename)
            self.guide.open_topic(topic)
            self.assertIn('<img',self.guide.reader.toHtml())
            note='current project may differ' if filename.startswith('silicon-reference-run/') else 'not current project results'
            self.assertIn(note,self.guide.reader.toPlainText())
    def test_source_conventions_not_conflated(self):
        self.assertIn('raw, not incident-normalized',GUIDES['MEEP FDTD'])
        self.assertIn('keeps k fixed',GUIDES['Δn sweep and carrier density'])
        self.assertIn('same baseline sample',GUIDES['Fixed-wavelength Δn readout'])
        self.assertIn('not simulate pulse travel',GUIDES['Field comparison and 3D playback'])
        self.assertIn('not exposed',GUIDES['MEEP FDTD'])
    def test_document_links_allow_only_bundled_whitelist(self):
        with patch('qt_help.QDesktopServices.openUrl') as open_url:
            self.guide.open_document(QUrl('guide:../private.txt'))
            self.guide.open_document(QUrl('help-image:../private.png'))
            self.guide.open_document(QUrl('https://example.com'))
            open_url.assert_not_called()
            self.guide.open_document(QUrl('guide:MEEP_FDTD.md'))
            self.assertEqual(open_url.call_count,1)
            self.guide.open_document(QUrl('help-image:first-device.png'))
            self.assertEqual(open_url.call_count,2)
        for filename in DOCUMENTS.values():self.assertTrue((ASSET_ROOT.parent/filename).is_file())
    def test_about_controls_are_reparented_not_reimplemented(self):
        class AboutStub(QWidget):
            def check_for_updates(self):pass
        page=AboutStub();layout=QVBoxLayout(page);marker=QLabel('Original update controls');layout.addWidget(marker)
        add_help_tabs(page)
        self.assertEqual(page.help_tabs.count(),4)
        self.assertEqual([page.help_tabs.tabText(i) for i in range(4)],['User guide','Shortcuts','About','Updates'])
        self.assertIs(marker.parent(),page.help_tabs.widget(2))
        page.help_tabs.setCurrentIndex(2)
        page.help_guide.open_topic('Materials')
        self.assertEqual(page.help_tabs.currentIndex(),0)
        self.assertIn('dataset',page.help_guide.reader.toPlainText())
        page.deleteLater();APP.processEvents()

    def test_first_device_is_native_illustrated_and_search_remains_available(self):
        self.guide.resize(1460,840);self.guide.show();APP.processEvents()
        self.assertIs(self.guide.guide_stack.currentWidget(),self.guide.first_page)
        self.assertEqual(len(self.guide.step_badges),5)
        self.assertFalse(self.guide.example_illustration.pixmap.isNull())
        self.assertGreater(self.guide.example_panel.x(),0)
        self.assertIn('input errors',FIRST_STEPS[3][1]);self.assertIn('Unit cell',FIRST_STEPS[3][1])
        self.assertFalse(self.guide.topics.item(0).icon().isNull())
        self.guide.open_topic('Materials')
        self.assertIs(self.guide.guide_stack.currentWidget(),self.guide.reader)
        self.guide.open_topic('Getting started')
        self.assertIs(self.guide.guide_stack.currentWidget(),self.guide.first_page)

    def test_quick_actions_use_active_library_and_update_page(self):
        with tempfile.TemporaryDirectory() as directory:
            page=QWidget();page.store=SimpleNamespace(library=SimpleNamespace(root=Path(directory)),busy=False)
            page.check_for_updates=Mock();QVBoxLayout(page).addWidget(QLabel('Identity'))
            add_help_tabs(page);page.resize(1460,840);page.show();APP.processEvents()
            guide=page.help_guide
            for button in guide.action_buttons.values():
                self.assertGreaterEqual(button.height(),74)
                self.assertTrue(button.isEnabled())
            with patch('qt_help.QDesktopServices.openUrl',return_value=True) as open_url:
                guide.library_button.click();guide.logs_button.click()
                self.assertEqual(open_url.call_count,2)
                for args in open_url.call_args_list:self.assertEqual(Path(args.args[0].toLocalFile()),Path(directory))
            guide.update_button.click();page.check_for_updates.assert_called_once()
            self.assertIs(guide.center_tabs.currentWidget(),guide.updates_page)
            self.assertIn('desktop-crash.log',guide.action_status.text())
            page.close();page.deleteLater();APP.processEvents()

    def test_example_uses_project_replace_guard_and_real_geometry(self):
        from data_library import DataLibrary
        from qt_core import ProjectStore
        with tempfile.TemporaryDirectory() as directory:
            store=ProjectStore(DataLibrary(directory),restore=False)
            window=QWidget();window.store=store;window.check_for_updates=Mock()
            window._confirm_project_replace=Mock(return_value=False);window._navigate_route=Mock();window.status=QLabel()
            QVBoxLayout(window).addWidget(QLabel('Identity'));add_help_tabs(window)
            guide=window.help_guide;original=store.project()
            self.assertFalse(guide.open_example());self.assertEqual(store.project(),original)
            window._confirm_project_replace.assert_called_once();window._navigate_route.assert_not_called()
            store.busy=True;window._confirm_project_replace.reset_mock()
            self.assertFalse(guide.open_example());window._confirm_project_replace.assert_not_called()
            store.busy=False;window._confirm_project_replace.return_value=True
            self.assertTrue(guide.open_example());window._navigate_route.assert_called_once_with(0)
            sample=json.loads(EXAMPLE_PROJECT.read_text(encoding='utf-8'))
            self.assertEqual(store.project()['layers'],sample['layers'])
            self.assertEqual(store.project()['patterns'],sample['patterns'])
            self.assertEqual(store.project()['materials'],sample['materials'])
            self.assertEqual([layer['Name'] for layer in sample['layers']],['Air','Silicon','SiO2'])
            self.assertEqual(sample['patterns'][0]['Layer'],'Silicon')
            self.assertEqual(sample['patterns'][0]['SizeX_um'],.1)
            self.assertEqual(sample['patterns'][0]['SizeY_um'],.1)
            self.assertEqual(sample['layers'][1]['Thickness_um'],.22)
            self.assertEqual(sample['layers'][-1]['Thickness_um'],0)
            self.assertIn('no computed results',window.status.text())
            window.close();window.deleteLater();APP.processEvents()

    def test_real_update_card_is_reused_in_updates_tab(self):
        from qt_about import AboutPage
        from qt_core import ProjectStore
        from data_library import DataLibrary
        with tempfile.TemporaryDirectory() as directory:
            page=AboutPage(ProjectStore(DataLibrary(directory),restore=False))
            original_button=page.check_button;original_card=page.update_card
            add_help_tabs(page)
            self.assertIs(page.check_button,original_button)
            self.assertIs(page.update_card,original_card)
            self.assertIs(original_card.parent(),page.help_guide.updates_page)
            self.assertTrue(page.help_guide.updates_page.isAncestorOf(original_button))
            self.assertEqual(page.last_checked.objectName(),'helpSecondary')
            self.assertEqual(page.status_detail.objectName(),'helpSecondary')
            page.close();page.deleteLater();APP.processEvents()

    def test_compact_topic_images_fit_and_run_stop_are_searchable(self):
        self.guide.resize(980,720);self.guide.show();APP.processEvents()
        self.guide.open_topic('Materials');APP.processEvents()
        self.assertEqual(self.guide.reader.horizontalScrollBar().maximum(),0)
        self.guide.resize(800,650);APP.processEvents()
        self.assertEqual(self.guide.reader.horizontalScrollBar().maximum(),0)
        block=self.guide.reader.document().begin()
        while block.isValid():
            iterator=block.begin()
            while not iterator.atEnd():
                fragment=iterator.fragment()
                if fragment.isValid() and fragment.charFormat().isImageFormat():
                    image=fragment.charFormat().toImageFormat();native=QImage(QUrl(image.name()).toLocalFile())
                    self.assertAlmostEqual(image.height()/image.width(),native.height()/native.width(),places=2)
                    block_height=self.guide.reader.document().documentLayout().blockBoundingRect(block).height()
                    self.assertLessEqual(block_height,image.height()+40)
                iterator+=1
            block=block.next()
        self.guide.query.setText('Stop requests cancellation')
        titles=[self.guide.topics.item(i).text() for i in range(self.guide.topics.count())]
        self.assertIn('Run, Stop and progress',titles)

    def test_actual_example_opens_real_plots_and_bundled_result_links(self):
        self.assertIsNotNone(self.guide.actual_example_button)
        self.guide.actual_example_button.click()
        text=self.guide.reader.toPlainText();html=self.guide.reader.toHtml()
        self.assertIn('actual-spectrum-plot.png',html)
        self.assertIn('actual-fields-plot.png',html)
        self.assertIn('0–100%',text);self.assertIn('power fractions',text)
        self.assertIn('linear |E| / incident |E|',text)
        self.assertIn('constant indices',text)
        with patch('qt_help.QDesktopServices.openUrl') as open_url:
            for filename in RESULT_LINKS.values():
                self.assertTrue((ASSET_ROOT.parent/filename).is_file(),filename)
                self.guide.open_document(QUrl('guide:'+filename))
                self.assertEqual(Path(open_url.call_args.args[0].toLocalFile()),ASSET_ROOT.parent/filename)
            self.assertEqual(open_url.call_count,len(RESULT_LINKS))
            self.guide.open_document(QUrl('guide:help_assets/silicon-reference-run/../private.csv'))
            self.assertEqual(open_url.call_count,len(RESULT_LINKS))

    def test_actual_bundle_checksums_inputs_energy_and_complex_fields(self):
        bundle=json.loads((REAL_EXAMPLE_ROOT/'bundle.json').read_text(encoding='utf-8'))
        self.assertEqual(bundle['status'],'complete')
        for item in bundle['files']:
            path=REAL_EXAMPLE_ROOT/item['file']
            self.assertEqual(path.stat().st_size,item['bytes'],item['file'])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),item['sha256'],item['file'])
        project=json.loads((REAL_EXAMPLE_ROOT/'project.json').read_text(encoding='utf-8'))
        example=json.loads(EXAMPLE_PROJECT.read_text(encoding='utf-8'))
        for key in ('settings','layers','patterns','materials','desktop_search'):
            self.assertEqual(project[key],example[key],key)
        spectrum=pd.read_csv(REAL_EXAMPLE_ROOT/'results.csv')
        self.assertEqual(len(spectrum),41)
        self.assertEqual(spectrum['wavelength_nm'].tolist(),list(range(1515,1556)))
        self.assertTrue(np.isfinite(spectrum[['R','T','A']].to_numpy()).all())
        self.assertLess(np.abs(spectrum['R']+spectrum['T']-1).max(),1e-10)
        self.assertLess(spectrum['R'].max(),1);self.assertGreater(spectrum['T'].min(),0)
        for basis in (49,121):
            other=pd.read_csv(REAL_EXAMPLE_ROOT/f'basis-{basis}/results.csv')
            self.assertEqual(other['wavelength_nm'].tolist(),spectrum['wavelength_nm'].tolist())
            self.assertLess(np.abs(other[['R','T']].to_numpy()-spectrum[['R','T']].to_numpy()).max(),.002)
        samples=json.loads((REAL_EXAMPLE_ROOT/'field-samples.json').read_text(encoding='utf-8'))
        self.assertEqual(len(samples['samples']),41)
        for sample in samples['samples']:
            fields=pd.read_csv(REAL_EXAMPLE_ROOT/sample['file'])
            self.assertEqual(len(fields),3125)
            columns=['Ex_real','Ex_imag','Ey_real','Ey_imag','Ez_real','Ez_imag']
            values=fields[columns].to_numpy()
            self.assertTrue(np.isfinite(values).all(),sample['file'])
            np.testing.assert_allclose(fields['E2'].to_numpy(),np.sum(values**2,axis=1),rtol=1e-10,atol=1e-12)
        validation=json.loads((REAL_EXAMPLE_ROOT/'scientific-validation.json').read_text(encoding='utf-8'))
        self.assertEqual(validation['status'],'passed')

if __name__=='__main__':unittest.main()
