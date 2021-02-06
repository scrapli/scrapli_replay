import pytest

from scrapli.driver.core.cisco_iosxe import IOSXEDriver
from scrapli_replay.server.collector import ScrapliCollector
from scrapli_replay.server.server import BaseSSHServerSession


@pytest.fixture(scope="function")
def scrapli_conn():
    scrapli_conn = IOSXEDriver(host="localhost")
    return scrapli_conn


@pytest.fixture(scope="function")
def basic_collector(scrapli_conn):
    channel_inputs = ["some input"]
    interact_events = [[("some input", "some pattern", False)]]
    paging_indicator = "--More--"
    paging_escape_string = "non-standard"

    collector = ScrapliCollector(
        channel_inputs=channel_inputs,
        interact_events=interact_events,
        paging_indicator=paging_indicator,
        paging_escape_string=paging_escape_string,
        scrapli_connection=scrapli_conn,
    )

    return collector


@pytest.fixture(scope="function")
def basic_server():
    server = BaseSSHServerSession(
        collect_data={
            "on_open_inputs": ["openstuff"],
            "initial_privilege_level": "veryprivvy",
            "privilege_level_prompts": {"veryprivvy": "veryprivvyprompt"},
        }
    )
    return server
