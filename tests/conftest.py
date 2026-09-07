import pathlib

import pytest


@pytest.fixture
def config_path() -> pathlib.Path:
    return pathlib.Path(__file__).parents[1] / "config" / "sources.yaml"
