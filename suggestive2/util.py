import os.path


def expand(path):
    return os.path.abspath(os.path.expanduser(os.path.expandvars(path)))
