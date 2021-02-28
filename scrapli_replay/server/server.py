"""scrapli_replay.server.server"""
import asyncio
from enum import Enum
from typing import Any, Dict, Optional, Type

import asyncssh
from ruamel.yaml import safe_load  # type: ignore

from scrapli_replay.exceptions import ScrapliReplayServerError
from scrapli_replay.logging import logger

BASE_SERVER_KEY = b"""-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAlwAAAAdzc2gtcn
NhAAAAAwEAAQAAAIEAwahUv5Tf3vWQzmz2de791K+vy2WQP9q5eOCAIlD2dFb9lTCg3CNl
kJRLMwelj4eJVdfT6YfQjRfbOkuMtGmwz+ed9ulHBVQ8Ee7JuSfxRcazWx2Wet5wzA0vkv
dohzw20jHhmLpbAi/x20Zxv5R+jK3o/+x6ciIW6sYCoQXJw88AAAIQhQL0T4UC9E8AAAAH
c3NoLXJzYQAAAIEAwahUv5Tf3vWQzmz2de791K+vy2WQP9q5eOCAIlD2dFb9lTCg3CNlkJ
RLMwelj4eJVdfT6YfQjRfbOkuMtGmwz+ed9ulHBVQ8Ee7JuSfxRcazWx2Wet5wzA0vkvdo
hzw20jHhmLpbAi/x20Zxv5R+jK3o/+x6ciIW6sYCoQXJw88AAAADAQABAAAAgQCE8ss7uz
j2GCARlzycOjaIjRRizpb5P2+VTIqrBGot9IqioX/NoX9YgnYd0mIW5zWheUpCSLskIfyf
SL6QHP8EinQ2e5VPO8sJ3So/2/a9H58ATAZX5D/Rmzjjbh9S57NqlM4y+tSaMVZbUFq53D
uhw+OTG1skt3aK4icJVoYWAQAAAEAkDdyAeM/njkl8IrcutV0Qz9uttRJ7piVGswZmwSiG
aBOVYrSvjNen23FuXXHErMTQbDSMzvI2njBB1P10rteWAAAAQQDjdvmIZGQgLaDqFIQH89
M0USeQavVKmVOjnHMOSzuKzhXoMEGaRtV6s1z6R+0FSblMju69I8KP9x8hmw8JxBn1AAAA
QQDZ86OGU3St5fz9INTz+x6wcsVVDXTywDjlU8UDrpZN9Y8WBiTSG1aNRm7IZXxOcmEJ7L
CwttJsdhYnN0En/zgzAAAAFGNhcmxAaW1wb3N0b3JlLmxvY2FsAQIDBAUG
-----END OPENSSH PRIVATE KEY-----
"""


class OnOpenState(str, Enum):
    PRE = "pre_on_open"  # as in no "on_open" stuff (disable paging) has been done
    POST = "post_on_open"


