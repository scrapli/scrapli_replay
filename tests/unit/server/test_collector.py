import logging
from io import BytesIO

import pytest

from scrapli.driver.core.cisco_iosxe.sync_driver import IOSXEDriver
from scrapli.exceptions import ScrapliConnectionError
from scrapli_replay.exceptions import ScrapliReplayException
from scrapli_replay.server.collector import (
    InteractiveEvent,
    InteractStep,
    ScrapliCollector,
    ScrapliCollectorChannel,
    StandardEvent,
)


def test_collector_instantiation(scrapli_conn):
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

    assert collector.channel_inputs == channel_inputs
    assert collector.interact_events == interact_events
    assert collector.paging_indicator == paging_indicator
    assert collector.paging_escape_string == paging_escape_string

    assert isinstance(collector.channel_log, BytesIO)

    assert collector.scrapli_connection == scrapli_conn
    assert (
        collector.scrapli_connection.channel._base_channel_args.channel_log == collector.channel_log
    )
    assert isinstance(collector.scrapli_connection.channel, ScrapliCollectorChannel)

    # using iosxe driver, hence these assertions; asserting we get the appropriate values out of the
    # scrapli connection, also that we patch the on open/close methods with None
    assert collector.scrapli_connection_default_desired_privilege_level == "privilege_exec"
    assert collector.scrapli_connection_standard_on_open.__name__ == "iosxe_on_open"
    assert collector.scrapli_connection_standard_on_close.__name__ == "iosxe_on_close"
    assert collector.scrapli_connection.on_open is None
    assert collector.scrapli_connection.on_close is None

    # make sure we didnt somehow screw up the defaults of things
    assert collector.on_open_enabled is False
    assert collector.on_open_inputs == []
    assert collector.on_close_inputs == []
    assert collector.collected_priv_prompts is False

    # assert the privilege patterns all get figured out and set
    assert collector._privilege_escalate_inputs == ["configure terminal", "tclsh"]
    assert collector._privilege_deescalate_inputs == ["disable", "end", "tclquit"]
    assert collector._interact_privilege_escalations == [
        [
            ("enable", "^(?:enable\\s){0,1}password:\\s?$", False),
            ("__AUTH_SECONDARY__", "^((?!tcl)[a-z0-9.\\-_@/:]){1,63}#$", True),
        ]
    ]

    # check to make sure we start off the all expected patterns with the paging indicator
    assert collector.all_expected_patterns == ["--More--"]


def test_collector_instantiation_no_scrapli_conn(caplog):
    caplog.set_level(logging.DEBUG, logger="scrapli.channel")

    channel_inputs = ["some input"]
    interact_events = [[("some input", "some pattern", False)]]
    paging_indicator = "--More--"
    paging_escape_string = "non-standard"

    collector = ScrapliCollector(
        channel_inputs=channel_inputs,
        interact_events=interact_events,
        paging_indicator=paging_indicator,
        paging_escape_string=paging_escape_string,
        host="localhost",
        platform="cisco_iosxe",
        channel_log="something",  # passing to make sure we warn user that this will be ignored
    )

    assert isinstance(collector.scrapli_connection, IOSXEDriver)

    # only care to validate that the user warning log record is correct/good
    channel_log_log_record = caplog.records[0]
    assert (
        "channel_log arg provided, replacing with ScrapliCollector channel_log"
        in channel_log_log_record.msg
    )
    assert logging.WARNING == channel_log_log_record.levelno


def test_collector_instantiation_no_scrapli_conn_no_platform():
    channel_inputs = ["some input"]
    interact_events = [[("some input", "some pattern", False)]]
    paging_indicator = "--More--"
    paging_escape_string = "non-standard"

    with pytest.raises(ScrapliReplayException) as exc:
        ScrapliCollector(
            channel_inputs=channel_inputs,
            interact_events=interact_events,
            paging_indicator=paging_indicator,
            paging_escape_string=paging_escape_string,
            host="localhost",
        )

    assert (
        str(exc.value)
        == "must provide 'platform' as a kwarg if you dont provide a connection object!"
    )


def test_open(monkeypatch, basic_collector):
    monkeypatch.setattr("scrapli.driver.base.sync_driver.Driver.open", lambda _: None)
    monkeypatch.setattr("scrapli.channel.sync_channel.Channel.get_prompt", lambda _: "c3560cx#")

    assert basic_collector.initial_privilege_level == ""
    basic_collector.open()
    assert basic_collector.initial_privilege_level == "privilege_exec"


