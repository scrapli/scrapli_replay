# Basic Usage


## What do you need to get done!?!

First things first: what do you need to get done? scrapli replay contains two similar yet very different testing 
tools. 

The first, is the pytest plugin -- a plugin to mark tests with. This plugin will record scrapli session 
inputs and outputs and save them, that way you can store these test sessions and re-use them (without needing a 
"live" device) in your CI setup.

The second, is a "collector", and a "server" that allow you to build semi-interactive SSH servers that you can 
connect to for testing purposes.

As you'd expect, if you are writing tests and wanting to have some reasonable assurances that your code that 
interacts with scrapli is doing what you think it should be doing, then you probably want to use the pytest plugin! 
If you just want to have a mock SSH server to play with, then the collector/server may be interesting to you.


## Pytest Plugin

### Overview and Use Case

As shown in the quickstart guide, getting going with the pytest plugin is fairly straightforward -- tests that 
contain scrapli operations can be marked with the `scrapli_replay` marker, causing scrapli replay to automagically 
wrap this test and record or replay sessions within the test.

In order for scrapli replay to do this, there is one big caveat: the scrapli connection *must be opened within the 
test*! Projects like `pytest-vcr` don't have this requirement because the sessions are stateless HTTP(s) sessions -- 
this is of course not the case for Telnet/SSH where we have more or less a stateful connection object. This may 
sound like a limiting factor for scrapli replay and perhaps it is, however it is relatively easy to work with as 
you'll see below!

Here is a very simple example of a class that creates a scrapli connection and has some methods to do stuff:

```python
import re
from scrapli import Scrapli


class Example:
    def __init__(self):
        self.conn = Scrapli(
            host="c3560", platform="cisco_iosxe", ssh_config_file=True, auth_strict_key=False
        )
        # dont do this! dont have side affects in init, but helps demonstrate things!
        self.conn.open()

    def do_stuff(self):
        """Get the version from the device"""
        version_result = self.conn.send_command(command="show version | i Software")

        if version_result.failed is True:
            return "__FAILURE__"

        version_result_string = version_result.result
        version_result_match = re.findall(
            pattern=r"Version ([a-z0-9\.\(\)]*)", string=version_result_string, flags=re.I
        )

        if not version_result_match:
            return "__FAILURE__"

        return version_result_match[0]
```

Let's pretend we want to write some tests for the `do_stuff` method of this example class. We probably want to have 
at least three test cases for this method:

1. Testing a failed result from the initial show command
2. Testing a success event where we properly get and parse the version string
3. Testing a failed parsing of the version string

For cases one and three we probably don't want or need scrapli replay -- we could simply patch the `send_command` 
method of scrapli, returning bad data -- either a bad scrapli `Response` object, or a `Response` object with data 
that will cause our regex to fail.

For case number 2, however, we *could* also patch scrapli and return correct data, this would validate that our 
function, when given appropriate outputs from scrapli, does what it should do. This would be a valuable test. With 
scrapli replay, however, we can take this a bit further! We can now create a test case that records *actual device 
inputs and outputs* and saves that data in a scrapli replay session. Subsequent tests can then *replay* that input 
and output data. Rather than just testing that our regex works w/ some patched response data we can now very simply 
test not only that, but also scrapli -- ensuring that scrapli is behaving as you would expect!


### How it Works

Before jumping into how to use scrapli replay, it's worth spending a bit of time to understand how it works. At a 
high level, scrapli replay is a Pytest plugin that you can "mark" tests with. By marking a test you are effectively 
"wrapping" that test in the scrapli replay `ScrapliReplay` class.

The pytest plugin then uses the `ScrapliReplay` class as a context manager, yielding to your test within the context 
manager. For tests that are marked `asyncio` we simply use the async context manager capability instead of the 
synchronous version. This selection of sync vs async happens transparently to you --  you just need to mark your 
tests with the `asyncio` marker if they are asyncio (which you had to do anyway, so no biggie!).