class BaseSSHServerSession(asyncssh.SSHServerSession):  # type: ignore
    def __init__(self, collect_data: Dict[str, Any]) -> None:
        """
        SSH Server Session class

        Inherits from asyncssh and provides some extra context/setup for the mock network devices

        Args:
            collect_data: dictionary of the collected data necessary to run a mock server

        Returns:
            None

        Raises:
            N/A

        """
        logger.debug("ssh session initiated")

        self._chan: asyncssh.editor.SSHLineEditorChannel

        self._hide_input = False
        self._interacting = False
        self._interacting_event: Optional[Dict[str, Any]] = None
        self._interact_index = 0
        self._on_open_state = OnOpenState.PRE

        self.collect_data = collect_data

        self._on_open_commands_list = self.collect_data["on_open_inputs"].copy()
        self.current_privilege_level = self.collect_data["initial_privilege_level"]

    def connection_made(self, chan: asyncssh.editor.SSHLineEditorChannel) -> None:
        """
        SSH Connection made!

        Args:
            chan: channel editor object

        Returns:
            None

        Raises:
            N/A

        """
        self._chan = chan

    def shell_requested(self) -> bool:
        """
        Handle shell requested; always return True

        Args:
            N/A

        Returns:
            bool: always True!

        Raises:
            N/A

        """
        return True

    def _return_current_prompt(self) -> str:
        """
        Return the current privilege level prompt

        Args:
            N/A

        Returns:
            str: prompt for current privilege level

        Raises:
            N/A

        """
        privilege_level: str = self.collect_data["privilege_level_prompts"][
            self.current_privilege_level
        ]
        return privilege_level

    def session_started(self) -> None:
        """
        SSH session started

        Initial SSH session started

        Args:
            N/A

        Returns:
            None

        Raises:
            N/A

        """
        self.repaint_prompt()

    def repaint_prompt(self) -> None:
        """
        Paint the prompt to the ssh channel

        Args:
            N/A

        Returns:
            None

        Raises:
            N/A

        """
        logger.debug("writing device prompt")
        self._chan.write(self._return_current_prompt())

    def interactive_event(self, channel_input: str) -> None:
        """
        Handle "interactive" channel input

        Args:
            channel_input: input sent from the user on the channel

        Returns:
            None

        Raises:
            ScrapliReplayServerError: if we get None for self._interacting_data

        """
        if not self._interacting_event:
            raise ScrapliReplayServerError(
                "attempting to handle interactive event but not in interacting mode. this should"
                " never happen, definitely a bug"
            )

        if self._hide_input:
            # un hide input!
            logger.debug("re-enabling channel echo")
            self._chan.set_echo(echo=True)
            self._hide_input = False

        event_step = self._interacting_event["event_steps"][self._interact_index]

        if event_step["hidden_input"]:
            if channel_input != "scrapli":
                # if we have bad auth, basically we'll get stuck here forever... way easier than
                # trying to model/record all the different device types auth failures i think...
                logger.warning("interactive event input is 'hidden' but input is not 'scrapli'")
                self._interact_index -= 1
                event_step = self._interacting_event["event_steps"][self._interact_index]
        elif channel_input != event_step["channel_input"]:
            # bail out and send an invalid input message for the current priv level
            logger.warning("interactive event input does not match recorded event")
            self._interacting = False
            self._interacting_event = None
            self._interact_index = 0
            self.unknown_event()
            return

        self._chan.write(event_step["channel_output"])

        if self._interact_index + 1 == len(self._interacting_event["event_steps"]):
            # this is the last step, reset all the things
            logger.debug("interactive event complete, resetting interacting mode")
            self.current_privilege_level = self._interacting_event["result_privilege_level"]
            self._interacting = False
            self._interacting_event = None
            self._interact_index = 0
            return

        self._interact_index += 1

        if self._interacting_event["event_steps"][self._interact_index]["hidden_input"]:
            # next event is "hidden"... so... hide it...
            logger.debug("next interact event has hidden input, disabling channel echo")
            self._chan.set_echo(echo=False)
            self._hide_input = True

    def standard_event(self, channel_input: str, event: Dict[str, Any]) -> None:
        """
        Handle "normal" command channel input

        Args:
            channel_input: input sent from the user on the channel
            event: the event data for the given input

        Returns:
            None

        Raises:
            N/A

        """
        # i think if one of these is true both should always be... but just in case...
        if event["channel_output"] == "__CLOSES_CONNECTION__" or event["closes_connection"] is True:
            logger.debug("channel input should close connection, closing...")
            # write empty string to bump the connection closed message to a new line like a normal
            # device
            self._chan.write("")
            self.eof_received()
            # reset privilege level and on open state
            self.current_privilege_level = self.collect_data["initial_privilege_level"]
            self._on_open_state = OnOpenState.PRE
            self._on_open_commands_list = self.collect_data["on_open_inputs"].copy()
            return

        self._chan.write(event["channel_output"])
        self.current_privilege_level = event["result_privilege_level"]

        # try to decide if on open things are "done"
        if channel_input in self._on_open_commands_list:
            logger.debug("an 'on open' command was received, popping from on open commands list")
            self._on_open_commands_list.pop(self._on_open_commands_list.index(channel_input))

        if not self._on_open_commands_list:
            logger.debug("an 'on open' commands all executed, setting on open state to 'POST'")
            self._on_open_state = OnOpenState.POST

    def unknown_event(self) -> None:
        """
        Handle unknown channel input

        Args:
            N/A

        Returns:
            None

        Raises:
            N/A

        """
        logger.debug("an unknown event has been initiated")

        event = self.collect_data["unknown_events"][self.current_privilege_level][
            self._on_open_state.value
        ]
        self._chan.write(event["channel_output"])
        if event["closes_connection"] is True:
            logger.debug("channel input should close connection, closing...")
            self.eof_received()
        self.current_privilege_level = event["result_privilege_level"]

    def data_received(self, data: str, datatype: None) -> None:
        """
        Handle data received on ssh channel

        Args:
            data: string of data sent to channel
            datatype: dunno! in base class though :)

        Returns:
            None

        Raises:
            N/A

        """
        _ = datatype
        # in the future we can cutoff the inputs if it is over X width if disable width has not yet
        # been ran -- not needed now but could be cool; if we just send a return, we should NOT
        # strip that!
        channel_input = data if data == "\n" else data.rstrip()

        logger.debug(f"received channel input: '{channel_input}'")

        if self._interacting:
            logger.debug("already in interacting mode, continuing with interact events")
            self.interactive_event(channel_input=channel_input)
            return

        if channel_input == "\n":
            logger.debug("channel input was return, just repaint prompt")
            self.repaint_prompt()
            return

        current_event = self.collect_data["events"][self.current_privilege_level][
            self._on_open_state.value
        ].get(channel_input)

        if current_event:
            if current_event["type"] == "standard":
                logger.debug("standard channel event")
                self.standard_event(channel_input=channel_input, event=current_event)
            else:
                logger.debug("interactive channel event")
                # set to interacting mode, assign the current interactive event
                self._interacting = True
                self._interacting_event = current_event
                self.interactive_event(channel_input=channel_input)
            return

        logger.debug("unknown channel event")
        self.unknown_event()

    def eof_received(self) -> None:
        """
        Handle eof

        Args:
            N/A

        Returns:
            None

        Raises:
            N/A

        """
        self._chan.exit(0)

    def break_received(self, msec: float) -> None:
        """
        Handle break

        Args:
            msec: dunno, but in base class implementation :)

        Returns:
            None

        Raises:
            N/A

        """
        self.eof_received()


