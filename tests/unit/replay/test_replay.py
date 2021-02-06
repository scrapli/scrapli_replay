from io import BytesIO
from pathlib import Path

import pytest

from scrapli_replay.exceptions import ScrapliReplayException
from scrapli_replay.replay.replay import ConnectionProfile, ReplayMode, ScrapliReplay


def test_scrapli_replay_basic():
    replay = ScrapliReplay(session_name="test1", replay_mode="record")
    assert replay.session_directory == Path.cwd()
    assert replay.session_name == "test1"
    # even though we said record replay mode should be record since there is no session saved
    assert replay.replay_mode == ReplayMode.RECORD
    assert replay.replay_session == {}
    assert isinstance(replay._read_log, BytesIO)
    assert replay._write_log == []
    assert replay._patched_open is None
    assert replay._wrapped_connection_profile is None


def test_scrapli_replay_existing_session(fs):
    fs.create_file(f"{Path.cwd()}/test1.yaml", contents="---\nsomekey: somevalue\n")
    # set replay mode to record, but will end up as replay as session exists!
    # pyfakefs does not like additional slashes in path it seems... so just set it to empty string
    replay = ScrapliReplay(session_directory="", session_name="test1", replay_mode="record")
    assert str(replay.session_directory) == "."
    assert replay.session_name == "test1"
    assert replay.replay_mode == ReplayMode.REPLAY
    assert replay.replay_session == {"somekey": "somevalue"}
    assert isinstance(replay._read_log, BytesIO)
    assert replay._write_log == []
    assert replay._patched_open is None
    assert replay._wrapped_connection_profile is None


def test_scrapli_replay_invalid_replay_mode():
    with pytest.raises(ScrapliReplayException):
        ScrapliReplay(session_name="test1", replay_mode="blah")


def test_session_exists(fs):
    fs.create_file(f"{Path.cwd()}test1.yaml", contents="---\nsomekey: somevalue\n")
    replay = ScrapliReplay(session_directory="", session_name="test1", replay_mode="record")
    assert replay._session_exists() is True
    fs.remove_object(f"{Path.cwd()}test1.yaml")
    assert replay._session_exists() is False


def test_record_session_profile(scrapli_conn):
    replay = ScrapliReplay(session_name="test1", replay_mode="record")
    replay._record_connection_profile(scrapli_conn=scrapli_conn)
    assert replay._wrapped_connection_profile.host == "localhost"
    assert replay._wrapped_connection_profile.port == 22
    assert replay._wrapped_connection_profile.auth_username == ""
    assert replay._wrapped_connection_profile.auth_password is False
    assert replay._wrapped_connection_profile.auth_private_key == ""
    assert replay._wrapped_connection_profile.auth_private_key_passphrase is False
    assert replay._wrapped_connection_profile.auth_bypass is False
    assert replay._wrapped_connection_profile.transport == "system"


def test_common_replay_mode():
    replay = ScrapliReplay(session_name="test1", replay_mode="record")
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

    replay._wrapped_connection_profile = ConnectionProfile(**connection_profile)
    actual_device_outputs, actual_scrapli_inputs = replay._common_replay_mode()

    actual_device_outputs = list(actual_device_outputs)
    actual_scrapli_inputs = list(actual_scrapli_inputs)

    assert actual_device_outputs == ["", "C3560CX#"]
    assert actual_scrapli_inputs == [("\n", False), ("terminal length 0", False)]


def test_common_replay_mode_exception():
    replay = ScrapliReplay(session_name="test1", replay_mode="record")

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
    replay._wrapped_connection_profile = ConnectionProfile(**connection_profile)
    replay.replay_session["connection_profile"] = connection_profile
    replay.replay_session["connection_profile"]["host"] = "blah"

    with pytest.raises(ScrapliReplayException):
        replay._common_replay_mode()
