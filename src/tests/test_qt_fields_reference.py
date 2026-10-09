"""Reference Fields controls operate on genuine saved samples."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_compute import FieldsPage
APP = QApplication.instance() or QApplication([])

class ReferenceFieldsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ProjectStore(DataLibrary(self.temp.name), restore=False)
        self.page = FieldsPage(self.store)
        folder = Path(self.temp.name) / 'fields'; folder.mkdir()
        rows = []
        for plane in ('xy', 'xz'):
            for x in (-1., 0., 1.):
                for y in (-1., 0., 1.):
                    intensity = 1 + x*x + y*y
                    rows.append(dict(plane=plane, layer='Film', x_um=x, y_um=y, z_um=y,
                                     E2=intensity, Ex_real=np.sqrt(intensity), Ex_imag=0.,
                                     Ey_real=0., Ey_imag=0., Ez_real=0., Ez_imag=0.))
        pd.DataFrame(rows).to_csv(folder/'electric_fields.csv', index=False)
        (folder/'field_model.json').write_text(json.dumps(dict(wavelength_nm=1530, model={})))
        self.page.field_directory = folder
        self.page.render_fields()

    def tearDown(self):
        self.page.close(); self.page.deleteLater(); APP.processEvents(); self.temp.cleanup()

    def test_saved_measurements_and_shared_scale_match_samples(self):
        self.assertEqual(self.page.saved_wavelength.text(), '1530 nm')
        self.assertEqual(self.page.sample_count.text(), '18')
        self.assertAlmostEqual(float(self.page.maximum.text()), np.sqrt(3), places=4)
        axes = self.page.plot.figure.axes[:2]
        self.assertIs(axes[0].collections[0].norm, axes[1].collections[0].norm)
        self.assertTrue(self.page.plot.toolbar.isHidden())
        self.assertEqual(axes[1].get_aspect(), 'auto')

    def test_contour_overlay_changes_the_saved_data_display(self):
        self.page.contour.setValue(-3)
        self.page.contour_enabled.setChecked(True)
        self.assertEqual(self.page.contour_value.text(), '-3 dB')
        self.assertGreater(len(self.page.plot.figure.axes[0].collections), 1)
        self.page.contour_enabled.setChecked(False)
        self.assertEqual(len(self.page.plot.figure.axes[0].collections), 1)

if __name__ == '__main__': unittest.main()
