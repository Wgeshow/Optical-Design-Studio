"""Removing a workspace must disconnect its long-lived store callbacks."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6 import sip
from PyQt6.QtCore import QObject, QCoreApplication, QEvent, pyqtSignal
from PyQt6.QtWidgets import QApplication
from qt_research_common import ResearchWorkspaceBase
from qt_research_journey import ResearchExecutionPanels

APP=QApplication.instance() or QApplication([])


class Store(QObject):
    busy_changed=pyqtSignal(bool)
    changed=pyqtSignal(str)
    progress=pyqtSignal(dict)
    run_finished=pyqtSignal(dict)
    run_failed=pyqtSignal(str)
    busy=False
    def cancel(self):pass


class ResearchExecutionLifetimeTests(unittest.TestCase):
    def test_deleted_workspace_cannot_receive_any_later_store_event(self):
        store=Store()
        page=ResearchWorkspaceBase(store)
        panels=ResearchExecutionPanels(page)
        page._owns_run=True
        panels._observing_run=True
        self.assertGreater(store.receivers(store.changed), 0)
        page.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        APP.processEvents()
        errors=[]
        with patch('sys.excepthook',side_effect=lambda kind,error,tb:errors.append(str(error))):
            store.changed.emit('study')
            store.busy_changed.emit(False)
            store.progress.emit({'message':'Other workspace progress'})
            store.run_failed.emit('Other workspace failure')
            store.run_finished.emit({'summary':{'status':'complete'}})
            APP.processEvents()
        self.assertEqual(errors,[])
        # Python references remain in this test, so PyQt may retain proxy
        # receiver counts. The owned Qt receiver must still be destroyed and
        # incapable of dispatching to the deleted controls.
        self.assertTrue(sip.isdeleted(panels))


if __name__=='__main__':unittest.main()
