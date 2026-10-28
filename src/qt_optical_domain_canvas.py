"""Read-only domain sketches driven by actual optical study inputs."""
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget
from qt_common import COLORS, theme_manager


class OpticalDomainCanvas(QWidget):
    def __init__(self, store, controls=None, parent=None):
        super().__init__(parent)
        self.store, self.controls = store, controls or {}
        self.setMinimumSize(260, 280)
        self.setAccessibleName('FDTD domain preview; geometry only, not a field solution')
        theme_manager().changed.connect(self.update)
        if hasattr(store, 'changed'): store.changed.connect(self.update)
        for control in self.controls.values():
            for name in ('valueChanged', 'currentIndexChanged', 'toggled'):
                signal = getattr(control, name, None)
                if signal is not None:
                    signal.connect(self.update)
                    break

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors=COLORS[theme_manager().mode]
        p.fillRect(self.rect(), QColor(colors['panel']))
        w, h = self.width(), self.height()
        box = QRectF(72, 58, max(100, w-144), max(150, h-114))
        p.setPen(QColor(colors['text']))
        p.drawText(12, 24, 'Solved domain · geometry preview')
        p.drawText(12, 43, 'Periodic laterally · normal incidence · PML along Z')
        p.setBrush(QColor('#dfedff')); p.drawRect(box)
        depth = min(38., box.height()/6)
        p.fillRect(QRectF(box.x(), box.y(), box.width(), depth), QColor('#a8ccf5'))
        p.fillRect(QRectF(box.x(), box.bottom()-depth, box.width(), depth), QColor('#a8ccf5'))
        p.drawText(box.adjusted(8, 0, -8, -box.height()+depth), Qt.AlignmentFlag.AlignCenter, 'PML')
        p.drawText(QRectF(box.x(), box.bottom()-depth, box.width(), depth), Qt.AlignmentFlag.AlignCenter, 'PML')
        try:
            rows = [r for r in self.store.layers.to_dict('records') if float(r.get('Thickness_um', 0)) > 0]
        except (AttributeError, ValueError, TypeError): rows = []
        center = QRectF(box.x()+10, box.y()+box.height()*.36, box.width()-20, box.height()*.30)
        colors = ('#b9cce0', '#7cadd8', '#d5e0ed', '#91badb')
        if rows:
            total = sum(float(r.get('Thickness_um', 0)) for r in rows)
            y = center.y()
            for i, row in enumerate(rows):
                height = center.height()*float(row.get('Thickness_um', 0))/total
                p.fillRect(QRectF(center.x(), y, center.width(), height), QColor(colors[i%len(colors)]))
                y += height
        else:
            p.drawText(center, Qt.AlignmentFlag.AlignCenter, 'No finite layers configured')
        p.setPen(QPen(QColor('#2168b4'), 2, Qt.PenStyle.DashLine))
        for x in (box.left(), box.right()): p.drawLine(int(x), int(box.top()+depth), int(x), int(box.bottom()-depth))
        p.setPen(QColor('#234563'))
        p.drawText(5, int(box.center().y()), 'Periodic')
        p.drawText(int(box.right()+3), int(box.center().y()), 'Periodic')
        p.drawText(12, h-14, 'Schematic padding/stack spacing · physical inputs remain editable')
        p.end()


