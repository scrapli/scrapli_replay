from io import StringIO

import pytest
from asyncssh.editor import SSHLineEditorChannel

from scrapli_replay.exceptions import ScrapliReplayException
from scrapli_replay.server.server import OnOpenState


def test_base_server_session(basic_server):
    # make sure our default internal flags dont get buggered up
    assert basic_server._hide_input is False
    assert basic_server._interacting is False
    assert basic_server._interacting_event is None
    assert basic_server._interact_index == 0
    assert basic_server._on_open_state == OnOpenState.PRE
    assert basic_server._on_open_commands_list == ["openstuff"]
    assert basic_server.current_privilege_level == "veryprivvy"


def test_connection_made(basic_server):
    chan = SSHLineEditorChannel("", "", "", "")
    basic_server.connection_made(chan)
    assert basic_server._chan is chan


def test_shell_requested(basic_server):
    assert basic_server.shell_requested() is True


def test_return_current_prompt(basic_server):
    assert basic_server._return_current_prompt() == "veryprivvyprompt"


def test_session_started(basic_server):
    basic_server._chan = StringIO()
    basic_server.session_started()
    basic_server._chan.seek(0)
    assert basic_server._chan.read() == "veryprivvyprompt"


def test_repaint_prompt(basic_server):
    basic_server._chan = StringIO()
    basic_server.repaint_prompt()
    basic_server._chan.seek(0)
    assert basic_server._chan.read() == "veryprivvyprompt"


def test_interactive_event_no_interactive_event(basic_server):
    with pytest.raises(ScrapliReplayException):
        basic_server.interactive_event(channel_input="blah")


def test_interactive_event(monkeypatch, basic_server):
    basic_server._chan = SSHLineEditorChannel("", "", "", "")
    basic_server._chan.set_echo = lambda echo: None
    chan = StringIO()

    def dummy_write(cls, data):
        nonlocal chan
        chan.write(data)

    monkeypatch.setattr("asyncssh.editor.SSHLineEditorChannel.write", dummy_write)

    basic_server.collect_data = {
        "unknown_events": {
            "veryprivvy": {
                "pre_on_open": {
                    "channel_output": "bad stuff",
                    "closes_connection": False,
                    "result_privilege_level": "veryprivvy",
                }
            }
        }
    }
    interact_event = {
        "result_privilege_level": "privilege_exec",
        "event_steps": [
            {
                "channel_input": "blah",
                "channel_output": "blahblahblah",
                "hidden_input": False,
                "returns_prompt": True,
            },
            {
                "channel_input": "scrapli",
                "channel_output": "blah2blah2blah2",
                "hidden_input": True,
                "returns_prompt": True,
            },
            {
                "channel_input": "blah",
                "channel_output": "blah2blah2blah2",
                "hidden_input": True,
                "returns_prompt": True,
            },
            {
                "channel_input": "blah",
                "channel_output": "blah2blah2blah2",
                "hidden_input": False,
                "returns_prompt": True,
            },
        ],
    }
    basic_server._interacting_event = interact_event

    # setting this as it normally gets set in the "data_received" method
    basic_server._interacting = True
    basic_server.interactive_event(channel_input="blah")

    assert basic_server._interact_index == 1
    assert basic_server._hide_input is True
    chan.seek(0)
    assert chan.read() == "blahblahblah"

    basic_server.interactive_event(channel_input="scrapli")
    assert basic_server._interact_index == 2
    assert basic_server._hide_input is True
    chan.seek(0)
    assert chan.read() == "blahblahblahblah2blah2blah2"

    basic_server.interactive_event(channel_input="blah")
    # hidden input true, but we didnt send the password (scrapli) so we are stuck at this stage
    assert basic_server._interact_index == 2
    assert basic_server._hide_input is True

    # set the interact event index up so we can hit the last event and test that we return an
    # unknown event
    basic_server._interact_index = 3
    basic_server.interactive_event(channel_input="NOTblah")

    assert basic_server._interact_index == 0
    assert basic_server._hide_input is False
    chan.seek(0)
    assert chan.read() == "blahblahblahblah2blah2blah2blah2blah2blah2bad stuff"

    # setting back to interacting mode to test the hitting the last interact step
    basic_server._interacting = True
    basic_server._interacting_event = interact_event

    basic_server._interact_index = 3
    basic_server.interactive_event(channel_input="blah")
    assert basic_server._interact_index == 0
    assert basic_server._hide_input is False
    chan.seek(0)
    assert chan.read() == "blahblahblahblah2blah2blah2blah2blah2blah2bad stuffblah2blah2blah2"


