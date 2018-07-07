import tempfile
import pytest
import os.path
from suggestive2.config import load_config


@pytest.fixture
def tempdir():
    with tempfile.TemporaryDirectory() as dirname:
        yield dirname


def test_default_config(tempdir):
    # Create empty file
    path = os.path.join(tempdir, 'myconfig.py')
    open(path, 'a').close()

    assert load_config(path) == load_config()


def test_config_override(tempdir):
    # Create empty file
    path = os.path.join(tempdir, 'myconfig.py')
    with open(path, 'w') as f:
        f.write("""\
class Mpd:
    host = 'override-host'
    port = 12345
""")

    conf = load_config(path)
    assert conf['mpd']['host'] == 'override-host'
    assert conf['mpd']['port'] == 12345
