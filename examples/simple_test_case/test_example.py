"""scrapli_replay.examples.simple_test_case.test_example"""
import pytest
from example import Example

from scrapli.response import Response


def test_example_do_stuff_patching(monkeypatch, example_instance):
    """Test Example.do_stuff"""

    def patched_send_command(cls, command):  # pylint: disable=W0613
        r = Response(host="localhost", channel_input=command)
        r.record_response(b"Software Version 15.2(4)E7")
        return r

    monkeypatch.setattr(
        "scrapli.driver.network.sync_driver.NetworkDriver.send_command", patched_send_command
    )
    assert example_instance.do_stuff() == "15.2(4)E7"


@pytest.mark.scrapli_replay
def test_example_do_stuff_no_fixture():
    """Test Example.do_stuff"""
    assert Example().do_stuff() == "15.2(4)E7"


@pytest.mark.scrapli_replay
def test_example_do_stuff_with_fixture(example_instance):
    """Test Example.do_stuff"""
    assert example_instance.do_stuff() == "15.2(4)E7"
