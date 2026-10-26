"""Native startup chooser for two workspaces sharing one project library."""
from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDialog, QFrame, QHBoxLayout,
    QLabel, QProgressBar, QPushButton, QScrollArea, QSizeGrip, QSizePolicy, QVBoxLayout, QWidget)

from qt_common import COLORS, theme_manager
from qt_custom_device import DeviceCanvas
from qt_reference_style import optical_logo, reference_icon

STARTUP_WORKSPACE_KEY='startup_workspace_v1'


def normalize_workspace_profile(value,default=None):
    """Normalize user-facing aliases; reject unknown explicit choices."""
    if value is None or value=='':return default
    if not isinstance(value,str):raise ValueError('Workspace must be device, original, or ask.')
    key=value.strip().casefold().replace('-','_').replace(' ','_')
    aliases={'device':'device','device_studio':'device','modern':'device','new':'device','multiphysics':'device',
        'original':'original','original_optical':'original','original_optical_studio':'original',
        'classic':'original','legacy':'original','ask':'ask','choose':'ask','chooser':'ask'}
    if key not in aliases:raise ValueError('Workspace must be device, original, or ask.')
    return aliases[key]


def _preview_device():
    """A read-only structure illustration; no project or solver state is used."""
    base=dict(cx_um=0.,cy_um=0.,angle_deg=0.,vertices=[],enabled=True)
    return dict(schema_version=1,name='Si device illustration',width_um=2.,depth_um=2.,temperature_K=300.,
        mesh=dict(nx=16,ny=16,nz_per_layer=8,max_nodes=0),
        layers=[dict(id='p',name='p-Si',material_id='silicon',thickness_um=.2,donor_cm3=0.,acceptor_cm3=1e17,enabled=True),
            dict(id='n',name='n-Si',material_id='silicon',thickness_um=.8,donor_cm3=1e16,acceptor_cm3=0.,enabled=True)],
        shapes=[dict(base,id=f'hole_{ix}_{iy}',name='Air hole',layer_id='p',shape='circle',operation='void',
            material_id='air',cx_um=ix*.45,cy_um=iy*.45,size_x_um=.18,size_y_um=.18)
            for iy in (-1,0,1) for ix in (-1,0,1)],doping_regions=[],
        contacts=[dict(base,id='P',name='P Au ring',layer_id='p',surface='top',boundary='ohmic',voltage_V=0.,bias_scale=1.,
            shape='square_ring',size_x_um=1.8,size_y_um=1.8,inner_size_x_um=1.3,inner_size_y_um=1.3,
            optical_material_name='Au',optical_thickness_um=.03),
            dict(base,id='N',name='N Au reflector',layer_id='n',surface='bottom',boundary='ohmic',voltage_V=0.,bias_scale=0.,
            shape='rectangle',size_x_um=2.,size_y_um=2.,optical_material_name='Au',optical_thickness_um=.1)])


class _DeviceThumbnail(DeviceCanvas):
    def __init__(self,parent=None):
        super().__init__('3d',parent)
        self.compact_preview=True;self.depth_display_mode='film'
        self.set_device(_preview_device());self.setMinimumSize(0,190)
        self.setAccessibleName('Device Studio structure preview with nine air holes and gold square-ring contact')
        self.setToolTip('Rotate the device preview by dragging.')

    def _paint_axes(self,painter):
        pass

    def minimumSizeHint(self):return QSize(0,190)