def test_close(monkeypatch, basic_collector):
    # not testing much really... but in the future we may do other "stuff" at close of collector,
    # so just sketching this out for now
    monkeypatch.setattr("scrapli.driver.base.sync_driver.Driver.close", lambda _: None)

    basic_collector.close()


def test_collect_privilege_prompts(monkeypatch, basic_collector):
    monkeypatch.setattr("scrapli.driver.base.sync_driver.Driver.open", lambda _: None)
    monkeypatch.setattr("scrapli.channel.sync_channel.Channel.get_prompt", lambda _: "c3560cx#")
    basic_collector.open()

    # we can expect scrapli to behave so we just want to test the logic here... so we'll just make
    # the base collector have one prompt so our testing is easier here... lazy? perhaps!
    basic_collector.privilege_level_prompts = {"privilege_exec": ""}
    basic_collector._collect_privilege_prompts()
    assert basic_collector.privilege_level_prompts == {"privilege_exec": "c3560cx#"}


def test_extend_all_expected_prompts(basic_collector):
    basic_collector.collected_priv_prompts = True
    basic_collector.privilege_level_prompts = {"privilege_exec": "c3560cx#"}

    basic_collector._extend_all_expected_prompts()

    assert basic_collector.all_expected_patterns == ["--More--", "c3560cx#"]


def test_extend_all_expected_prompts_exception(basic_collector):
    with pytest.raises(ScrapliReplayException):
        basic_collector._extend_all_expected_prompts()


@pytest.mark.parametrize(
    "test_data",
    (
        ("\nsomething", "something"),
        ("\n\n\nsomething", "\n\nsomething"),
        ("something", "something"),
    ),
    ids=(
        "single_newline",
        "many_newline",
        "noline",
    ),
)
def test_strip_leading_newline(basic_collector, test_data):
    _input, expected = test_data
    assert basic_collector._strip_leading_newline(channel_output=_input) == expected


def test_collect_on_open_inputs(monkeypatch, basic_collector):
    monkeypatch.setattr(
        "scrapli.driver.network.sync_driver.NetworkDriver.acquire_priv",
        lambda cls, target_priv: None,
    )
    monkeypatch.setattr(
        "scrapli.channel.sync_channel.Channel.write", lambda cls, channel_input, redacted: None
    )

    def dummy_on_open(cls):
        cls.channel.write("something")
        cls.channel.send_return()

    basic_collector.scrapli_connection_standard_on_open = dummy_on_open

    basic_collector._collect_on_open_inputs()
    assert basic_collector.on_open_inputs == ["something"]


def test_collect_on_close_inputs(monkeypatch, basic_collector):
    # patching open too as we expect things to close... so we try to reopen of course
    monkeypatch.setattr("scrapli.driver.base.sync_driver.Driver.open", lambda _: None)
    monkeypatch.setattr(
        "scrapli.driver.network.sync_driver.NetworkDriver.acquire_priv",
        lambda cls, target_priv: None,
    )
    monkeypatch.setattr(
        "scrapli.channel.sync_channel.Channel.write", lambda cls, channel_input, redacted: None
    )

    def dummy_get_prompt(cls):
        raise ScrapliConnectionError

    monkeypatch.setattr("scrapli.channel.sync_channel.Channel.get_prompt", dummy_get_prompt)

    def dummy_on_close(cls):
        cls.channel.write("something")
        cls.channel.send_return()

    # set the initial priv level so the open after the exception doesnt try to get prompt again
    basic_collector.initial_privilege_level = "privilege_exec"
    basic_collector.scrapli_connection_standard_on_close = dummy_on_close

    basic_collector._collect_on_close_inputs()
    assert basic_collector.on_close_inputs == ["something"]


