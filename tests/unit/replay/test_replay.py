import sys
from io import BytesIO
from pathlib import Path

import pytest
from ruamel.yaml import safe_load  # type: ignore

from scrapli_replay.exceptions import ScrapliReplayException
from scrapli_replay.replay.replay import (
    ConnectionProfile,
    ReplayMode,
    ScrapliReplay,
    ScrapliReplayInstance,
)


def test_scrapli_replay_basic():
    replay = ScrapliReplay(session_name="test1", replay_mode="record")
    assert replay.session_directory == Path.cwd()
    assert replay.session_name == "test1"
    # even though we said record replay mode should be record since there is no session saved
    assert replay.replay_mode == ReplayMode.RECORD
    assert replay.replay_session == {}
    assert replay.wrapped_instances == {}
    assert replay._patched_open is None


@pytest.mark.skipif(sys.version_info > (3, 9), reason="skipping pending pyfakefs 3.10 support")
def test_scrapli_replay_existing_session(fs):
    fs.create_file(
        f"{Path.cwd()}/test1.yaml",
        contents="---\nsomesession:\n  interactions:\n  - something",
    )
    # set replay mode to record, but will end up as replay as session exists!
    # pyfakefs does not like additional slashes in path it seems... so just set it to empty string
    replay = ScrapliReplay(session_directory="", session_name="test1", replay_mode="record")
    assert str(replay.session_directory) == "."
    assert replay.session_name == "test1"
    assert replay.replay_mode == ReplayMode.REPLAY
    assert replay.replay_session == {"somesession": {"interactions": ["something"]}}
    assert replay.wrapped_instances == {}
    assert replay._patched_open is None


def test_scrapli_replay_invalid_replay_mode():
    with pytest.raises(ScrapliReplayException):
        ScrapliReplay(session_name="test1", replay_mode="blah")


@pytest.mark.skipif(sys.version_info > (3, 9), reason="skipping pending pyfakefs 3.10 support")
def test_session_exists(fs):
    fs.create_file(
        f"{Path.cwd()}/test1.yaml",
        contents="---\nsomesession:\n  interactions:\n  - something",
    )
    replay = ScrapliReplay(session_directory="", session_name="test1", replay_mode="record")
    assert replay._session_exists() is True
    fs.remove_object(f"{Path.cwd()}test1.yaml")
    assert replay._session_exists() is False


def test_record_session_profile(scrapli_conn):
    replay = ScrapliReplay(session_name="test1", replay_mode="record")
    conn_profile = replay.create_connection_profile(scrapli_conn=scrapli_conn)
    assert conn_profile.host == "localhost"
    assert conn_profile.port == 22
    assert conn_profile.auth_username == ""
    assert conn_profile.auth_password is False
    assert conn_profile.auth_private_key == ""
    assert conn_profile.auth_private_key_passphrase is False
    assert conn_profile.auth_bypass is False
    assert conn_profile.transport == "system"


def test_common_replay_mode():
    connection_profile = {
        "host": "c3560",
        "port": 22,
        "auth_username": "vrnetlab",
        "auth_password": True,
        "auth_private_key": "",
        "auth_private_key_passphrase": False,
        "auth_bypass": False,
        "transport": "asyncssh",
        "auth_secondary": False,
    }
    replay = ScrapliReplayInstance(
        replay_mode=ReplayMode.RECORD, connection_profile=ConnectionProfile(**connection_profile)
    )

    replay.replay_session = {}
    replay.replay_session["connection_profile"] = connection_profile

    replay.replay_session["interactions"] = [
        {
            "channel_output": "",
            "expected_channel_input": "\n",
            "expected_channel_input_redacted": False,
        },
        {
            "channel_output": "C3560CX#",
            "expected_channel_input": "terminal length 0",
            "expected_channel_input_redacted": False,
        },
    ]

    replay.connection_profile = ConnectionProfile(**connection_profile)
    actual_device_outputs, actual_scrapli_inputs = replay._common_replay_mode()

    actual_device_outputs = list(actual_device_outputs)
    actual_scrapli_inputs = list(actual_scrapli_inputs)

    assert actual_device_outputs == ["", "C3560CX#"]
    assert actual_scrapli_inputs == [("\n", False), ("terminal length 0", False)]


def test_common_replay_mode_exception():
    connection_profile = {
        "host": "c3560",
        "port": 22,
        "auth_username": "vrnetlab",
        "auth_password": True,
        "auth_private_key": "",
        "auth_private_key_passphrase": False,
        "auth_bypass": False,
        "transport": "asyncssh",
        "auth_secondary": False,
    }
    replay = ScrapliReplayInstance(
        replay_mode=ReplayMode.RECORD, connection_profile=ConnectionProfile(**connection_profile)
    )

    replay._wrapped_connection_profile = ConnectionProfile(**connection_profile)
    replay.replay_session["connection_profile"] = connection_profile
    replay.replay_session["connection_profile"]["host"] = "blah"

    with pytest.raises(ScrapliReplayException):
        replay._common_replay_mode()


