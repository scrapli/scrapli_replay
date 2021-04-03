"""scrapli_replay.server.collector"""
from copy import copy
from dataclasses import asdict, dataclass
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple, Union, cast

from ruamel.yaml import YAML  # type: ignore

from scrapli import Scrapli
from scrapli.channel.sync_channel import Channel
from scrapli.driver.core import EOSDriver
from scrapli.driver.network.sync_driver import NetworkDriver
from scrapli.exceptions import ScrapliConnectionError
from scrapli.helper import user_warning
from scrapli_replay.exceptions import ScrapliReplayException
from scrapli_replay.logging import logger

# pylint: disable=W0212


@dataclass()
class StandardEvent:
    # the actual stuff the channel outputs
    channel_output: str
    # the privilege level at the end of the event
    result_privilege_level: str
    # if the event should, if False that would basically be like running a long command
    # w/ paging still on, so we are stuck at --More-- prompt
    returns_prompt: bool = True
    # "exit" is a "standard" event, but it obviously can cause the connection to close, so for
    # any event like that we'll set this to True, but of course it will default to False as that
    # is the much more common/likely scenario
    closes_connection: bool = False
    # would be cool to add response delay -- i.e. device takes .04 seconds before spitting data out
    # when this command is ran, could also add delay in the middle of a command, like it sputters
    # while outputting data or something


@dataclass()
class InteractStep:
    # the expected input, if an unexpected input occurs during an "interaction" we have
    # to raise some error to a user like a device would
    channel_input: str
    # the actual stuff the channel outputs
    channel_output: str
    # if the channel in put is "hidden" like for password prompts
    hidden_input: bool = False
    # if the event should, if False that would basically be like running a long command
    # w/ paging still on, so we are stuck at --More-- prompt
    returns_prompt: bool = True


@dataclass()
class InteractiveEvent:
    # the privilege level at the end of the event
    result_privilege_level: Optional[str] = None
    # list of all of the "steps" in the interact event
    event_steps: Optional[List[InteractStep]] = None


class ScrapliCollectorChannel(Channel):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.captured_writes: List[str] = []

    def write(self, channel_input: str, redacted: bool = False) -> None:
        self.captured_writes.append(channel_input)
        super().write(channel_input=channel_input, redacted=redacted)