class BaseServer(asyncssh.SSHServer):  # type: ignore
    def __init__(self, session: Type[asyncssh.SSHServerSession], collect_data: str):
        self.session = session

        with open(collect_data, "r") as f:
            self.collect_data = safe_load(f)

    def session_requested(self) -> asyncssh.SSHServerSession:
        """
        Session requested; return ServerSession object

        `ServerSession` set in `run` to be the appropriate SSHServerSession type for a given
        platform, i.e. `IOSXESSHServerSession`

        Args:
            N/A

        Returns:
            asyncssh.SSHServerSession: SSHServerSession

        Raises:
            N/A

        """
        return self.session(collect_data=self.collect_data)

    def begin_auth(self, username: str) -> bool:
        """
        Begin auth; always returns True

        Args:
            username: username for auth

        Returns:
            bool: always True

        Raises:
            N/A

        """
        return True

    def password_auth_supported(self) -> bool:
        """
        Password auth supported; always return True

        Args:
            N/A

        Returns:
            bool: always True

        Raises:
            N/A

        """
        return True

    def public_key_auth_supported(self) -> bool:
        """
        Public key auth supported; always return True

        Args:
            N/A

        Returns:
            bool: always True

        Raises:
            N/A

        """
        return True

    def validate_password(self, username: str, password: str) -> bool:
        """
        Validate provided username/password

        Args:
            username: username to check for auth
            password: password to check for auth

        Returns:
            bool: True if user/password is correct (scrapli/scrapli)

        Raises:
            N/A

        """
        if username == password == "scrapli":
            return True
        return False

    def validate_public_key(
        self, username: str, key: asyncssh.rsa._RSAKey  # pylint: disable=W0212
    ) -> bool:
        """
        Validate provided public key

        Args:
            username: username to check for auth
            key: asyncssh RSAKey to check for auth

        Returns:
            bool: True if ssh key is correct

        Raises:
            N/A

        """
        if (
            username == "scrapli"
            and key.get_fingerprint() == "SHA256:rb1CVtQCkWBAzm1AxV7xR7BLBawUwFUlUVFVu+QYQBM"
        ):
            return True
        return False


async def start(port: int = 2222, collect_data: str = "scrapli_replay.yaml") -> None:
    """
    Temporary run server entrypoint

    Args:
        port: port to run the instance on
        collect_data: string path/name to collect data yaml file

    Returns:
        None

    Raises:
        N/A

    """

    def server_factory() -> asyncssh.SSHServer:
        server = BaseServer(session=BaseSSHServerSession, collect_data=collect_data)
        return server

    await asyncssh.create_server(
        server_factory,
        "localhost",
        port,
        server_host_keys=[BASE_SERVER_KEY],
    )


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start())
    loop.run_forever()
