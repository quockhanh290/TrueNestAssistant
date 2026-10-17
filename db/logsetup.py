"""File logging for the bot and the webapp.

start-all.ps1 starts both with pythonw: sys.stdout and sys.stderr are None,
so logging.basicConfig had nowhere to write and every traceback, warning and
print vanished (measured 17/10). setup() gives each process a size-rotated
file in logs/ and routes everything there:
  - the logging module (root logger, INFO and up);
  - print() and anything written to stdout/stderr, when they are None;
  - uncaught exceptions in the main thread and in threads.

Stdlib only. Lives in db/ only because that is the shared package both entry
points already import; it touches no database.
"""
import logging
import logging.handlers
import os
import re
import sys
import threading

MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5
FORMAT = "%(asctime)s %(levelname)s %(name)s [%(process)d] %(message)s"


# Bot API URLs carry the token: https://api.telegram.org/bot<id>:<secret>/...
# httpx logs every request URL at INFO. Anything shaped like a token, and the
# configured token itself, is replaced before a line is written anywhere.
TOKEN_RE = re.compile(r"\d{6,}:[A-Za-z0-9_-]{20,}")
# loggers that print full request URLs at INFO
QUIET_LOGGERS = ("httpx", "httpcore")


def redact(text):
    """Text with every bot token replaced by ***."""
    for env in ("TELEGRAM_BOT_TOKEN", "BOT_TOKEN"):
        tok = (os.environ.get(env) or "").strip()
        if len(tok) >= 8:
            text = text.replace(tok, "***")
    return TOKEN_RE.sub("***", text)


class RedactingFormatter(logging.Formatter):
    """Masks tokens in the whole formatted line: message, arguments and
    traceback text (an exception message can hold the URL too)."""

    def format(self, record):
        return redact(super().format(record))


def default_log_dir():
    """TRUENEST_LOG_DIR, else <repo>/logs next to the running code."""
    env = os.environ.get("TRUENEST_LOG_DIR")
    if env:
        return env
    return os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "logs")


class _LineToLog:
    """File-like object that sends each written line to a logger."""

    def __init__(self, logger, level):
        self.logger, self.level, self._buf = logger, level, ""

    def write(self, text):
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self.logger.log(self.level, line)
        return len(text)

    def flush(self):
        if self._buf.strip():
            self.logger.log(self.level, self._buf)
        self._buf = ""

    def isatty(self):
        return False


def _install_excepthooks():
    log = logging.getLogger("uncaught")

    def hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            return sys.__excepthook__(exc_type, exc, tb)
        log.critical("uncaught exception", exc_info=(exc_type, exc, tb))

    def thread_hook(args):
        if args.exc_type is SystemExit:
            return
        log.critical("uncaught exception in thread %s",
                     getattr(args.thread, "name", "?"),
                     exc_info=(args.exc_type, args.exc_value,
                               args.exc_traceback))
    sys.excepthook = hook
    threading.excepthook = thread_hook


def setup(name, log_dir=None, level=logging.INFO):
    """Log to <log_dir>/<name>.log (rotating). Returns the file path.

    Call it first thing in an entry point, under `if __name__ ==
    "__main__"`, so tests that import the module keep their own logging.
    """
    log_dir = log_dir or default_log_dir()
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, f"{name}.log")
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8",
        delay=False)
    handler.setFormatter(RedactingFormatter(FORMAT))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(level)
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    if sys.stderr is not None:
        # run from a console: keep printing there as basicConfig did
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(RedactingFormatter(FORMAT))
        root.addHandler(console)
    if sys.stdout is None:
        sys.stdout = _LineToLog(logging.getLogger("stdout"), logging.INFO)
    if sys.stderr is None:
        sys.stderr = _LineToLog(logging.getLogger("stderr"), logging.ERROR)
    _install_excepthooks()
    logging.getLogger(name).info("logging to %s (pid %d)", path, os.getpid())
    return path


def log_system_exit(name, exc):
    """SystemExit skips sys.excepthook; record why the process stopped."""
    if exc.code not in (None, 0):
        logging.getLogger(name).error("exit: %s", exc.code)
