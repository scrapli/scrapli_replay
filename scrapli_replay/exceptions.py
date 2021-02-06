"""scrapli_replay.exceptions"""


class ScrapliReplayException(Exception):
    """
    Base class for scrapli_replay exceptions

    Does not inherit from scrapli base exception so that these exceptions are very clearly not from
    "normal" scrapli!

    """


class ScrapliReplayConnectionProfileError(ScrapliReplayException):
    """Exception for connection profile errors"""


class ScrapliReplayExpectedInputError(ScrapliReplayException):
    """Exception for errors where expected inputs do not match reality"""


class ScrapliReplayServerError(ScrapliReplayException):
    """Base exception for scrapli_replay server related errors"""