class _OriginalThumbnail(QWidget):
    """Scalable native illustration of the original optical controls."""
    def __init__(self,parent=None):
        super().__init__(parent);self.setMinimumSize(0,190)
        self.setAccessibleName('Original Optical Studio layer, pattern, material and spectrum illustration')
        theme_manager().changed.connect(self.update)

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c=COLORS[theme_manager().mode]
        p.fillRect(self.rect(),QColor(c['field']))
        factor=min(self.width()/650.,self.height()/360.)
        p.translate((self.width()-650*factor)/2,(self.height()-360*factor)/2);p.scale(factor,factor)
        p.setFont(QFont('Segoe UI',10))
        def panel(rect,title):
            p.setPen(QPen(QColor(c['border']),1));p.setBrush(QColor(c['panel']));p.drawRoundedRect(rect,3,3)
            p.fillRect(QRectF(rect.left()+1,rect.top()+1,rect.width()-2,27),QColor(c['header']))
            p.setPen(QColor(c['text']));font=QFont(p.font());font.setBold(True);p.setFont(font)
            p.drawText(QRectF(rect.left()+9,rect.top()+3,rect.width()-18,21),Qt.AlignmentFlag.AlignVCenter,title)
            font.setBold(False);p.setFont(font)
        layer_rect=QRectF(8,8,281,165);panel(layer_rect,'Layers')
        stack_rect=QRectF(299,8,343,165);panel(stack_rect,'Layer stack')
        swatches=['#91cee8','#4fa8e8','#91c89c','#ee929c','#55a4e6','#778fa3']
        for index,name in enumerate(('Air','SiO₂','AlGaAs','GaAs','ITO','Substrate')):
            y=53+index*18
            p.setPen(QColor(c['muted']));p.drawText(QPointF(18,y+11),str(index+1))
            p.fillRect(QRectF(39,y,12,12),QColor(swatches[index]))
            p.setPen(QColor(c['text']));p.drawText(QPointF(59,y+11),name)
            p.drawText(QPointF(189,y+11),('—','110','70','220','500','—')[index])
        for index,(name,color) in enumerate(zip(('Air','SiO₂','AlGaAs','GaAs','ITO','Substrate'),swatches)):
            p.fillRect(QRectF(324,60+index*13,171,13),QColor(color))
            p.fillRect(QRectF(516,48+index*18,12,12),QColor(color));p.setPen(QColor(c['text']));p.drawText(QPointF(536,59+index*18),name)
        patterns=QRectF(8,184,217,167);panel(patterns,'Patterns')
        materials=QRectF(235,184,160,167);panel(materials,'Materials')
        spectrum=QRectF(405,184,237,167);panel(spectrum,'Optical spectra')
        for index,(name,parameter) in enumerate((('Circle','r = 120 nm'),('Rectangle','w = 450 nm'),('Circle','r = 80 nm'),('Rectangle','w = 300 nm'))):
            y=230+index*25;p.setPen(QColor(c['text']));p.drawText(QPointF(23,y),name);p.drawText(QPointF(101,y),parameter)
        for index,name in enumerate(('Si','SiO₂','AlGaAs','Au')):
            y=230+index*25;p.setPen(QColor(c['text']));p.drawText(QPointF(246,y),name);p.drawText(QPointF(319,y),('n(λ)','k(λ)')[index%2])
        chart=QRectF(432,223,174,105)
        p.setPen(QPen(QColor(c['grid']),.8))
        for index in range(5):
            x=chart.left()+chart.width()*index/4;y=chart.top()+chart.height()*index/4
            p.drawLine(QPointF(x,chart.top()),QPointF(x,chart.bottom()));p.drawLine(QPointF(chart.left(),y),QPointF(chart.right(),y))
        for key,color in enumerate((c['accent'],'#62d698','#f48282')):
            curve=QPainterPath()
            for index in range(100):
                x=index/99
                value=(.19+.72*math.exp(-((x-.57)/.24)**4)) if key==0 else (.17+.49*math.exp(-((x-.34)/.12)**2)+.09*math.sin(x*9)) if key==1 else (.06+.17*math.exp(-((x-.74)/.15)**2))
                point=QPointF(chart.left()+x*chart.width(),chart.bottom()-value*chart.height())
                curve.moveTo(point) if index==0 else curve.lineTo(point)
            p.setPen(QPen(QColor(color),1.8));p.drawPath(curve)
            p.drawLine(QPointF(614,232+key*17),QPointF(625,232+key*17));p.setPen(QColor(c['text']));p.drawText(QPointF(628,236+key*17),'RTA'[key])
        p.setPen(QColor(c['muted']));p.drawText(QRectF(427,331,185,15),Qt.AlignmentFlag.AlignCenter,'Wavelength (nm)')


class _WorkspaceHeader(QFrame):
    """The native window manager moves the frameless chooser from its header."""
    def __init__(self,parent=None):
        super().__init__(parent);self._drag_offset=None

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            handle=self.window().windowHandle()
            if handle is not None and handle.startSystemMove():
                event.accept();return
            self._drag_offset=event.globalPosition().toPoint()-self.window().pos()
            event.accept();return
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if self._drag_offset is not None and event.buttons()&Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint()-self._drag_offset)
            event.accept();return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        self._drag_offset=None;super().mouseReleaseEvent(event)


