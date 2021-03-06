import sys

import _pytest
import pytest

from scrapli_replay.replay.pytest_scrapli_replay import _finalize_fixture_args, pytest_addoption

Parser = _pytest.config.argparsing.Parser


@pytest.fixture(scope="session", autouse=True)
def plugin_loaded(pytestconfig):
    # Check that the plugin has been properly installed before proceeding
    assert pytestconfig.pluginmanager.hasplugin("scrapli_replay")


def test_scrapli_replay_options():
    parser = Parser()
    pytest_addoption(parser=parser)
    scrapli_replay_group = parser.getgroup("scrapli_replay")
    # test setting all things to non-default and making sure they get parsed appropriately
    parsed_options = scrapli_replay_group.parser.parse(
        [
            "--scrapli-replay-mode",
            "record",
            "--scrapli-replay-directory",
            "blah/blah",
            "--scrapli-replay-overwrite",
            "sometest,sometest1",
            "--scrapli-replay-disable",
            "--scrapli-replay-block-network",
            ".",
        ]
    )
    assert parsed_options.scrapli_replay_mode == "record"
    assert parsed_options.scrapli_replay_directory == "blah/blah"
    assert parsed_options.scrapli_replay_overwrite == "sometest,sometest1"
    assert parsed_options.scrapli_replay_disable is True
    assert parsed_options.scrapli_replay_block_network is True


@pytest.mark.skipif(sys.version_info > (3, 9), reason="skipping pending pyfakefs 3.10 support")
def test_finalize_fixture_args(fs):
    # building some dummy objects to not bother with creating "real" pytest objects -- mostly i care
    # about testing that the options get parsed and returned correctly and will assume pytest is
    # handling their part nicely like they always do!
    class DummyConfig:
        def __init__(self):
            self.scrapli_replay_mode = "overwrite"
            self.scrapli_replay_directory = "sessiondir"
            self.scrapli_replay_overwrite = "thistest,thisonetoo"
            self.scrapli_replay_disable = True
            self.scrapli_replay_block_network = True

        def getoption(self, opt):
            return getattr(self, opt)

    class DummyModule:
        __name__ = "mytestmodule"

    class DummyFunction:
        __name__ = "mytestfunc"

    class DummyNode:
        name = "sometestnode"

    class DummyRequest:
        def __init__(self):
            self.config = DummyConfig()
            self.module = DummyModule()
            self.function = DummyFunction()
            self.node = DummyNode()
            self.cls = None

    request = DummyRequest()

    assert _finalize_fixture_args(request=request) == (
        "overwrite",
        "sessiondir",
        ["thistest", "thisonetoo"],
        True,
        "sometestnode",
        True,
    )