While the `ScrapliReplaly` context manager is active (while your test is running) `ScrapliReplay` patches the `open` 
method of scrapli and a `ConnectionProfile` is recorded (host/user/is using password/auth 
bypass/etc.). This `ConnectionProfile` is stored as part of the scrapli replay session data -- allowing us to 
validate that during subsequent test runs the connection information has not changed (if it has we raise an 
exception to fail the test).

After the `ConnectionProfile` is recorded, the scrapli `Channel` (or `AsyncChannel`) read and write methods are 
patched (replaced) with scrapli replay read/write methods. If the current test iteration is in "record" mode, we 
patch with the "record" read/write, otherwise we patch with the "replay" read/write -- these methods do what they 
sound like! Recording or replaying session data.

At completion of your test, when the context manager is closing the session will be dumped to a yaml file in your 
session output directory (by default this is a folder located with your test file).

Due to the fact that scrapli replay uses the open method of scrapli in order to fetch connection data and also to 
patch the channel objects, there is a requirement that the test actually opens the connection. This sounds perhaps 
limiting, and probably it is somewhat, however you can fairly easily work around this by having a fixture that 
returns an object with the connection already opened -- this fixture currently must be scoped to the *function* 
level. This will hopefully be improved in further scrapli replay releases to allow us to cache session-wide fixtures.


### How to Use it

As shown in the quickstart, using scrapli replay is fairly straightforward -- simply mark a test with the correct 
marker. The complication generally will come from needing to have the connection opened within that test being 
wrapped -- this section will showcase some basic ways to use scrapli replay, as well as how we can handle the 
connection opening problem.

Working with the example class from the overview section, let's handle test case number 2. To start, we can do this 
with the patching method -- without scrapli replay:

```python
from scrapli.response import Response


def test_example_do_stuff_patching(monkeypatch, example_instance):
    """Test Example.do_stuff"""
    def patched_send_command(cls, command):
        r = Response(host="localhost", channel_input=command)
        r.record_response(b"Software Version 15.2(4)E7")
        return r

    monkeypatch.setattr("scrapli.driver.network.sync_driver.NetworkDriver.send_command", patched_send_command)
    assert example_instance.do_stuff() == "15.2(4)E7"
```

This works reasonably well, and properly tests our regex does indeed find the version string; of course you could 
actually return a real device output instead of hte abbreviated output here as well -- that would make things a bit 
more "real". This is nice, but it does not test any scrapli behavior at all as scrapli is completely patched out of 
the test. There must be a better way!

Let's now re-write this test using scrapli replay:

```python
import pytest
from example import Example  # <- this is assuming directory structure as in the "examples/simple_test_case" example!

@pytest.mark.scrapli_replay
def test_example_do_stuff_no_fixture():
    """Test Example.do_stuff"""
    assert Example().do_stuff() == "15.2(4)E7"
```

No patching?! Amazing! So... what is going on here?

The `Example` class (from the snippet way above here) is created, which causes the scrapli connection to open, then 
we call the `do_stuff` method which fetches the version and parses it with some regex. Scrapli replay is "aware" of 
this test due to the marker -- this basically means that this test is living inside of a scrapli replay context 
manager... you can think of it as something like this:

```python
with ScrapliReplay:
    test()
```

An oversimplified example, but not by much!

If you run this example (from the examples dir in the repo) the first time the test is ran, scrapli will actually 
connect to your device and record the output. This of course means that you need proper credentials/access in order 
to get this first recording done -- using ssh keys/config file so that you don't need to store any user/creds in 
your test is a great way to deal with this.

At the end of the test, scrapli replay will dump the "session" data out to a yaml file in a new folder called 
"scrapli_replay_sessions" that was created in the same directory of your test file (you can change this, see the 
options section!). This "session" file looks like this:

```yaml
connection_profile:
  host: c3560
  port: 22
  auth_username: ''
  auth_password: false
  auth_private_key: ''
  auth_private_key_passphrase: false
  auth_bypass: false
  transport: system
  auth_secondary: false
interactions:
  - channel_output: "Warning: Permanently added 'c3560,172.31.254.1' (RSA) to the\
      \ list of known hosts.\n\nC3560CX#"
    expected_channel_input: "\n"
    expected_channel_input_redacted: false
  - channel_output: "\nC3560CX#"
    expected_channel_input: terminal length 0
    expected_channel_input_redacted: false
  - channel_output: terminal length 0
    expected_channel_input: "\n"
    expected_channel_input_redacted: false
  - channel_output: "\nC3560CX#"
    expected_channel_input: terminal width 512
    expected_channel_input_redacted: false
  - channel_output: terminal width 512
    expected_channel_input: "\n"
    expected_channel_input_redacted: false
  - channel_output: "\nC3560CX#"
    expected_channel_input: show version | i Software
    expected_channel_input_redacted: false
  - channel_output: show version | i Software
    expected_channel_input: "\n"
    expected_channel_input_redacted: false
  - channel_output: "\nCisco IOS Software, C3560CX Software (C3560CX-UNIVERSALK9-M),\
      \ Version 15.2(4)E7, RELEASE SOFTWARE (fc2)\nC3560CX#"
    expected_channel_input:
    expected_channel_input_redacted: false
```

As you can see, connection details are stored (but never credentials) -- in the event of password authentication the 
password is not stored and is marked as "REDACTED" in the interactions output.

Running the test again you'll notice that its even faster than scrapli normally is! Why? Because there is no actual 
connection going out to the device, the connection will just be automagically replayed from this session data!

Now if you have a billion tests to write, or you are needing to pass lots of inputs in order to create your scrapli 
connection objects in every single test... that wouldn't be very fun! In cases like this it would be a great idea to 
put either the scrapli connection object, or the device containing the connection object into a fixture and allowing 
pytest to pass that fixture into each test function. Here is a simple example of a fixture for our example setup:

```python
import pytest
from example import Example


@pytest.fixture(scope="function")
def example_instance():
    """Simple fixture to return Example instance"""
    yield Example()
```

And... a test taking advantage of this fixture:

```python
@pytest.mark.scrapli_replay
def test_example_do_stuff_with_fixture(example_instance):
    """Test Example.do_stuff"""
    assert example_instance.do_stuff() == "15.2(4)E7"
```

It is important to note that the fixture scope *must be* set to `function` -- again, this is because scrapli replay 
*requires* the connection to be opened within the test it is wrapping in order to properly record the connection 
profile and patch the read/write methods!


### Pytest Plugin Options

scrapli replay supports a handful of arguments to modify its behavior, currently, these are configurable via the 
pytest cli -- in the future they will likely be configurable by a dedicated fixture as well.

The available options are:


#### Mode

The "replay" mode setting manages how scrapli replay handles replaying or recording sessions. This setting has the 
following options:

- replay: the default mode; if no session exists scrapli replay will record/create one, otherwise it will "replay" 
  existing sessions (meaning you dont need to connect to a device)
- record: *probably* not needed often, does at it says -- records things. If a session exists it will auto switch to 
  replay mode (meaning *not* overwrite the session)
- overwrite: overwrite existing all sessions always

This option is configurable with the `--scrapli-replay-mode` switch:

```bash
python -m pytest tests --scrapli-replay-mode overwrite
```


#### Directory

By default, scrapli replay stores the recorded sessions in a directory in the same folder as the test that is being 
executed. This is modifiable with the `--scrapli-replay-directory` switch:

```bash
python -m pytest tests --scrapli-replay-directory /my/cool/session/dir
```


#### Overwrite

If you need to overwrite only certain test session data, you can do so by using the `--scrapli-replay-overwrite` 
switch. This argument accepts a comma separated list of test names of which to overwrite the session data.

```bash
python -m pytest tests --scrapli-replay-overwrite test1,test2,test3
```


#### Disable

Finally, you can disable entirely the scrapli replay functionality -- meaning your tests will run "normally" without 
any of the scrapli replay patching/session work happening. This is done with the `--scrapli-replay-disable` flag.

