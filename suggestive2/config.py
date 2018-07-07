"""Default configuration"""

from collections import ChainMap
from typing import Optional
import importlib
import inspect
import os
import random
import shutil
import string
import sys
import tempfile

import suggestive2.types
from suggestive2.util import expand


class Mpd:
    host = 'localhost'
    port = 6600


def get_temp_package():
    while True:
        temp_package = ''.join(random.choice(string.ascii_letters) for _ in range(16))
        if temp_package not in sys.modules:
            return temp_package


def load_config(path: Optional[str] = None) -> suggestive2.types.Config:
    path = expand(path) if path else path

    defaults = {key: vars(value)
                for key, value in globals().items()
                if inspect.isclass(value)}

    if path and os.path.isfile(path):
        with tempfile.TemporaryDirectory() as tempdir:
            temp_package = get_temp_package()
            shutil.copyfile(path, os.path.join(tempdir, f'{temp_package}.py'))

            sys.path.insert(0, tempdir)
            config = importlib.import_module(temp_package)

            config_vals = {
                section: vars(getattr(config, section)) if hasattr(config, section) else {}
                for section in defaults
            }

            result = {section: ChainMap(config_vals[section], defaults[section])
                      for section in defaults}
            del sys.path[0]
    else:
        result = {section: ChainMap(value) for section, value in defaults.items()}

    return {key.lower(): value for key, value in result.items()}