@pytest.mark.parametrize(
    "test_data",
    (False, True),
    ids=(
        "pre_open",
        "post_open",
    ),
)
def test_collect_standard_event(monkeypatch, test_data, basic_collector):
    # lots of patching here... basically we know the individual components work so we really just
    # want to make sure the overall flow does what we think it should...

    basic_collector.on_open_enabled = test_data
    on_open_enabled_key = "post_on_open" if basic_collector.on_open_enabled else "pre_on_open"

    # patch acquire priv so we are just always in the right priv
    monkeypatch.setattr(
        "scrapli.driver.network.sync_driver.NetworkDriver.acquire_priv",
        lambda cls, target_priv: None,
    )

    # patch get prompt because we will check to see what the resulting prompt is for each command
    monkeypatch.setattr("scrapli.channel.sync_channel.Channel.get_prompt", lambda _: "c3560cx#")

    # patch send input and read because we are obviously sending something and reading the output!
    def dummy_send_input_and_read(cls, channel_input, expected_outputs, read_duration=0):
        return b"raw output", b"output"

    monkeypatch.setattr(
        "scrapli.channel.sync_channel.Channel.send_input_and_read", dummy_send_input_and_read
    )

    basic_collector._collect_standard_event(channel_input="show version")

    for priv_level in basic_collector.scrapli_connection.privilege_levels:
        assert basic_collector.events[priv_level][on_open_enabled_key][
            "show version"
        ] == StandardEvent(
            channel_output="raw output",
            result_privilege_level="privilege_exec",
            returns_prompt=True,
            closes_connection=False,
        )


@pytest.mark.parametrize(
    "test_data",
    (False, True),
    ids=(
        "pre_open",
        "post_open",
    ),
)
def test_collect_standard_event_closes_connection(monkeypatch, test_data, basic_collector):
    # lots of patching here... basically we know the individual components work so we really just
    # want to make sure the overall flow does what we think it should...

    basic_collector.on_open_enabled = test_data
    on_open_enabled_key = "post_on_open" if basic_collector.on_open_enabled else "pre_on_open"

    # patch acquire priv so we are just always in the right priv
    monkeypatch.setattr(
        "scrapli.driver.network.sync_driver.NetworkDriver.acquire_priv",
        lambda cls, target_priv: None,
    )

    # patch get prompt because we will check to see what the resulting prompt is for each command
    monkeypatch.setattr("scrapli.channel.sync_channel.Channel.get_prompt", lambda _: "c3560cx#")

    # patch send input and read because we are obviously sending something and reading the output!
    def dummy_send_input_and_read(cls, channel_input, expected_outputs, read_duration=0):
        raise ScrapliConnectionError

    monkeypatch.setattr(
        "scrapli.channel.sync_channel.Channel.send_input_and_read", dummy_send_input_and_read
    )

    # additionally patching open as we would try to reopen after the connection closes
    monkeypatch.setattr("scrapli.driver.base.sync_driver.Driver.open", lambda _: None)

    basic_collector._collect_standard_event(channel_input="show version")

    for priv_level in basic_collector.scrapli_connection.privilege_levels:
        assert basic_collector.events[priv_level][on_open_enabled_key][
            "show version"
        ] == StandardEvent(
            channel_output="__CLOSES_CONNECTION__",
            result_privilege_level="privilege_exec",
            returns_prompt=False,
            closes_connection=True,
        )


@pytest.mark.parametrize(
    "test_data",
    (False, True),
    ids=(
        "pre_open",
        "post_open",
    ),
)
def test_collect_standard_event_paging_indicated(monkeypatch, test_data, basic_collector):
    # lots of patching here... basically we know the individual components work so we really just
    # want to make sure the overall flow does what we think it should...

    basic_collector.on_open_enabled = test_data
    on_open_enabled_key = "post_on_open" if basic_collector.on_open_enabled else "pre_on_open"

    # patch acquire priv so we are just always in the right priv
    monkeypatch.setattr(
        "scrapli.driver.network.sync_driver.NetworkDriver.acquire_priv",
        lambda cls, target_priv: None,
    )

    # patch get prompt because we will check to see what the resulting prompt is for each command
    monkeypatch.setattr("scrapli.channel.sync_channel.Channel.get_prompt", lambda _: "c3560cx#")

    # patch send input and read because we are obviously sending something and reading the output!
    def dummy_send_input_and_read(cls, channel_input, expected_outputs, read_duration=0):
        return b"blah --More--", b"blah --More--"

    monkeypatch.setattr(
        "scrapli.channel.sync_channel.Channel.send_input_and_read", dummy_send_input_and_read
    )

    # additionally patching write so we can ignore the paging escape input
    monkeypatch.setattr(
        "scrapli.channel.sync_channel.Channel.write", lambda cls, channel_input, redacted: None
    )

    basic_collector._collect_standard_event(channel_input="show version")

    for priv_level in basic_collector.scrapli_connection.privilege_levels:
        assert basic_collector.events[priv_level][on_open_enabled_key][
            "show version"
        ] == StandardEvent(
            channel_output="blah --More--",
            result_privilege_level="privilege_exec",
            returns_prompt=False,
            closes_connection=False,
        )


