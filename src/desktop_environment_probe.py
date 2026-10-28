"""Check the source desktop environment, including a real native Fresnel solve."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile


def check():
    """Run all imports and checks with disposable user data and preferences."""
    scratch = Path(sys.prefix)/'.startup-checks'
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='desktop-', dir=scratch) as folder:
        local_data = Path(folder)/'local-app-data'
        local_data.mkdir()
        overrides = dict(LOCALAPPDATA=str(local_data), S4_LIBRARY_ROOT=folder,
                         QT_QPA_PLATFORM='offscreen')
        previous = {name: os.environ.get(name) for name in overrides}
        try:
            # bootstrap and qt_app can load or validate add-ons on import, so
            # isolate their profile before importing any application modules.
            os.environ.update(overrides)
            return _check()
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


def _check():
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError('The Windows native solver needs 64-bit Python 3.12.')
    import struct
    if struct.calcsize('P') != 8:
        raise RuntimeError('The Windows native solver needs 64-bit Python.')
    from bootstrap import initialize
    initialize(1)
    from PyQt6 import QtCore, QtWidgets
    import numpy
    import scipy
    import pandas
    import shapely
    from electrical_solver import _load_core
    _load_core()
    from backend import build_simulation, load_runtime
    from model import DEFAULT_PERFORMANCE
    native = load_runtime(DEFAULT_PERFORMANCE)
    model = dict(ax=1., ay=1., basis=9, patterns=[], materials=[
        dict(name='Air', model='constant_eps', a=1., b=0.),
        dict(name='Glass', model='constant_eps', a=2.25, b=0.)], layers=[
        dict(name='Top', thickness=0., material='Air'),
        dict(name='Film', thickness=.2, material='Glass'),
        dict(name='Bottom', thickness=0., material='Glass')])
    simulation = build_simulation(native, model, 1550.)
    simulation.SetFrequency(1000./1550.)
    simulation.SetExcitationPlanewave(IncidenceAngles=(0., 0.), sAmplitude=complex(0), pAmplitude=complex(-1), Order=0)
    forward, backward = simulation.GetPowerFlux('Top', 0.)
    transmitted, _ = simulation.GetPowerFlux('Bottom', 0.)
    r, t = -backward.real/forward.real, transmitted.real/forward.real
    if abs(r-.04) > 1e-9 or abs(t-.96) > 1e-9:
        raise RuntimeError('Native solver Fresnel check failed: R='+str(r)+', T='+str(t))
    # Construct the actual application, including every setup editor and shared
    # material/search dependency, inside the disposable profile set by check().
    from qt_app import OpticalStudio
    from qt_core import ProjectStore
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = OpticalStudio(ProjectStore())
    application.processEvents()
    pages = window.pages.count() if hasattr(window, 'pages') and hasattr(window.pages, 'count') else None
    window.close()
    application.processEvents()
    return dict(python=sys.executable, qt=QtCore.QT_VERSION_STR, numpy=numpy.__version__, scipy=scipy.__version__,
        native_s4=native.__file__, fresnel_R=r, fresnel_T=t, desktop_constructed=True, pages=pages)


if __name__ == '__main__':
    try:
        print(json.dumps(check(), indent=2))
    except Exception as exc:
        print('Desktop environment is not ready: '+str(exc), file=sys.stderr)
        raise SystemExit(1)
