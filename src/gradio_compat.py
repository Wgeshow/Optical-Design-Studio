"""Optional Gradio binding for modules shared with the native Qt desktop."""
try:
    import gradio as gr
except ModuleNotFoundError:
    class _Request:
        pass

    class _Error(RuntimeError):
        pass

    def _unavailable(*args, **kwargs):
        raise RuntimeError(
            'The optional Gradio web interface is not included in this '
            'native desktop build.'
        )

    class _UnavailableGradio:
        Request = _Request
        Error = _Error

        def __getattr__(self, name):
            return _unavailable

    gr = _UnavailableGradio()