async def test_setup_async_replay_mode(monkeypatch, scrapli_conn):
    device_outputs = iter(["", "C3560CX#"])
    scrapli_inputs = iter([("\n", False), ("terminal length 0", False)])

    def _common_replay_mode(cls):
        return device_outputs, scrapli_inputs

    monkeypatch.setattr(
        "scrapli_replay.replay.replay.ScrapliReplayInstance._common_replay_mode",
        _common_replay_mode,
    )

    connection_profile = {
        "host": "c3560",
        "port": 22,
        "auth_username": "vrnetlab",
        "auth_password": True,
        "auth_private_key": "",
        "auth_private_key_passphrase": False,
        "auth_bypass": False,
        "transport": "asyncssh",
        "auth_secondary": False,
    }
    replay = ScrapliReplayInstance(
        replay_mode=ReplayMode.RECORD, connection_profile=ConnectionProfile(**connection_profile)
    )
    replay.setup_async_replay_mode(scrapli_conn=scrapli_conn)

    # read off the channel, asserts we got the correct async method patched ++ we are returning
    # what we expect
    assert await scrapli_conn.channel.read() == b""
    assert await scrapli_conn.channel.read() == b"C3560CX#"

    # we're out of stuff to read back, we should be having a bad day here
    with pytest.raises(ScrapliReplayException):
        await scrapli_conn.channel.read()


def test_setup_replay_mode(monkeypatch, scrapli_conn):
    device_outputs = iter(["", "C3560CX#"])
    scrapli_inputs = iter([("\n", False), ("terminal length 0", False)])

    def _common_replay_mode(cls):
        return device_outputs, scrapli_inputs

    monkeypatch.setattr(
        "scrapli_replay.replay.replay.ScrapliReplayInstance._common_replay_mode",
        _common_replay_mode,
    )

    connection_profile = {
        "host": "c3560",
        "port": 22,
        "auth_username": "vrnetlab",
        "auth_password": True,
        "auth_private_key": "",
        "auth_private_key_passphrase": False,
        "auth_bypass": False,
        "transport": "asyncssh",
        "auth_secondary": False,
    }
    replay = ScrapliReplayInstance(
        replay_mode=ReplayMode.RECORD, connection_profile=ConnectionProfile(**connection_profile)
    )
    replay.setup_replay_mode(scrapli_conn=scrapli_conn)

    # read off the channel, asserts we got the correct async method patched ++ we are returning
    # what we expect
    assert scrapli_conn.channel.read() == b""
    assert scrapli_conn.channel.read() == b"C3560CX#"

    # we're out of stuff to read back, we should be having a bad day here
    with pytest.raises(ScrapliReplayException):
        scrapli_conn.channel.read()