```bash
python -m pytest tests --scrapli-replay-disable
```


## Collector and Server

### Overview

The scrapli replay "collector" and "server" functionality is useful for creating mock ssh servers that are 
"semi-interactive". You can provide any number of commands (not configs! more on this in a bit) that you would like 
to collect from a device, and the collector will run the provided commands at all privilege levels, and with and 
without "on_open" functionality being executed (generally this means with and without paging being disabled). The 
collector will also collect any on open commands, on close commands, all privilege escalation/deescalation commands, 
and "unknown" or invalid command output from every privilege level. 

Just like the pytest plugin, the scrapli replay collector will output the collected data to a yaml file. This yaml 
file is then consumed by the scrapli replay server. The server itself is an asyncssh server that does its best to 
look and feel just like the real device that you collected the data from.

### Collector

As outlined in the overview section, the collector.... collects things! The collector tries to collect as much info 
from the device as is practical, with the ultimate goal of being able to allow the server to look pretty close to a 
real device.

Before continuing, it is important to note that currently the collector can only be used with *network devices* -- 
meaning it *must* be used with a scrapli platform that extends the `NetworkDriver` class; moreover it *must* be used 
with a *synchronous* transport. There will likely *not* be any asyncio support for the collector (it doesn't seem to 
be very valuable to add asyncio support...  please open an issue if you disagree!).

To get started with the collector is fairly straight forward, simply create a collector class, passing in the 
commands you wish to collect, some details about "paging" (more on this in a sec), and the kwargs necessary to create 
the scrapli connection to collect from:

```python
from scrapli_replay.server.collector import ScrapliCollector

scrapli_kwargs = {
    "host": "localhost",
    "port": 24022,
    "ssh_config_file": False,
    "auth_strict_key": False,
    "auth_username": "vrnetlab",
    "auth_password": "VR-netlab9",
    "auth_secondary": "VR-netlab9",
    "platform": "arista_eos",
}

collector = ScrapliCollector(
    channel_inputs=["show version", "show run"],
    interact_events=[
        [("clear logg", "Clear logging buffer [confirm]", False), ("", "switch#", False)]
    ],
    paging_indicator="--More--",
    paging_escape_string="\x1b",
    **scrapli_kwargs,
)
```

If you are familiar with scrapli connections, the above snippet should look fairly similar! In addition to the 
scrapli connection data we see a few extra things:

- `channel_inputs` -- a list of "inputs" you wish to send to the device for recording. Each of these inputs will be 
  run at every privilege level of the device, and before and after executing the "on_open" function (if applicable)
- `interact_events` -- similar to "normal" scrapli, a list of lists of tuples of "interact events" to record at each 
  privilege level (and before/after on_open)
- `paging_indicator` -- this is what it sounds like -- a string that lets us know if the device has paginated output 
  data
- `paging_escape_string` -- a string to send to "cancel" a command output if paging is encountered -- typically an 
  escape, or a `q` works for most devices

*Note* -- you can also pass an existing scrapli connection to the `scrapli_connection` argument if you prefer 
(instead of the kwargs needed to create a connection)!


Once a collector object has been created, you can open the connection and simply run the `collect` method, followed 
by the `dump` method:

```python
collector.open()
collector.collect()
collector.close()
collector.dump()
```

The session data will be dumped to a yaml file called "scrapli_replay_collector_session.yaml" (configurable with the 
`collector_session_filename` argument) in your current directory. Once you have a session stored, you can run the 
"server" to create a semi-interactive ssh server!


### Server

Starting the scrapli replay server is simple!

```python
import asyncio
from scrapli_replay.server.server import start


async def main() -> None:
    await start(port=2001, collect_data="scrapli_replay_collector_session.yaml")


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    loop.run_forever()
```

You can pass whatever port you wish for the `port` argument, and the `collect_data` must be the collected 
data from the collector.

