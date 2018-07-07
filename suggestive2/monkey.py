import urwid
import sys


def _exception_handler(self, loop, context):
    exc = context.get('exception')
    if exc:
        loop.stop()
        if not isinstance(exc, urwid.ExitMainLoop):
            # Store the exc_info so we can re-raise after the loop stops
            import sys
            self._exc_info = sys.exc_info()
            if self._exc_info == (None, None, None):
                self._exc_info = (type(exc), exc, None)
    else:
        loop.default_exception_handler(context)


def monkeypatch():
	urwid.AsyncioEventLoop._exception_handler = _exception_handler
