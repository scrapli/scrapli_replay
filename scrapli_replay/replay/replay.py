"""scrapli_replay.replay.replay"""
# pylint: disable=C0302
import asyncio
import re
import types
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from io import BytesIO
from pathlib import Path
from types import TracebackType
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Type, Union
from unittest import mock

import pytest
from ruamel.yaml import YAML, safe_load  # type: ignore

import scrapli
from scrapli.channel.async_channel import AsyncChannel
from scrapli.channel.base_channel import BaseChannel
from scrapli.channel.sync_channel import Channel
from scrapli.driver.base.async_driver import AsyncDriver
from scrapli.driver.base.sync_driver import Driver
from scrapli.driver.network.sync_driver import NetworkDriver
from scrapli_replay.exceptions import (
    ScrapliReplayConnectionProfileError,
    ScrapliReplayException,
    ScrapliReplayExpectedInputError,
)

# used to replace scrapli cfg session name/id in channel write log
SCRAPLI_CFG_SESSION_PATTERN = re.compile(pattern=r"scrapli_cfg_\d+")


class ReplayMode(Enum):
    RECORD = "record"
    REPLAY = "replay"
    OVERWRITE = "overwrite"


@dataclass()
class ConnectionProfile:
    # password things will just be False for not used, or True for used, we'll never store them
    host: str
    port: int
    auth_username: str
    auth_password: bool
    auth_private_key: str
    auth_private_key_passphrase: bool
    auth_bypass: bool
    transport: str
    # auth secondary only applies to network drivers, so its optional
    auth_secondary: bool = False


