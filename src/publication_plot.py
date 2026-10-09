"""Publication dimensions and typography shared by all desktop Matplotlib plots."""
import copy,json
from pathlib import Path
from matplotlib import rc_context

DEFAULTS=dict(width_mm=180.,height_mm=110.,font='DejaVu Sans',label_pt=10.,tick_pt=9.,title_pt=11.,legend_pt=8.5,line_pt=1.5,axis_pt=.8,marker_pt=4.,dpi=600)

def defaults():
    from qt_common import preferences
    try:
        saved=json.loads(preferences().value('figure_style','{}'))
        return validate(dict(DEFAULTS,**saved))
    except (ValueError,TypeError):return dict(DEFAULTS)

def validate(values):
    import math
    result=dict(DEFAULTS,**values)
    for key in DEFAULTS:
        if key=='font':
            if not isinstance(result[key],str) or not result[key].strip():raise ValueError('Choose a font family.')
            continue
        result[key]=float(result[key])
        if not math.isfinite(result[key]) or result[key]<=0:raise ValueError('Figure settings must be positive and finite.')
    if not 40<=result['width_mm']<=400 or not 30<=result['height_mm']<=400:raise ValueError('Use width 40–400 mm and height 30–400 mm.')
    if not 72<=result['dpi']<=1200:raise ValueError('Export resolution must be 72–1200 DPI.')
    return result

def apply_style(figure,style,paper=False):
    from matplotlib.layout_engine import ConstrainedLayoutEngine
    engine=figure.get_layout_engine()
    if isinstance(engine,ConstrainedLayoutEngine):engine.set(w_pad=.07,h_pad=.07)
    for ax in figure.axes:
        ax.title.set_fontsize(style['title_pt']);ax.title.set_fontfamily(style['font'])
        for axis in [ax.xaxis,ax.yaxis]+([ax.zaxis] if hasattr(ax,'zaxis') else []):
            axis.label.set_fontsize(style['label_pt']);axis.label.set_fontfamily(style['font'])
            axis.get_offset_text().set_fontsize(style['tick_pt']);axis.get_offset_text().set_fontfamily(style['font'])
            for text in axis.get_ticklabels():text.set_fontsize(style['tick_pt']);text.set_fontfamily(style['font'])
        ax.tick_params(labelsize=style['tick_pt'],width=style['axis_pt'],length=3,direction='out')
        for spine in ax.spines.values():spine.set_linewidth(style['axis_pt'])
        for line in ax.lines:
            line.set_linewidth(style['line_pt']);line.set_markersize(style['marker_pt'])
        for text in ax.texts:text.set_fontfamily(style['font']);text.set_fontsize(style['tick_pt'])
        legend=ax.get_legend()
        if legend:
            for text in legend.get_texts():text.set_fontfamily(style['font']);text.set_fontsize(style['legend_pt'])
            for line in legend.get_lines():line.set_linewidth(style['line_pt']);line.set_markersize(style['marker_pt'])
        if paper:
            ax.set_facecolor('white');ax.tick_params(colors='#202020')
            for axis in [ax.xaxis,ax.yaxis]+([ax.zaxis] if hasattr(ax,'zaxis') else []):
                axis.label.set_color('#202020');axis.get_offset_text().set_color('#202020')
                if hasattr(axis,'set_pane_color'):
                    axis.set_pane_color((1,1,1,1));axis.line.set_color('#303030');axis._axinfo['grid']['color']='#d9d9d9'
            ax.title.set_color('#202020')
            for text in ax.texts:
                text.set_color('#202020')
                if text.get_bbox_patch() is not None:
                    text.get_bbox_patch().set_facecolor('white');text.get_bbox_patch().set_edgecolor('#cccccc')
            for spine in ax.spines.values():spine.set_color('#303030')
            for line in [*ax.get_xgridlines(),*ax.get_ygridlines()]:line.set_color('#d9d9d9')
            if legend:
                legend.get_frame().set_facecolor('white');legend.get_frame().set_edgecolor('#cccccc')
                for text in legend.get_texts():text.set_color('#202020')
    for text in figure.texts:
        text.set_fontfamily(style['font']);text.set_fontsize(style['title_pt'])
        if paper:text.set_color('#202020')
    if paper:figure.set_facecolor('white')

def export_figure(figure,path,style):
    """Write at exact paper dimensions, never at the preview widget's dimensions."""
    from qt_common import apply_plot_theme
    style=validate(style)
    original_size=figure.get_size_inches().copy();original_dpi=figure.dpi
    try:
        figure.set_size_inches(style['width_mm']/25.4,style['height_mm']/25.4,forward=False)
        apply_style(figure,style,paper=True)
        with rc_context({'pdf.fonttype':42,'ps.fonttype':42,'svg.fonttype':'none','savefig.bbox':None}):
            figure.savefig(path,dpi=style['dpi'],facecolor='white',edgecolor='white',transparent=False)
    finally:
        figure.set_size_inches(original_size,forward=False);figure.set_dpi(original_dpi)
        apply_plot_theme(figure);apply_style(figure,style)
        if figure.canvas:figure.canvas.draw_idle()

