import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QPoint
from PyQt6.QtTest import QTest
from matplotlib.figure import Figure
from qt_common import PlotWidget

class HoverTests(unittest.TestCase):
 def test_hover_does_not_resize_canvas_or_plot(self):
  app=QApplication.instance() or QApplication([])
  plot=PlotWidget();plot.resize(800,600)
  fig=Figure();axis=fig.add_subplot();axis.plot([0,1],[0,1])
  plot.draw_figure(fig);plot.show();app.processEvents();plot.canvas.draw();app.processEvents()
  before=(plot.size(),plot.canvas_host.size(),plot.canvas.size())
  for text in ('x=1 y=2','x=0.123456789012345 y=123456789012345.6789','', 'x=1e-200 y=1e200'):
   plot.toolbar.set_message(text)
   QTest.mouseMove(plot.canvas,QPoint(100,100));app.processEvents()
   self.assertEqual((plot.size(),plot.canvas_host.size(),plot.canvas.size()),before)
  plot.resize(900,700);app.processEvents()
  self.assertNotEqual(plot.canvas.size(),before[2])
  plot.close();plot.deleteLater();app.processEvents()
