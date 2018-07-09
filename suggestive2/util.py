import weakref
import os.path


def expand(path):
    return os.path.abspath(os.path.expanduser(os.path.expandvars(path)))


def run_method_coroutine(loop, method, *args):
    proxy = weakref.proxy(method.__self__)
    weak_method = method.__func__.__get__(proxy)
    return loop.create_task(weak_method(*args))
