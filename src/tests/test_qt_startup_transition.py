"""Real CLI startup keeps a painted surface until the selected studio opens.

Each profile runs in a fresh Qt process through qt_app.main and a real chooser
button. Instrumentation observes real visibility/paint events; it does not
replace the chooser, studio, project store, or application event loop.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE=Path(__file__).resolve().parents[1]
CHILD=r'''
import json,os,time,faulthandler,atexit,weakref
faulthandler.enable()
from pathlib import Path
from unittest.mock import patch
from PyQt6.QtCore import QEvent,QObject,QRect,Qt,QTimer
from PyQt6.QtWidgets import QApplication,QMainWindow,QWidget,QScrollArea
from PyQt6.QtTest import QTest
from PyQt6 import sip
import qt_app
from qt_workspace_start import WorkspaceStartDialog
from qt_common import preferences

started=time.monotonic()
main_window_ref=lambda:None
report=dict(profile=os.environ['ODS_TEST_PROFILE'],events=[],constructors=0,unexpected_setup_shows=0)
def elapsed():return round(time.monotonic()-started,4)
def checkpoint():Path(os.environ['ODS_TEST_REPORT']).write_text(json.dumps(report,indent=2),encoding='utf-8')
def record_shutdown(stage):
    report.setdefault('shutdown_checkpoints',[]).append(dict(stage=stage,time=elapsed()))
    checkpoint()
atexit.register(lambda:record_shutdown('atexit'))
class Observer(QObject):
    def __init__(self):super().__init__();self.painted=set();self.finalized=False
    def eventFilter(self,obj,event):
        if not isinstance(obj,QWidget) or not obj.isWindow():return False
        kind=event.type()
        if kind in (QEvent.Type.Show,QEvent.Type.Hide,QEvent.Type.Paint):
            name=obj.objectName() or type(obj).__name__
            if name=='setupFieldRow' or name.startswith('setupTable_') or name in ('setupCard','setupCards'):
                if kind==QEvent.Type.Show:report['unexpected_setup_shows']+=1
                return False
            if name=='workspaceLoadingWindow' and kind==QEvent.Type.Paint and os.environ.get('ODS_TEST_CANCEL_LOADING')=='1' and not getattr(self,'cancel_scheduled',False):
                self.cancel_scheduled=True;QTimer.singleShot(50,cancel_loading)
            if kind==QEvent.Type.Paint:self.painted.add(id(obj))
            if kind!=QEvent.Type.Paint or id(obj) not in getattr(self,'recorded',set()):
                report['events'].append(dict(time=elapsed(),type=kind.name,window=name))
                if kind==QEvent.Type.Paint:
                    if not hasattr(self,'recorded'):self.recorded=set()
                    self.recorded.add(id(obj))
            if isinstance(obj,Studio) and kind==QEvent.Type.Show:
                report['main_show_completed_constructor']=getattr(obj,'_construction_complete',obj.completed)
                report['main_show_profile']=obj.workspace_profile
                checkpoint()
            if isinstance(obj,Studio) and kind==QEvent.Type.Paint and not self.finalized:
                self.finalized=True
                report['first_main_paint']=elapsed()
                report['first_main_paint_state']=obj.windowState().value
                report['loading_visible_at_main_paint']=any(w.isVisible() and w.objectName()=='workspaceLoadingWindow' for w in QApplication.topLevelWidgets())
                checkpoint()
                QTimer.singleShot(500,lambda:finish(obj))
        return False
class App(QApplication):
    def __init__(self,args):
        super().__init__(args)
        self.observer=Observer();self.installEventFilter(self.observer)
        seed=QMainWindow();seed.setGeometry(QRect(25,30,980,720))
        seed.setWindowState(Qt.WindowState.WindowMaximized)
        settings=preferences();settings.setValue('geometry',seed.saveGeometry());settings.setValue('page',0);settings.sync()
        seed.deleteLater()
        QTimer.singleShot(0,click_choice)
        QTimer.singleShot(90000,lambda:self.exit(91))
        self.aboutToQuit.connect(finish_cancel)
        self.aboutToQuit.connect(lambda:record_shutdown('aboutToQuit'))
def build_surface():
    app=QApplication.instance()
    surfaces=[w for w in app.topLevelWidgets() if w.isVisible()]
    report['surface_visible_during_build']=bool(surfaces)
    report['surface_painted_during_build']=any(id(w) in app.observer.painted for w in surfaces)
    report['build_surface_names']=[w.objectName() or type(w).__name__ for w in surfaces]
class Studio(qt_app.OpticalStudio):
    def __init__(self,*args,**kwargs):
        global main_window_ref
        main_window_ref=weakref.ref(self)
        self.completed=False;report['constructors']+=1;report['constructor_start']=elapsed()
        build_surface()
        before=time.monotonic();super().__init__(*args,**kwargs);self.completed=True
        report['constructor_seconds']=round(time.monotonic()-before,4)
        report['constructor_end']=elapsed()
    def advance_startup(self):
        if not report.get('deferred_build_started'):
            report['deferred_build_started']=elapsed();build_surface()
        report['advance_begin']=elapsed();checkpoint()
        stage=super().advance_startup()
        report['last_stage']=stage;report['advance_end']=elapsed();checkpoint()
        return stage
def click_choice():
    app=QApplication.instance();dialog=app.activeModalWidget()
    if not isinstance(dialog,WorkspaceStartDialog):QTimer.singleShot(10,click_choice);return
    button=dialog.open_buttons[report['profile']]
    scroll=dialog.findChild(QScrollArea);scroll.ensureWidgetVisible(button,0,0)
    QTest.qWait(20);report['choice_clicked']=elapsed()
    QTest.mouseClick(button,Qt.MouseButton.LeftButton)
def cancel_loading():
    window=next((w for w in QApplication.topLevelWidgets() if w.objectName()=='workspaceLoadingWindow' and w.isVisible()),None)
    if window is None:raise RuntimeError('Loading window disappeared before Cancel was clicked.')
    report['cancel_clicked']=elapsed();QTest.mouseClick(window.cancel_button,Qt.MouseButton.LeftButton)
def finish_cancel():
    if os.environ.get('ODS_TEST_CANCEL_LOADING')!='1':return
    report['cancelled_main_visible']=any(isinstance(w,Studio) and w.isVisible() for w in QApplication.topLevelWidgets())
    report['cancelled_main_ever_shown']=any(e['window']=='opticalStudioWindow' and e['type']=='Show' for e in report['events'])
    report['cancelled_loading_visible']=any(w.objectName()=='workspaceLoadingWindow' and w.isVisible() for w in QApplication.topLevelWidgets())
    Path(os.environ['ODS_TEST_REPORT']).write_text(json.dumps(report,indent=2),encoding='utf-8')
def finish(window):
    report.update(visible=window.isVisible(),maximized=window.isMaximized(),
        profile_final=window.workspace_profile,main_windows=len([w for w in QApplication.topLevelWidgets() if isinstance(w,Studio) and w.isVisible()]),
        pending_startup_state=getattr(window,'_startup_window_state',Qt.WindowState.WindowNoState).value,
        normal_geometry=[window.normalGeometry().width(),window.normalGeometry().height()],
        live_loading=len([w for w in QApplication.topLevelWidgets() if w.objectName()=='workspaceLoadingWindow' and w.isVisible()]),
        live_choosers=len([w for w in QApplication.topLevelWidgets() if isinstance(w,WorkspaceStartDialog) and w.isVisible()]))
    Path(os.environ['ODS_TEST_REPORT']).write_text(json.dumps(report,indent=2),encoding='utf-8')
    record_shutdown('finish_before_exit')
    if os.environ.get('ODS_TEST_CLOSE_MODE','close')=='close':
        QTest.mouseClick(window.chrome.close_button,Qt.MouseButton.LeftButton)
    else:
        QApplication.instance().quit()
with patch.object(qt_app,'QApplication',App),patch.object(qt_app,'OpticalStudio',Studio):
    code=qt_app.main(['--workspace','ask','--no-restore','--library',os.environ['S4_LIBRARY_ROOT'],'--look','dark'])
    returned_window=main_window_ref()
    report['main_deleted_after_return']=returned_window is None or sip.isdeleted(returned_window)
    report['coordinator_cleared_after_return']=getattr(QApplication.instance(),'_desktop_startup',None) is None
    record_shutdown('main_returned')
record_shutdown('patch_context_exited')
if not Path(os.environ['ODS_TEST_REPORT']).is_file():raise RuntimeError('Startup did not reach a visible main paint: '+str(report))
record_shutdown('before_SystemExit')
raise SystemExit(code)
'''

MINIMAL_CHILD=r'''
import json,os,time,atexit,faulthandler,weakref
from pathlib import Path
from unittest.mock import patch
faulthandler.enable()
from PyQt6.QtCore import QTimer,Qt
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from PyQt6 import sip
import qt_app
from qt_common import theme_manager
started=time.monotonic();report=dict(checkpoints=[])
main_window_ref=lambda:None
def checkpoint(stage):
    report['checkpoints'].append(dict(stage=stage,time=round(time.monotonic()-started,4)))
    Path(os.environ['ODS_TEST_REPORT']).write_text(json.dumps(report,indent=2),encoding='utf-8')
atexit.register(lambda:checkpoint('atexit'))
def observe():
    global main_window_ref
    app=QApplication.instance();startup=getattr(app,'_desktop_startup',None)
    if startup is None or not startup.finished:
        QTimer.singleShot(50,observe);return
    window=startup.window
    main_window_ref=weakref.ref(window)
    report.update(profile=window.workspace_profile,visible=window.isVisible(),
        complete=window._construction_complete,loading_visible=startup.loading.isVisible() if not sip.isdeleted(startup.loading) else False)
    checkpoint('main_ready')
    QTimer.singleShot(100,lambda:QTest.mouseClick(window.chrome.close_button,Qt.MouseButton.LeftButton))
original=theme_manager().apply_look
def setup(*args,**kwargs):
    result=original(*args,**kwargs)
    app=QApplication.instance();app.aboutToQuit.connect(lambda:checkpoint('aboutToQuit'))
    QTimer.singleShot(50,observe);QTimer.singleShot(90000,lambda:app.exit(91))
    return result
with patch.object(theme_manager(),'apply_look',setup):
    code=qt_app.main(['--workspace','device','--no-restore','--library',os.environ['S4_LIBRARY_ROOT'],'--look','dark'])
    returned_window=main_window_ref()
    report['main_deleted_after_return']=returned_window is None or sip.isdeleted(returned_window)
    report['coordinator_cleared_after_return']=getattr(QApplication.instance(),'_desktop_startup',None) is None
    checkpoint('main_returned')
checkpoint('before_SystemExit')
raise SystemExit(code)
'''


class StartupTransitionTests(unittest.TestCase):
    def check_startup(self,profile,cancel=False):
        with tempfile.TemporaryDirectory(prefix='ods_startup_transition_',dir=SOURCE.parents[0].parent) as folder:
            root=Path(folder);path=root/'transition.json';script=root/'exercise_startup.py';script.write_text(CHILD,encoding='utf-8')
            env=dict(os.environ,QT_QPA_PLATFORM='offscreen',S4_LIBRARY_ROOT=str(root/'library'),
                ODS_TEST_PROFILE=profile,ODS_TEST_REPORT=str(path),MPLCONFIGDIR=str(root/'mpl'),TEMP=str(root),TMP=str(root))
            env['PYTHONPATH']=str(SOURCE)
            if cancel:env['ODS_TEST_CANCEL_LOADING']='1'
            completed=subprocess.run([sys.executable,str(script)],cwd=SOURCE,env=env,text=True,capture_output=True,timeout=100)
            diagnostic=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
            diagnostic.pop('events',None)
            crash=root/'library'/'desktop-crash.log'
            crash_text=crash.read_text(encoding='utf-8',errors='replace') if crash.is_file() else ''
            self.assertEqual(completed.returncode,0,completed.stdout+'\n'+completed.stderr+'\n'+json.dumps(diagnostic)+'\n'+crash_text)
            report=json.loads(path.read_text(encoding='utf-8'))
            summary={key:value for key,value in report.items() if key!='events'}
            self.assertTrue(report['main_deleted_after_return'],summary)
            self.assertTrue(report['coordinator_cleared_after_return'],summary)
            if cancel:
                self.assertIn('cancel_clicked',report,summary)
                self.assertFalse(report['cancelled_main_visible'],summary)
                self.assertFalse(report['cancelled_main_ever_shown'],summary)
                self.assertFalse(report['cancelled_loading_visible'],summary)
                self.assertEqual(report['unexpected_setup_shows'],0,summary)
                return report
            self.assertEqual(report['constructors'],1,report)
            self.assertTrue(report['main_show_completed_constructor'],report)
            self.assertEqual(report['main_show_profile'],profile,report)
            self.assertEqual(report['profile_final'],profile,report)
            self.assertTrue(report['visible']);self.assertTrue(report['maximized'])
            self.assertEqual(report['main_windows'],1);self.assertEqual(report['live_choosers'],0)
            self.assertEqual(report['live_loading'],0,summary)
            self.assertTrue(report['loading_visible_at_main_paint'],summary)
            self.assertEqual(report['pending_startup_state'],0)
            self.assertEqual(report['unexpected_setup_shows'],0,summary)
            self.assertTrue(report['surface_visible_during_build'],summary)
            self.assertTrue(report['surface_painted_during_build'],summary)
            return report

    def test_device_choice_transitions_to_one_complete_painted_studio(self):self.check_startup('device')
    def test_original_choice_transitions_to_one_complete_painted_studio(self):self.check_startup('original')
    def test_loading_cancel_exits_without_showing_partial_studio(self):self.check_startup('device',cancel=True)

    def test_selected_cli_closes_cleanly_with_unmodified_application_and_studio(self):
        with tempfile.TemporaryDirectory(prefix='ods_startup_lifetime_',dir=SOURCE.parents[0].parent) as folder:
            root=Path(folder);path=root/'transition.json';script=root/'exercise_lifetime.py';script.write_text(MINIMAL_CHILD,encoding='utf-8')
            env=dict(os.environ,QT_QPA_PLATFORM='offscreen',S4_LIBRARY_ROOT=str(root/'library'),
                ODS_TEST_REPORT=str(path),MPLCONFIGDIR=str(root/'mpl'),TEMP=str(root),TMP=str(root),PYTHONPATH=str(SOURCE))
            completed=subprocess.run([sys.executable,str(script)],cwd=SOURCE,env=env,text=True,capture_output=True,timeout=100)
            report=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
            crash=root/'library'/'desktop-crash.log'
            crash_text=crash.read_text(encoding='utf-8',errors='replace') if crash.is_file() else ''
            self.assertEqual(completed.returncode,0,completed.stdout+'\n'+completed.stderr+'\n'+json.dumps(report)+'\n'+crash_text)
            self.assertTrue(report['visible']);self.assertTrue(report['complete'])
            self.assertTrue(report['main_deleted_after_return'],report)
            self.assertTrue(report['coordinator_cleared_after_return'],report)
            self.assertEqual(report['profile'],'device');self.assertFalse(report['loading_visible'])
            self.assertIn('main_returned',[entry['stage'] for entry in report['checkpoints']])


if __name__=='__main__':unittest.main()
