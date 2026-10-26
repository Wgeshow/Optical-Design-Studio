"""Current workspace guidance is searchable and never mutates a project."""
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QApplication
from qt_help import HelpGuide,GUIDES,DOCUMENTS,ASSET_ROOT,REAL_EXAMPLE_ROOT

APP=QApplication.instance() or QApplication([])


class _GuideLinks(HTMLParser):
    def __init__(self):
        super().__init__();self.ids=set();self.targets=[]

    def handle_starttag(self,tag,attributes):
        attributes=dict(attributes)
        if attributes.get('id'):self.ids.add(attributes['id'])
        if tag=='a' and attributes.get('href'):self.targets.append(attributes['href'])
        if tag=='img' and attributes.get('src'):self.targets.append(attributes['src'])


class DeviceStudioHelpTests(unittest.TestCase):
    def setUp(self):
        self.page=HelpGuide()
        self.page.resize(1460,840)
        self.page.show()
        APP.processEvents()

    def tearDown(self):
        self.page.close();self.page.deleteLater();APP.processEvents()

    def test_latest_features_and_workspace_choice_are_searchable(self):
        terms=[('Switch workspace','Choose a workspace'),('49,284','PC area and automatic air holes'),
            ('Soft shadows','Device geometry and studio lighting'),('three distinct','I–V and C–V'),
            ('frozen-conductivity','I–V and C–V'),('Optical E/H','Results: saved runs, optical fields and phase'),
            ('stable IDs','Setup presets and validation'),('ITO','Electrical materials and custom definitions')]
        for term,title in terms:
            with self.subTest(term=term):
                self.page.query.setText(term)
                topics=[self.page.topics.item(i).text() for i in range(self.page.topics.count())]
                self.assertIn(title,topics)

    def test_all_twenty_setup_tabs_are_documented_by_their_actual_names(self):
        plan=json.loads((ASSET_ROOT.parent/'simulation_setup_plan.json').read_text('utf-8'))
        for mode in ('optical','electrical','coupled'):
            plain=html.unescape(re.sub('<[^>]+>','',GUIDES[mode.title()+' setup tabs']))
            for tab in plan['modes'][mode]['tabs']:
                self.assertIn(tab['title'],plain)

    def test_workspace_switch_scope_and_original_geometry_source_are_explicit(self):
        self.assertTrue(self.page.open_topic('Choose a workspace'))
        text=self.page.reader.toPlainText()
        for value in ('Device Studio','Original Optical Studio','same application','does not discard','rerun'):
            self.assertIn(value,text)
        self.page.open_topic('Original Optical Studio')
        text=self.page.reader.toPlainText()
        self.assertIn('optical layer and region tables',text)
        self.assertIn('not added automatically',text)
        self.assertIn('fundamental PC-pitch cell',text)
        self.assertIn('arbitrary crop settings',text)
        self.assertNotIn('new release version',text)

    def test_generated_workspace_reference_is_labelled_and_not_called_a_native_screenshot(self):
        if not (ASSET_ROOT/'workspace-choice-mockup.png').is_file():
            self.skipTest('Optional labelled workspace reference is not present')
        self.page.open_topic('Choose a workspace')
        text=self.page.reader.toPlainText()
        self.assertIn('AI-generated UI reference',text)
        self.assertIn('not a solver result or a native screenshot',text)
        self.assertIn('Open full-size UI reference',text)
        self.assertNotIn('Open full-size native image',text)

    def test_internal_topic_links_are_whitelisted_and_do_not_launch_external_actions(self):
        with patch('qt_help.QDesktopServices.openUrl') as external:
            self.page.open_document(QUrl('help-topic:Electrical setup tabs'))
            self.assertIn('Electrical setup tabs',self.page.reader.toPlainText())
            before=self.page.reader.toPlainText()
            self.page.open_document(QUrl('help-topic:../private.txt'))
            self.assertEqual(self.page.reader.toPlainText(),before)
            self.page.open_document(QUrl('https://example.com'))
            external.assert_not_called()
        self.assertFalse(self.page.open_topic('unknown topic'))

    def test_internal_links_and_bundled_document_targets_resolve(self):
        for title,body in GUIDES.items():
            for target in re.findall(r'href="help-topic:([^"]+)"',body):
                self.assertIn(html.unescape(target),GUIDES,title)
        for filename in DOCUMENTS.values():
            self.assertTrue((ASSET_ROOT.parent/filename).is_file(),filename)

    def test_standalone_guide_includes_current_topics_and_resolvable_links(self):
        source=ASSET_ROOT.parent
        document=(source/'USER_GUIDE.html').read_text('utf-8')
        for title in GUIDES:
            self.assertIn('<h2>'+html.escape(title)+'</h2>',document,title)
        links=_GuideLinks();links.feed(document)
        for target in links.targets:
            with self.subTest(target=target):
                if target.startswith('#'):self.assertIn(target[1:],links.ids)
                elif re.match(r'https?://',target):continue
                else:self.assertTrue((source/target).is_file(),target)
        self.assertNotIn('help-topic:',document)
        if (ASSET_ROOT/'workspace-choice-mockup.png').is_file():
            self.assertIn('AI-generated workspace-choice UI reference',document)

    def test_model_and_display_distinctions_remain_visible(self):
        doc=(ASSET_ROOT.parent/'DEVICE_STUDIO_GUIDE.md').read_text('utf-8')
        self.assertIn('not diode',doc)
        self.assertIn('AC frequency',GUIDES['I–V and C–V'])
        self.assertIn('Static electrical εr is never inferred',doc)
        self.assertIn('not solved optical/electrical fields',doc)
        self.assertIn('not electrical DC fields',GUIDES['Results: saved runs, optical fields and phase'])
        self.assertIn('S4 repeats',GUIDES['PC area and automatic air holes'])

    def test_guidance_opens_at_compact_width_and_verified_assets_are_retained(self):
        self.page.resize(980,720);APP.processEvents()
        self.page.open_topic('Electrical setup tabs');APP.processEvents()
        self.assertEqual(self.page.reader.horizontalScrollBar().maximum(),0)
        self.assertEqual(len(json.loads((REAL_EXAMPLE_ROOT/'field-samples.json').read_text('utf-8'))['samples']),41)
        doc=(ASSET_ROOT.parent/'DEVICE_STUDIO_GUIDE.md').read_text('utf-8')
        for value in ('Original Optical Studio','49,284','Optical E/H','Specular phase','not added automatically'):
            self.assertIn(value,doc)


if __name__=='__main__':
    unittest.main()