class ScrapliReplayInstance:
    def __init__(
        self,
        *,
        replay_mode: ReplayMode,
        connection_profile: ConnectionProfile,
        replay_session: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Scrapli replay

        Args:
            replay_mode: replay mode to use
            connection_profile: connection profile object
            replay_session: dict of replay session (used in replay mode, ignored in record mode)

        Returns:
            None

        Raises:
            N/A

        """
        self.replay_mode = replay_mode
        self.connection_profile = connection_profile

        self.replay_session = replay_session or {}

        self.read_log = BytesIO()
        self.write_log: List[Tuple[str, bool, int]] = []

        self._scrapli_cfg_session = ""

    def _common_replay_mode(self) -> Tuple[Iterator[str], Iterator[Tuple[str, bool]]]:
        """
        Handle common replay mode parsing of saved session data (common between sync/async)

        Args:
            N/A

        Returns:
            Tuple[Iterator[str], Iterator[Tuple[str, bool]]]: returns the device_outputs and
                scrapli_inputs iterators to use in the replay read/write methods

        Raises:
            ScrapliReplayConnectionProfileError: if recorded connection profile does not match the
                actual connection profile

        """
        actual_connection_profile = ConnectionProfile(**self.replay_session["connection_profile"])

        if actual_connection_profile != self.connection_profile:
            msg = "recorded connection profile does not match current connection profile"
            raise ScrapliReplayConnectionProfileError(msg)

        device_outputs = iter(
            [interaction["channel_output"] for interaction in self.replay_session["interactions"]]
        )
        scrapli_inputs = iter(
            [
                (
                    interaction["expected_channel_input"],
                    interaction["expected_channel_input_redacted"],
                )
                for interaction in self.replay_session["interactions"]
            ]
        )
        return device_outputs, scrapli_inputs

    def setup_async_replay_mode(self, scrapli_conn: AsyncDriver) -> None:
        """
        Patch scrapli Channel read/write methods in "replay" mode

        Args:
            scrapli_conn: scrapli connection to fetch data from

        Returns:
            None

        Raises:
            N/A

        """
        device_outputs, scrapli_inputs = self._common_replay_mode()
        self._patch_async_read_replay(scrapli_conn=scrapli_conn, device_outputs=device_outputs)
        self._patch_write_replay(scrapli_conn=scrapli_conn, scrapli_inputs=scrapli_inputs)

    def setup_replay_mode(self, scrapli_conn: Driver) -> None:
        """
        Patch scrapli Channel read/write methods in "replay" mode

        Args:
            scrapli_conn: scrapli connection to fetch data from

        Returns:
            None

        Raises:
            N/Ah

        """
        device_outputs, scrapli_inputs = self._common_replay_mode()
        self._patch_read_replay(scrapli_conn=scrapli_conn, device_outputs=device_outputs)
        self._patch_write_replay(scrapli_conn=scrapli_conn, scrapli_inputs=scrapli_inputs)

    def _patch_async_read_replay(
        self, scrapli_conn: AsyncDriver, device_outputs: Iterator[str]
    ) -> None:
        """
        Patch scrapli AsyncChannel read method in "replay" mode

        Args:
            scrapli_conn: scrapli connection to fetch data from
            device_outputs: iterator of inputs that the read method should return for the "fake"
                connection

        Returns:
            None

        Raises:
            N/A

        """

        async def patched_read(cls: AsyncChannel) -> bytes:
            """
            Patched AsyncChannel.read method

            Args:
                cls: scrapli Channel self

            Returns:
                bytes: bytes read from teh channel

            Raises:
                ScrapliReplayException: if there are no more outputs from the session to replay

            """
            try:
                buf = next(device_outputs).encode()

                # if we see this string we know we actually need to ship out the current scrapli cfg
                # session name that we capture during the replay write method
                if b"__SCRAPLI_CFG_SESSION_NAME__" in buf and self._scrapli_cfg_session:
                    buf = self._scrapli_cfg_session.encode()
                    self._scrapli_cfg_session = ""

            except StopIteration as exc:
                msg = "No more device outputs to replay"
                raise ScrapliReplayException(msg) from exc

            cls.logger.debug(f"read: {repr(buf)}")

            if cls.channel_log:
                cls.channel_log.write(buf)

            if cls._base_channel_args.comms_ansi:  # pylint: disable=W0212
                buf = cls._strip_ansi(buf=buf)  # pylint: disable=W0212

            return buf

        scrapli_conn.channel.read = types.MethodType(  # type: ignore
            patched_read, scrapli_conn.channel
        )

    def _patch_read_replay(self, scrapli_conn: Driver, device_outputs: Iterator[str]) -> None:
        """
        Patch scrapli Channel read method in "replay" mode

        Args:
            scrapli_conn: scrapli connection to fetch data from
            device_outputs: iterator of inputs that the read method should return for the "fake"
                connection

        Returns:
            None

        Raises:
            N/A

        """

        def patched_read(cls: Channel) -> bytes:
            """
            Patched Channel.read method

            Args:
                cls: scrapli Channel self

            Returns:
                bytes: bytes read form the channel

            Raises:
                ScrapliReplayException: if there are no more outputs from the session to replay

            """
            try:
                buf = next(device_outputs).encode()

                # if we see this string we know we actually need to ship out the current scrapli cfg
                # session name that we capture during the replay write method
                if b"__SCRAPLI_CFG_SESSION_NAME__" in buf and self._scrapli_cfg_session:
                    buf = self._scrapli_cfg_session.encode()
                    self._scrapli_cfg_session = ""

            except StopIteration as exc:
                msg = "No more device outputs to replay"
                raise ScrapliReplayException(msg) from exc

            cls.logger.debug(f"read: {repr(buf)}")

            if cls.channel_log:
                cls.channel_log.write(buf)

            if cls._base_channel_args.comms_ansi:  # pylint: disable=W0212
                buf = cls._strip_ansi(buf=buf)  # pylint: disable=W0212

            return buf

        scrapli_conn.channel.read = types.MethodType(  # type: ignore
            patched_read, scrapli_conn.channel
        )

    def _patch_write_replay(
        self, scrapli_conn: Union[AsyncDriver, Driver], scrapli_inputs: Iterator[Tuple[str, bool]]
    ) -> None:
        """
        Patch scrapli Channel write method in "replay" mode

        Args:
            scrapli_conn: scrapli connection to fetch data from
            scrapli_inputs: inputs to assert are true that scrapli should be sending

        Returns:
            None

        Raises:
            N/A

        """

        def patched_write(cls: BaseChannel, channel_input: str, redacted: bool = False) -> None:
            """
            Patched Channel.write method

            Args:
                cls: scrapli Channel self
                channel_input: input to send to the channel
                redacted: if input should be redacted from log

            Returns:
                None

            Raises:
                ScrapliReplayExpectedInputError: if actual input does not match expected input

            """
            expected_input, expected_redacted = next(scrapli_inputs)

            if redacted is True:
                _channel_input = "REDACTED"
            elif re.search(pattern=SCRAPLI_CFG_SESSION_PATTERN, string=channel_input):
                _channel_input = re.sub(
                    pattern=SCRAPLI_CFG_SESSION_PATTERN,
                    string=channel_input,
                    repl="__SCRAPLI_CFG_SESSION_NAME__",
                )
                # if we see a scrapli cfg session in the replay we have to store it as it has a
                # timestamp -- we need to replay this back so scrapli doesnt break
                self._scrapli_cfg_session = channel_input
            else:
                _channel_input = channel_input

            if not all((expected_input == _channel_input, expected_redacted == redacted)):
                msg = "expected channel input does not match actual channel input"
                raise ScrapliReplayExpectedInputError(msg)

            log_output = "REDACTED" if redacted else repr(channel_input)
            cls.logger.debug(f"write: {log_output}")

        scrapli_conn.channel.write = types.MethodType(  # type: ignore
            patched_write, scrapli_conn.channel
        )

    def setup_async_record_mode(self, scrapli_conn: AsyncDriver) -> None:
        """
        Patch scrapli AsyncChannel read and write methods in "record" mode

        Args:
            scrapli_conn: scrapli connection to fetch data from

        Returns:
            None

        Raises:
            N/A

        """
        self._patch_async_read_record(scrapli_conn=scrapli_conn)
        self._patch_write_record(scrapli_conn=scrapli_conn)

    def setup_record_mode(self, scrapli_conn: Driver) -> None:
        """
        Patch scrapli Channel read and write methods in "record" mode

        Args:
            scrapli_conn: scrapli connection to fetch data from

        Returns:
            None

        Raises:
            N/A

        """
        self._patch_read_record(scrapli_conn=scrapli_conn)
        self._patch_write_record(scrapli_conn=scrapli_conn)

    def _patch_async_read_record(self, scrapli_conn: AsyncDriver) -> None:
        """
        Patch scrapli AsyncChannel read method in "record" mode

        Args:
            scrapli_conn: scrapli connection to fetch data from

        Returns:
            None

        Raises:
            N/A

        """

        async def patched_read(cls: AsyncChannel) -> bytes:
            """
            Patched Channel.read method

            Args:
                cls: scrapli Channel self

            Returns:
                bytes: bytes read

            Raises:
                N/A

            """
            buf: bytes = await cls.transport.read()
            buf = buf.replace(b"\r", b"")

            self.read_log.write(buf)

            cls.logger.debug(f"read: {repr(buf)}")

            if cls.channel_log:
                cls.channel_log.write(buf)

            if cls._base_channel_args.comms_ansi:  # pylint: disable=W0212
                buf = cls._strip_ansi(buf=buf)  # pylint: disable=W0212

            return buf

        scrapli_conn.channel.read = types.MethodType(  # type: ignore
            patched_read, scrapli_conn.channel
        )

    def _patch_read_record(self, scrapli_conn: Driver) -> None:
        """
        Patch scrapli Channel read method in "record" mode

        Args:
            scrapli_conn: scrapli connection to fetch data from

        Returns:
            None

        Raises:
            N/A

        """

        def patched_read(cls: Channel) -> bytes:
            """
            Patched Channel.read method

            Args:
                cls: scrapli Channel self

            Returns:
                bytes: bytes read

            Raises:
                N/A

            """
            buf: bytes = cls.transport.read()
            buf = buf.replace(b"\r", b"")

            self.read_log.write(buf)

            cls.logger.debug(f"read: {repr(buf)}")

            if cls.channel_log:
                cls.channel_log.write(buf)

            if cls._base_channel_args.comms_ansi:  # pylint: disable=W0212
                buf = cls._strip_ansi(buf=buf)  # pylint: disable=W0212

            return buf

        scrapli_conn.channel.read = types.MethodType(  # type: ignore
            patched_read, scrapli_conn.channel
        )

    def _patch_write_record(
        self,
        scrapli_conn: Union[AsyncDriver, Driver],
    ) -> None:
        """
        Patch scrapli Channel write method in "record" mode

        Args:
            scrapli_conn: scrapli connection to fetch data from

        Returns:
            None

        Raises:
            N/A

        """

        def patched_write(cls: BaseChannel, channel_input: str, redacted: bool = False) -> None:
            """
            Patched Channel.write method

            Args:
                cls: scrapli Channel self
                channel_input: input to send to the channel
                redacted: if input should be redacted from log

            Returns:
                None

            Raises:
                N/A

            """
            _channel_input = re.sub(
                pattern=SCRAPLI_CFG_SESSION_PATTERN,
                repl="__SCRAPLI_CFG_SESSION_NAME__",
                string=channel_input,
            )

            self.write_log.append((_channel_input, redacted, self.read_log.tell()))

            log_output = "REDACTED" if redacted else repr(channel_input)
            cls.logger.debug(f"write: {log_output}")

            cls.transport.write(channel_input=channel_input.encode())

        scrapli_conn.channel.write = types.MethodType(  # type: ignore
            patched_write, scrapli_conn.channel
        )

    def telnet_patch_update_log(self, auth_username: str) -> None:
        """
        Patch the read log for telnet connections

        This method removes "leading dead space" and any extra returns/dead space between user and
        password and the first prompt/banner showing up. This only is necessary for telnet conns.

        Args:
             auth_username: username from the patched scrapli object

        Returns:
            None

        Raises:
            N/A

        """
        updatedwrite_log = []
        for write_log_entry in self.write_log:
            updatedwrite_log.append(write_log_entry)
            if write_log_entry[1] is True:
                break
        # append the *last* entry in the write log back to the updated list -- this will
        # get us reading up through the banner/initial prompt
        updatedwrite_log.append(self.write_log[-1])

        # for telnet connections we may have some "dead space" (empty reads) at the
        # beginning of the interactions, get rid of that as it is not needed here
        index = 0
        for index, write_log_entry in enumerate(updatedwrite_log):
            if write_log_entry[0] == auth_username:
                # we've got the index of the updated write log starting at the username
                # we know we can slice everything off before this now
                break
        updatedwrite_log = updatedwrite_log[index:]

        # finally update the replay class write log w/ our modified version
        self.write_log = updatedwrite_log


class ScrapliReplay:
    def __init__(
        self,
        *,
        session_directory: Optional[str] = None,
        session_name: Optional[str] = None,
        replay_mode: str = "record",
        block_network: bool = False,
    ) -> None:
        """
        Scrapli replay

        Args:
            session_directory: directory to write session data to
            session_name: name of session to write out
            replay_mode: replay mode to use
            block_network: if set to True, no network connections will be made, though any stored
                sessions will be ran normally

        Returns:
            None

        Raises:
            ScrapliReplayException: if invalid replay mode provided

        """
        if session_directory is None or not Path(session_directory).is_dir():
            self.session_directory = Path.cwd()
        else:
            self.session_directory = Path(session_directory)

        # session name will generally come from pytest test name, but for ad-hoc use it can be
        # auto-generated w/ timestamp
        self.session_name = (
            session_name or f"scrapli_replay_session_{round(datetime.now().timestamp())}"
        )

        if replay_mode not in (
            "record",
            "replay",
            "overwrite",
        ):
            raise ScrapliReplayException("replay mode invalid")

        if replay_mode == "record" and self._session_exists():
            print(
                "session exists but replay mode is not set to overwrite, using replay mode 'replay'"
            )
            replay_mode = "replay"
        elif not self._session_exists():
            replay_mode = "record"

        self.replay_mode = ReplayMode[replay_mode.upper()]

        self.replay_session: Dict[str, Any] = {}
        if self.replay_mode == ReplayMode.REPLAY:
            with open(f"{self.session_directory}/{self.session_name}.yaml", "r") as f:
                self.replay_session = safe_load(f)
            # if we open a session and there are no interactions recorded for any of the hosts then
            # something is not right -- we will need to re-record a session
            if not all(
                instance_session.get("interactions", None)
                for instance_session in self.replay_session.values()
            ):
                self.replay_mode = ReplayMode.RECORD

        self._block_network = block_network
        self._patched_open: Optional[mock._patch[Any]] = None  # noqa
        self.wrapped_instances: Dict[str, ScrapliReplayInstance] = {}

    def __call__(self, wrapped_func: Callable[..., Any]) -> Callable[..., Any]:
        """
        Use ScrapliReplay as a decorator

        Decide if the wrapped function is sync or async and wrap that function/coroutine in context
        manager of self

        Args:
            wrapped_func: function being decorated

        Returns:
            decorate: decorated func

        Raises:
            N/A

        """
        if asyncio.iscoroutinefunction(wrapped_func):

            async def decorate(*args: Any, **kwargs: Any) -> Any:
                async with self:
                    return await wrapped_func(*args, **kwargs)

        else:
            # ignoring type error:
            # "All conditional function variants must have identical signatures"
            # one is sync one is async so never going to be identical here!
            def decorate(*args: Any, **kwargs: Any) -> Any:  # type: ignore
                with self:
                    return wrapped_func(*args, **kwargs)

        return decorate

    def __enter__(self) -> None:
        """
        Enter method for context manager

        Args:
            N/A

        Returns:
            None

        Raises:
            N/A

        """

        def patched_open(cls: Driver) -> None:
            """
            Patched Driver.open method

            Patched at the driver and dealing w/ the on open/auth things as this way we never have
            to think about which transport is being used

            Args:
                cls: scrapli Drive self

            Returns:
                None

            Raises:
                N/A

            """
            instance_name = self.create_instance_name(scrapli_conn=cls)

            connection_profile = self.create_connection_profile(scrapli_conn=cls)
            instance_object = ScrapliReplayInstance(
                replay_mode=self.replay_mode,
                connection_profile=connection_profile,
                replay_session=self.replay_session.get(instance_name, {}),
            )
            self.wrapped_instances[instance_name] = instance_object

            if self.replay_mode == ReplayMode.REPLAY:
                instance_object.setup_replay_mode(scrapli_conn=cls)
            else:
                if self._block_network is True:
                    # if block network is true and we got here then there is no session recorded, so
                    # we need to skip this test
                    pytest.skip(
                        "scrapli-replay block-network is True, no session recorded, "
                        "skipping test..."
                    )

                # if we are not in replay mode, we are in record or overwrite (same/same) so setup
                # the record read/write channel methods and then do "normal" stuff
                instance_object.setup_record_mode(scrapli_conn=cls)
                cls.transport.open()

            cls._pre_open_closing_log(closing=False)  # pylint: disable=W0212

            if cls.transport_name in ("system",) and not cls.auth_bypass:
                cls.channel.channel_authenticate_ssh(
                    auth_password=cls.auth_password,
                    auth_private_key_passphrase=cls.auth_private_key_passphrase,
                )
            if (
                cls.transport_name
                in (
                    "telnet",
                    "asynctelnet",
                )
                and not cls.auth_bypass
            ):
                cls.channel.channel_authenticate_telnet(
                    auth_username=cls.auth_username, auth_password=cls.auth_password
                )
                if self.replay_mode == ReplayMode.RECORD:
                    instance_object.telnet_patch_update_log(auth_username=cls.auth_username)

            if cls.on_open:
                cls.on_open(cls)

            cls._post_open_closing_log(closing=False)  # pylint: disable=W0212

        self._patched_open = mock.patch.object(
            target=scrapli.driver.base.sync_driver.Driver, attribute="open", new=patched_open
        )
        self._patched_open.start()

    def __exit__(
        self,
        exception_type: Optional[Type[BaseException]],
        exception_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        """
        Exit method to cleanup for context manager

        Args:
            exception_type: exception type being raised
            exception_value: message from exception being raised
            traceback: traceback from exception being raised

        Returns:
            None

        Raises:
            ScrapliReplayException: if patched open is none for some reason

        """
        if not self._patched_open:
            raise ScrapliReplayException(
                "patched open is None, but we are in exit... this should never happen, definitely "
                "a bug"
            )

        self._patched_open.stop()

        if self.replay_mode == ReplayMode.RECORD or self.replay_mode == ReplayMode.OVERWRITE:
            self._save()

    async def __aenter__(self) -> None:
        """
        Enter method for context manager

        Args:
            N/A

        Returns:
            None

        Raises:
            N/A

        """

        async def patched_open(cls: AsyncDriver) -> None:
            """
            Patched AsyncDriver.open method

            Patched at the driver and dealing w/ the on open/auth things as this way we never have
            to think about which transport is being used

            Args:
                cls: scrapli Drive self

            Returns:
                None

            Raises:
                N/A

            """
            instance_name = self.create_instance_name(scrapli_conn=cls)

            connection_profile = self.create_connection_profile(scrapli_conn=cls)
            instance_object = ScrapliReplayInstance(
                replay_mode=self.replay_mode,
                connection_profile=connection_profile,
                replay_session=self.replay_session.get(instance_name, {}),
            )
            self.wrapped_instances[instance_name] = instance_object

            if self.replay_mode == ReplayMode.REPLAY:
                instance_object.setup_async_replay_mode(scrapli_conn=cls)
            else:
                if self._block_network is True:
                    # if block network is true and we got here then there is no session recorded, so
                    # we need to skip this test
                    pytest.skip(
                        "scrapli-replay block-network is True, no session recorded, "
                        "skipping test..."
                    )

                # if we are not in replay mode, we are in record or overwrite (same/same) so setup
                # the record read/write channel methods and then do "normal" stuff
                instance_object.setup_async_record_mode(scrapli_conn=cls)
                await cls.transport.open()

            cls._pre_open_closing_log(closing=False)  # pylint: disable=W0212

            if (
                cls.transport_name
                in (
                    "telnet",
                    "asynctelnet",
                )
                and not cls.auth_bypass
            ):
                await cls.channel.channel_authenticate_telnet(
                    auth_username=cls.auth_username, auth_password=cls.auth_password
                )
                if self.replay_mode == ReplayMode.RECORD:
                    instance_object.telnet_patch_update_log(auth_username=cls.auth_username)

            if cls.on_open:
                await cls.on_open(cls)

            cls._post_open_closing_log(closing=False)  # pylint: disable=W0212

        self._patched_open = mock.patch.object(
            scrapli.driver.base.async_driver.AsyncDriver, "open", new=patched_open
        )
        self._patched_open.start()

    async def __aexit__(
        self,
        exception_type: Optional[Type[BaseException]],
        exception_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        """
        Exit method to cleanup for async context manager

        Args:
            exception_type: exception type being raised
            exception_value: message from exception being raised
            traceback: traceback from exception being raised

        Returns:
            None

        Raises:
            ScrapliReplayException: if patched open is none for some reason

        """
        if not self._patched_open:
            raise ScrapliReplayException(
                "patched open is None, but we are in exit... this should never happen, definitely "
                "a bug"
            )

        self._patched_open.stop()

        if self.replay_mode == ReplayMode.RECORD or self.replay_mode == ReplayMode.OVERWRITE:
            self._save()

    def create_instance_name(self, scrapli_conn: Union[AsyncDriver, Driver]) -> str:
        """
        Create as unique as possible instance name for a given connection

        Since hash cant be relied on to between python executions we need to have some way to have a
        decent idea about what connection is what... using the host and port is maybe not enough as
        a user may have multiple connections to the same device in a test session. Adding in the
        transport *might* help (maybe one is ssh one is netconf or telnet), but still not 100%...
        Adding in the logging uid is handy, but only if the user set one, so we also will tack on
        an extra field basically counting how many of the same connections we've seen. We *may* not
        support multiple connections because it may be too troublesome (but users could add an
        arbitrary logging uid to differentiate), but we'll put it there anyway for now...

        Args:
            scrapli_conn: scrapli connection to fetch data from

        Returns:
            str: instance name to use for the connection

        Raises:
            N/A

        """
        instance_name = (
            f"{scrapli_conn.host}:{scrapli_conn.port}:"
            f"{scrapli_conn.transport.__class__.__name__}:"
            f"{scrapli_conn.logger.extra.get('uid', '')}"
        )
        similar_instance_names = [
            inst_name for inst_name in self.wrapped_instances if inst_name.startswith(instance_name)
        ]
        instance_name = f"{instance_name}:{len(similar_instance_names)}"
        return instance_name

    @staticmethod
    def create_connection_profile(scrapli_conn: Union[AsyncDriver, Driver]) -> ConnectionProfile:
        """
        Record connection information

        Args:
            scrapli_conn: scrapli connection to fetch data from

        Returns:
            ConnectionProfile: recorded connection profile

        Raises:
            N/A

        """
        recorded_connection_profile = ConnectionProfile(
            host=scrapli_conn.host,
            port=scrapli_conn.port,
            auth_username=scrapli_conn.auth_username,
            auth_password=bool(scrapli_conn.auth_password),
            auth_private_key=scrapli_conn.auth_private_key,
            auth_private_key_passphrase=bool(scrapli_conn.auth_private_key_passphrase),
            auth_bypass=scrapli_conn.auth_bypass,
            transport=scrapli_conn.transport_name,
        )

        if isinstance(scrapli_conn, NetworkDriver):
            recorded_connection_profile.auth_secondary = bool(scrapli_conn.auth_secondary)

        return recorded_connection_profile

    def _session_exists(self) -> bool:
        """
        Check if a session file already exists

        Args:
            N/A

        Returns:
            bool:

        Raises:
            N/A

        """
        if Path(f"{self.session_directory}/{self.session_name}.yaml").is_file():
            return True
        return False

    def _serialize(self) -> Dict[str, Any]:
        """
        Serialize in memory session data into a yaml-friendly output

        Args:
            N/A

        Returns:
             None

        Raises:
            N/A

        """
        instance_replay_sessions = {}

        for instance_name, replay_instance in self.wrapped_instances.items():
            instance_read_log = replay_instance.read_log
            instance_write_log = replay_instance.write_log

            read_log_len = instance_read_log.tell()
            instance_read_log.seek(0)

            instance_replay_session: Dict[str, Any] = {}
            instance_replay_sessions[instance_name] = instance_replay_session

            try:
                instance_replay_session["connection_profile"] = asdict(
                    replay_instance.connection_profile
                )
            except TypeError:
                # connection was already open so we couldn't patch it
                instance_replay_session["connection_profile"] = {}

            instance_replay_session["interactions"] = []

            # all things after the "initial output" is an "interaction"
            previous_read_to_position = 0
            for write_data in instance_write_log:
                write_input, redacted, read_to_position = write_data

                channel_bytes_output = instance_read_log.read(
                    read_to_position - previous_read_to_position
                )
                try:
                    channel_output = channel_bytes_output.decode()
                except UnicodeDecodeError:
                    # unclear if this will ever be a problem... leaving it in this try/except for
                    # posterity...
                    channel_output = channel_bytes_output.decode(errors="ignore")

                # replace any output w/ the scrapli cfg replace pattern
                channel_output = re.sub(
                    pattern=SCRAPLI_CFG_SESSION_PATTERN,
                    repl="__SCRAPLI_CFG_SESSION_NAME__",
                    string=channel_output,
                )

                instance_replay_session["interactions"].append(
                    {
                        "channel_output": channel_output,
                        "expected_channel_input": write_input if not redacted else "REDACTED",
                        "expected_channel_input_redacted": redacted,
                    }
                )
                previous_read_to_position = read_to_position

            if previous_read_to_position != read_log_len:
                # we can end up w/ "extra" data if we dont close the connection -- as in scrapli
                # will have read one more thing than it wrote -- so we check to see if there is
                # remaining read log data, and if so add one final interaction
                instance_replay_session["interactions"].append(
                    {
                        "channel_output": instance_read_log.read().decode(),
                        "expected_channel_input": None,
                        "expected_channel_input_redacted": False,
                    }
                )

        return instance_replay_sessions

    def _save(self) -> None:
        """
        Save the contents of a session

        Args:
            N/A

        Returns:
             None

        Raises:
            N/A

        """
        with open(f"{self.session_directory}/{self.session_name}.yaml", "w") as f:
            yaml = YAML()
            yaml.indent(mapping=2, sequence=4, offset=2)
            yaml.dump(self._serialize(), f)