@pytest.mark.parametrize(
    "test_data",
    (False, True),
    ids=(
        "pre_open",
        "post_open",
    ),
)
def test_collect_unknown_event(monkeypatch, test_data, basic_collector):
    # lots of patching here... basically we know the individual components work so we really just
    # want to make sure the overall flow does what we think it should...

    basic_collector.on_open_enabled = test_data
    on_open_enabled_key = "post_on_open" if basic_collector.on_open_enabled else "pre_on_open"

    # patch acquire priv so we are just always in the right priv
    monkeypatch.setattr(
        "scrapli.driver.network.sync_driver.NetworkDriver.acquire_priv",
        lambda cls, target_priv: None,
    )

    # patch get prompt because we will check to see what the resulting prompt is for each command
    monkeypatch.setattr("scrapli.channel.sync_channel.Channel.get_prompt", lambda _: "c3560cx#")

    # patch send input and read because we are obviously sending something and reading the output!
    def dummy_send_input_and_read(cls, channel_input, expected_outputs, read_duration=0):
        return b"raw output", b"output"

    monkeypatch.setattr(
        "scrapli.channel.sync_channel.Channel.send_input_and_read", dummy_send_input_and_read
    )

    basic_collector._collect_unknown_events()

    for priv_level in basic_collector.scrapli_connection.privilege_levels:
        assert basic_collector.unknown_events[priv_level][on_open_enabled_key] == StandardEvent(
            channel_output="raw output",
            result_privilege_level="privilege_exec",
            returns_prompt=True,
            closes_connection=False,
        )


@pytest.mark.parametrize(
    "test_data",
    (False, True),
    ids=(
        "pre_open",
        "post_open",
    ),
)
def test_collect_unknown_event_closes_connection(monkeypatch, test_data, basic_collector):
    # lots of patching here... basically we know the individual components work so we really just
    # want to make sure the overall flow does what we think it should...

    basic_collector.on_open_enabled = test_data
    on_open_enabled_key = "post_on_open" if basic_collector.on_open_enabled else "pre_on_open"

    # patch acquire priv so we are just always in the right priv
    monkeypatch.setattr(
        "scrapli.driver.network.sync_driver.NetworkDriver.acquire_priv",
        lambda cls, target_priv: None,
    )

    # patch get prompt because we will check to see what the resulting prompt is for each command
    monkeypatch.setattr("scrapli.channel.sync_channel.Channel.get_prompt", lambda _: "c3560cx#")

    # patch send input and read because we are obviously sending something and reading the output!
    def dummy_send_input_and_read(cls, channel_input, expected_outputs, read_duration=0):
        raise ScrapliConnectionError

    monkeypatch.setattr(
        "scrapli.channel.sync_channel.Channel.send_input_and_read", dummy_send_input_and_read
    )

    # additionally patching open as we would try to reopen after the connection closes
    monkeypatch.setattr("scrapli.driver.base.sync_driver.Driver.open", lambda _: None)

    basic_collector._collect_unknown_events()

    for priv_level in basic_collector.scrapli_connection.privilege_levels:
        assert basic_collector.unknown_events[priv_level][on_open_enabled_key] == StandardEvent(
            channel_output="__CLOSES_CONNECTION__",
            result_privilege_level="privilege_exec",
            returns_prompt=False,
            closes_connection=True,
        )


@pytest.mark.parametrize(
    "test_data",
    (False, True),
    ids=(
        "pre_open",
        "post_open",
    ),
)
def test_collect_unknown_event_paging_indicated(monkeypatch, test_data, basic_collector):
    # lots of patching here... basically we know the individual components work so we really just
    # want to make sure the overall flow does what we think it should...

    basic_collector.on_open_enabled = test_data
    on_open_enabled_key = "post_on_open" if basic_collector.on_open_enabled else "pre_on_open"

    # patch acquire priv so we are just always in the right priv
    monkeypatch.setattr(
        "scrapli.driver.network.sync_driver.NetworkDriver.acquire_priv",
        lambda cls, target_priv: None,
    )

    # patch get prompt because we will check to see what the resulting prompt is for each command
    monkeypatch.setattr("scrapli.channel.sync_channel.Channel.get_prompt", lambda _: "c3560cx#")

    # patch send input and read because we are obviously sending something and reading the output!
    def dummy_send_input_and_read(cls, channel_input, expected_outputs, read_duration=0):
        return b"blah --More--", b"blah --More--"

    monkeypatch.setattr(
        "scrapli.channel.sync_channel.Channel.send_input_and_read", dummy_send_input_and_read
    )

    # additionally patching write so we can ignore the paging escape input
    monkeypatch.setattr(
        "scrapli.channel.sync_channel.Channel.write", lambda cls, channel_input, redacted: None
    )

    basic_collector._collect_unknown_events()

    for priv_level in basic_collector.scrapli_connection.privilege_levels:
        assert basic_collector.unknown_events[priv_level][on_open_enabled_key] == StandardEvent(
            channel_output="blah --More--",
            result_privilege_level="privilege_exec",
            returns_prompt=False,
            closes_connection=False,
        )


