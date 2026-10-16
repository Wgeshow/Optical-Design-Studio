import os,tempfile,unittest
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from matplotlib.figure import Figure
from publication_plot import DEFAULTS,export_figure,apply_style

class PublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def figure(self):
        figure=Figure(figsize=(7,4),layout='constrained')
        axis=figure.add_subplot(111);axis.plot([1400,1500,1600],[.1,.9,.2],label='Transmission')
        axis.set(xlabel='Wavelength (nm)',ylabel='Transmission',title='Index sweep')
        axis.legend()
        return figure

    def test_raster_size_vector_exports_and_restore(self):
        from PIL import Image
        figure=self.figure();before=tuple(figure.get_size_inches())
        style=dict(DEFAULTS,width_mm=90,height_mm=60,dpi=300)
        with tempfile.TemporaryDirectory() as directory:
            for suffix in ('png','pdf','svg','tiff'):
                file=Path(directory)/('figure.'+suffix)
                export_figure(figure,file,style)
                self.assertGreater(file.stat().st_size,1000)
            with Image.open(Path(directory)/'figure.png') as img:
                self.assertLessEqual(abs(img.width-90/25.4*300),1)
                self.assertLessEqual(abs(img.height-60/25.4*300),1)
                self.assertEqual(img.convert('RGB').getpixel((0,0)),(255,255,255))
            svg=(Path(directory)/'figure.svg').read_text()
            self.assertIn('Wavelength (nm)',svg)
        self.assertEqual(tuple(figure.get_size_inches()),before)

    def test_typography_and_line_width_are_modular(self):
        figure=self.figure();axis=figure.axes[0]
        apply_style(figure,dict(DEFAULTS,label_pt=12,line_pt=2.5,title_pt=14,tick_pt=10))
        self.assertEqual(axis.xaxis.label.get_fontsize(),12)
        self.assertEqual(axis.lines[0].get_linewidth(),2.5)
        self.assertEqual(axis.title.get_fontsize(),14)

    def test_live_canvas_fills_host_independently_of_publication_paper(self):
        from qt_common import PlotWidget
        widget=PlotWidget();widget.draw_figure(self.figure());widget.show()
        paper_size=(widget.figure_style['width_mm'],widget.figure_style['height_mm'])
        for width,height in [(1100,450),(500,850),(900,600)]:
            widget.resize(width,height)
            for _ in range(4):self.app.processEvents()
            self.assertLessEqual(abs(widget.canvas.width()-widget.canvas_host.width()),1)
            self.assertLessEqual(abs(widget.canvas.height()-widget.canvas_host.height()),1)
            self.assertEqual(type(widget.canvas).__name__,'NativeFigureCanvas')
        self.assertEqual((widget.figure_style['width_mm'],widget.figure_style['height_mm']),paper_size)
        widget.figure_style.update(width_mm=90,height_mm=90)
        widget.fit_canvas()
        self.app.processEvents()
        self.assertLessEqual(abs(widget.canvas.width()-widget.canvas_host.width()),1)
        self.assertLessEqual(abs(widget.canvas.height()-widget.canvas_host.height()),1)
        widget.hide()

    def test_field_maps_use_equal_physical_scale(self):
        import pandas as pd
        from qt_compute import field_figure
        with tempfile.TemporaryDirectory() as directory:
            rows=[dict(plane=p,x_um=x,y_um=y,z_um=y,E2=1,layer='Film') for p in ('xy','xz') for x in [0,1,2] for y in [0,.1,.2]]
            pd.DataFrame(rows).to_csv(Path(directory)/'electric_fields.csv',index=False)
            figure=field_figure(directory,arrows=False)
            self.assertEqual([axis.get_aspect() for axis in figure.axes[:2]],[1.,1.])

    def test_settings_dialog_applies_axis_and_curve_labels(self):
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QLineEdit,QDialogButtonBox
        from qt_common import PlotWidget
        widget=PlotWidget();widget.draw_figure(self.figure())
        def edit():
            dialog=self.app.activeModalWidget()
            for entry in dialog.findChildren(QLineEdit):
                if entry.text()=='Index sweep':entry.setText('Edited title')
                elif entry.text()=='Transmission':entry.setText('Normalized power')
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
        QTimer.singleShot(100,edit)
        widget.edit_figure_settings()
        self.assertEqual(widget.figure.axes[0].get_title(),'Edited title')
        self.assertEqual(widget.figure.axes[0].get_ylabel(),'Normalized power')
        self.assertEqual(widget.figure.axes[0].lines[0].get_label(),'Normalized power')
        widget.hide()

if __name__=='__main__':unittest.main()
