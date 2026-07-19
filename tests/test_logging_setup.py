import logging
from logging.handlers import RotatingFileHandler

from tclauncher.__main__ import setup_logging


def test_setup_logging_installs_rotating_handler(tmp_path):
    root = logging.getLogger()
    old_handlers = root.handlers[:]
    try:
        setup_logging(str(tmp_path))
        rotating = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
        assert len(rotating) == 1
        assert rotating[0].maxBytes == 1_000_000
        assert rotating[0].backupCount == 2
        assert rotating[0].baseFilename == str(tmp_path / "launcher.log")
    finally:
        for h in root.handlers[:]:
            if h not in old_handlers:
                root.removeHandler(h)
                h.close()
        root.handlers = old_handlers
