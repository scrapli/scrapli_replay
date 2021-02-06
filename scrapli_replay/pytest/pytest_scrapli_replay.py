"""scrapli_replay.pytest.scrapli_replay"""
from pathlib import Path
from typing import Any, Iterator

import _pytest
import pytest

SubRequest = _pytest.fixtures.SubRequest  # pylint: disable=W0212


def pytest_addoption(parser: Any) -> None:
    """
    Scrapli Replay Pytest options

    Args:
        parser:

    Returns:
        None

    Raises:
        N/A

    """
    group = parser.getgroup("scrapli")
    group.addoption(
        "--scrapli-replay-mode",
        action="store",
        dest="scrapli_replay_mode",
        default="replay",
        choices=["replay", "record", "overwrite"],
        help="Set the recording mode for scrapli_replay",
    )
    group.addoption(
        "--scrapli-replay-directory",
        action="store",
        dest="scrapli_replay_directory",
        default=None,
        help=(
            "Set the recording output directory for scrapli_replay; if not set sessions are stored "
            "in a 'scrapli_replay' folder in the directory of the test file"
        ),
    )
    group.addoption(
        "--scrapli-replay-overwrite",
        action="store",
        dest="scrapli_replay_overwrite",
        default=None,
        help=(
            "Comma separated list of test names, these sessions will be overwritten (re-recorded)"
        ),
    )


@pytest.fixture(scope="function")
def scrapli_replay(request: SubRequest) -> Iterator[None]:
    """
    Scrapli replay pytest plugin

    Args:
        request: pytest request object

    Yields:
        None

    Raises:
        N/A

    """
    # importing here to not break coverage for the rest of things... if/when this import is not here
    # it gets imported *before* coverage starts which means that the things in replay.replay dont
    # get proper coverage figured out
    from scrapli_replay.replay.replay import ScrapliReplay  # pylint: disable=C0415

    opt_replay_mode = request.config.getoption("scrapli_replay_mode")
    opt_config_dir = request.config.getoption("scrapli_replay_directory")
    opt_overwrite = request.config.getoption("scrapli_replay_overwrite").split(",")

    test_directory = opt_config_dir or str(Path(request.module.__file__).parents[0])
    test_module = request.module.__name__
    test_name = request.function.__name__

    if test_name in opt_overwrite:
        opt_replay_mode = "overwrite"

    with ScrapliReplay(
        session_directory=test_directory,
        session_name=f"{test_module}_{test_name}",
        replay_mode=opt_replay_mode,
    ):
        yield