class ReciprocalPathCanvas(QWidget):
    """Fractional reciprocal-coordinate preview, never a band calculation."""
    def __init__(self, workspace, parent=None):
        super().__init__(parent); self.workspace=workspace
        self.setMinimumHeight(210)
        self.setAccessibleName('Reciprocal sampling preview in fractional coordinates k1 and k2')
        workspace.kpoints.cellChanged.connect(self.update)
        workspace.sampling.currentIndexChanged.connect(self.update)
        workspace.grid_counts.textChanged.connect(self.update)
        workspace.grid_offset.textChanged.connect(self.update)
        theme_manager().changed.connect(self.update)

    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors=COLORS[theme_manager().mode]
        p.fillRect(self.rect(),QColor(colors['panel'])); p.setPen(QColor(colors['text']))
        mode=self.workspace.sampling.currentData()
        p.drawText(12,22,'Reciprocal sampling · k1/k2 projection · not a band solution')
        try:
            if mode=='grid':
                counts=[int(v.strip()) for v in self.workspace.grid_counts.text().split(',')]
                offset=[float(v.strip()) for v in self.workspace.grid_offset.text().split(',')]
                if len(counts)<2 or min(counts)<=0: raise ValueError()
                points=[(i/counts[0]+offset[0],j/counts[1]+offset[1])
                        for i in range(min(counts[0],25)) for j in range(min(counts[1],25))]
                note='Grid preview capped at 25 points per displayed axis; exact counts remain in inputs.'
            else:
                table=self.workspace.kpoints
                points=[tuple(float(table.item(row,col).text()) for col in range(2)) for row in range(table.rowCount())]
                note='Path connects vertices.' if mode=='path' else 'Explicit samples are not connected.'
            if not points: raise ValueError()
            xmin,xmax=min(x for x,y in points),max(x for x,y in points)
            ymin,ymax=min(y for x,y in points),max(y for x,y in points)
            dx,dy=max(xmax-xmin,.25),max(ymax-ymin,.25)
            frame=QRectF(50,43,max(80,self.width()-95),max(70,self.height()-88))
            p.setPen(QPen(QColor(colors['border']),1)); p.drawRect(frame)
            mapped=[(frame.x()+frame.width()*(.1+.8*(x-xmin)/dx),frame.bottom()-frame.height()*(.1+.8*(y-ymin)/dy)) for x,y in points]
            p.setPen(QPen(QColor(colors['accent']),2))
            if mode=='path':
                for first,last in zip(mapped,mapped[1:]): p.drawLine(int(first[0]),int(first[1]),int(last[0]),int(last[1]))
            p.setBrush(QColor(colors['accent']))
            for index,(x,y) in enumerate(mapped):
                p.drawEllipse(QRectF(x-3,y-3,6,6))
                if mode!='grid': p.drawText(int(x+5),int(y-5),str(index+1))
            p.setPen(QColor(colors['text'])); p.drawText(12,self.height()-13,note)
        except (ValueError,AttributeError,IndexError,TypeError):
            p.drawText(12,65,'Finish the reciprocal coordinates to update this preview; draft values are preserved.')
        p.end()


class OpticalSamplingCanvas(QWidget):
    """Current-value sampling diagram, with no calculated spectrum or field."""
    def __init__(self, values, title, controls=(), parent=None):
        super().__init__(parent); self.values=values; self.title=title
        self.setMinimumSize(300,280); self.setAccessibleName(title+'; input schematic only')
        for control in controls:
            for name in ('valueChanged','currentIndexChanged','textChanged','toggled'):
                signal=getattr(control,name,None)
                if signal is not None: signal.connect(self.update); break
        theme_manager().changed.connect(self.update)

    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors=COLORS[theme_manager().mode]; p.fillRect(self.rect(),QColor(colors['panel']))
        p.setPen(QColor(colors['text'])); p.drawText(20,30,self.title)
        try:
            values=self.values(); first=float(values['first']); last=float(values['last'])
            if last<first: raise ValueError()
            w,h=self.width(),self.height(); y=max(130,h*.43); left,right=50,w-50
            p.setPen(QPen(QColor(colors['border']),1)); p.drawLine(left,int(y),right,int(y))
            p.setBrush(QColor(colors['select'])); p.setPen(QPen(QColor(colors['accent']),2))
            p.drawRect(QRectF(left+25,y-44,max(30,right-left-50),44))
            for x in (left+25,right-25): p.drawLine(int(x),int(y-48),int(x),int(y+9))
            p.setPen(QColor(colors['text']))
            p.drawText(left,int(y+30),f'{first:g} nm'); p.drawText(max(left+90,right-90),int(y+30),f'{last:g} nm')
            p.drawText(20,int(y+67),str(values.get('detail','')))
            if 'center' in values:
                p.setPen(QPen(QColor(colors['accent']),1,Qt.PenStyle.DashLine))
                p.drawLine(int((left+right)/2),int(y-58),int((left+right)/2),int(y+8))
                p.setPen(QColor(colors['text'])); p.drawText(20,int(y+95),f'Reference / selected wavelength: {values["center"]:g} nm')
            p.drawText(20,h-44,str(values.get('source','')))
            p.drawText(20,h-20,'Input sampling schematic · no computed spectrum or fields')
        except (ValueError,TypeError,KeyError):
            p.drawText(20,80,'Finish the wavelength range to update this schematic.')
        p.end()
