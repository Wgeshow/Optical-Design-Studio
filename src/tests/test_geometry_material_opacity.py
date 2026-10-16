"""Material preview opacity affects real pixels without rebuilding geometry."""
import os
import unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import QApplication
from qt_common import theme_manager
from qt_device_builder import GeometryViewport
from tests.test_qt_structure import MemoryStore


class GeometryMaterialOpacityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        theme_manager().apply_look('glass_dark',persist=False)
        self.view=GeometryViewport();self.view.resize(680,640)
        self.view.layers=[dict(Name='Air',Material='Air',Thickness_um=0),
            dict(Name='Patterned',Material='GaAs',Thickness_um=.22),
            dict(Name='Lower',Material='SiC',Thickness_um=0)]
        self.view.patterns=[dict(layer='Patterned',material='Air',shape='circle',
            cx=0,cy=0,sx=.1,sy=.1,angle=0)]
        self.view.selected='Patterned';self.view.cells=1
        self.view.ax=self.view.ay=.54;self.view.exploded=False
        self.view.hidden_layers={'Air'};self.view.show_axes=False
        self.view.angle=-.78;self.view.elevation=.7
        self.view.show();self.app.processEvents()

    def tearDown(self):
        self.view.close();self.view.deleteLater();self.app.processEvents()

    def test_body_reveals_lower_material_and_zero_matches_hidden_geometry(self):
        original_layers=[dict(layer) for layer in self.view.layers]
        original_patterns=[dict(region) for region in self.view.patterns]
        camera=(self.view.angle,self.view.elevation,self.view.zoom)
        self.view.grab()
        geometry=self.view._stack_geometry()
        projection=self.view._projection
        overlap=projection[1][6].intersected(projection[2][6])
        bounds=overlap.boundingRect()
        points=[(x,y) for y in range(int(bounds.top())+4,int(bounds.bottom())-4,5)
            for x in range(int(bounds.left())+4,int(bounds.right())-4,5)
            if all(overlap.contains(QPointF(x+dx,y+dy))
                for dx,dy in ((0,0),(-4,-4),(-4,4),(4,-4),(4,4)))]
        self.assertGreater(len(points),100)
        images={}
        for opacity in (100,40,0):
            self.view.material_opacities={'GaAs':opacity}
            self.view.layer_colors={'Lower':'#00ff00'}
            first=self.view.grab().toImage()
            self.view.layer_colors={'Lower':'#ff00ff'}
            second=self.view.grab().toImage()
            changed=sum(first.pixel(x,y)!=second.pixel(x,y) for x,y in points)
            if opacity==100:self.assertEqual(changed,0)
            else:self.assertGreater(changed,100)
            images[opacity]=second
            self.assertIs(self.view._stack_geometry(),geometry)
            self.assertIs(self.view._projection,projection)
        self.assertGreater(sum(images[100].pixel(x,y)!=images[40].pixel(x,y)
            for x,y in points),100)
        self.assertGreater(sum(images[40].pixel(x,y)!=images[0].pixel(x,y)
            for x,y in points),100)
        self.view.hidden_layers.add('Patterned')
        hidden=self.view.grab().toImage()
        self.assertEqual(sum(images[0].pixel(x,y)!=hidden.pixel(x,y)
            for x,y in points),0,'An invisible material must cast no visible wall, rim or shadow')
        self.assertEqual(self.view.layers,original_layers)
        self.assertEqual(self.view.patterns,original_patterns)
        self.assertEqual((self.view.angle,self.view.elevation,self.view.zoom),camera)

    def test_unit_cell_and_section_apply_preview_opacity(self):
        for mode in ('Unit cell','Cross-section'):
            self.view.mode=mode
            images=[]
            for opacity in (100,40,0):
                self.view.material_opacities={'GaAs':opacity}
                images.append(self.view.grab().toImage())
            for first,second in zip(images,images[1:]):
                changes=sum(first.pixel(x,y)!=second.pixel(x,y)
                    for y in range(30,610,5) for x in range(30,650,5))
                self.assertGreater(changes,100,mode)

    def test_model_receives_copy_of_exact_material_opacity_map(self):
        store=MemoryStore();store.appearance={'material_opacities':{'GaAs':40}}
        original_layers=store.layers.copy(deep=True)
        original_patterns=store.patterns.copy(deep=True)
        self.view.set_model(store,'PCS1',3)
        self.assertEqual(self.view.material_opacities,{'GaAs':40})
        self.assertEqual(self.view.material_opacity(self.view.layers[1]),.4)
        self.assertEqual(self.view.material_opacity(self.view.layers[0]),1.)
        store.appearance['material_opacities']['GaAs']=0
        self.assertEqual(self.view.material_opacities,{'GaAs':40})
        self.assertTrue(store.layers.equals(original_layers))
        self.assertTrue(store.patterns.equals(original_patterns))


if __name__=='__main__':unittest.main()