def test__collect(basic_collector):
    # testing that the private collect method cycles through all inputs and runs the unknown,
    # standard and interactive collectors
    unknown_collected = False
    standard_collected = True
    interactive_collected = True

    def dummy_collect_unknown_events():
        nonlocal unknown_collected
        unknown_collected = True

    def dummy_collect_standard_event(channel_input):
        nonlocal standard_collected
        assert channel_input == "show version"
        standard_collected = True

    def dummy_collect_interactive_event(interact_event):
        nonlocal interactive_collected
        assert interact_event == [("someinput", "someprompt", True)]
        interactive_collected = True

    basic_collector._collect_unknown_events = dummy_collect_unknown_events
    basic_collector._collect_standard_event = dummy_collect_standard_event
    basic_collector._collect_interactive_event = dummy_collect_interactive_event

    basic_collector.channel_inputs = ["show version"]
    basic_collector.interact_events = [[("someinput", "someprompt", True)]]
    basic_collector._collect()

    assert unknown_collected is True
    assert standard_collected is True
    assert interactive_collected is True


def test_serialize(basic_collector):
    basic_collector.events = {
        "exec": {
            "pre_on_open": {
                "terminal width 512": StandardEvent(
                    channel_output="C3560CX#",
                    result_privilege_level="privilege_exec",
                    returns_prompt=True,
                    closes_connection=False,
                )
            },
            "post_on_open": {
                "clear logg": InteractiveEvent(
                    result_privilege_level="tclsh",
                    event_steps=[
                        InteractStep(
                            channel_input="clear logg",
                            channel_output="Clear logging buffer [confirm]",
                            hidden_input=False,
                            returns_prompt=True,
                        ),
                        InteractStep(
                            channel_input="\n",
                            channel_output="C3560CX(tcl)#",
                            hidden_input=False,
                            returns_prompt=True,
                        ),
                    ],
                )
            },
        }
    }
    basic_collector.unknown_events = {
        "exec": {
            "pre_on_open": StandardEvent(
                channel_output="% Unknown command or computer name, or unable to find computer address\nC3560CX>",
                result_privilege_level="exec",
                returns_prompt=True,
                closes_connection=False,
            )
        }
    }

    basic_collector._serialize()

    assert basic_collector.dumpable_events == {
        "exec": {
            "pre_on_open": {
                "terminal width 512": {
                    "channel_output": "C3560CX#",
                    "result_privilege_level": "privilege_exec",
                    "returns_prompt": True,
                    "closes_connection": False,
                    "type": "standard",
                }
            },
            "post_on_open": {
                "clear logg": {
                    "result_privilege_level": "tclsh",
                    "event_steps": [
                        {
                            "channel_input": "clear logg",
                            "channel_output": "Clear logging buffer [confirm]",
                            "hidden_input": False,
                            "returns_prompt": True,
                        },
                        {
                            "channel_input": "\n",
                            "channel_output": "C3560CX(tcl)#",
                            "hidden_input": False,
                            "returns_prompt": True,
                        },
                    ],
                    "type": "interactive",
                }
            },
        },
        "privilege_exec": {"pre_on_open": {}, "post_on_open": {}},
        "configuration": {"pre_on_open": {}, "post_on_open": {}},
        "tclsh": {"pre_on_open": {}, "post_on_open": {}},
    }
    assert basic_collector.dumpable_unknown_events == {
        "exec": {
            "pre_on_open": {
                "channel_output": "% Unknown command or computer name, or unable to find computer address\nC3560CX>",
                "result_privilege_level": "exec",
                "returns_prompt": True,
                "closes_connection": False,
            },
            "post_on_open": None,
        },
        "privilege_exec": {"pre_on_open": None, "post_on_open": None},
        "configuration": {"pre_on_open": None, "post_on_open": None},
        "tclsh": {"pre_on_open": None, "post_on_open": None},
    }


def test_dump():
    pass
