"""Phase display contracts use the complete sampling and preserve raw exports."""
import csv
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

import numpy as np
import pandas as pd
from spectral_phase import (write_phase_csv,read_phase_preview,phase_display_frame,
    phase_figure,export_phase_display_csv,measure_phase)


def ramp(count=241,gap=None):
    return [[index,1000+index,0,None if index==gap else (index*45+180)%360-180,
             None if index==gap else (index*45+180)%360-180] for index in range(count)]


class PhaseDisplayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ods_phase_display_',dir=Path(__file__).resolve().parents[3])
        self.path=Path(self.temp.name)/'phase.csv'

    def tearDown(self):self.temp.cleanup()

    def test_conversion_modes_and_cycle_ticks_preserve_raw_input(self):
        raw=pd.DataFrame(dict(wavelength_nm=range(1,6),angle_deg=[0]*5,
            reflection_phase_deg=[-180,-90,0,90,180],transmission_phase_deg=[-180,-90,0,90,180]))
        before=raw.copy(deep=True)
        positive=phase_display_frame(raw,'positive','radians')
        np.testing.assert_allclose(positive.reflection_display_radians,[math.pi,1.5*math.pi,0,.5*math.pi,math.pi])
        signed=phase_display_frame(raw,'signed','pi')
        np.testing.assert_allclose(signed.reflection_display_pi,[-1,-.5,0,.5,-1])
        degrees=phase_display_frame(raw,'unwrapped','degrees')
        np.testing.assert_allclose(degrees.reflection_display_degrees,[-180,-90,0,90,180])
        pd.testing.assert_frame_equal(raw,before)
        figure=phase_figure(raw,'positive','radians')
        self.assertEqual(figure.axes[0].get_ylim(),(0,2*math.pi))
        self.assertEqual([tick.get_text() for tick in figure.axes[0].get_yticklabels()],['0','π/2','π','3π/2','2π'])
        figure=phase_figure(raw,'positive','pi')
        self.assertEqual(figure.axes[0].get_ylim(),(0,2))
        self.assertEqual(figure.axes[0].get_ylabel(),'Phase / π')

    def test_near_zero_coefficient_has_undefined_phase(self):
        class TinySignal:
            def GetAmplitudes(self,layer,offset):
                return ([0.,1.],[0.,1e-11]) if layer=='above' else ([0.,1e-9],[0.,0.])
        model=dict(materials=[dict(name='Air',model='constant_nk',a=1.,b=0.)],
            layers=[dict(name=name,material='Air') for name in ('above','film','below')],patterns=[],phi=0.)
        reflection,transmission=measure_phase(TinySignal(),model,1000,0)
        self.assertIsNone(reflection)
        self.assertEqual(transmission,0.)

    def test_unwrap_matches_numpy_half_cycle_ties_and_dense_signals(self):
        sequences=([0,180,0,-180,0,180],[170,-170,-150,170],
            [1e-12,2e-12,3e-12],np.mod(np.linspace(0,360*40,10001),360)-180)
        for phases in sequences:
            frame=pd.DataFrame(dict(wavelength_nm=np.arange(len(phases))+1000,angle_deg=0,
                reflection_phase_deg=phases,transmission_phase_deg=phases))
            actual=phase_display_frame(frame,'unwrapped','degrees')
            expected=np.unwrap(np.asarray(phases,dtype=float),period=360)
            np.testing.assert_allclose(actual.reflection_display_degrees,expected,rtol=0,atol=1e-10)

    def test_full_sampling_is_unwrapped_before_preview_decimation(self):
        write_phase_csv(self.path,ramp())
        preview=read_phase_preview(self.path,count=3,limit=5)
        self.assertLessEqual(len(preview),5)
        self.assertEqual(preview.attrs['phase_sample_count'],241)
        self.assertEqual(preview.iloc[-1].reflection_change_deg,10800)
        displayed=phase_display_frame(preview,'unwrapped','pi')
        self.assertEqual(displayed.iloc[-1].reflection_change_pi,60)
        self.assertEqual(displayed.iloc[-1].reflection_display_pi,60)
        wrapped=phase_figure(preview,'positive','radians')
        # These preview positions omit entire cycles; joining their wrapped
        # values would draw a false low-frequency triangle/sawtooth.
        for line in wrapped.axes[0].lines:
            finite=np.isfinite(line.get_ydata())
            self.assertFalse((finite[:-1]&finite[1:]).any())

    def test_unsampled_gap_is_not_bridged_and_resets_cycle_reference(self):
        write_phase_csv(self.path,ramp(gap=90))
        preview=read_phase_preview(self.path,limit=5)
        self.assertFalse((preview.wavelength_nm==1090).any())
        self.assertEqual(preview.iloc[-1].reflection_change_deg,(240-91)*45)
        self.assertEqual(preview.reflection_segment.nunique(),2)
        figure=phase_figure(preview,'unwrapped','pi')
        self.assertEqual(len(figure.axes[0].lines),2)
        for line in figure.axes[0].lines:
            x=line.get_xdata()
            finite=np.isfinite(x)
            for first,second in zip(x[:-1],x[1:]):
                self.assertFalse(first<1090<second)
            self.assertFalse(finite.all())

    def test_angle_branches_and_nonfinite_samples_have_separate_references(self):
        rows=[[0,1,0,170,0],[1,2,0,-170,45],[2,3,0,float('nan'),90],
              [3,4,0,-160,135],[4,1,10,170,0],[5,2,10,-170,45]]
        write_phase_csv(self.path,rows)
        frame=read_phase_preview(self.path)
        self.assertEqual(frame.attrs['phase_variable'],'wavelength_nm')
        self.assertEqual(list(frame.reflection_change_deg.dropna()),[0,20,0,0,20])
        self.assertEqual(frame.reflection_segment.nunique(),3)
        self.assertEqual(list(frame.transmission_change_deg),[0,45,90,135,0,45])
        # An angle sweep at another wavelength is a separate branch as well.
        write_phase_csv(self.path,[[0,1000,0,170,0],[1,1000,1,-170,45],
                                   [2,1100,0,90,90],[3,1100,1,100,100]])
        frame=read_phase_preview(self.path)
        self.assertEqual(frame.attrs['phase_variable'],'angle_deg')
        self.assertEqual(list(frame.reflection_change_deg),[0,20,0,10])
        # Malformed/nonfinite coordinates cannot supply a connected display
        # phase even when their raw phase column happens to be finite.
        broken=pd.DataFrame(dict(wavelength_nm=['1000','bad','1002'],angle_deg=[0,0,0],
            reflection_phase_deg=['170','-170','-160'],transmission_phase_deg=['0','10','20']))
        display=phase_display_frame(broken,'positive','pi')
        self.assertTrue(pd.isna(display.iloc[1].reflection_display_pi))
        self.assertEqual(display.iloc[2].reflection_change_pi,0)

    def test_display_export_streams_all_rows_and_keeps_original_columns(self):
        write_phase_csv(self.path,ramp(gap=90))
        raw=self.path.read_bytes()
        output=Path(self.temp.name)/'display.csv'
        export_phase_display_csv(self.path,output,'unwrapped','pi')
        source=list(csv.DictReader(raw.decode().splitlines()))
        exported=list(csv.DictReader(output.read_text().splitlines()))
        self.assertEqual(len(exported),241)
        self.assertEqual(exported[-1]['phase_display_mode'],'unwrapped')
        self.assertEqual(exported[-1]['phase_display_unit'],'pi')
        for before,after in zip(source,exported):
            self.assertEqual(before,{key:after[key] for key in before})
        self.assertEqual(exported[90]['reflection_display_pi'],'')
        self.assertAlmostEqual(float(exported[-1]['reflection_change_pi']),(240-91)*45/180)
        self.assertEqual(self.path.read_bytes(),raw)
        with self.assertRaisesRegex(ValueError,'different file'):
            export_phase_display_csv(self.path,self.path)
        self.assertEqual(self.path.read_bytes(),raw)

    def test_physical_reference_uses_full_same_grid_and_reference_gaps(self):
        write_phase_csv(self.path,ramp(gap=90))
        reference=Path(self.temp.name)/'bare-reference.csv'
        write_phase_csv(reference,[[i,1000+i,0,None if i==120 else 20,None if i==120 else 20] for i in range(241)])
        source_bytes=self.path.read_bytes();reference_bytes=reference.read_bytes()
        preview=read_phase_preview(self.path,limit=5,reference_path=reference)
        self.assertEqual(preview.attrs['phase_reference_mode'],'reference_csv')
        self.assertEqual(preview.iloc[-1].reflection_change_deg,(240-121)*45)
        self.assertEqual(preview.iloc[-1].reflection_phase_deg,0)
        self.assertEqual(preview.iloc[-1].reflection_effective_phase_deg,-20)
        output=Path(self.temp.name)/'relative-display.csv'
        export_phase_display_csv(self.path,output,'unwrapped','pi',reference)
        result=pd.read_csv(output)
        self.assertTrue(pd.isna(result.iloc[90].reflection_display_pi))
        self.assertTrue(pd.isna(result.iloc[120].reflection_display_pi))
        self.assertEqual(result.iloc[-1].phase_reference_mode,'reference_csv')
        self.assertIn('matching polarization',result.iloc[-1].phase_reference_convention)
        self.assertEqual(len(result.iloc[-1].phase_reference_sha256),64)
        self.assertEqual(self.path.read_bytes(),source_bytes)
        self.assertEqual(reference.read_bytes(),reference_bytes)
        with self.assertRaisesRegex(ValueError,'physical reference CSV'):
            export_phase_display_csv(self.path,reference,reference_path=reference)

    def test_reference_grid_mismatch_is_checked_after_preview_selection(self):
        write_phase_csv(self.path,ramp())
        reference=Path(self.temp.name)/'different-grid.csv'
        rows=ramp();rows[100][1]+=.001
        write_phase_csv(reference,rows)
        with self.assertRaisesRegex(ValueError,'sample 101.*match exactly'):
            read_phase_preview(self.path,limit=5,reference_path=reference)
        output=Path(self.temp.name)/'invalid-display.csv'
        with self.assertRaisesRegex(ValueError,'No interpolation'):
            export_phase_display_csv(self.path,output,reference_path=reference)
        self.assertFalse(output.exists())
        write_phase_csv(reference,ramp(240))
        with self.assertRaisesRegex(ValueError,'same number of rows'):
            read_phase_preview(self.path,reference_path=reference)

    def test_reference_half_cycle_ties_preserve_complex_ratio_direction(self):
        reference=Path(self.temp.name)/'tie-reference.csv'
        write_phase_csv(self.path,[[0,1000,0,0,0],[1,1001,0,180,-180],[2,1002,0,0,0]])
        write_phase_csv(reference,[[i,1000+i,0,0,0] for i in range(3)])
        frame=phase_display_frame(read_phase_preview(self.path,reference_path=reference),'unwrapped','degrees')
        np.testing.assert_array_equal(frame.reflection_display_degrees,[0,180,0])
        np.testing.assert_array_equal(frame.transmission_display_degrees,[0,-180,0])
        np.testing.assert_allclose(frame.reflection_display_degrees,
            np.rad2deg(np.unwrap(np.angle(np.exp(1j*np.deg2rad([0,180,0]))))),atol=1e-10)