Once the server is running you should be able to SSH to the server on the provided port just as if it were a "real" 
device! The username and password will always be "scrapli" regardless of what the credentials were for the collected 
server -- this is done so we never have to deal with or think about storing credentials.

There are several big caveats to be aware of!

- Credentials: username/password (including for "enable" password) will always be "scrapli", as mentioned this is to 
  keep things simple and not deal with storing any credential data
- Configs: configuration things are not supported and probably won't ever be. It would be a lot of work to keep 
  track of when/if a user sends a config and what the resulting configuration would look like...
- Paging: if you execute a command that would not complete due to paging not being disabled (i.e. "show run" before 
  "terminal lenght 0") the server will also not complete the show command -- sending a return at this point will get 
  you back to the prompt. This is intentional -- if you use the server to test scrapli scripts we want things to 
  look/feel like real... meaning scrapli would be stuck here looking for a prompt it can never find and eventually 
  time out.
- Paging again...: You must send *all* commands from the "on_open" function of a driver in order to disable paging...
  yes of course "terminal length 0" would disable paging for a "show run" command on an IOS-XE device, *but* we only 
  know that the "on_open" function of the IOS-XE driver runs both "terminal length 0" AND "terminal width 512"... 
  until both of these commands are seen paging is not disabled.
- Paging again... again...: Paging cannot be disabled other than exiting and reconnecting to the mock server. As 
  scrapli doesnt know how to re-enable paging we can't know that for the collector either.
  
With all the bad stuff out of the way, let's check out a mock server:

```
$ ssh localhost -p 2001 -l scrapli
Warning: Permanently added '[localhost]:2222' (RSA) to the list of known hosts.
Password:
C3560CX#show version
Cisco IOS Software, C3560CX Software (C3560CX-UNIVERSALK9-M), Version 15.2(4)E7, RELEASE SOFTWARE (fc2)
Technical Support: http://www.cisco.com/techsupport
Copyright (c) 1986-2018 by Cisco Systems, Inc.
Compiled Tue 18-Sep-18 13:20 by prod_rel_team

ROM: Bootstrap program is C3560CX boot loader
BOOTLDR: C3560CX Boot Loader (C3560CX-HBOOT-M) Version 15.2(4r)E5, RELEASE SOFTWARE (fc4)

C3560CX uptime is 1 week, 3 days, 2 hours, 55 minutes
System returned to ROM by power-on
System restarted at 07:13:48 PST Thu Jan 14 2021
System image file is "flash:c3560cx-universalk9-mz.152-4.E7.bin"
Last reload reason: power-on



This product contains cryptographic features and is subject to United
States and local country laws governing import, export, transfer and
use. Delivery of Cisco cryptographic products does not imply
third-party authority to import, export, distribute or use encryption.
Importers, exporters, distributors and users are responsible for
 --More--
C3560CX#
```

In the above output we connect to the mock server (with username/password of "scrapli") and execute the "show 
version" command -- as paging has *not* been disabled we get the lovely "--More--" pagination indicator. Simply 
sending another return here gets us back to our prompt.

Continuing on... let's try to disable paging:

```
<< SNIP >>
This product contains cryptographic features and is subject to United
States and local country laws governing import, export, transfer and
use. Delivery of Cisco cryptographic products does not imply
third-party authority to import, export, distribute or use encryption.
Importers, exporters, distributors and users are responsible for
 --More--
C3560CX#terminal length 0
C3560CX#terminal width 511
% Unknown command or computer name, or unable to find computer address
C3560CX#terminal width 512
C3560CX#
```

Whoops - you can see that sending "terminal width 511" (instead of the "correct" command from the "on_open" 
function "terminal width 512") caused the server to send us an "Unknown command" output -- similar to if you sent an 
bad command on a "real" switch.

Now that we have paging disabled, we can try the "show version" command again:

