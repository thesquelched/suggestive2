import pytest

from suggestive2.config import load_config


@pytest.fixture
def config():
    return load_config()
