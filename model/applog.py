"""Application log: one small rotating file, so errors are kept instead of lost.

The log is ~/Library/Logs/PTracker/ptracker.log (up to 1 MB, plus 3 older
files). Inside the installed app, print() output has nowhere to go, so
stdout and stderr are sent to the log as well. Uncaught errors in the main
thread and in background threads are logged with their traceback.

Use it from any module:
    from model.applog import log
    log.info("Prices refreshed for %d symbols", n)
    log.exception("Could not refresh prices")   # inside an except block
"""

import logging
import logging.handlers
import os
import sys
import threading

LOG_DIR = os.path.expanduser("~/Library/Logs/PTracker")
LOG_PATH = os.path.join(LOG_DIR, "ptracker.log")

log = logging.getLogger("ptracker")


class _StreamToLog:
    """A file-like object that turns written lines into log records."""

    def __init__(self, level: int):
        self._level = level
        self._buf = ""

    def write(self, text):
        self._buf += str(text)
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                log.log(self._level, line.rstrip())
        return len(text)

    def flush(self):
        if self._buf.strip():
            log.log(self._level, self._buf.rstrip())
        self._buf = ""

    def isatty(self):
        return False


def setup_logging() -> logging.Logger:
    """Create the log file handler once. Safe to call more than once."""
    if getattr(setup_logging, "_done", False):
        return log
    setup_logging._done = True

    log.setLevel(logging.INFO)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"))
        log.addHandler(handler)
    except OSError:
        pass  # no log file is better than no app

    if getattr(sys, "frozen", False):
        sys.stdout = _StreamToLog(logging.INFO)
        sys.stderr = _StreamToLog(logging.WARNING)
    else:
        console = logging.StreamHandler(sys.__stderr__)
        console.setLevel(logging.WARNING)
        console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        log.addHandler(console)

    def _excepthook(exc_type, exc, tb):
        log.critical("Uncaught error", exc_info=(exc_type, exc, tb))

    def _thread_excepthook(args):
        log.error("Uncaught error in thread %s", getattr(args.thread, "name", "?"),
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    log.info("PTracker started (python %s, frozen=%s)", sys.version.split()[0],
             bool(getattr(sys, "frozen", False)))
    return log
