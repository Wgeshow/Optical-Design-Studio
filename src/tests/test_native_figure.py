"""Scientific array/coordinate invariants and real Qt plot interactions."""
import os
import tempfile
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
from PyQt6.QtCore import Qt, QPoint, QPointF
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from matplotlib.figure import Figure
from matplotlib.colors import LogNorm
from matplotlib.patches import Rectangle
from matplotlib.artist import Artist
from matplotlib.ticker import PercentFormatter, FixedLocator, FixedFormatter
from qt_common import PlotWidget, theme_manager
from qt_native_figure import NativeFigureCanvas

APP = QApplication.instance() or QApplication([])


class NativeFigureTests(unittest.TestCase):
    def setUp(self):
        self.plot = PlotWidget()
        self.plot.resize(900, 620)
        self.plot.show()
        APP.processEvents()

    def tearDown(self):
        self.plot.close()
        self.plot.deleteLater()
        APP.processEvents()

    def draw(self, figure):
        self.plot.draw_figure(figure)
        for _ in range(3):
            APP.processEvents()
        self.assertEqual(self.plot.canvas.unsupported_artists, [])
        return self.plot.canvas

    def painted_axis_labels(self, axis):
        image=QImage(1000,800,QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter=QPainter(image)
        try:
            if axis.style.get('tickFont'):painter.setFont(axis.style['tickFont'])
            specs=axis.generateDrawSpecs(painter)
            return [text for _,_,text in specs[2]] if specs else []
        finally:painter.end()

    def test_native_phase_cycle_ticks_and_wrapped_endpoints_render_in_all_units(self):
        import math
        import pandas as pd
        from spectral_phase import phase_figure
        frame=pd.DataFrame(dict(wavelength_nm=np.arange(17)+1000,angle_deg=0,
            reflection_phase_deg=(np.arange(17)*45+180)%360-180,
            transmission_phase_deg=(np.arange(17)*45+180)%360-180))
        self.plot.toolbar.hide()
        for height in (328,430):
          self.plot.resize(900,height)
          for unit,cycle in [('radians',2*math.pi),('pi',2.),('degrees',360.)]:
            for mode in ('positive','signed','unwrapped'):
                with self.subTest(height=height,unit=unit,mode=mode):
                    figure=phase_figure(frame,mode,unit)
                    expected_arrays=[np.asarray(line.get_ydata()).copy() for axis in figure.axes for line in axis.lines]
                    canvas=self.draw(figure)
                    self.assertFalse(canvas.grab().isNull())
                    for row,(source,native) in enumerate((axis,canvas.plots[axis].getAxis('left')) for axis in figure.axes):
                        lower,upper=native.range
                        values=native.tickValues(lower,upper,150)[0][1]
                        labels=native.tickStrings(values,1,1)
                        if row==0 and mode!='unwrapped':
                            expected=np.linspace(0,cycle,5) if mode=='positive' else np.linspace(-cycle/2,cycle/2,5)
                            np.testing.assert_allclose(values,expected)
                            if unit=='radians':
                                expected_labels=['0','π/2','π','3π/2','2π'] if mode=='positive' else ['−π','−π/2','0','π/2','π']
                                self.assertEqual(labels,expected_labels)
                            painted=self.painted_axis_labels(native)
                            self.assertIn(labels[0],painted)
                            self.assertIn(labels[-1],painted)
                            if height==328:self.assertLess(canvas.axis_views[source].height(),85)
                        else:
                            self.assertTrue(values)
                            np.testing.assert_allclose(np.asarray(values)/cycle,np.round(np.asarray(values)/cycle),atol=1e-10)
                            if unit=='radians':self.assertTrue(all(label=='0' or label.rstrip('π').lstrip('−-').isdigit() for label in labels),labels)
                    records=[record for record in canvas.data_records if record['kind']=='line']
                    for expected,record in zip(expected_arrays,records):np.testing.assert_array_equal(record['raw_y'],expected)

    def test_explicit_fixed_labels_keep_coordinate_identity_after_native_zoom(self):
        figure=Figure();source=figure.subplots();source.plot([0,1],[0,1])
        source.yaxis.set_major_locator(FixedLocator([0,.25,.75,1]))
        source.yaxis.set_major_formatter(FixedFormatter(['zero','quarter','three-quarter','one']))
        canvas=self.draw(figure);view=canvas.axis_views[source]
        view.setYRange(.2,1,padding=0);APP.processEvents()
        native=canvas.plots[source].getAxis('left')
        values=native.tickValues(*native.range,150)[0][1]
        self.assertEqual(values,[.25,.75,1.])
        self.assertEqual(native.tickStrings(values,1,.25),['quarter','three-quarter','one'])

    def test_full_line_arrays_fraction_formatter_and_host_size_are_independent_of_paper(self):
        figure = Figure(figsize=(2, 9))
        axis = figure.subplots()
        x = np.linspace(900, 1700, 24001)
        y = .5+.3*np.sin(x)
        source, = axis.plot(x, y, label='Transmission')
        axis.set(xlabel='Wavelength (nm)', ylabel='Incident power (%)', ylim=(0, 1))
        axis.yaxis.set_major_formatter(PercentFormatter(xmax=1))
        axis.legend()
        canvas = self.draw(figure)
        self.assertIsInstance(canvas, NativeFigureCanvas)
        record = next(row for row in canvas.data_records if row['source_artist'] is source)
        np.testing.assert_array_equal(record['raw_x'], x)
        np.testing.assert_array_equal(record['raw_y'], y)
        self.assertIn('20', canvas.plots[axis].getAxis('left').tickStrings([.2], 1, .1)[0])
        self.assertGreater(canvas.width(), 880)
        self.plot.figure_style.update(width_mm=40, height_mm=300)
        self.plot.fit_canvas()
        APP.processEvents()
        self.assertGreater(canvas.width(), 880)
        self.assertGreater(canvas.height(), 550)
        self.assertEqual([item.toolTip() for item in self.plot.toolbar.buttons.values()],
                         ['Fit', 'Pan', 'Zoom', 'Copy', 'Export', 'Figure settings'])

    def test_nonuniform_mesh_shared_lognorm_and_inverted_depth_keep_exact_cells(self):
        figure = Figure()
        axes = figure.subplots(1, 2)
        xedges = np.array([-.4, -.15, .08, .4])
        zedges = np.array([0, .015, .09, .22, .6])
        values = np.array([[.01, .04, .1], [.2, .3, .4], [1, 3, 9], [2, 4, 7]])
        norm = LogNorm(vmin=.01, vmax=10)
        artists = []
        for axis in axes:
            artists.append(axis.pcolormesh(xedges, zedges, values, norm=norm, cmap='turbo'))
            axis.set(xlabel='x (µm)', ylabel='Depth z (µm)')
            axis.invert_yaxis()
        figure.colorbar(artists[-1], ax=axes, label='|E|² / incident |E|² · same scale')
        canvas = self.draw(figure)
        records = [row for row in canvas.data_records if row['kind'] == 'mesh']
        self.assertEqual(len(records), 2)
        for record in records:
            np.testing.assert_array_equal(record['values'], values)
            np.testing.assert_array_equal(record['coordinates'][0, :, 0], xedges)
            np.testing.assert_array_equal(record['coordinates'][:, 0, 1], zedges)
            np.testing.assert_array_equal(record['normalized_values'], norm(values))
            self.assertIs(record['norm'], norm)
            self.assertTrue(canvas.axis_views[record['source_axis']].state['yInverted'])
        self.assertEqual(len(canvas.colorbars), 1)
        self.assertIs(canvas.colorbars[0]['norm'], norm)
        self.assertEqual(canvas.colorbars[0]['native_item'].getAxis('right').tickStrings([0, .5, 1], 1, .5), ['0.01', '0.3162', '10'])

    def test_image_origin_and_extent_are_physical_not_row_index_coordinates(self):
        figure = Figure()
        axes = figure.subplots(1, 2)
        values = np.array([[1, 2, 3], [7, 8, 9]])
        for axis, origin in zip(axes, ('lower', 'upper')):
            axis.imshow(values, origin=origin, extent=(-300, 300, -90, 210), interpolation='nearest')
        canvas = self.draw(figure)
        images = [row for row in canvas.data_records if row['kind'] == 'image']
        for image in images:
            np.testing.assert_array_equal(image['values'], values)
            np.testing.assert_array_equal(image['coordinates'][0, :, 0], [-300, -100, 100, 300])
        np.testing.assert_array_equal(images[0]['coordinates'][:, 0, 1], [-90, 60, 210])
        np.testing.assert_array_equal(images[1]['coordinates'][:, 0, 1], [210, 60, -90])

    def test_local_and_shared_colorbars_follow_declared_source_subplot_bindings(self):
        figure = Figure()
        axes = figure.subplots(2, 2).ravel()
        norm = LogNorm(vmin=.01, vmax=10.)
        values = np.array([[.02, .3], [1., 8.]])
        meshes = [axis.pcolormesh([-.3, .02, .3], [0, .015, .22], values, norm=norm) for axis in axes]
        for index in (0, 1):
            figure.colorbar(meshes[index], ax=axes[index], label=f'Local {index}')
        figure.colorbar(meshes[3], ax=axes[2:].tolist(), label='Shared bottom row')
        canvas = self.draw(figure)
        self.assertEqual(len(canvas.colorbars), 3, 'Identical norms do not merge distinct source colorbars')
        for index in (0, 1):
            record = canvas.colorbars[index]
            self.assertEqual(record['parents'], (axes[index],))
            self.assertFalse(record['shared'])
            plot_cell = canvas.view.ci.items[canvas.plots[axes[index]]][0]
            self.assertEqual(record['grid_position'], (plot_cell[0], plot_cell[1]+1, 1, 1))
            self.assertIs(record['norm'], norm)
        shared = canvas.colorbars[2]
        self.assertEqual(shared['parents'], tuple(axes[2:]))
        self.assertTrue(shared['shared'])
        self.assertEqual(shared['grid_position'][0::2], (1, 1), 'A bottom-row shared bar does not span unrelated top plots')
        for record, mesh in zip([row for row in canvas.data_records if row['kind']=='mesh'], meshes):
            np.testing.assert_array_equal(record['values'], mesh.get_array())
            np.testing.assert_array_equal(record['coordinates'], mesh.get_coordinates())
            self.assertIs(record['norm'], norm)

    def test_horizontal_shared_colorbar_keeps_source_orientation_units_and_inverse_scale(self):
        figure = Figure()
        axes = figure.subplots(1, 2)
        norm = LogNorm(vmin=.01, vmax=10.)
        for axis in axes:
            image = axis.imshow([[.01, .1], [1, 10]], norm=norm)
        figure.colorbar(image, ax=axes, orientation='horizontal', label='Intensity (physical units)')
        canvas = self.draw(figure)
        record = canvas.colorbars[0]
        self.assertEqual(record['parents'], tuple(axes))
        self.assertEqual(record['grid_position'], (1, 0, 1, 2))
        self.assertTrue(record['native_item'].horizontal)
        axis = record['native_item'].getAxis('bottom')
        self.assertEqual(axis.labelText, 'Intensity (physical units)')
        self.assertEqual(axis.tickStrings([0, .5, 1], 1, .5), ['0.01', '0.3162', '10'])

    def test_equal_physical_axes_keep_same_pixel_scale_when_native_host_resizes(self):
        figure = Figure()
        axis = figure.subplots()
        axis.pcolormesh([-.27, 0, .27], [0, .015, .09, .22], np.ones((3, 2)))
        axis.set(xlim=(-.27, .27), ylim=(.22, 0), aspect='equal')
        canvas = self.draw(figure)
        for width, height in ((900, 620), (460, 760), (1120, 410)):
            self.plot.resize(width, height)
            for _ in range(3): APP.processEvents()
            view = canvas.axis_views[axis]
            origin = view.mapViewToScene(QPointF(0, .1))
            dx = view.mapViewToScene(QPointF(.1, .1))-origin
            dz = view.mapViewToScene(QPointF(0, .2))-origin
            self.assertAlmostEqual(abs(dx.x()), abs(dz.y()), delta=1e-9)
            self.assertGreater(dz.y(), 0, 'Positive saved depth runs downward')
            self.assertEqual(view.state['aspectLocked'], 1.)

    def test_figure_settings_typography_updates_native_axes_titles_legend_and_colorbar(self):
        figure = Figure()
        axis = figure.subplots()
        axis.plot([0, 1], [0, 1], label='Measured')
        image = axis.imshow([[1, 2], [3, 4]], extent=(0, 1, 0, 1))
        axis.set(xlabel='x (µm)', ylabel='y (µm)', title='Physical plane')
        axis.legend()
        figure.suptitle('Saved result')
        figure.colorbar(image, ax=axis, label='Intensity')
        self.plot.figure_style.update(font='Courier New', label_pt=22, tick_pt=18,
                                      title_pt=26, legend_pt=20)
        canvas = self.draw(figure)
        native = canvas.plots[axis]
        for side in ('bottom', 'left'):
            self.assertEqual(native.getAxis(side).labelStyle['font-size'], '22pt')
            self.assertEqual(native.getAxis(side).labelStyle['font-family'], 'Courier New')
            self.assertEqual(native.getAxis(side).style['tickFont'].pointSizeF(), 18)
        self.assertEqual(native.titleLabel.opts['size'], '26pt')
        self.assertEqual(native.titleLabel.opts['family'], 'Courier New')
        self.assertEqual(canvas.view.getItem(0, 0).opts['size'], '26pt')
        self.assertEqual(native.legend.items[0][1].opts['size'], '20pt')
        self.assertEqual(native.legend.items[0][1].opts['family'], 'Courier New')
        colorbar = canvas.colorbars[0]['native_item'].getAxis('right')
        self.assertEqual(canvas.colorbars[0]['native_item'].getAxis('left').labelText, '')
        self.assertEqual(colorbar.labelStyle['font-size'], '22pt')
        self.assertEqual(colorbar.style['tickFont'].pointSizeF(), 18)

    def test_logarithmic_ticks_unwrap_nested_mathtext_without_changing_raw_values(self):
        figure = Figure()
        axis = figure.subplots()
        raw = np.array([.001, .01, .1, 1, 10])
        source, = axis.plot(np.arange(len(raw)), raw)
        axis.set_yscale('log')
        canvas = self.draw(figure)
        np.testing.assert_array_equal(canvas.data_records[0]['raw_y'], raw)
        ticks = canvas.plots[axis].getAxis('left').tickStrings([-3, -2, -1, 0, 1], 1, 1)
        self.assertEqual(ticks, ['10^-3', '10^-2', '10^-1', '10^0', '10^1'])
        self.assertFalse(any('\\' in tick for tick in ticks))

    def test_contours_rotated_outline_vectors_and_error_intervals_are_native(self):
        figure = Figure()
        axis = figure.subplots()
        x, y = np.meshgrid(np.linspace(-1, 1, 9), np.linspace(-.6, .6, 7))
        values = x*x+3*y*y
        axis.pcolormesh(x, y, values, shading='nearest')
        contour = axis.contour(x, y, values, levels=[.3, .7], colors='white', linestyles='dashed')
        outline = Rectangle((-.2, -.1), .4, .2, angle=28, rotation_point='center', fill=False)
        axis.add_patch(outline)
        arrows = axis.quiver([-.5, .5], [-.2, .2], [1, -.5], [.1, -.4], color='white',
                             angles='xy', scale_units='xy', scale=4)
        interval = axis.errorbar([-.6, .6], [.4, .5], yerr=[.1, .2], fmt='o', capsize=3)
        axis.set_aspect('equal')
        canvas = self.draw(figure)
        contours = [row for row in canvas.data_records if row['kind'] == 'contour']
        self.assertEqual(len(contours), 1)
        np.testing.assert_array_equal(contours[0]['levels'], contour.levels)
        self.assertTrue(contours[0]['native_items'])
        for item, style, width in zip(contours[0]['native_items'], contour.get_linestyles(), contour.get_linewidths()):
            self.assertEqual(item.edge.style(), Qt.PenStyle.CustomDashLine)
            np.testing.assert_allclose(np.asarray(item.edge.dashPattern())*width, style[1])
        patch = next(row for row in canvas.data_records if row['source_artist'] is outline)
        expected = outline.get_transform().transform(outline.get_path().vertices)
        expected = axis.transData.inverted().transform(expected)
        np.testing.assert_allclose(patch['vertices'], expected, rtol=0, atol=1e-12)
        vector = next(row for row in canvas.data_records if row['source_artist'] is arrows)
        np.testing.assert_array_equal(vector['x'], [-.5, .5])
        np.testing.assert_array_equal(vector['u'], [1, -.5])
        np.testing.assert_array_equal(vector['v'], [.1, -.4])
        self.assertEqual(len(vector['native_items']), 2)
        for vertices, origin, displacement in zip(vector['vertices'], arrows.XY, np.column_stack((arrows.U, arrows.V))):
            # The outer arrowhead tip remains at the requested physical vector
            # endpoint even though the live viewport has a different size.
            np.testing.assert_allclose(vertices[3], origin+displacement/arrows.scale, rtol=0, atol=1e-12)
        segments = next(row for row in canvas.data_records if row['source_artist'] is interval.lines[2][0])
        for actual, source in zip(segments['segments'], interval.lines[2][0].get_segments()):
            np.testing.assert_array_equal(actual, source)

    def test_actual_qt_click_hover_bridge_preserves_source_axis_identity_and_data(self):
        figure = Figure()
        axis = figure.subplots()
        axis.plot([0, 10], [0, 20])
        axis.set(xlim=(0, 10), ylim=(0, 20))
        canvas = self.draw(figure)
        clicks, moves = [], []
        canvas.mpl_connect('button_press_event', clicks.append)
        canvas.mpl_connect('motion_notify_event', moves.append)
        self.assertIn('button_press_event', canvas.callbacks.callbacks)
        scene = canvas.axis_views[axis].mapViewToScene(__import__('PyQt6.QtCore', fromlist=['QPointF']).QPointF(4, 8))
        point = canvas.view.mapFromScene(scene)
        QTest.mouseMove(canvas.view.viewport(), point)
        QTest.mouseClick(canvas.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        for _ in range(3):
            APP.processEvents()
        self.assertTrue(clicks)
        self.assertIs(clicks[-1].inaxes, axis)
        self.assertAlmostEqual(clicks[-1].xdata, 4, delta=.03)
        self.assertAlmostEqual(clicks[-1].ydata, 8, delta=.05)
        self.assertEqual(clicks[-1].button, 1)
        self.assertIs(canvas.toolbar, self.plot.toolbar)
        self.plot.toolbar.pan()
        self.assertTrue(canvas.toolbar.mode)
        self.plot.toolbar.zoom()
        self.plot.retheme()
        self.assertEqual(self.plot.toolbar.mode, 'zoom rect')
        self.assertTrue(self.plot.toolbar.buttons['Zoom'].isChecked())
        self.assertEqual(canvas.axis_views[axis].state['mouseMode'], 1)
        self.plot.draw_figure(figure)
        self.assertEqual(canvas.axis_views[axis].state['mouseMode'], 1)
        self.plot.toolbar.home()
        self.assertEqual(canvas.toolbar.mode, '')

    def test_unsupported_scientific_artist_is_visible_and_3d_is_never_flattened(self):
        figure = Figure()
        axis = figure.subplots()
        axis.add_artist(Artist())
        self.plot.draw_figure(figure)
        self.assertEqual(len(self.plot.canvas.unsupported_artists), 1)
        self.assertTrue(self.plot.canvas.warning.isVisible())
        self.assertIn('Unsupported scientific artist', self.plot.canvas.warning.text())
        three_d = Figure()
        axis = three_d.add_subplot(projection='3d')
        axis.scatter([1], [2], [3])
        self.plot.draw_figure(three_d)
        self.assertFalse(self.plot.canvas.data_records)
        self.assertIn('never flattened', self.plot.canvas.warning.text())


if __name__ == '__main__':
    unittest.main()
