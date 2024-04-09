"""scrapli_replay.examples.simple_test_case.conftest"""

import pytest
from example import Example


@pytest.fixture(scope="function")
def example_instance():
    """Simple fixture to return Example instance"""
    yield Example()