def test_serialize():
    connection_profile = {
        "host": "c3560",
        "port": 22,
        "auth_username": "vrnetlab",
        "auth_password": True,
        "auth_private_key": "",
        "auth_private_key_passphrase": False,
        "auth_bypass": False,
        "transport": "asyncssh",
        "auth_secondary": False,
    }
    replay = ScrapliReplayInstance(
        replay_mode=ReplayMode.RECORD, connection_profile=ConnectionProfile(**connection_profile)
    )

    replay.read_log = BytesIO(
        b"Warning: Permanently added 'c3560,172.31.254.1' (RSA) to the list of known hosts.\nPassword: "
        b"\n\nC3560CX#\nC3560CX#terminal length 0\nC3560CX#terminal width 512\nC3560CX#show run | i "
        b"hostname\nhostname C3560CX\nC3560CX#\nC3560CX#"
    )
    replay.write_log = [
        ("VR-netlab9", True, 92),
        ("\n", False, 92),
        ("\n", False, 102),
        ("terminal length 0", False, 111),
        ("\n", False, 128),
        ("terminal width 512", False, 137),
        ("\n", False, 155),
        ("show run | i hostname", False, 164),
        ("\n", False, 185),
        ("\n", False, 211),
        ("exit", False, 220),
        ("\n", False, 220),
    ]

    replay_wrapper = ScrapliReplay()
    replay_wrapper.wrapped_instances["fakesession"] = replay
    actual_replay_session = replay_wrapper._serialize()

    assert actual_replay_session == {
        "fakesession": {
            "connection_profile": {
                "host": "c3560",
                "port": 22,
                "auth_username": "vrnetlab",
                "auth_password": True,
                "auth_private_key": "",
                "auth_private_key_passphrase": False,
                "auth_bypass": False,
                "transport": "asyncssh",
                "auth_secondary": False,
            },
            "interactions": [
                {
                    "channel_output": "Warning: Permanently added 'c3560,172.31.254.1' (RSA) to the list of known hosts.\nPassword: ",
                    "expected_channel_input": "REDACTED",
                    "expected_channel_input_redacted": True,
                },
                {
                    "channel_output": "",
                    "expected_channel_input": "\n",
                    "expected_channel_input_redacted": False,
                },
                {
                    "channel_output": "\n\nC3560CX#",
                    "expected_channel_input": "\n",
                    "expected_channel_input_redacted": False,
                },
                {
                    "channel_output": "\nC3560CX#",
                    "expected_channel_input": "terminal length 0",
                    "expected_channel_input_redacted": False,
                },
                {
                    "channel_output": "terminal length 0",
                    "expected_channel_input": "\n",
                    "expected_channel_input_redacted": False,
                },
                {
                    "channel_output": "\nC3560CX#",
                    "expected_channel_input": "terminal width 512",
                    "expected_channel_input_redacted": False,
                },
                {
                    "channel_output": "terminal width 512",
                    "expected_channel_input": "\n",
                    "expected_channel_input_redacted": False,
                },
                {
                    "channel_output": "\nC3560CX#",
                    "expected_channel_input": "show run | i hostname",
                    "expected_channel_input_redacted": False,
                },
                {
                    "channel_output": "show run | i hostname",
                    "expected_channel_input": "\n",
                    "expected_channel_input_redacted": False,
                },
                {
                    "channel_output": "\nhostname C3560CX\nC3560CX#",
                    "expected_channel_input": "\n",
                    "expected_channel_input_redacted": False,
                },
                {
                    "channel_output": "\nC3560CX#",
                    "expected_channel_input": "exit",
                    "expected_channel_input_redacted": False,
                },
                {
                    "channel_output": "",
                    "expected_channel_input": "\n",
                    "expected_channel_input_redacted": False,
                },
                {
                    "channel_output": "",
                    "expected_channel_input": None,
                    "expected_channel_input_redacted": False,
                },
            ],
        }
    }


@pytest.mark.skipif(sys.version_info > (3, 9), reason="skipping pending pyfakefs 3.10 support")
def test_save(fs):
    connection_profile = {
        "host": "c3560",
        "port": 22,
        "auth_username": "vrnetlab",
        "auth_password": True,
        "auth_private_key": "",
        "auth_private_key_passphrase": False,
        "auth_bypass": False,
        "transport": "asyncssh",
        "auth_secondary": False,
    }
    replay = ScrapliReplayInstance(
        replay_mode=ReplayMode.RECORD, connection_profile=ConnectionProfile(**connection_profile)
    )

    replay._wrapped_connection_profile = ConnectionProfile(**connection_profile)
    replay.read_log = BytesIO(
        b"Warning: Permanently added 'c3560,172.31.254.1' (RSA) to the list of known hosts.\nPassword: "
        b"\n\nC3560CX#\nC3560CX#"
    )
    replay.write_log = [
        ("VR-netlab9", True, 92),
        ("\n", False, 92),
        ("\n", False, 102),
    ]

    replay_wrapper = ScrapliReplay(session_directory="", session_name="test1", replay_mode="record")
    replay_wrapper.wrapped_instances["fakesession"] = replay
    replay_wrapper._save()

    with open(f"./test1.yaml", "r") as f:
        loaded = safe_load(f)
        assert loaded == {
            "fakesession": {
                "connection_profile": {
                    "host": "c3560",
                    "port": 22,
                    "auth_username": "vrnetlab",
                    "auth_password": True,
                    "auth_private_key": "",
                    "auth_private_key_passphrase": False,
                    "auth_bypass": False,
                    "transport": "asyncssh",
                    "auth_secondary": False,
                },
                "interactions": [
                    {
                        "channel_output": "Warning: Permanently added 'c3560,172.31.254.1' (RSA) to the list of known hosts.\nPassword: ",
                        "expected_channel_input": "REDACTED",
                        "expected_channel_input_redacted": True,
                    },
                    {
                        "channel_output": "",
                        "expected_channel_input": "\n",
                        "expected_channel_input_redacted": False,
                    },
                    {
                        "channel_output": "\n\nC3560CX#",
                        "expected_channel_input": "\n",
                        "expected_channel_input_redacted": False,
                    },
                    {
                        "channel_output": "\nC3560CX#",
                        "expected_channel_input": None,
                        "expected_channel_input_redacted": False,
                    },
                ],
            }
        }
