"""Logging for a packaged application.

A frozen build has no console to print to, so diagnostics have to go somewhere
the user can find and attach to a bug report. This module writes a rotating log
file into the platform log directory and keeps stderr for development.

**What must never reach the log**: the text a user is automating (it may be a
password, a message, or anything else they typed into the editor), profile
contents, and file paths from inside profiles. The engine's own log lines are
descriptive rather than verbatim, and :class:`RedactingFilter` is the backstop -
it rewrites the two shapes that would otherwise leak typed text.
"""

from __future__ import annotations

import logging
import logging.handlers
import re
from pathlib import Path

from .metadata import APP_SLUG

LOG_FILENAME = f"{APP_SLUG}.log"
MAX_BYTES = 1_000_000
BACKUP_COUNT = 3

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

#: ``type 'secret text' (11 chars)`` - the action description format.
_DESCRIPTION = re.compile(r"type '(?P<text>.*?)' \((?P<count>\d+) chars\)", re.DOTALL)
#: ``TypeText(text='secret text'…)`` - a dataclass repr.
_REPR = re.compile(r"TypeText\(([^)]*?)text=(?P<quote>['\"])(?P<text>.*?)(?P=quote)", re.DOTALL)


class RedactingFilter(logging.Filter):
    """Removes automated text from log records.

    Applied to every handler this module installs. It rewrites the message
    rather than dropping the record, so the diagnostic value (which action, how
    long, which adapter) survives while the content does not.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = self.redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True

    @staticmethod
    def redact(message: str) -> str:
        message = _DESCRIPTION.sub(
            lambda match: f"type <redacted, {match.group('count')} chars>", message
        )
        return _REPR.sub(
            lambda match: f"TypeText({match.group(1)}text=<redacted, "
            f"{len(match.group('text'))} chars>",
            message,
        )


def configure_logging(
    *,
    verbose: bool = False,
    log_directory: Path | None = None,
    to_file: bool = True,
) -> Path | None:
    """Install stderr and rotating-file logging. Returns the log file path.

    Safe to call more than once: previously installed handlers are replaced.
    A log directory that cannot be created is reported on stderr and the
    application continues with console logging only - failing to start because
    logging failed would be worse than losing the log.
    """
    level = logging.DEBUG if verbose else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    redactor = RedactingFilter()
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.WARNING)
    console.setFormatter(logging.Formatter(_FORMAT))
    console.addFilter(redactor)
    root.addHandler(console)

    if not to_file or log_directory is None:
        return None

    try:
        log_directory.mkdir(parents=True, exist_ok=True)
        path = log_directory / LOG_FILENAME
        file_handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
    except OSError as error:
        logging.getLogger(__name__).warning("file logging unavailable: %s", error)
        return None

    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    file_handler.addFilter(redactor)
    root.addHandler(file_handler)
    return path