class WorkspaceStartDialog(QDialog):
    """A user action accepts immediately; the helper owns preference writes."""
    def __init__(self,parent=None,current='device'):
        super().__init__(parent)
        normalized=normalize_workspace_profile(current,'device')
        self.selected_profile=normalized if normalized in ('device','original') else 'device'
        self._choice_committed=False
        self.setObjectName('workspaceStartDialog');self.setWindowTitle('Optical Design Studio · Choose your workspace')
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint,True)
        self.setMinimumSize(640,620)
        available=QApplication.primaryScreen().availableGeometry() if QApplication.primaryScreen() is not None else None
        self.resize(min(1586,max(640,available.width()-40)) if available is not None else 1586,
                    min(992,max(620,available.height()-60)) if available is not None else 992)
        root=QVBoxLayout(self);root.setContentsMargins(0,0,0,0);root.setSpacing(0)
        header=_WorkspaceHeader();header.setObjectName('workspaceBrandHeader');header.setFixedHeight(64)
        brand_row=QHBoxLayout(header);brand_row.setContentsMargins(26,8,26,8);brand_row.setSpacing(17)
        logo=QLabel();logo.setPixmap(optical_logo(42));logo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents);brand_row.addWidget(logo)
        self.brand=QLabel('Optical Design Studio');self.brand.setObjectName('workspaceBrand');self.brand.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents);brand_row.addWidget(self.brand);brand_row.addStretch()
        self.close_button=QPushButton('×');self.close_button.setObjectName('workspaceClose')
        self.close_button.setAccessibleName('Close workspace chooser');self.close_button.setToolTip('Close (Esc)')
        self.close_button.setFixedSize(34,34);self.close_button.setAutoDefault(False)
        self.close_button.clicked.connect(self.reject);brand_row.addWidget(self.close_button)
        root.addWidget(header)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);root.addWidget(scroll,1)
        self.content=QWidget();self.content.setObjectName('workspaceChoiceContent');scroll.setWidget(self.content)
        self.content_layout=QVBoxLayout(self.content);self.content_layout.setContentsMargins(65,22,65,18);self.content_layout.setSpacing(19)
        intro=QVBoxLayout();intro.setSpacing(4)
        self.heading=QLabel('Choose your workspace');self.heading.setObjectName('workspaceHeading');self.heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle=QLabel('Two workspaces. One project library.');self.subtitle.setObjectName('workspaceSubtitle');self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        intro.addWidget(self.heading);intro.addWidget(self.subtitle);self.content_layout.addLayout(intro)
        self.card_host=QWidget();self.card_layout=QHBoxLayout(self.card_host);self.card_layout.setContentsMargins(0,0,0,0);self.card_layout.setSpacing(32)
        self.cards={};self.open_buttons={};self.previews={}
        definitions=(('device','Device Studio','Optical, electrical & coupled',
            ('Editable device structures','Shared optical & electrical setup','I–V, C–V & linked results'),('cube','materials','simulation'),_DeviceThumbnail),
            ('original','Original Optical Studio','Original optical workflow',
            ('Layer & pattern tables','S4 spectra, sweeps & fields','Original optical controls'),('layers','sweep','settings'),_OriginalThumbnail))
        for profile,title,subtitle,features,icons,preview_type in definitions:
            card=QFrame();card.setObjectName('workspaceChoiceCard');card.setProperty('profile',profile)
            card.setMinimumWidth(0);card.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
            layout=QVBoxLayout(card);layout.setContentsMargins(18,15,18,20);layout.setSpacing(8)
            name=QLabel(title);name.setObjectName('workspaceCardTitle');name.setAlignment(Qt.AlignmentFlag.AlignCenter);layout.addWidget(name)
            lead=QLabel(subtitle);lead.setObjectName('workspaceCardSubtitle');lead.setAlignment(Qt.AlignmentFlag.AlignCenter);layout.addWidget(lead)
            preview_frame=QFrame();preview_frame.setObjectName('workspaceThumbnailFrame')
            preview_layout=QVBoxLayout(preview_frame);preview_layout.setContentsMargins(1,1,1,1)
            preview=preview_type();preview_layout.addWidget(preview);layout.addWidget(preview_frame,1)
            self.previews[profile]=preview
            feature_layout=QVBoxLayout();feature_layout.setSpacing(8);feature_layout.setContentsMargins(8,8,8,7)
            for feature,icon_name in zip(features,icons):
                row=QHBoxLayout();row.setSpacing(19)
                icon=QLabel();icon.setObjectName('workspaceFeatureIcon');icon.setPixmap(reference_icon(icon_name,COLORS[theme_manager().mode]['accent']).pixmap(27,27));icon.setFixedWidth(37);row.addWidget(icon)
                text=QLabel(feature);text.setObjectName('workspaceFeature');text.setWordWrap(True);row.addWidget(text,1);feature_layout.addLayout(row)
            layout.addLayout(feature_layout)
            button=QPushButton('Open '+title);button.setObjectName('openDeviceStudio' if profile=='device' else 'openOriginalOpticalStudio')
            button.setProperty('workspaceAction',True);button.setMinimumHeight(51);button.setAutoDefault(True)
            button.clicked.connect(lambda checked=False,value=profile:self.choose_profile(value));layout.addWidget(button)
            self.cards[profile]=card;self.open_buttons[profile]=button;self.card_layout.addWidget(card,1)
        self.content_layout.addWidget(self.card_host,1)
        footer=QVBoxLayout();footer.setSpacing(7)
        remember_row=QHBoxLayout();remember_row.addStretch()
        self.remember_check=QCheckBox('Remember my choice');self.remember_check.setObjectName('workspaceRemember');self.remember_check.setChecked(False)
        remember_row.addWidget(self.remember_check);remember_row.addStretch();footer.addLayout(remember_row)
        self.switch_hint=QLabel('You can switch workspaces from Menu.');self.switch_hint.setObjectName('workspaceSwitchHint');self.switch_hint.setAlignment(Qt.AlignmentFlag.AlignCenter);footer.addWidget(self.switch_hint)
        self.content_layout.addLayout(footer)
        self.resize_grip=QSizeGrip(self);self.resize_grip.setObjectName('workspaceResizeGrip')
        self.resize_grip.setAccessibleName('Resize workspace chooser');self.resize_grip.setFixedSize(18,18)
        self.open_buttons[self.selected_profile].setDefault(True)
        self.open_buttons[self.selected_profile].setFocus()
        theme_manager().changed.connect(self._apply_style);self._apply_style()

    @property
    def remember_choice(self):return self.remember_check.isChecked()

    def choose_profile(self,profile):
        profile=normalize_workspace_profile(profile)
        if profile not in ('device','original'):raise ValueError('Choose Device Studio or Original Optical Studio.')
        if self._choice_committed:return
        self._choice_committed=True
        for action in self.open_buttons.values():action.setEnabled(False)
        self.remember_check.setEnabled(False)
        self.selected_profile=profile;self.accept()

    def _apply_style(self,*_):
        c=COLORS[theme_manager().mode]
        self.setStyleSheet(f'''
            QDialog#workspaceStartDialog, QWidget#workspaceChoiceContent {{background:{c['bg']};color:{c['text']};}}
            #workspaceStartDialog QScrollArea {{background:{c['bg']};border:0;}}
            #workspaceStartDialog QLabel {{background:transparent;color:{c['text']};}}
            #workspaceBrandHeader {{background:{c['header']};border-bottom:1px solid {c['border']};}}
            #workspaceBrand {{font-size:25px;font-weight:400;}}
            #workspaceClose {{background:transparent;color:{c['muted']};border:0;border-radius:5px;font-size:29px;padding:0;}}
            #workspaceClose:hover {{background:{c['field']};color:{c['text']};}}
            #workspaceClose:focus {{border:1px solid {c['accent']};}}
            #workspaceHeading {{font-size:50px;font-weight:600;}}
            #workspaceSubtitle {{font-size:28px;color:{c['muted']};}}
            #workspaceChoiceCard {{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {c['panel']},stop:1 {c['bg']});border:1px solid {c['border']};border-radius:9px;}}
            #workspaceCardTitle {{font-size:36px;font-weight:600;}}
            #workspaceCardSubtitle {{font-size:24px;color:{c['muted']};}}
            #workspaceThumbnailFrame {{background:{c['field']};border:1px solid {c['border']};border-radius:7px;}}
            #workspaceFeature {{font-size:20px;}}
            #workspaceStartDialog QPushButton[workspaceAction="true"] {{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {c['accent']},stop:1 #087eef);border:1px solid {c['accent']};border-radius:6px;color:#ffffff;font-size:23px;padding:6px 10px;}}
            #workspaceStartDialog QPushButton[workspaceAction="true"]:hover {{background:#258df1;border-color:#8cd8ff;}}
            #workspaceStartDialog QPushButton[workspaceAction="true"]:focus {{border:2px solid #b9e8ff;}}
            #workspaceRemember {{font-size:18px;color:{c['text']};spacing:10px;}}
            #workspaceRemember::indicator {{width:19px;height:19px;border:1px solid {c['text']};border-radius:3px;background:{c['field']};}}
            #workspaceRemember::indicator:checked {{background:{c['accent']};}}
            #workspaceSwitchHint {{font-size:16px;color:{c['muted']};}}
        ''')
        self._update_layout()

    def _update_layout(self):
        if not hasattr(self,'card_layout'):return
        from PyQt6.QtWidgets import QBoxLayout
        narrow=self.width()<1100
        self.card_layout.setDirection(QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight)
        self.content_layout.setContentsMargins(22 if narrow else 65,18 if narrow else 22,22 if narrow else 65,18)
        for card in self.cards.values():card.setMinimumHeight(490 if narrow else 600)
        # The same full-size cards scroll vertically on a compact screen.
        self.heading.setWordWrap(narrow);self.subtitle.setWordWrap(narrow)

    def resizeEvent(self,event):
        super().resizeEvent(event);self._update_layout()
        if hasattr(self,'resize_grip'):
            self.resize_grip.move(self.width()-22,self.height()-22);self.resize_grip.raise_()