class ScrapliCollector:
    def __init__(
        self,
        channel_inputs: List[str],
        interact_events: List[List[Tuple[str, str, bool]]],
        paging_indicator: str,
        paging_escape_string: str = "\x1b",
        scrapli_connection: Optional[NetworkDriver] = None,
        collector_session_filename: str = "scrapli_replay_collector_session.yaml",
        **kwargs: Dict[str, Any],
    ) -> None:
        """
        Scrapli Collector Class

        Patches scrapli so that we can record the connection inputs and outputs from the channel

        Args:
            channel_inputs: list of channel inputs to record
            interact_events: list of interact events to record
            paging_indicator: string that indicates when the device is prompting for user input to
                continue paging the output
            paging_escape_string: string to use to escape the paging prompt
            scrapli_connection: already instantiated scrapli connection -- you can pass this or just
                the kwargs necessary to instantiate one for you
            collector_session_filename: name of file to save collector session output to
            kwargs: kwargs to instantiate scrapli connection, *must* include platform as this will
                instantiate the connection via `Scrapli` factory class!

        Returns:
            None

        Raises:
            ScrapliReplayException: if no valid scrapli connection or connection data present

        """
        logger.debug("creating scrapli replay collector")

        self.channel_inputs = channel_inputs
        self.interact_events = interact_events
        self.paging_indicator = paging_indicator
        self.paging_escape_string = paging_escape_string

        self.collector_session_filename = collector_session_filename

        self.channel_log = BytesIO()
        # making the channel log unclose-able so we can retain the channel log even throughout
        # connections being closed
        self.channel_log.close = lambda: None  # type: ignore

        if scrapli_connection:
            logger.debug("scrapli connection provided")
            self.scrapli_connection = scrapli_connection
            self.scrapli_connection._base_channel_args.channel_log = self.channel_log

            if self.scrapli_connection.isalive():
                # want to close it so we can reset the on open (paging stuff)
                self.scrapli_connection.close()

        else:
            logger.debug("no scrapli connection provided, building one from kwargs")
            if not kwargs.get("platform"):
                msg = "must provide 'platform' as a kwarg if you dont provide a connection object!"
                logger.critical(msg)
                raise ScrapliReplayException(msg)

            if kwargs.pop("channel_log", None):
                user_warning(
                    title="Ignored argument!",
                    message="channel_log arg provided, replacing with ScrapliCollector channel_log",
                )

            self.scrapli_connection = Scrapli(
                channel_log=self.channel_log,
                **kwargs,  # type: ignore
            )

        self.scrapli_connection_original_timeout_transport = (
            self.scrapli_connection.timeout_transport
        )
        # update the channel to be an instance of the ScrapliCollectorChannel
        self.scrapli_connection.channel = ScrapliCollectorChannel(
            transport=self.scrapli_connection.transport,
            base_channel_args=self.scrapli_connection._base_channel_args,
        )

        # store the "normal" default desired privilege level
        self.scrapli_connection_default_desired_privilege_level = (
            self.scrapli_connection.default_desired_privilege_level
        )

        # store and reset the on_open/on_close to None so we can manage when we want to disable
        # paging and such
        self.scrapli_connection_standard_on_open = self.scrapli_connection.on_open
        self.scrapli_connection_standard_on_close = self.scrapli_connection.on_close
        self.scrapli_connection.on_open = None
        self.scrapli_connection.on_close = None

        # bool to just indicate if we have ran the on open stuff
        self.on_open_enabled = False
        self.on_open_inputs: List[str] = []

        self.on_close_inputs: List[str] = []

        # flag to indicate if we have collected priv prompts yet
        self.collected_priv_prompts = False

        # Future: support recording any login auth/banner stuff too

        platform_privilege_levels = self.scrapli_connection.privilege_levels.keys()
        self.initial_privilege_level = ""
        self.privilege_level_prompts: Dict[str, str] = {
            privilege_level_name: "" for privilege_level_name in platform_privilege_levels
        }

        # commands captured from driver privilege levels for escalate/deescalate
        self._privilege_escalate_inputs: List[str] = []
        self._privilege_deescalate_inputs: List[str] = []
        self._interact_privilege_escalations: List[List[Tuple[str, str, bool]]] = []

        self.events: Dict[str, Dict[str, Dict[str, Union[StandardEvent, InteractiveEvent]]]] = {
            privilege_level_name: {"pre_on_open": {}, "post_on_open": {}}
            for privilege_level_name in platform_privilege_levels
        }
        self.dumpable_events: Dict[str, Dict[str, Dict[str, Any]]] = {
            privilege_level_name: {"pre_on_open": {}, "post_on_open": {}}
            for privilege_level_name in platform_privilege_levels
        }

        # this would be similar to the events but for an unknown input, like we have in the v2 thing
        self.unknown_events: Dict[str, Dict[str, Optional[StandardEvent]]] = {
            privilege_level_name: {"pre_on_open": None, "post_on_open": None}
            for privilege_level_name in platform_privilege_levels
        }
        self.dumpable_unknown_events: Dict[str, Dict[str, Optional[Any]]] = {
            privilege_level_name: {"pre_on_open": None, "post_on_open": None}
            for privilege_level_name in platform_privilege_levels
        }

        # this is a list of all possible prompts -- because we are going to use send and expect we
        # need to be able to expect any prompt OR the paging pattern... so after open and we collect
        # the prompts for each priv level, we can build this list
        self.all_expected_patterns = [self.paging_indicator]

        self._determine_privilege_inputs()

    def open(self) -> None:
        """
        Open the Collector and the underlying scrapli connection

        Args:
            N/A

        Returns:
            None

        Raises:
            None

        """
        self.scrapli_connection.open()

        if not self.initial_privilege_level:
            # only need to fetch this on the initial open, not for subsequent opens when we need
            # to reconnect!
            logger.debug(
                "no initial privilege level set, must be first open... setting initial privilege "
                "level"
            )
            self.initial_privilege_level = self._get_current_privilege_level_name()

    def close(self) -> None:
        """
        Close the Collector and the underlying scrapli connection

        Args:
            N/A

        Returns:
            None

        Raises:
            None

        """
        self.scrapli_connection.close()

    def _determine_privilege_inputs(self) -> None:
        """
        Private method to figure out what the privilege escalation/deescalation inputs are

        Args:
            N/A

        Returns:
            None

        Raises:
            None

        """
        logger.debug("building all privilege level inputs/interactions from scrapli driver")

        self._privilege_escalate_inputs = [
            priv.escalate
            for priv in self.scrapli_connection.privilege_levels.values()
            if not priv.escalate_auth and priv.escalate
        ]
        self._privilege_deescalate_inputs = [
            priv.deescalate
            for priv in self.scrapli_connection.privilege_levels.values()
            if priv.deescalate
        ]

        interact_privilege_escalations_levels = [
            priv
            for priv in self.scrapli_connection.privilege_levels.values()
            if priv.escalate_auth and priv.escalate_prompt
        ]
        self._interact_privilege_escalations = [
            [
                (priv.escalate, priv.escalate_prompt, False),
                ("__AUTH_SECONDARY__", priv.pattern, True),
            ]
            for priv in interact_privilege_escalations_levels
        ]

    def _get_current_privilege_level_name(self, prompt: Optional[str] = None) -> str:
        """
        Convenience method to fetch current privilege level name from the current prompt

        Args:
            prompt: prompt pattern to use, if not supplied, we'll fetch current prompt

        Returns:
            str: string name of current privilege level

        Raises:
            N/A

        """
        if not prompt:
            prompt = self.scrapli_connection.get_prompt()
        priv_name: str = self.scrapli_connection._determine_current_priv(prompt)[0]
        return priv_name

    def _collect_privilege_prompts(self) -> None:
        """
        Private method to get all of the prompts for each priv of the underlying device

        Args:
            N/A

        Returns:
            None

        Raises:
            None

        """
        for priv_level in self.privilege_level_prompts:
            logger.info(f"collecting prompt for priv level {priv_level}")
            self.scrapli_connection.acquire_priv(priv_level)
            self.privilege_level_prompts[priv_level] = self.scrapli_connection.get_prompt()

        self.collected_priv_prompts = True

    def _extend_all_expected_prompts(self) -> None:
        """
        Extend the "all_expected_prompts" to include all the captured privilege level prompts

        Args:
            N/A

        Returns:
            None

        Raises:
            ScrapliReplayException: if privilege patterns aren't collected before running this

        """
        if not self.collected_priv_prompts:
            msg = (
                "attempting to build all expected prompts pattern, but have not collected privilege"
                " level prompts yet, failing"
            )
            logger.critical(msg)
            raise ScrapliReplayException(msg)

        self.all_expected_patterns.extend(
            [prompt for _, prompt in self.privilege_level_prompts.items()]
        )

    @staticmethod
    def _strip_leading_newline(channel_output: str) -> str:
        """
        Remove a single leading newline if present

        Args:
            channel_output: channel output to remove single leading newline from

        Returns:
            str: channel output w/ leading newline removed

        Raises:
            N/A

        """
        if channel_output.startswith("\n"):
            final_channel_output = channel_output[1:]
            return final_channel_output
        return channel_output

    def _collect_on_open_inputs(self) -> None:
        """
        Private method to figure out what the "on_open" commands are

        Args:
            N/A

        Returns:
            None

        Raises:
            None

        """
        self.scrapli_connection.acquire_priv(
            self.scrapli_connection_default_desired_privilege_level
        )

        logger.info("collecting on open inputs")

        self.scrapli_connection.channel = cast(
            ScrapliCollectorChannel, self.scrapli_connection.channel
        )
        starting_write_log_count = len(self.scrapli_connection.channel.captured_writes)
        self.scrapli_connection_standard_on_open(self.scrapli_connection)  # type: ignore
        ending_write_log_count = len(self.scrapli_connection.channel.captured_writes)

        write_log_slice = ending_write_log_count - starting_write_log_count
        on_open_writes = self.scrapli_connection.channel.captured_writes[-write_log_slice:]

        # all we need to do here is to fetch the commands that were sent, then we can "handle" them
        # with the standard collection (since we already handle disconnects there), we can assume
        # with reasonable safety that each command will really come in "pairs" -- the command itself
        # and a return. after reversing the list we can just get every other list item
        on_open_writes.reverse()
        self.on_open_inputs = on_open_writes[1::2]

    def _collect_on_close_inputs(self) -> None:
        """
        Private method to figure out what the "on_close" commands are

        Args:
            N/A

        Returns:
            None

        Raises:
            None

        """
        self.scrapli_connection.acquire_priv(
            self.scrapli_connection_default_desired_privilege_level
        )

        logger.info("collecting on close inputs")

        self.scrapli_connection.channel = cast(
            ScrapliCollectorChannel, self.scrapli_connection.channel
        )
        starting_write_log_count = len(self.scrapli_connection.channel.captured_writes)
        self.scrapli_connection_standard_on_close(self.scrapli_connection)  # type: ignore
        ending_write_log_count = len(self.scrapli_connection.channel.captured_writes)

        write_log_slice = ending_write_log_count - starting_write_log_count
        on_close_writes = self.scrapli_connection.channel.captured_writes[-write_log_slice:]

        # all we need to do here is to fetch the commands that were sent, then we can "handle" them
        # with the standard collection (since we already handle disconnects there), we can assume
        # with reasonable safety that each command will really come in "pairs" -- the command itself
        # and a return. after reversing the list we can just get every other list item
        on_close_writes.reverse()
        self.on_close_inputs = on_close_writes[1::2]

        # the connection *should* have closed at this point, so we'll check that and reopen, because
        # we didnt do a "normal" close (at the driver level) we maybe cant check with "isalive()"
        try:
            self.scrapli_connection.get_prompt()
        except ScrapliConnectionError:
            logger.debug("connection closed, re-opening")
            self.open()

    def _collect_standard_event(self, channel_input: str) -> None:
        """
        Private method to execute and record commands provided to the Collector

        Runs the commands at *all* priv levels so that we can build more context about how the
        device behaves

        Args:
            channel_input: input to send

        Returns:
            None

        Raises:
            None

        """
        on_open_enabled_key = "post_on_open" if self.on_open_enabled else "pre_on_open"

        for priv_level in self.scrapli_connection.privilege_levels:
            logger.info(f"collecting input {channel_input} for priv level {priv_level}")

            self.scrapli_connection.acquire_priv(priv_level)

            try:
                raw_output, _ = self.scrapli_connection.channel.send_input_and_read(
                    channel_input=channel_input,
                    expected_outputs=self.all_expected_patterns,
                    # especially nxos in vrouter is v v v slow....
                    read_duration=60,
                )
            except ScrapliConnectionError:
                logger.debug("connection closed connection, documenting and re-opening")
                closes_connection = True
                channel_output = "__CLOSES_CONNECTION__"
                returns_prompt = False
                # because we use "send_input_and_read" if we lose the connection during this the
                # transport timeout will have been set to 2s or something during the send input
                # and read event, we want to make sure to reset it back to "normal" after this
                # failure
                self.scrapli_connection.timeout_transport = (
                    self.scrapli_connection_original_timeout_transport
                )
                # reopen the connection so things can continue!
                self.open()
            else:
                closes_connection = False
                channel_output = raw_output.decode()
                returns_prompt = True
                if self.paging_indicator.encode() in raw_output:
                    logger.debug("encountered paging indicator, sending escape string")
                    self.scrapli_connection.channel.write(channel_input=self.paging_escape_string)
                    self.scrapli_connection.channel.send_return()
                    returns_prompt = False

            result_privilege_level = self._get_current_privilege_level_name()

            final_channel_output = self._strip_leading_newline(channel_output=channel_output)

            channel_input_event = StandardEvent(
                channel_output=final_channel_output,
                result_privilege_level=result_privilege_level,
                returns_prompt=returns_prompt,
                closes_connection=closes_connection,
            )

            self.events[priv_level][on_open_enabled_key][channel_input] = channel_input_event

    def _collect_interactive_event_hidden_input(
        self, channel_input: str, channel_response: str
    ) -> bytes:
        """
        Send "hidden" input during interactive event collection

        Args:
            channel_input: input to send
            channel_response: response to expect

        Returns:
            bytes: raw bytes read from channel

        Raises:
            None

        """
        _channel_input = channel_input
        if channel_input == "__AUTH_SECONDARY__":
            _channel_input = self.scrapli_connection.auth_secondary
        self.scrapli_connection.channel.write(channel_input=_channel_input)
        self.scrapli_connection.channel.send_return()
        bytes_channel_outputs = [
            channel_output.encode() for channel_output in self.all_expected_patterns
        ]
        bytes_channel_outputs.append(channel_response.encode())
        raw_output: bytes = self.scrapli_connection.channel._read_until_prompt_or_time(
            channel_outputs=bytes_channel_outputs,
            # especially nxos in vrouter is v v v slow....
            read_duration=60,
        )
        return raw_output

    def _collect_interactive_event_standard_input(
        self, channel_input: str, channel_response: str
    ) -> bytes:
        """
        Send "standard" input during interactive event collection

        Args:
            channel_input: input to send
            channel_response: response to expect

        Returns:
            bytes: raw bytes read from channel

        Raises:
            None

        """
        all_patterns_and_expected_interact_prompt = copy(self.all_expected_patterns)
        all_patterns_and_expected_interact_prompt.append(channel_response)

        raw_output, _ = self.scrapli_connection.channel.send_input_and_read(
            channel_input=channel_input,
            expected_outputs=all_patterns_and_expected_interact_prompt,
            # especially nxos in vrouter is v v v slow....
            read_duration=60,
        )

        if channel_input == "":
            # if we just send a return, we'll end up w/ two newlines before the prompt or whatever
            # output we get, so let's remove the leading devices comms_return_char
            slice_length = len(self.scrapli_connection.comms_return_char)
            final_channel_output = raw_output[slice_length:]
            return final_channel_output  # type: ignore
        return raw_output  # type: ignore

    def _collect_interactive_parse_channel_input(
        self, channel_input: str, hidden_input: bool
    ) -> str:
        """
        Parse the response to put in the StandardEvent

        Args:
            channel_input: input to send
            hidden_input: bool if channel_input was hidden

        Returns:
            str: channel input to put into collection dict

        Raises:
            None

        """
        _channel_input = channel_input
        if hidden_input and channel_input == "__AUTH_SECONDARY__":
            _channel_input = "__AUTH_SECONDARY__"
        elif hidden_input:
            _channel_input = "__REDACTED__"
        elif not channel_input:
            _channel_input = self.scrapli_connection.comms_return_char
        return _channel_input

    def _collect_interactive_event(self, interact_event: List[Tuple[str, str, bool]]) -> None:
        """
        Private method to execute and record all interactive commands provided to the Collector

        Runs the commands at *all* priv levels so that we can build more context about how the
        device behaves

        Args:
            interact_event: interactive event to capture

        Returns:
            None

        Raises:
            None

        """
        on_open_enabled_key = "post_on_open" if self.on_open_enabled else "pre_on_open"

        for priv_level in self.scrapli_connection.privilege_levels:
            self.scrapli_connection.acquire_priv(priv_level)

            logger.info(
                f"collecting interactive event {interact_event} for priv level {priv_level}"
            )

            interactive_event = InteractiveEvent(event_steps=[])
            initiating_channel_input = interact_event[0][0]

            for interact_step in interact_event:
                channel_input = interact_step[0]
                channel_response = interact_step[1]
                try:
                    hidden_input = interact_step[2]
                except IndexError:
                    hidden_input = False

                if hidden_input:
                    raw_output = self._collect_interactive_event_hidden_input(
                        channel_input=channel_input, channel_response=channel_response
                    )
                else:
                    raw_output = self._collect_interactive_event_standard_input(
                        channel_input=channel_input, channel_response=channel_response
                    )

                returns_prompt = True
                if self.paging_indicator.encode() in raw_output:
                    self.scrapli_connection.channel.write(channel_input=self.paging_escape_string)
                    self.scrapli_connection.channel.send_return()
                    returns_prompt = False

                _channel_input = self._collect_interactive_parse_channel_input(
                    channel_input=channel_input, hidden_input=hidden_input
                )

                final_channel_output = self._strip_leading_newline(
                    channel_output=raw_output.decode()
                )

                step = InteractStep(
                    channel_input=_channel_input,
                    channel_output=final_channel_output,
                    hidden_input=hidden_input,
                    returns_prompt=returns_prompt,
                )

                interactive_event.event_steps.append(step)  # type: ignore

                if returns_prompt is False:
                    # probably not likely to happen during interactive... but maybe?
                    break

                if any(pattern in raw_output.decode() for pattern in self.all_expected_patterns):
                    # we are done w/ the "event" because we are back at a prompt we know
                    break

            interactive_event.result_privilege_level = self._get_current_privilege_level_name()
            self.events[priv_level][on_open_enabled_key][
                initiating_channel_input
            ] = interactive_event

    def _collect_unknown_events(self) -> None:
        """
        Private method to execute and record "unknown" commands

        Runs the commands at *all* priv levels so that we can build more context about how the
        device behaves

        Args:
            N/A

        Returns:
            None

        Raises:
            None

        """
        on_open_enabled_key = "post_on_open" if self.on_open_enabled else "pre_on_open"

        for priv_level in self.scrapli_connection.privilege_levels:
            self.scrapli_connection.acquire_priv(priv_level)

            logger.info(f"collecting unknown input for priv level {priv_level}")

            try:
                raw_output, _ = self.scrapli_connection.channel.send_input_and_read(
                    channel_input="__UNKNOWN_INPUT__", expected_outputs=self.all_expected_patterns
                )
            except ScrapliConnectionError:
                closes_connection = True
                channel_output = "__CLOSES_CONNECTION__"
                returns_prompt = False
                # reopen the connection so things can continue!
                self.open()
            else:
                closes_connection = False
                channel_output = raw_output.decode()
                returns_prompt = True
                if self.paging_indicator.encode() in raw_output:
                    self.scrapli_connection.channel.write(channel_input=self.paging_escape_string)
                    self.scrapli_connection.channel.send_return()
                    returns_prompt = False

            result_privilege_level = self._get_current_privilege_level_name()

            final_channel_output = self._strip_leading_newline(channel_output=channel_output)

            channel_unknown_input_event = StandardEvent(
                channel_output=final_channel_output,
                result_privilege_level=result_privilege_level,
                returns_prompt=returns_prompt,
                closes_connection=closes_connection,
            )

            self.unknown_events[priv_level][on_open_enabled_key] = channel_unknown_input_event

    def _collect_priv_and_open_close(self) -> None:
        """
        Collect privilege escalation/deescalation and on open/close inputs/outputs

        Args:
            N/A

        Returns:
            None

        Raises:
            N/A

        """
        self._collect_on_open_inputs()
        for on_open_input in self.on_open_inputs:
            self._collect_standard_event(channel_input=on_open_input)

        self._collect_on_close_inputs()
        for on_close_input in self.on_close_inputs:
            self._collect_standard_event(channel_input=on_close_input)

        for privilege_escalate_input in self._privilege_escalate_inputs:
            self._collect_standard_event(channel_input=privilege_escalate_input)

        for privilege_deescalate_input in self._privilege_deescalate_inputs:
            self._collect_standard_event(channel_input=privilege_deescalate_input)

        for interact_privilege_event in self._interact_privilege_escalations:
            self._collect_interactive_event(interact_event=interact_privilege_event)

    def _collect(self) -> None:
        """
        Private method to execute all the "standard" and "interactive" collections

        Args:
            N/A

        Returns:
            None

        Raises:
            None

        """
        self._collect_unknown_events()

        for channel_input in self.channel_inputs:
            self._collect_standard_event(channel_input=channel_input)

        for interact_event in self.interact_events:
            self._collect_interactive_event(interact_event=interact_event)

    def collect(self) -> None:
        """
        Primary public collection method

        Args:
            N/A

        Returns:
            None

        Raises:
            None

        """
        self._collect_privilege_prompts()
        self._extend_all_expected_prompts()

        self._collect_priv_and_open_close()

        if isinstance(self.scrapli_connection, EOSDriver):
            # arista will leave paging enabled even after you exit a connection... kinda throws
            # things off! so we'll put it back... hate having one off things like this but not sure
            # there is another easy fix
            self.scrapli_connection.send_command(command="no terminal length")

        self._collect()

        # close the connection, and reassign the "normal" on open so we can capture everything
        # with "on_open" things done (paging disabled and whatever else)
        self.close()
        self.scrapli_connection.on_open = self.scrapli_connection_standard_on_open
        self.scrapli_connection.on_close = self.scrapli_connection_standard_on_close
        self.open()
        self.on_open_enabled = True

        self._collect_priv_and_open_close()
        self._collect()

    def _serialize(self) -> None:
        """
        Serialize the collected data so it can be dumped to yaml nicely

        Args:
            N/A

        Returns:
            None

        Raises:
            None

        """
        logger.debug("serializing collected inputs to be yaml friendly")

        for privilege_level in self.events:
            for on_open_state in self.events[privilege_level]:
                for channel_input in self.events[privilege_level][on_open_state]:
                    self.dumpable_events[privilege_level][on_open_state][channel_input] = asdict(
                        self.events[privilege_level][on_open_state][channel_input]
                    )
                    self.dumpable_events[privilege_level][on_open_state][channel_input]["type"] = (
                        "standard"
                        if isinstance(
                            self.events[privilege_level][on_open_state][channel_input],
                            StandardEvent,
                        )
                        else "interactive"
                    )

        for privilege_level in self.unknown_events:
            for on_open_state in self.unknown_events[privilege_level]:
                self.dumpable_unknown_events[privilege_level][on_open_state] = asdict(
                    self.unknown_events[privilege_level][on_open_state]
                )

    def dump(self) -> None:
        """
        Primary public dump method to dump collected data out to yaml

        Args:
            N/A

        Returns:
            None

        Raises:
            None

        """
        self._serialize()

        logger.debug("dumping collected inputs to yaml")

        dumpable_dict: Dict[str, Any] = {}
        dumpable_dict["events"] = self.dumpable_events
        dumpable_dict["unknown_events"] = self.dumpable_unknown_events
        dumpable_dict["initial_privilege_level"] = self.initial_privilege_level
        dumpable_dict["privilege_level_prompts"] = self.privilege_level_prompts
        dumpable_dict["on_open_inputs"] = self.on_open_inputs

        with open(self.collector_session_filename, "w") as f:
            yaml = YAML()
            yaml.indent(mapping=2, sequence=4, offset=2)
            yaml.dump(dumpable_dict, f)