def test_standard_event_closes_connection(basic_server):
    basic_server._chan = StringIO()
    basic_server.eof_received = lambda: None
    basic_server._on_open_state = OnOpenState.POST
    basic_server.current_privilege_level = "taco"

    basic_server.standard_event(
        channel_input="exit", event={"channel_output": "__CLOSES_CONNECTION__"}
    )

    assert basic_server.current_privilege_level == "veryprivvy"
    assert basic_server._on_open_state == OnOpenState.PRE
    basic_server._chan.seek(0)
    # we write an empty line to make it look like normal devices do
    assert basic_server._chan.read() == ""


def test_standard_event(basic_server):
    basic_server._chan = StringIO()
    basic_server._on_open_state = OnOpenState.PRE
    basic_server.current_privilege_level = "taco"

    basic_server.standard_event(
        channel_input="openstuff",
        event={
            "channel_output": "stuff",
            "result_privilege_level": "veryprivvy",
            "closes_connection": False,
        },
    )

    # assert we got all the on open stuff set to post and the on open commands is empty now
    assert basic_server.current_privilege_level == "veryprivvy"
    assert basic_server._on_open_state == OnOpenState.POST
    basic_server._chan.seek(0)
    assert basic_server._chan.read() == "stuff"
    assert basic_server._on_open_commands_list == []


def test_data_received_interacting(monkeypatch, basic_server):
    dispatched_to_interactive_event = False

    def dummy_interactive_event(cls, channel_input):
        nonlocal dispatched_to_interactive_event
        dispatched_to_interactive_event = True

    monkeypatch.setattr(
        "scrapli_replay.server.server.BaseSSHServerSession.interactive_event",
        dummy_interactive_event,
    )

    basic_server._interacting = True
    basic_server.data_received(data="something", datatype=None)
    assert dispatched_to_interactive_event is True


def test_data_received_return(monkeypatch, basic_server):
    dispatched_to_repaint_prompt = False

    def dummy_repaint_prompt(cls):
        nonlocal dispatched_to_repaint_prompt
        dispatched_to_repaint_prompt = True

    monkeypatch.setattr(
        "scrapli_replay.server.server.BaseSSHServerSession.repaint_prompt", dummy_repaint_prompt
    )

    basic_server.data_received(data="\n", datatype=None)
    assert dispatched_to_repaint_prompt is True


def test_data_received_standard_event(monkeypatch, basic_server):
    dispatched_to_standard_event = False

    def dummy_standard_event(cls, channel_input, event):
        nonlocal dispatched_to_standard_event
        dispatched_to_standard_event = True

    monkeypatch.setattr(
        "scrapli_replay.server.server.BaseSSHServerSession.standard_event", dummy_standard_event
    )

    basic_server.collect_data = {
        "events": {
            "veryprivvy": {
                "pre_on_open": {
                    "blah": {
                        "channel_output": "someswitchoutput",
                        "result_privilege_level": "newpriv",
                        "returns_prompt": True,
                        "closes_connection": False,
                        "type": "standard",
                    }
                }
            }
        }
    }

    basic_server.data_received(data="blah", datatype=None)
    assert dispatched_to_standard_event is True


def test_data_received_interact_event(monkeypatch, basic_server):
    dispatched_to_interact_event = False

    def dummy_interactive_event(cls, channel_input):
        nonlocal dispatched_to_interact_event
        dispatched_to_interact_event = True

    monkeypatch.setattr(
        "scrapli_replay.server.server.BaseSSHServerSession.interactive_event",
        dummy_interactive_event,
    )

    basic_server.collect_data = {
        "events": {
            "veryprivvy": {
                "pre_on_open": {
                    "blah": {
                        "result_privilege_level": "privilege_exec",
                        "event_steps": [
                            {
                                "channel_input": "enable",
                                "channel_output": "Password: ",
                                "hidden_input": False,
                                "returns_prompt": True,
                            }
                        ],
                        "type": "interact",
                    }
                }
            }
        }
    }

    basic_server.data_received(data="blah", datatype=None)
    assert dispatched_to_interact_event is True


def test_data_received_unknown_event(monkeypatch, basic_server):
    dispatched_to_unknown_event = False

    def dummy_unknown_event(cls):
        nonlocal dispatched_to_unknown_event
        dispatched_to_unknown_event = True

    monkeypatch.setattr(
        "scrapli_replay.server.server.BaseSSHServerSession.unknown_event",
        dummy_unknown_event,
    )

    basic_server.collect_data = {
        "events": {"veryprivvy": {"pre_on_open": {}}},
        "unknown_events": {
            "veryprivvy": {
                "pre_on_open": {
                    "channel_output": "bad stuff",
                    "closes_connection": False,
                    "result_privilege_level": "veryprivvy",
                }
            }
        },
    }

    basic_server.data_received(data="blah", datatype=None)
    assert dispatched_to_unknown_event is True
