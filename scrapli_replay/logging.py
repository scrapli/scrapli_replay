"""scrapli_replay.logging"""
from logging import Formatter, LogRecord, NullHandler, getLogger


class ScrapliReplayFormatter(Formatter):
    def __init__(self, log_header: bool = True, caller_info: bool = False) -> None:
        """
        Scrapli Replay Formatter

        Emit nicely formatted log messages

        Args:
            log_header: print log header or not
            caller_info: print caller info or not (like module/function/lineno)

        Returns:
            None

        Raises:
            N/A

        """
        log_format = "{message_id:<5} | {asctime} | {levelname:<8} | {message}"
        if caller_info:
            log_format = (
                "{message_id:<5} | {asctime} | {levelname:<8} | "
                "{module:<20} | {funcName:<20} | {lineno:<5} | {message}"
            )

        super().__init__(fmt=log_format, style="{")

        self.log_header = log_header
        self.caller_info = caller_info
        self.message_id = 1

        self.header_record = LogRecord(
            name="header",
            level=0,
            pathname="",
            lineno=0,
            msg="MESSAGE",
            args=(),
            exc_info=None,
        )
        self.header_record.message_id = 0  # type: ignore
        self.header_record.asctime = "TIMESTAMP".ljust(23, " ")
        self.header_record.levelname = "LEVEL"
        self.header_record.module = "MODULE"
        self.header_record.funcName = "FUNCNAME"
        self.header_record.lineno = 0
        self.header_record.message = "MESSAGE"

    def formatMessage(self, record: LogRecord) -> str:
        """
        Override standard library logging Formatter.formatMessage

        Args:
            record: LogRecord to format

        Returns:
            str: log string to emit

        Raises:
            N/A

        """
        record.message_id = self.message_id  # type: ignore

        if self.caller_info:
            record.module = (
                record.module[:20] if len(record.module) <= 20 else f"{record.module[:17]}..."
            )
            record.funcName = (
                record.funcName[:20] if len(record.funcName) <= 20 else f"{record.funcName[:17]}..."
            )

        message = self._style.format(record)

        if self.message_id == 1 and self.log_header:
            # ignoring type for these fields so we can put "pretty" data into the log "header" row
            self.header_record.message_id = "ID"  # type: ignore
            self.header_record.lineno = "LINE"  # type: ignore
            header_message = self._style.format(self.header_record)
            message = header_message + "\n" + message

        self.message_id += 1

        return message


logger = getLogger("scrapli_replay")
logger.addHandler(NullHandler())
