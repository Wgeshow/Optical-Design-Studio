"""Saved calculation models agree across the panel and workspace readouts."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QApplication

from qt_electrical_results import saved_result_model_labels,terminal_curve_figure
from qt_results_workspace import ResultsWorkspace
from tests.test_qt_results_workspace import _device,_volume

APP=QApplication.instance() or QApplication([])


class SavedModelLabelTests(unittest.TestCase):
    def test_explicit_transport_fallback_keeps_fd_and_ideal_interface(self):
        summary=dict(model='custom_device',results=[],semiconductor_current_predicted=True,
            options=dict(transport=dict(mode='semiconductor_dd',statistics='fermi_dirac',
                heterojunction=dict(model='ideal_quasi_fermi'))))
        frame=pd.DataFrame(dict(bias_V=[0.,.1],current_A=[0.,1e-9]))
        labels=saved_result_model_labels(summary,iv_data=frame)
        expected='Self-consistent semiconductor drift diffusion · Fermi–Dirac · ideal quasi-Fermi interface'
        self.assertEqual(labels['run_model'],expected)
        self.assertEqual(labels['iv_scope'],expected)

    def test_unrecorded_current_model_is_not_assumed_ohmic(self):
        frame=pd.DataFrame(dict(bias_V=[0.,.1],current_A=[0.,1e-9]))
        labels=saved_result_model_labels(dict(model='custom_device',results=[],options=dict(transport=dict(mode='disabled'))),iv_data=frame)
        self.assertEqual(labels['iv_scope'],'Saved current (model not recorded)')
        figure=terminal_curve_figure(frame,None)
        self.assertEqual(figure.axes[0].lines[0].get_label(),labels['iv_scope'])

    def test_saved_study_transport_details_take_precedence_over_input_fallback(self):
        summary=dict(model='custom_device',results=[],options=dict(transport=dict(mode='semiconductor_dd',statistics='boltzmann')))
        info=dict(studies=dict(iv=dict(model='Self-consistent semiconductor drift diffusion',
            transport=dict(mode='semiconductor_dd',statistics='fermi_dirac'))))
        labels=saved_result_model_labels(summary,info)
        self.assertIn('Fermi–Dirac',labels['run_model'])
        self.assertNotIn('Boltzmann',labels['run_model'])
        self.assertEqual(labels['iv_scope'],'No saved current study')


class WorkspaceModelLabelTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='result_model_labels_')
        self.directory=Path(self.temp.name);self.workspace=ResultsWorkspace()

    def tearDown(self):
        self.workspace.close();self.workspace.deleteLater();APP.processEvents();self.temp.cleanup()

    def saved_run(self,name,transport=None,study_model=None,row_model=None,*,currents=True):
        directory=self.directory/name;directory.mkdir()
        volume=directory/'volume.npz';np.savez_compressed(volume,**_volume(0.))
        summary=dict(model='custom_device',device=_device(),options=dict(device=_device()),results=[dict(bias_V=0.,volume_npz=str(volume),checks={})])
        if transport is not None:
            summary['options']['transport']=copy.deepcopy(transport)
            if transport.get('mode')=='semiconductor_dd':summary['semiconductor_current_predicted']=True
        if currents:
            frame=pd.DataFrame(dict(bias_V=[0.,.1],current_A=[0.,1e-9]))
            if row_model is not None:frame['model']=row_model
            frame.to_csv(directory/'electrical_iv.csv',index=False)
            pd.DataFrame(dict(bias_V=[0.,.1],capacitance_F=[1e-15,1e-15])).to_csv(directory/'electrical_cv.csv',index=False)
        if study_model is not None:
            info=dict(studies=dict(iv=dict(model=study_model,transport=copy.deepcopy(transport or {})),
                cv=dict(model='Saved DC electrode-charge derivative',warnings=['No frequency-resolved AC calculation'])))
            (directory/'electrical_study_summary.json').write_text(json.dumps(info),encoding='utf-8')
        return directory,summary

    def assert_current_readouts(self,current):
        widget=self.workspace
        self.assertIn(current,widget.run_value_labels['model'].text())
        self.assertTrue(widget.summary_label.text().startswith(widget.run_value_labels['model'].text()))
        self.assertEqual(widget.current_scope.text(),'Current / I–V: '+current)
        self.assertEqual(widget.iv_scope.text().splitlines()[0],current)
        self.assertEqual(widget.terminal_cards['iv'].title_label.text(),'I–V · '+current)
        self.assertEqual(widget.iv_plot.figure.axes[0].lines[0].get_label(),current)

    def test_all_saved_transport_modes_agree_across_every_readout(self):
        dd='Self-consistent semiconductor drift diffusion'
        cases=[('boltzmann',dict(mode='semiconductor_dd',statistics='boltzmann'),dd,dd+' · Boltzmann'),
            ('fd',dict(mode='semiconductor_dd',statistics='fermi_dirac'),dd,dd+' · Fermi–Dirac'),
            ('interface',dict(mode='semiconductor_dd',statistics='fermi_dirac',heterojunction=dict(model='ideal_quasi_fermi')),
                dd,dd+' · Fermi–Dirac · ideal quasi-Fermi interface'),
            ('leakage',dict(mode='dielectric_leakage'),'Sourced Poole–Frenkel leakage','Sourced Poole–Frenkel leakage'),
            ('legacy',dict(mode='disabled'),'Ohmic conductivity estimate (not junction transport/leakage)',
                'Ohmic conductivity estimate (not junction transport/leakage)')]
        for name,transport,model,expected in cases:
            with self.subTest(name=name):
                directory,summary=self.saved_run(name,transport,model,row_model='Lower-priority recorded row label')
                self.workspace.set_result(directory,summary);APP.processEvents()
                self.assert_current_readouts(expected)
                self.assertEqual(self.workspace.terminal_cards['cv'].title_label.text(),'C–V · Saved DC electrode-charge derivative')
                self.assertEqual(self.workspace.cv_plot.figure.axes[0].lines[0].get_label(),'Saved DC electrode-charge derivative')
                self.assertIn('No frequency-resolved AC calculation',self.workspace.cv_scope.text())

    def test_csv_row_model_fallback_is_shared_when_study_metadata_is_missing(self):
        directory,summary=self.saved_run('row-only',row_model='Recorded junction continuity model')
        self.workspace.set_result(directory,summary);APP.processEvents()
        self.assert_current_readouts('Recorded junction continuity model')

    def test_no_study_and_optical_only_runs_clear_previous_current_labels(self):
        directory,summary=self.saved_run('first',dict(mode='semiconductor_dd',statistics='boltzmann'),
            'Self-consistent semiconductor drift diffusion')
        self.workspace.set_result(directory,summary)
        directory,summary=self.saved_run('without-study',dict(mode='semiconductor_dd',statistics='fermi_dirac'),currents=False)
        self.workspace.set_result(directory,summary);APP.processEvents()
        self.assertIn('Fermi–Dirac',self.workspace.run_value_labels['model'].text())
        self.assertEqual(self.workspace.current_scope.text(),'Current / I–V: No saved current study')
        self.assertEqual(self.workspace.iv_scope.text(),'No saved current study')
        self.assertEqual(self.workspace.terminal_cards['iv'].title_label.text(),'I–V · No saved current study')
        optical=self.directory/'optical';optical.mkdir()
        self.workspace.set_result(optical,dict(model='optical_only',results=[]));APP.processEvents()
        self.assertEqual(self.workspace.run_value_labels['model'].text(),'Periodic optical solve')
        self.assertTrue(self.workspace.summary_label.text().startswith('Periodic optical solve'))
        self.assertEqual(self.workspace.current_scope.text(),'Current / I–V: No saved current study')
        self.assertEqual(self.workspace.terminal_cards['cv'].title_label.text(),'C–V · No saved capacitance study')
        self.assertEqual(len(self.workspace.iv_plot.figure.axes[0].lines),0)


if __name__=='__main__':unittest.main()