class WorkspaceLoadingWindow(QWidget):
    """Opaque non-modal startup surface while the GUI creates hidden pages."""
    cancelled=pyqtSignal()

    def __init__(self,profile='device',parent=None):
        super().__init__(parent)
        selected=normalize_workspace_profile(profile,'device')
        if selected not in ('device','original'):raise ValueError('Choose Device Studio or Original Optical Studio.')
        self.profile=selected;self._cancel_sent=False;self._shutdown=False
        self.setObjectName('workspaceLoadingWindow');self.setWindowTitle('Optical Design Studio · Opening workspace')
        self.setWindowFlags(Qt.WindowType.Window|Qt.WindowType.FramelessWindowHint)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground,True)
        self.setAutoFillBackground(True)
        self.setFixedSize(680,330)
        root=QVBoxLayout(self);root.setContentsMargins(0,0,0,0);root.setSpacing(0)
        header=_WorkspaceHeader();header.setObjectName('loadingBrandHeader');header.setFixedHeight(60)
        brand=QHBoxLayout(header);brand.setContentsMargins(22,10,17,10);brand.setSpacing(12)
        logo=QLabel();logo.setPixmap(optical_logo(30));logo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents);brand.addWidget(logo)
        name=QLabel('Optical Design Studio');name.setObjectName('loadingBrand');name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents);brand.addWidget(name);brand.addStretch()
        self.close_button=QPushButton('×');self.close_button.setObjectName('loadingClose');self.close_button.setFixedSize(32,32)
        self.close_button.setAccessibleName('Cancel opening workspace');self.close_button.setToolTip('Cancel (Esc)');self.close_button.clicked.connect(self.close);brand.addWidget(self.close_button)
        root.addWidget(header)
        body=QVBoxLayout();body.setContentsMargins(28,23,28,23);body.setSpacing(12)
        self.heading=QLabel('Opening '+('Device Studio' if selected=='device' else 'Original Optical Studio'))
        self.heading.setObjectName('loadingHeading');body.addWidget(self.heading)
        self.subtitle=QLabel('Preparing your workspace. Your project library is shared.')
        self.subtitle.setObjectName('loadingSubtitle');self.subtitle.setWordWrap(True);body.addWidget(self.subtitle)
        self.progress=QProgressBar();self.progress.setObjectName('loadingProgress');self.progress.setRange(0,0)
        self.progress.setTextVisible(False);self.progress.setFixedHeight(12);self.progress.setAccessibleName('Opening workspace progress');body.addWidget(self.progress)
        self.stage_line=QLabel('Preparing the interface…');self.stage_line.setObjectName('loadingStage')
        self.stage_line.setTextFormat(Qt.TextFormat.PlainText);self.stage_line.setWordWrap(True);self.stage_line.setMinimumHeight(32);body.addWidget(self.stage_line)
        actions=QHBoxLayout();actions.addStretch()
        self.cancel_button=QPushButton('Cancel');self.cancel_button.setObjectName('loadingCancel')
        self.cancel_button.setAccessibleName('Cancel opening workspace');self.cancel_button.setMinimumSize(110,36)
        self.cancel_button.clicked.connect(self._request_cancel);actions.addWidget(self.cancel_button);body.addLayout(actions)
        root.addLayout(body,1)
        self.cancel_button.setFocus()
        theme_manager().changed.connect(self._apply_style);self._apply_style()
        screen=QApplication.primaryScreen()
        if screen is not None:self.move(screen.availableGeometry().center()-self.rect().center())

    def set_stage(self,message):
        if self._shutdown or self._cancel_sent:return
        self.stage_line.setText(str(message))
        self.stage_line.setAccessibleName('Opening workspace: '+str(message))

    def _request_cancel(self):
        if self._shutdown or self._cancel_sent:return
        self._cancel_sent=True;self.cancel_button.setEnabled(False);self.close_button.setEnabled(False)
        self.stage_line.setText('Cancelling workspace startup…');self.cancelled.emit()

    def shutdown_without_cancel(self):
        if self._shutdown:return
        self._shutdown=True;self.hide();self.deleteLater()

    def closeEvent(self,event):
        if self._shutdown:event.accept()
        else:self._request_cancel();event.ignore()

    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape:self._request_cancel();event.accept()
        else:super().keyPressEvent(event)

    def _apply_style(self,*_):
        c=COLORS[theme_manager().mode]
        palette=self.palette();palette.setColor(palette.ColorRole.Window,QColor(c['bg']));self.setPalette(palette)
        self.setStyleSheet(f'''
            QWidget#workspaceLoadingWindow {{background:{c['bg']};color:{c['text']};border:1px solid {c['border']};}}
            #workspaceLoadingWindow QLabel {{background:transparent;border:0;color:{c['text']};}}
            #loadingBrandHeader {{background:{c['header']};border:0;border-bottom:1px solid {c['border']};}}
            #loadingBrand {{font-size:20px;}}
            #loadingHeading {{font-size:28px;font-weight:600;}}
            #loadingSubtitle {{font-size:16px;color:{c['muted']};}}
            #loadingStage {{font-size:15px;color:{c['muted']};}}
            #loadingProgress {{background:{c['field']};border:0;border-radius:5px;}}
            #loadingProgress::chunk {{background:{c['accent']};border-radius:5px;}}
            #loadingCancel {{background:{c['field']};border:1px solid {c['border']};border-radius:5px;color:{c['text']};font-size:15px;padding:5px 16px;}}
            #loadingCancel:hover {{background:{c['hover']};border-color:{c['accent']};}}
            #loadingCancel:focus {{border-color:{c['accent']};}}
            #loadingCancel:disabled {{color:{c['muted']};}}
            #loadingClose {{background:transparent;border:0;color:{c['muted']};font-size:26px;padding:0;}}
            #loadingClose:hover {{background:{c['field']};color:{c['text']};}}
            #loadingClose:focus {{border:1px solid {c['accent']};}}
        ''')


def choose_startup_workspace(explicit,settings,parent=None,current='device'):
    """Resolve launch overrides, remembered choice, or an accepted native dialog."""
    selected=normalize_workspace_profile(explicit)
    if selected in ('device','original'):return selected
    if selected!='ask':
        try:remembered=normalize_workspace_profile(settings.value(STARTUP_WORKSPACE_KEY,None))
        except ValueError:remembered=None
        if remembered in ('device','original'):return remembered
    dialog=WorkspaceStartDialog(parent,current=current)
    try:
        if dialog.exec()!=QDialog.DialogCode.Accepted:return None
        profile=normalize_workspace_profile(dialog.selected_profile)
        if profile not in ('device','original'):return None
        if dialog.remember_choice:settings.setValue(STARTUP_WORKSPACE_KEY,profile)
        else:settings.remove(STARTUP_WORKSPACE_KEY)
        settings.sync()
        return profile
    finally:
        dialog.deleteLater()
