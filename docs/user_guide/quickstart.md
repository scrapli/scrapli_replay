# Quick Start Guide


## Installation

In most cases installation via pip is the simplest and best way to install scrapli replay.
See [here](/user_guide/installation) for advanced installation details.

```
pip install scrapli-replay
```


## A Simple Example (Pytest)

Simply mark your tests containing scrapli code with the `scrapli_replay` marker:

```python
@pytest.mark.scrapli_replay
def test_something_else():
    with IOSXEDriver(**MY_DEVICE) as conn:
        result = conn.send_command("show run | i hostname")
```
