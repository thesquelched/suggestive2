"""Default configuration"""

import os.path
import inspect
from importlib import import_module
from collections import ChainMap
from typing import Optional
import sys
import suggestive2.types


class Mpd:
    host = 'localhost'
    port = 6600


def load_config(path: Optional[str] = None) -> suggestive2.types.Config:
    defaults = {key: vars(value)
                for key, value in globals().items()
                if inspect.isclass(value)}

    if path and os.path.isfile(path):
        sys.path.insert(0, os.path.dirname(path))
        config = import_module(os.path.splitext(os.path.basename(path))[0])

        config_vals = {section: vars(getattr(config, section)) if hasattr(config, section) else {}
                       for section in defaults}

        result = {section: ChainMap(config_vals[section], defaults[section])
                  for section in defaults}
    else:
        result = {section: ChainMap(value) for section, value in defaults.items()}

    return {key.lower(): value for key, value in result.items()}
