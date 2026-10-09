"""Create small, lossless Help illustrations from actual native UI captures."""
from pathlib import Path
import hashlib
import json
import os
import sys
import tempfile
from types import SimpleNamespace
from PyQt6.QtCore import Qt,QPoint
from PyQt6.QtGui import QImage,QPixmap,QPainter,QRegion
from PyQt6.QtWidgets import QApplication,QWidget

root=Path(__file__).resolve().parent
app=root.parent
current=app.parent/'ui_redesign_20261008'/'implemented-review'
legacy=app/'guide_images'
sources={name:current/name for name in (
 'structure.png','materials.png','simulation-rcwa.png','simulation-meep.png',
 'simulation-index-shift.png','simulation-fields.png','simulation-saved-results.png',
 'simulation-sweep.png','ai-search.png','settings.png')}
sources.update({
 'structure-regions.png':legacy/'structure-regions.png',
 'structure-cross-section.png':legacy/'structure-cross-section.png',
 'materials-import-csv.png':legacy/'materials-import-csv.png',
 'simulation-phase.png':legacy/'simulation-phase-and-phase-change.png',
 'field-playback.png':legacy/'engine-electric-fields-3d-field-playback.png',
 'ai-search-training.png':legacy/'ai-search-training.png',
 'settings-performance.png':legacy/'settings-performance.png',
})
manifest=[]
for filename,source in sources.items():
    image=QImage(str(source))
    if image.isNull():raise RuntimeError(f'Missing native screenshot: {source}')
    thumbnail=image.scaledToWidth(768,Qt.TransformationMode.SmoothTransformation)
    if not thumbnail.save(str(root/filename)):raise RuntimeError(filename)
    manifest.append({'asset':filename,'source':str(source),'description':'Real Qt screenshot, resized only; example values are not current project results.'})
# Render exactly the bundled geometry with the application's native viewer.
# An isolated data root keeps capture generation out of the user's library.
with tempfile.TemporaryDirectory(prefix='s4_help_capture_') as temporary:
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    os.environ['S4_LIBRARY_ROOT']=temporary
    sys.path.insert(0,str(app))
    import pandas as pd
    from qt_common import theme_manager
    from qt_device_builder import GeometryViewport
    qt_app=QApplication.instance() or QApplication([])
    project=json.loads((root/'air-hole-example.json').read_text(encoding='utf-8'))
    store=SimpleNamespace(layers=pd.DataFrame(project['layers']),patterns=pd.DataFrame(project['patterns']),settings=project['settings'],appearance=project['appearance'])
    viewport=GeometryViewport();viewport.resize(360,440);viewport.set_model(store,'',3)
    viewport.show()
    for look,filename in (('glass_dark','first-device.png'),('glass_light','first-device-light.png')):
        theme_manager().apply_look(look,persist=False);qt_app.processEvents()
        capture=QPixmap(720,880);capture.setDevicePixelRatio(2);capture.fill(Qt.GlobalColor.transparent)
        painter=QPainter(capture)
        viewport.render(painter,QPoint(),QRegion(),QWidget.RenderFlag.DrawChildren)
        painter.end()
        if not capture.save(str(root/filename)):raise RuntimeError(filename)
        manifest.append({'asset':filename,'source':'GeometryViewport.set_model(air-hole-example.json, cells=3)','description':f'Native Qt geometry renderer capture in {look} of the bundled constant-index tutorial. Exploded display is not to scale; no calculated spectrum or field values.'})
    viewport.close()
actual=root/'silicon-reference-run'
if (actual/'bundle.json').is_file():
    bundle=json.loads((actual/'bundle.json').read_text(encoding='utf-8'))
    for item in bundle['files']:
        if not item['file'].endswith('.png'):continue
        path=actual/item['file']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise RuntimeError(f'Actual simulation image checksum changed: {path}')
        manifest.append({'asset':'silicon-reference-run/'+item['file'],'source':item['source'],
            'sha256':item['sha256'],'provenance':'silicon-reference-run/provenance.json',
            'description':'Actual production S4 calculation or its applied inputs, rendered by native Qt/Matplotlib; no invented curves or fields. Constant-index demonstration model.'})
(root/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print(f'Saved {len(manifest)} native screenshot examples')
