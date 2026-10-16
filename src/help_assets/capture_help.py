"""Capture Help in the real desktop composition with isolated example data."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
temporary=tempfile.TemporaryDirectory(prefix='s4_help_review_')
os.environ['S4_LIBRARY_ROOT']=temporary.name
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root.parent))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QTextCursor
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_app import OpticalStudio
from qt_common import theme_manager
from qt_help import REAL_EXAMPLE_TOPIC

app=QApplication([]);app.setQuitOnLastWindowClosed(False)
store=ProjectStore(DataLibrary(temporary.name),restore=False)
store.load_project(json.loads((root/'air-hole-example.json').read_text(encoding='utf-8')))
window=OpticalStudio(store);window.resize(1536,1024);window.show()
theme_manager().apply_look('glass_dark',persist=False)
window.adapt_interface();window._navigate_route(7)
guide=window.pages['About'].help_guide
for index,name in ((0,'help-native-proof'),(2,'help-about-proof'),(3,'help-updates-proof')):
    guide.center_tabs.setCurrentIndex(index)
    for _ in range(6):app.processEvents()
    window.grab().save(str(root/(name+'.png')))
    if index==0:
        gallery=root.parent.parent/'ui_redesign_20261008'/'implemented-review'/'help.png'
        window.grab().save(str(gallery))
guide.open_topic('Materials')
for _ in range(4):app.processEvents()
window.grab().save(str(root/'help-materials-proof.png'))
guide.open_topic(REAL_EXAMPLE_TOPIC)
for _ in range(6):app.processEvents()
window.grab().save(str(root/'help-actual-spectrum-proof.png'))
cursor=guide.reader.document().find('Actual S4 fields at 1550 nm')
cursor.movePosition(QTextCursor.MoveOperation.PreviousBlock)
guide.reader.setTextCursor(cursor);guide.reader.ensureCursorVisible()
for _ in range(6):app.processEvents()
guide.reader.verticalScrollBar().setValue(round(guide.reader.document().documentLayout().blockBoundingRect(cursor.block()).top()))
for _ in range(4):app.processEvents()
window.grab().save(str(root/'help-actual-fields-proof.png'))
guide.open_topic('Getting started');window.resize(1024,768);window.adapt_interface()
for _ in range(6):app.processEvents()
window.grab().save(str(root/'help-compact-proof.png'))
window._saved_project=store.project();window.close();app.processEvents()
print(root/'help-native-proof.png')