class PhaseControlsTests(unittest.TestCase):
    setUp=PhaseDisplayTests.setUp
    tearDown=PhaseDisplayTests.tearDown
    def test_saved_phase_controls_update_figure_and_complete_exports(self):
        from PyQt6.QtWidgets import QApplication
        from qt_optical_results import SpecularPhaseResultsPanel
        app=QApplication.instance() or QApplication([])
        write_phase_csv(self.path,ramp(gap=90))
        panel=SpecularPhaseResultsPanel();panel.set_path(self.path)
        try:
            self.assertEqual(panel.phase_mode.currentData(),'positive')
            self.assertEqual(panel.phase_unit.currentData(),'radians')
            panel.phase_mode.setCurrentIndex(panel.phase_mode.findData('unwrapped'))
            panel.phase_unit.setCurrentIndex(panel.phase_unit.findData('pi'));app.processEvents()
            self.assertEqual(panel.plot.figure.axes[0].get_ylabel(),'Phase / π')
            self.assertIn('Unwrapped phase',panel.plot.figure.axes[0].get_title())
            reference=Path(self.temp.name)/'saved-bare.csv'
            write_phase_csv(reference,[[i,1000+i,0,20,20] for i in range(241)])
            self.assertTrue(panel.set_reference_path(reference))
            self.assertEqual(panel.phase_reference.currentData(),'csv')
            self.assertIn(reference.name,panel.reference_label.text())
            self.assertIn('assumes matching',panel.plot.figure._suptitle.get_text())
            invalid=Path(self.temp.name)/'wrong-grid.csv'
            write_phase_csv(invalid,ramp(240))
            self.assertFalse(panel.set_reference_path(invalid))
            self.assertEqual(panel.reference_path,reference)
            output=Path(self.temp.name)/'saved-display.csv'
            with patch('qt_optical_results.QFileDialog.getSaveFileName',return_value=(str(output),'CSV')):panel.export_display_csv()
            exported=pd.read_csv(output)
            self.assertEqual(len(exported),241)
            self.assertIn('reflection_display_pi',exported)
            self.assertEqual(exported.iloc[-1].phase_reference_mode,'reference_csv')
            self.assertEqual(exported.iloc[-1].phase_reference_csv,str(reference.resolve()))
            output=Path(self.temp.name)/'saved-raw.csv'
            with patch('qt_optical_results.QFileDialog.getSaveFileName',return_value=(str(output),'CSV')):panel.export_csv()
            self.assertEqual(output.read_bytes(),self.path.read_bytes())
            # The selection also governs the actual exported Matplotlib figure.
            figure_path=Path(self.temp.name)/'selected-phase.png'
            panel.plot.export_figure(figure_path)
            self.assertGreater(figure_path.stat().st_size,1000)
            panel.phase_reference.setCurrentIndex(0);app.processEvents()
            self.assertEqual(panel.frame.attrs['phase_reference_mode'],'stack_boundaries')
            self.assertIn('Absolute boundary',panel.reference_label.text())
        finally:
            panel.close();panel.deleteLater();app.processEvents()

    def test_original_phase_controls_roundtrip_and_export_full_display(self):
        from PyQt6.QtWidgets import QApplication
        from data_library import DataLibrary
        from qt_core import ProjectStore
        from qt_compute import SimulationPage,phase_preview
        app=QApplication.instance() or QApplication([])
        store=ProjectStore(DataLibrary(Path(self.temp.name)/'library'),restore=False)
        page=SimulationPage(store)
        try:
            write_phase_csv(self.path,ramp())
            page.spectrum_directory=self.path.parent
            page.phase_frame=phase_preview(self.path,241,limit=5)
            page.phase_mode.setCurrentIndex(page.phase_mode.findData('unwrapped'))
            page.phase_unit.setCurrentIndex(page.phase_unit.findData('pi'));app.processEvents()
            self.assertEqual({key:store.search_state['phase_display'][key] for key in ('mode','unit')},dict(mode='unwrapped',unit='pi'))
            self.assertEqual(page.phase_plot.figure.axes[0].get_ylabel(),'Phase / π')
            reference=Path(self.temp.name)/'original-bare.csv'
            write_phase_csv(reference,[[i,1000+i,0,20,20] for i in range(241)])
            self.assertTrue(page.set_phase_reference_path(reference))
            self.assertEqual(store.search_state['phase_display']['reference_mode'],'csv')
            self.assertEqual(store.search_state['phase_display']['reference_csv'],str(reference))
            self.assertIn(reference.name,page.phase_reference_label.text())
            output=Path(self.temp.name)/'original-display.csv'
            with patch('qt_compute.QFileDialog.getSaveFileName',return_value=(str(output),'CSV')):page.export_phase_display_csv()
            exported=pd.read_csv(output)
            self.assertEqual(len(exported),241)
            self.assertAlmostEqual(exported.iloc[-1].reflection_display_pi,60-20/180)
            self.assertEqual(exported.iloc[-1].phase_reference_mode,'reference_csv')
            snapshot=store.portable_project();store.load_project(snapshot);app.processEvents()
            self.assertEqual(page.phase_mode.currentData(),'unwrapped')
            self.assertEqual(page.phase_unit.currentData(),'pi')
            self.assertEqual(page.phase_reference.currentData(),'csv')
            self.assertEqual(page.phase_reference_path,reference)
            self.assertEqual(page.phase_frame.attrs['phase_reference_mode'],'reference_csv')
            invalid=Path(self.temp.name)/'original-wrong-grid.csv'
            write_phase_csv(invalid,ramp(240))
            self.assertFalse(page.set_phase_reference_path(invalid))
            self.assertEqual(page.phase_reference_path,reference)
        finally:
            page.close();page.deleteLater();app.processEvents()


if __name__=='__main__':unittest.main()