```
<< SNIP >>
This product contains cryptographic features and is subject to United
States and local country laws governing import, export, transfer and
use. Delivery of Cisco cryptographic products does not imply
third-party authority to import, export, distribute or use encryption.
Importers, exporters, distributors and users are responsible for
 --More--
C3560CX#terminal length 0
C3560CX#terminal width 511
% Unknown command or computer name, or unable to find computer address
C3560CX#terminal width 512
C3560CX#show version
Cisco IOS Software, C3560CX Software (C3560CX-UNIVERSALK9-M), Version 15.2(4)E7, RELEASE SOFTWARE (fc2)
Technical Support: http://www.cisco.com/techsupport
Copyright (c) 1986-2018 by Cisco Systems, Inc.
Compiled Tue 18-Sep-18 13:20 by prod_rel_team

ROM: Bootstrap program is C3560CX boot loader
BOOTLDR: C3560CX Boot Loader (C3560CX-HBOOT-M) Version 15.2(4r)E5, RELEASE SOFTWARE (fc4)

C3560CX uptime is 1 week, 3 days, 2 hours, 55 minutes
System returned to ROM by power-on
System restarted at 07:13:48 PST Thu Jan 14 2021
System image file is "flash:c3560cx-universalk9-mz.152-4.E7.bin"
Last reload reason: power-on



This product contains cryptographic features and is subject to United
States and local country laws governing import, export, transfer and
use. Delivery of Cisco cryptographic products does not imply
third-party authority to import, export, distribute or use encryption.
Importers, exporters, distributors and users are responsible for
compliance with U.S. and local country laws. By using this product you
agree to comply with applicable laws and regulations. If you are unable
to comply with U.S. and local laws, return this product immediately.

A summary of U.S. laws governing Cisco cryptographic products may be found at:
http://www.cisco.com/wwl/export/crypto/tool/stqrg.html

If you require further assistance please contact us by sending email to
export@cisco.com.

License Level: ipservices
License Type: Permanent Right-To-Use
Next reload license Level: ipservices

cisco WS-C3560CX-8PC-S (APM86XXX) processor (revision A0) with 524288K bytes of memory.
Processor board ID FOC1911Y0NH
Last reset from power-on
3 Virtual Ethernet interfaces
12 Gigabit Ethernet interfaces
The password-recovery mechanism is enabled.

512K bytes of flash-simulated non-volatile configuration memory.
Base ethernet MAC Address       : C8:00:84:B2:E9:80
Motherboard assembly number     : 73-16471-04
Power supply part number        : 341-0675-01
Motherboard serial number       : FOC190608U7
Power supply serial number      : DCB190430Z0
Model revision number           : A0
Motherboard revision number     : A0
Model number                    : WS-C3560CX-8PC-S
System serial number            : FOC1911Y0NH
Top Assembly Part Number        : 68-5359-01
Top Assembly Revision Number    : A0
Version ID                      : V01
CLEI Code Number                : CMM1400DRA
Hardware Board Revision Number  : 0x02


Switch Ports Model                     SW Version            SW Image
------ ----- -----                     ----------            ----------
*    1 12    WS-C3560CX-8PC-S          15.2(4)E7             C3560CX-UNIVERSALK9-M


Configuration register is 0xF

C3560CX#
```

That looks about right! How about config mode?

```
C3560CX#configure terminal
Enter configuration commands, one per line.  End with CNTL/Z.
C3560CX(config)#show version
                  ^
% Invalid input detected at '^' marker.

C3560CX(config)#
```

Sending a "show" command in config mode fails like you'd expect too. This is because we "collected" all the 
requested inputs at every privilege level. We can't send configs really because we didn't collect any and 
collector/server is not built to deal with configs anyway.

Ok, back down to exec?

```
C3560CX(config)#show version
                  ^
% Invalid input detected at '^' marker.

C3560CX(config)#end
C3560CX#disable
C3560CX>enable
Password:
C3560CX#
```

Down to exec no problem, and back up to privilege exec -- remember that the password is "scrapli"!

Thats about it for scrapli replay server -- the hope is that this can be useful for folks to do a bit of offline 
testing of basic scrapli (or whatever else really) scripts!
