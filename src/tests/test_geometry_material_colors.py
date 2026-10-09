"""Material RGB metadata changes native pixels, with layer overrides taking priority."""
import copy
import os
import tempfile
import unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtCore import Qt,QPointF
from PyQt6.QtWidgets import QApplication
from data_library import DataLibrary
from qt_core import ProjectStore
from qt_common import theme_manager
from qt_device_builder import GeometryViewport,DeviceBuilderPage
from qt_appearance import AppearancePage
from tests.test_qt_structure import MemoryStore


class GeometryMaterialColorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        theme_manager().apply_look('glass_dark',persist=False)
        self.temp=tempfile.TemporaryDirectory()
        self.store=ProjectStore(DataLibrary(self.temp.name),restore=False)
        sample=MemoryStore();self.store.set_structure(sample.materials,sample.layers,sample.patterns)
        self.view=GeometryViewport();self.view.resize(780,760)
        self.view.hidden_layers={'AirAbove','AirBelow'};self.view.show_axes=False
        self.view.set_model(self.store,'PCS1',1);self.view.show();self.app.processEvents()
        self.extra=[]

    def tearDown(self):
        for widget in self.extra+[self.view]:widget.close();widget.deleteLater()
        self.app.processEvents();self.temp.cleanup()

    def update_colors(self,material,layer=None):
        values={'material_colors':material}
        if layer is not None:values['layer_colors']=layer
        self.store.update_appearance(values)
        self.view.set_model(self.store,self.view.selected,1)

    def optical_inputs(self):
        project=self.store.project()
        return {key:copy.deepcopy(project[key]) for key in ('materials','layers','patterns','settings','performance')}

    @staticmethod
    def changed(first,second,points):return sum(first.pixel(x,y)!=second.pixel(x,y) for x,y in points)

    def test_rendered_material_rgb_and_explicit_layer_priority_in_all_views(self):
        before=self.optical_inputs();undo=len(self.store._undo)
        for mode in ('3D Stack','Unit cell','Cross-section'):
            with self.subTest(mode=mode):
                self.view.mode=mode;self.view.selected='PCS1'
                self.update_colors({'GaAs':'#ff183a'},{'PCS1':'#37c85a'})
                first=self.view.grab().toImage()
                self.update_colors({'GaAs':'#244dff'})
                second=self.view.grab().toImage()
                if mode=='3D Stack':
                    path=self.view._projection[1][6];bounds=path.boundingRect()
                    points=[(x,y) for y in range(int(bounds.top())+5,int(bounds.bottom())-5,3)
                        for x in range(int(bounds.left())+5,int(bounds.right())-5,3)
                        if all(path.contains(QPointF(x+dx,y+dy)) for dx,dy in ((0,0),(-4,-4),(-4,4),(4,-4),(4,4)))]
                elif mode=='Unit cell':points=[(x,y) for y in range(100,660,5) for x in range(100,680,5)]
                else:
                    rect=next(path for path,name in self.view.hits if name=='PCS1')
                    points=[(x,y) for y in range(int(rect.top())+5,int(rect.bottom())-5,3)
                        for x in range(int(rect.left())+5,int(rect.right())-5,3)]
                self.assertGreater(len(points),100)
                self.assertEqual(self.changed(first,second,points),0,'Layer override must hold its actual rendered RGB')
                self.update_colors({'GaAs':'#244dff'},{});third=self.view.grab().toImage()
                self.assertGreater(self.changed(second,third,points),100)
                self.update_colors({'GaAs':'#ff183a'});fourth=self.view.grab().toImage()
                self.assertGreater(self.changed(third,fourth,points),100)
        self.assertEqual(self.optical_inputs(),before);self.assertEqual(len(self.store._undo),undo)

    def test_shared_material_updates_stack_swatches_settings_and_cached_geometry(self):
        page=DeviceBuilderPage(self.store);page.resize(1460,950);page.show()
        settings=AppearancePage(store=self.store);self.extra=[page,settings]
        self.view.grab();geometry=self.view._stack_geometry();projection=self.view._projection
        before=self.optical_inputs()
        self.update_colors({'GaAs':'#a847e6'},{'PCS1':'#d46b15'})
        self.app.processEvents();self.view.grab()
        self.assertIs(self.view._stack_geometry(),geometry);self.assertIs(self.view._projection,projection)
        for preview in (self.view,page.viewport,settings.viewport):
            self.assertEqual(preview.material_colors,{'GaAs':'#a847e6'})
            for i,layer in enumerate(preview.layers):
                if layer['Name']=='PCS1':self.assertEqual(preview.color(layer,i),'#d46b15')
                elif layer['Material']=='GaAs':self.assertEqual(preview.color(layer,i),'#a847e6')
        for i in (1,2):
            swatch=page.layer_list.item(i).data(Qt.ItemDataRole.UserRole+2)
            self.assertEqual(swatch,page.viewport.color(page.viewport.layers[i],i))
        self.store.appearance['material_colors']['GaAs']='#010203'
        self.assertEqual(self.view.material_colors,{'GaAs':'#a847e6'},'Viewport must copy metadata')
        self.assertEqual(self.optical_inputs(),before)

    def test_filled_region_uses_its_material_color_without_coloring_air_apertures(self):
        import pandas as pd
        from model import PAT_COLS
        filled=pd.DataFrame([['rectangle','PCS1','Au',.24,0.,.18,.22,35.]],columns=PAT_COLS)
        patterns=pd.concat([self.store.patterns,filled],ignore_index=True)
        self.store.set_structure(self.store.materials,self.store.layers,patterns)
        before=self.optical_inputs()
        for mode in ('3D Stack','Unit cell','Cross-section'):
            with self.subTest(mode=mode):
                self.view.mode=mode;self.view.selected='PCS1'
                self.update_colors({'Au':'#ef2040','Air':'#ff0000'})
                first=self.view.grab().toImage();geometry=self.view._stack_geometry()
                self.update_colors({'Au':'#15dc45','Air':'#ff0000'})
                second=self.view.grab().toImage()
                points=[(x,y) for y in range(30,self.view.height()-30,2) for x in range(30,self.view.width()-30,2)]
                self.assertGreater(self.changed(first,second,points),40)
                self.assertIs(self.view._stack_geometry(),geometry)
                # Air is a real empty region, so RGB metadata cannot paint its aperture.
                self.update_colors({'Au':'#15dc45','Air':'#0000ff'})
                third=self.view.grab().toImage()
                self.assertEqual(self.changed(second,third,points),0)
        self.assertEqual(self.optical_inputs(),before)

    def test_filled_region_opacity_is_independent_of_its_host_material(self):
        import pandas as pd
        from model import PAT_COLS
        filled=pd.DataFrame([['rectangle','PCS1','Au',.24,0.,.18,.22,35.]],columns=PAT_COLS)
        self.store.set_structure(self.store.materials,self.store.layers,pd.concat([self.store.patterns,filled],ignore_index=True))
        self.view.hidden_layers={layer['Name'] for layer in self.view.layers if layer['Name']!='PCS1'}
        before=self.optical_inputs()
        for mode in ('3D Stack','Unit cell','Cross-section'):
            with self.subTest(mode=mode):
                self.view.mode=mode;self.view.selected='PCS1'
                images=[]
                for opacity in (100,40,0):
                    self.store.update_appearance({'material_opacities':{'GaAs':0,'Au':opacity}})
                    self.update_colors({'Au':'#ef2040'})
                    images.append(self.view.grab().toImage())
                points=[(x,y) for y in range(30,self.view.height()-30,2) for x in range(30,self.view.width()-30,2)]
                self.assertGreater(self.changed(images[0],images[1],points),40,'A hidden host must retain the distinct visible material region')
                self.assertGreater(self.changed(images[1],images[2],points),40)
                geometry=self.view._stack_geometry()
                self.store.update_appearance({'material_opacities':{'GaAs':100,'Au':0}})
                self.view.set_model(self.store,'PCS1',1);visible_host=self.view.grab().toImage()
                if mode=='3D Stack':
                    path=self.view._projection[1][8][-1][0];bounds=path.boundingRect()
                    region_points=[(x,y) for y in range(int(bounds.top())+4,int(bounds.bottom())-4)
                        for x in range(int(bounds.left())+4,int(bounds.right())-4)
                        if all(path.contains(QPointF(x+dx,y+dy)) for dx,dy in ((-3,-3),(-3,3),(3,-3),(3,3)))]
                elif mode=='Unit cell':region_points=[(595,380),(600,380),(605,380)]
                else:
                    rect=next(path for path,name in self.view.hits if name=='PCS1')
                    x=round((rect.left()+rect.right())/2+.24/self.view.ax*rect.width())
                    region_points=[(x,round(rect.center().y())+dy) for dy in (-5,0,5)]
                self.assertTrue(region_points)
                self.assertEqual(self.changed(images[2],visible_host,region_points),0,'A zero-opacity region must reveal the backdrop instead of its host')
                self.assertIs(self.view._stack_geometry(),geometry)
        self.assertEqual(self.optical_inputs(),before)


if __name__=='__main__':unittest.main()
