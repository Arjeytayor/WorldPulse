"""Shared error logger for all WorldPulse modules.

Logs to a file always, and additionally to stdout when running in CI. On an
ephemeral runner the file dies with the machine, so a file-only logger makes
every CI failure undiagnosable -- which is exactly what happened on the first
GitHub Actions run.
"""

import logging
import os
import re
import sys

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "errors.log")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

# requests puts the full request URL in its exception strings, and the Telegram
# base URL embeds the bot token. Any logger.error(..., exc_info=True) around a
# Telegram call therefore writes the token to the log. GitHub masks registered
# secrets in workflow output, but this repo is public and the log file also
# lives on disk locally, so scrub at the source rather than trusting the mask.
_REDACTIONS = (
    re.compile(r"(/bot)\d{6,}:[\w-]{20,}"),
    re.compile(r"(?i)(api[_-]?key[\"'=: ]+)[\w-]{16,}"),
    re.compile(r"(?i)(bearer\s+)[\w.\-]{16,}"),
)


class _Redact(logging.Filter):
    """Strip credentials from anything on its way to a handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
            if record.exc_info:
                import traceback
                message += "\n" + "".join(traceback.format_exception(*record.exc_info))
                record.exc_info = None
                record.exc_text = None
            for pattern in _REDACTIONS:
                message = pattern.sub(r"\1***", message)
            record.msg = message
            record.args = ()
        except Exception:
            # A logger that raises turns a small failure into a crash.
            pass
        return True


_FORMAT = "%(asctime)s | %(levelname)s | %(module)s.%(funcName)s | %(message)s"
_DATEFMT = "%Y-%m-%dT%H:%M:%S"

logger = logging.getLogger("WorldPulseLogger")
logger.setLevel(logging.INFO)
logger.propagate = False

if not logger.handlers:
    _redact = _Redact()

    _file = logging.FileHandler(LOG_PATH, encoding="utf-8")
    _file.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
    _file.addFilter(_redact)
    logger.addHandler(_file)

    # GitHub Actions, and most other CI, set CI=true.
    if os.environ.get("CI"):
        _stream = logging.StreamHandler(sys.stdout)
        _stream.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
        _stream.addFilter(_redact)
        logger.addHandler(_stream)
