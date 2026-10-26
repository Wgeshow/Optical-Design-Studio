"""Consistent native surfaces and named tab selection for retained tools."""
from PyQt6.QtWidgets import QTabWidget
from PyQt6 import sip
import weakref
from qt_common import COLORS, theme_manager


def polish_tool_workspace(page):
    """Apply the same navy, borders and type used by the shared setup workspace."""
    page.setProperty('toolWorkspace',True)
    target=weakref.ref(page)
    def apply(*_):
        page=target()
        if page is None or sip.isdeleted(page):return
        c=COLORS[theme_manager().mode]
        page.setStyleSheet(f'''
        QWidget[toolWorkspace="true"] {{background:{c['bg']}; color:{c['text']}; font-family:'Segoe UI'; font-size:13px;}}
        QWidget[toolWorkspace="true"] QGroupBox {{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {c['panel']},stop:1 {c['bg']}); border:1px solid {c['border']}; border-radius:5px; margin-top:12px; padding:12px; font-size:14px; font-weight:600;}}
        QWidget[toolWorkspace="true"] QGroupBox::title {{subcontrol-origin:margin; left:12px; padding:0 6px; color:{c['text']};}}
        QWidget[toolWorkspace="true"] QTabWidget::pane {{border:1px solid {c['border']}; background:{c['panel']}; border-radius:5px;}}
        QWidget[toolWorkspace="true"] QTabBar::tab {{background:{c['field']}; color:{c['muted']}; padding:9px 12px; border-bottom:2px solid transparent; min-height:20px;}}
        QWidget[toolWorkspace="true"] QTabBar::tab:selected {{color:{c['accent']}; background:{c['panel']}; border-bottom-color:{c['accent']};}}
        QWidget[toolWorkspace="true"] QLineEdit,QWidget[toolWorkspace="true"] QSpinBox,QWidget[toolWorkspace="true"] QDoubleSpinBox,QWidget[toolWorkspace="true"] QComboBox {{background:{c['field']}; color:{c['text']}; border:1px solid {c['border']}; border-radius:4px; padding:5px 8px; min-height:23px; font-size:13px; font-weight:400;}}
        QWidget[toolWorkspace="true"] QLineEdit:focus,QWidget[toolWorkspace="true"] QComboBox:focus {{border-color:{c['accent']};}}
        QWidget[toolWorkspace="true"] QLabel,QWidget[toolWorkspace="true"] QCheckBox {{font-size:13px; font-weight:400;}}
        QWidget[toolWorkspace="true"] QPushButton {{min-height:24px; border-radius:4px; padding:5px 10px; font-size:13px;}}
        ''')
        for tabs in page.findChildren(QTabWidget):
            tabs.setUsesScrollButtons(True)
            tabs.tabBar().setExpanding(False)
            tabs.setDocumentMode(True)
    theme_manager().changed.connect(apply)
    apply()


def select_tool_tab(page, route):
    """Select declared parent and child tabs without relying on old engine indices."""
    mapping=page.tool_tabs
    key=route.split('/')[-1]
    destinations=mapping[key] if key in mapping else mapping.get(route)
    if destinations is None:
        return False
    for tabs,index in destinations:
        tabs.setCurrentIndex(index)
    return True
