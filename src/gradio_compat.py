"""Legacy callback types only. The application no longer loads a web UI."""
class _Request:
    pass

class _Error(RuntimeError):
    pass

def _unavailable(*args, **kwargs):
    raise RuntimeError('The web interface has been removed. Launch Optical Design Studio using launch_qt_gui.')

class _UnavailableGradio:
    Request = _Request
    Error = _Error

    def __getattr__(self, name):
        return _unavailable

gr = _UnavailableGradio()
