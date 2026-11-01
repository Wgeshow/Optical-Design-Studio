"""Explicit mesh construction only; no imports into a campaign or solver runs."""
import copy
from contextlib import ExitStack
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_photonic_bands import _rows, _fill
from qt_sesame_setup import SesameSetupWorkspace, generated_mesh_nodes, MESH_BUILDER_LIMIT
from sesame_transport import prepare
from test_sesame_generation_profile import configuration

APP = QApplication.instance() or QApplication([])


class MeshConstructionTests(unittest.TestCase):
    def test_uniform_base_and_required_coordinate_counts(self):
        np.testing.assert_array_equal(generated_mesh_nodes(0, 1, 5), [0, .25, .5, .75, 1])
        self.assertEqual(len(generated_mesh_nodes(0, 3, 100, [0, .1, 2.9, 3])), 102)
        self.assertEqual(len(generated_mesh_nodes(0, 3, 100, [0, 1.5, 3])), 101)

    def test_tolerance_merges_duplicates_and_prefers_authored_coordinate(self):
        near = .5+5e-13
        self.assertEqual(generated_mesh_nodes(0, 1, 3, [near, near]), [0, near, 1])
        self.assertEqual(len(generated_mesh_nodes(0, 1, 3, [.5+2e-12])), 4)
        self.assertEqual(generated_mesh_nodes(0, 3, 3, [3-2e-12]), [0, 1.5, 3])

    def test_nontransitive_near_coordinates_all_retain_backend_alignment(self):
        required = [.4, .4+7.5e-13, .4+1.5e-12]
        nodes = generated_mesh_nodes(0, 1, 3, required)
        for coordinate in required:
            self.assertTrue(np.any(np.isclose(nodes, coordinate, rtol=0, atol=max(1,abs(coordinate))*1e-12)))
        self.assertTrue(all(a < b for a,b in zip(nodes,nodes[1:])))

    def test_invalid_bounds_counts_and_coordinates_reject(self):
        cases = [(0,0,3,[]),(1,0,3,[]),(0,float('inf'),3,[]),(-1e308,1e308,3,[]),
            (0,1,2,[]),(0,1,3.5,[]),(0,1,True,[]),(0,1,'bad',[]),
            (0,1,3,[float('nan')]),(0,1,3,[-1e-15]),(0,1,3,[1.0001])]
        for values in cases:
            with self.subTest(values=values):
                with self.assertRaises(ValueError): generated_mesh_nodes(*values)

    def test_huge_requests_rejected_before_uniform_allocation(self):
        with patch('qt_sesame_setup.np.linspace') as linspace:
            for count, required in [(10**12, []), (3, [0]*(MESH_BUILDER_LIMIT+1))]:
                with self.assertRaises(ValueError):generated_mesh_nodes(0, 1, count, required)
            linspace.assert_not_called()

    def test_output_guard_and_unrepresentable_spacing(self):
        with self.assertRaises(ValueError):generated_mesh_nodes(0,1,MESH_BUILDER_LIMIT,[.123456789])
        with self.assertRaises(ValueError):generated_mesh_nodes(1e16,1e16+2,5)
        with self.assertRaises(ValueError):generated_mesh_nodes(0,1e-13,3)


class MeshBuilderUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mesh-builder-unit-',dir=os.environ.get('ODS_TEST_TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.store = ProjectStore(DataLibrary(Path(self.temp.name)/'library'),restore=False)
        self.pages = []

    def tearDown(self):
        from PyQt6 import sip
        for page in self.pages:
            page._save_timer.stop(); page._preview_timer.stop(); page._mesh_builder_timer.stop(); sip.delete(page)
        APP.processEvents()

    def page(self, dimension=1):
        identity = 'sesame_transport.2d' if dimension == 2 else 'sesame_transport'
        self.store.activate_study(identity)
        page = SesameSetupWorkspace(self.store,document_id=identity); self.pages.append(page)
        page.load_settings(configuration(dimension));return page

    def test_builder_choices_do_not_change_uniform_settings_or_draft(self):
        page=self.page(); options=copy.deepcopy(page.options()); draft=copy.deepcopy(page.draft())
        page.mesh_builder_toggle.setChecked(True); page.mesh_builder_end.setText('3')
        page.mesh_builder_count.setText('100'); page.mesh_builder_include.setChecked(True)
        page.preview_generated_mesh()
        self.assertEqual(page.options(),options);self.assertEqual(page.draft(),draft)
        self.assertFalse(page.domain_splitter.isAncestorOf(page.mesh_builder_body))
        self.assertIn('not exact script transcription',page.mesh_builder_note.text())

    def test_apply_changes_selected_axis_only_and_survives_draft_restore(self):
        page=self.page(); before=page.draft(); y=page.y_nodes.text()
        page.mesh_builder_count.setText('7');self.assertTrue(page.apply_generated_mesh())
        self.assertEqual(len(page.options()['settings']['x_nodes_um']),7);self.assertEqual(page.y_nodes.text(),y)
        after=page.draft()
        for key in ('regions','materials','contacts','defects'):self.assertEqual(before[key],after[key])
        page.x_nodes.setText('0, .5, 1');page.restore_draft(after)
        self.assertEqual(len(page.options()['settings']['x_nodes_um']),7)

    def test_invalid_or_stale_apply_is_atomic(self):
        page=self.page(); page.preview_generated_mesh();old=page.x_nodes.text()
        page.mesh_builder_start.setText('bad')
        self.assertFalse(page.mesh_builder_apply.isEnabled())
        self.assertFalse(page.apply_generated_mesh());self.assertEqual(page.x_nodes.text(),old)
        page.mesh_builder_start.setText('0');page.mesh_builder_include.setChecked(True);page.preview_generated_mesh()
        page.regions.item(0,2).setText('0, 2')
        self.assertFalse(page.apply_generated_mesh());self.assertEqual(page.x_nodes.text(),old)
        self.assertIn('outside',page.mesh_builder_preview.text())

    def test_y_is_unavailable_in_one_dimension(self):
        page=self.page();self.assertFalse(page.mesh_builder_axis.model().item(1).isEnabled())
        old=(page.x_nodes.text(),page.y_nodes.text());page.mesh_builder_axis.setCurrentIndex(1)
        self.assertFalse(page.apply_generated_mesh());self.assertEqual((page.x_nodes.text(),page.y_nodes.text()),old)

    def test_opt_out_does_not_parse_unfinished_geometry(self):
        page=self.page();page.regions.item(0,2).setText('unfinished')
        self.assertEqual(len(page._generated_mesh_values()),5)
        page.mesh_builder_include.setChecked(True)
        self.assertFalse(page.apply_generated_mesh())

    def test_explicit_2d_boundary_insertion_changes_discretization_and_passes_alignment(self):
        page=self.page(2);cfg=configuration(2)
        cfg['x_nodes_um']=cfg['y_nodes_um']=[0.,1.5,3.]
        cfg['regions'][0]['x_range_um']=cfg['regions'][0]['y_range_um']=[0.,3.]
        page.load_settings(cfg)
        page.add_row(page.defects,['line','0.1, 1.5; 2.9, 1.5','1e11','1e-15','1e-15','0','1, 0'])
        # The authored nonaligned draft is initially rejected by unchanged backend validation.
        with self.assertRaises(ValueError):prepare({},page.options()['settings'])
        page.mesh_builder_end.setText('3');page.mesh_builder_count.setText('100');page.mesh_builder_include.setChecked(True)
        page.preview_generated_mesh();self.assertIn('102 nodes',page.mesh_builder_preview.text())
        self.assertTrue(page.apply_generated_mesh())
        page.mesh_builder_axis.setCurrentIndex(1);page.preview_generated_mesh();self.assertIn('101 nodes',page.mesh_builder_preview.text())
        self.assertTrue(page.apply_generated_mesh())
        actual=prepare({},page.options()['settings'])
        self.assertEqual((len(actual['x_nodes_um']),len(actual['y_nodes_um'])),(102,101))
        self.assertIn(.1,actual['x_nodes_um']);self.assertIn(2.9,actual['x_nodes_um']);self.assertIn(1.5,actual['y_nodes_um'])

    def test_1d_defect_coordinate_is_included(self):
        page=self.page();page.add_row(page.defects,['point','.1','1e11','1e-15','1e-15','0','1, 0'])
        page.mesh_builder_include.setChecked(True)
        self.assertTrue(page.apply_generated_mesh());self.assertIn(.1,page.options()['settings']['x_nodes_um'])

    def test_malformed_defect_and_outside_geometry_fail_without_node_mutation(self):
        page=self.page(2);old=page.x_nodes.text()
        page.add_row(page.defects,['line','0.1, 0.5','1e11','1e-15','1e-15','0','1, 0'])
        page.mesh_builder_include.setChecked(True)
        self.assertFalse(page.apply_generated_mesh());self.assertEqual(page.x_nodes.text(),old)

    def test_preview_is_debounced_without_immediate_geometry_allocation(self):
        page=self.page();page.mesh_builder_toggle.setChecked(True)
        with patch.object(page,'_generated_mesh_values',return_value=[0,.5,1]) as generate:
            page.mesh_builder_count.setText('100');page.mesh_builder_count.setText('101')
            generate.assert_not_called();self.assertTrue(page._mesh_builder_timer.isActive())
            page._mesh_builder_timer.stop();page.preview_generated_mesh();generate.assert_called_once()

    def test_large_2d_product_guard_is_visible_and_atomic(self):
        page=self.page(2);old=page.x_nodes.text()
        page.y_nodes.setText(', '.join(map(str,np.linspace(0,1,1001))))
        page.mesh_builder_count.setText('1000')
        self.assertFalse(page.apply_generated_mesh());self.assertEqual(page.x_nodes.text(),old)
        self.assertIn('1,000,000',page.mesh_builder_note.text());self.assertIn('1,000,000',page.mesh_builder_preview.text())

    def test_editor_capacity_guard_prevents_silent_text_truncation(self):
        page=self.page();old=page.x_nodes.text();capacity=page.x_nodes.maxLength()
        page.mesh_builder_count.setText('2000');page.preview_generated_mesh()
        self.assertFalse(page.mesh_builder_apply.isEnabled());self.assertFalse(page.apply_generated_mesh())
        self.assertEqual(page.x_nodes.text(),old);self.assertEqual(page.x_nodes.maxLength(),capacity)
        self.assertIn(str(capacity),page.mesh_builder_preview.text())
        self.assertIn('character capacity',page.mesh_builder_note.text())

    def test_large_sketch_is_explicitly_thinned_without_losing_mesh_nodes(self):
        page=self.page();page.mesh_builder_count.setText('1000');self.assertTrue(page.apply_generated_mesh())
        with ExitStack() as stack:
            draw=stack.enter_context(patch.object(page.domain_preview,'draw_figure'))
            for preview,_,_ in page.assignment_previews.values():stack.enter_context(patch.object(preview,'draw_figure'))
            page.preview_domain()
        figure=draw.call_args.args[0]
        self.assertLessEqual(len(figure.axes[0].lines),203)
        self.assertEqual(len(page.options()['settings']['x_nodes_um']),1000)
        self.assertIn('201',page.preview_note.text());self.assertIn('all authored nodes are retained',page.preview_note.text())


if __name__=='__main__':unittest.main()
