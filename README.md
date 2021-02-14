[![Supported Versions](https://img.shields.io/pypi/pyversions/scrapli-replay.svg)](https://pypi.org/project/scrapli-replay)
[![PyPI version](https://badge.fury.io/py/scrapli-replay.svg)](https://badge.fury.io/py/scrapli-replay)
[![Weekly Build](https://github.com/scrapli/scrapli_replay/workflows/Weekly%20Build/badge.svg)](https://github.com/scrapli/scrapli_replay/workflows/Weekly%20Build)
[![Code Style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/ambv/black)
[![License: MIT](https://img.shields.io/badge/License-MIT-blueviolet.svg)](https://opensource.org/licenses/MIT)

scrapli_replay
==============

---

**Documentation**: <a href="https://scrapli.github.io/scrapli_replay" target="_blank">https://scrapli.github.io/scrapli_replay</a>

**Source Code**: <a href="https://github.com/scrapli/scrapli_replay" target="_blank">https://github.com/scrapli/scrapli_replay</a>

**Examples**: <a href="https://github.com/scrapli/scrapli_replay/tree/main/examples/simple_test_case" target="_blank">https://github.com/scrapli/scrapli_replay/tree/main/examples/simple_test_case</a>

---

scrapli_replay: Tools to enable easy testing of scrapli programs and to create semi-interactive SSH servers that 
look and feel like "real" network devices!


#### Key Features:

- __Easy__: Easily test scrapli code with Pytest, or create mock SSH servers to play with!
- __Pytest__: Love scrapli and Pytest? Want to test your code that contains scrapli components, but can't test 
  against real devices in your CI? scrapli_replay is a Pytest plugin to help you with exactly this -- its like 
  [VCR.py](https://vcrpy.readthedocs.io/en/latest/) and [pytest-vcr](http://pytest-vcr.readthedocs.io/en/latest/), but for scrapli!
- __Offline__: Want to be able to have the look and feel of a network device without having a network device? Create 
  a mock SSH server based on real network device behavior and run it in your CI or a Raspberry Pi (or whatever)!
- __Lightweight__: Want to spin up a bunch of test servers, but don't have the resources for real device images? 
  Asyncssh is fast and lightweight so you can run loads of mock SSH servers with very little resources!


## Installation

```
pip install scrapli_replay
```

See the [docs](https://scrapli.github.io/scrapli_replay/user_guide/installation) for other installation methods/details.



## A Simple (Pytest) Example

```python
@pytest.mark.scrapli_replay
def test_something_else():
    with IOSXEDriver(**MY_DEVICE) as conn:
        result = conn.send_command("show run | i hostname")
```