def edit_settings(widget):
    from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QComboBox,QLineEdit,QDialogButtonBox,QCheckBox,QLabel,QGroupBox,QScrollArea,QWidget
    from qt_common import number,integer,preferences
    dialog=QDialog(widget);dialog.setWindowTitle('Publication figure settings');dialog.resize(610,680)
    root=QVBoxLayout(dialog)
    scroll=QScrollArea();scroll.setWidgetResizable(True);root.addWidget(scroll,1)
    body=QWidget();layout=QVBoxLayout(body);scroll.setWidget(body)
    note=QLabel('Typography and labels update the live view. Width and height set the export paper size.');note.setWordWrap(True);layout.addWidget(note)
    presets=QComboBox();presets.addItems(['Custom','Single column · 90 × 65 mm','Double column · 180 × 110 mm','Square · 90 × 90 mm'])
    layout.addWidget(presets)
    columns=QHBoxLayout();layout.addLayout(columns)
    fields={}
    a=QGroupBox('Size and typography');b=QGroupBox('Lines and output');left,right=QFormLayout(a),QFormLayout(b);columns.addWidget(a);columns.addWidget(b)
    for key,label in [('width_mm','Width (mm)'),('height_mm','Height (mm)'),('font','Font family'),('label_pt','Axis labels (pt)'),('tick_pt','Tick labels (pt)'),('title_pt','Titles (pt)'),('legend_pt','Legend (pt)'),('line_pt','Line width (pt)'),('axis_pt','Axes width (pt)'),('marker_pt','Markers (pt)'),('dpi','Raster DPI')]:
        value=widget.figure_style[key]
        control=QLineEdit(value) if key=='font' else integer(int(value),72,1200) if key=='dpi' else number(value,.1,400,2)
        fields[key]=control;(left if key in ('width_mm','height_mm','font','label_pt','tick_pt','title_pt') else right).addRow(label,control)
    def preset(index):
        if index:fields['width_mm'].setValue([0,90,180,90][index]);fields['height_mm'].setValue([0,65,110,90][index])
    presets.currentIndexChanged.connect(preset)
    box=QGroupBox('Labels for this figure');form=QFormLayout(box);layout.addWidget(box)
    selector=QComboBox();axes=widget.figure.axes
    for i,axis in enumerate(axes):selector.addItem(f"Panel {i+1}: {axis.get_title() or axis.get_ylabel() or 'plot'}")
    title,xlabel,ylabel=QLineEdit(),QLineEdit(),QLineEdit()
    form.addRow('Panel / colorbar',selector);form.addRow('Title',title);form.addRow('X label',xlabel);form.addRow('Y label',ylabel)
    labels=[dict(title=a.get_title(),xlabel=a.get_xlabel(),ylabel=a.get_ylabel()) for a in axes]
    current=[0]
    def remember():
        if labels:labels[current[0]]=dict(title=title.text(),xlabel=xlabel.text(),ylabel=ylabel.text())
    def select(index):
        remember();current[0]=index
        if index>=0:
            title.setText(labels[index]['title']);xlabel.setText(labels[index]['xlabel']);ylabel.setText(labels[index]['ylabel'])
    if labels:title.setText(labels[0]['title']);xlabel.setText(labels[0]['xlabel']);ylabel.setText(labels[0]['ylabel'])
    selector.currentIndexChanged.connect(select)
    series=[line for axis in axes for line in axis.lines if line.get_label() and not line.get_label().startswith('_')]
    edits=[]
    if series:
        from matplotlib.colors import to_hex
        box=QGroupBox('Curve labels and styles');form=QFormLayout(box);layout.addWidget(box)
        curve=QComboBox()
        for line in series:curve.addItem(line.get_label())
        curve_label,curve_color=QLineEdit(),QLineEdit()
        curve_style=QComboBox();curve_style.addItems(['-','--','-.',':'])
        form.addRow('Curve',curve);form.addRow('Legend label',curve_label);form.addRow('Color (name or hex)',curve_color);form.addRow('Line style',curve_style)
        edits=[dict(label=line.get_label(),color=to_hex(line.get_color()),linestyle=line.get_linestyle()) for line in series]
        current_curve=[0]
        def remember_curve():edits[current_curve[0]]=dict(label=curve_label.text(),color=curve_color.text(),linestyle=curve_style.currentText())
        def select_curve(index):
            remember_curve();current_curve[0]=index
            curve_label.setText(edits[index]['label']);curve_color.setText(edits[index]['color']);curve_style.setCurrentText(edits[index]['linestyle'])
        curve_label.setText(edits[0]['label']);curve_color.setText(edits[0]['color']);curve_style.setCurrentText(edits[0]['linestyle'])
        curve.currentIndexChanged.connect(select_curve)
    save_defaults=QCheckBox('Use this style as the default for new figures');layout.addWidget(save_defaults)
    message=QLabel('');message.setWordWrap(True);layout.addWidget(message)
    buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);root.addWidget(buttons)
    def accept():
        try:
            style=validate({k:(v.text() if k=='font' else v.value()) for k,v in fields.items()})
            if series:
                from matplotlib.colors import is_color_like
                remember_curve()
                if any(not is_color_like(edit['color']) for edit in edits):raise ValueError('Enter a valid color name or #RRGGBB value.')
            remember()
            for axis,values in zip(axes,labels):axis.set(**values)
            for line,values in zip(series,edits):line.set(**values)
            for axis in axes:
                if axis.get_legend() and series:axis.legend(loc='best')
            widget.figure_style=style;apply_style(widget.figure,style);widget.fit_canvas();widget.canvas.draw_idle()
            if save_defaults.isChecked():preferences().setValue('figure_style',json.dumps(style))
            dialog.accept()
        except ValueError as exc:message.setText(str(exc))
    buttons.accepted.connect(accept);buttons.rejected.connect(dialog.reject)
    dialog.exec()
