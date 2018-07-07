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
