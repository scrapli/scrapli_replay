import re
from logging import LogRecord

from scrapli_replay.logging import ScrapliReplayFormatter


def test_scrapli_replay_formatter():
    formatter = ScrapliReplayFormatter(log_header=True, caller_info=True)
    record = LogRecord(
        name="test_log",
        level=20,
        pathname="somepath",
        lineno=999,
        msg="thisisalogmessage!",
        args=None,
        exc_info=None,
        func="coolfunc",
    )
    formatted_record = formatter.format(record=record)
    assert (
        re.sub(
            string=formatted_record,
            pattern=r"\d{4}-\d{2}\-\d{2} \d{2}:\d{2}:\d{2},\d{3}",
            repl="_TIMESTAMP___TIMESTAMP_",
        )
        == "ID    | TIMESTAMP               | LEVEL    | MODULE               | FUNCNAME             | LINE  | MESSAGE\n"
        "1     | _TIMESTAMP___TIMESTAMP_ | INFO     | somepath             | coolfunc             | 999   | thisisalogmessage!"
    )
