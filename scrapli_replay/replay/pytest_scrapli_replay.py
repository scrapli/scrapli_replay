"""scrapli_replay.pytest.scrapli_replay"""
from pathlib import Path
from typing import Any, AsyncIterator, Iterator, List, Tuple

import _pytest
import pytest

SubRequest = _pytest.fixtures.SubRequest  # pylint: disable=W0212
Config = _pytest.config.Config  # pylint: disable=W0212;
Parser = _pytest.config.argparsing.Parser  # pylint: disable=W0212


def pytest_addoption(parser: Parser) -> None:
    """
    Scrapli Replay Pytest options

    Args:
        parser: pytest option Parser

    Returns:
        None

    Raises:
        N/A

    """
    group = parser.getgroup("scrapli_replay")
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
        default="",
        help=(
            "Comma separated list of test names, these sessions will be overwritten (re-recorded)"
        ),
    )
    group.addoption(
        "--scrapli-replay-disable",
        action="store_true",
        dest="scrapli_replay_disable",
        default=False,
        help="Disable scrapli_replay entirely",
    )
    group.addoption(
        "--scrapli-replay-block-network",
        action="store_true",
        dest="scrapli_replay_block_network",
        default=False,
        help=(
            "Disable scrapli_replay network connections -- tests will work *if* sessions are "
            "already saved, no new sessions will be created/no connections will be made!"
        ),
    )


def pytest_load_initial_conftests(early_config: Config, parser: Parser, args: Any) -> None:
    """
    Register custom scrapli replay marker so scrapli replay can be used with pytest.mark

    This is not necessary if you just want to use scrapli_replay as a fixture, but it seems nicer
    to use it as a decorator (like pytest vcr). Also w/out this we get warnings and we dont want any
    of that silliness!

    Args:
        early_config: pytest Config object
        parser: pytest option Parser
        args: args... from something? I dunno

    Returns:
        None

    Raises:
        N/A

    """
    # parser and args aren't necessary for us here
    _, _ = parser, args
    early_config.addinivalue_line(
        "markers", "scrapli_replay: Mark the test as using scrapli_replay"
    )


def _finalize_fixture_args(request: SubRequest) -> Tuple[str, str, List[str], bool, str, bool]:
    """
    Finalize the arguments for a wrapped test

    Args:
        request: pytest request object

    Returns:
        Tuple: tuple of parsed options for a given test

    Raises:
        N/A

    """
    opt_replay_mode = request.config.getoption("scrapli_replay_mode")
    opt_config_dir = request.config.getoption("scrapli_replay_directory")
    opt_overwrite = request.config.getoption("scrapli_replay_overwrite").split(",")
    opt_disable = request.config.getoption("scrapli_replay_disable")
    opt_block_network = request.config.getoption("scrapli_replay_block_network")

    # set and make sure session directory exists
    if opt_config_dir:
        session_directory = str(Path(opt_config_dir).expanduser())
    else:
        session_directory = f"{Path(request.module.__file__).parents[0]}/scrapli_replay_sessions"
    Path(session_directory).mkdir(exist_ok=True)

    test_name = request.node.name
    if request.cls:
        test_name = f"{request.cls.__name__}.{test_name}"

    return (
        opt_replay_mode,
        session_directory,
        opt_overwrite,
        opt_disable,
        test_name,
        opt_block_network,
    )


@pytest.fixture(scope="function", autouse=True)
def _scrapli_replay_marker(request: SubRequest) -> None:
    """
    Wrap tests marked with pytest.mark.scrapli_replay with the scrapli_replay fixture

    Feels like there is almost certainly a better way than testing this *per function* but not clear
    to me what that is at this point...

    Args:
        request: pytest request object

    Returns:
        None

    Raises:
        N/A

    """
    function_markers = request.node.own_markers
    is_scrapli_replay = any(marker.name == "scrapli_replay" for marker in function_markers)

    if not is_scrapli_replay:
        # not a scrapli replay test function, nothing to do here
        return

    is_asyncio = any(marker.name == "asyncio" for marker in function_markers)

    if is_asyncio:
        request.getfixturevalue("async_scrapli_replay")
    else:
        request.getfixturevalue("scrapli_replay")


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

    (
        opt_replay_mode,
        session_directory,
        opt_overwrite,
        opt_disable,
        test_name,
        opt_block_network,
    ) = _finalize_fixture_args(request=request)

    if test_name in opt_overwrite:
        opt_replay_mode = "overwrite"

    if not opt_disable:
        with ScrapliReplay(
            session_directory=session_directory,
            session_name=test_name,
            replay_mode=opt_replay_mode,
            block_network=opt_block_network,
        ):
            yield
    else:
        yield


@pytest.mark.asyncio
@pytest.fixture(scope="function")
async def async_scrapli_replay(request: SubRequest) -> AsyncIterator[None]:
    """
    Async version of Scrapli replay pytest plugin

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

    (
        opt_replay_mode,
        session_directory,
        opt_overwrite,
        opt_disable,
        test_name,
        opt_block_network,
    ) = _finalize_fixture_args(request=request)

    if test_name in opt_overwrite:
        opt_replay_mode = "overwrite"

    if not opt_disable:
        async with ScrapliReplay(
            session_directory=session_directory,
            session_name=test_name,
            replay_mode=opt_replay_mode,
            block_network=opt_block_network,
        ):
            yield
    else:
        yield
