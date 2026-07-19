import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .config import LAUNCHER_USERDIR, ConfigManager
from .ui.main_window import MainWindow
from .ui.theme import apply_theme


def setup_logging(log_dir: str):
    handler = RotatingFileHandler(
        os.path.join(log_dir, "launcher.log"),
        maxBytes=1_000_000, backupCount=2, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s,%(msecs)03d %(name)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def main():
    os.makedirs(LAUNCHER_USERDIR, exist_ok=True)
    setup_logging(LAUNCHER_USERDIR)

    config = ConfigManager()
    config.load()

    app = QApplication(sys.argv)
    app.setApplicationName("The Cycle Launcher")
    apply_theme(app)
    icon_path = os.path.join(os.path.dirname(__file__), "assets", "icon.ico")
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    window = MainWindow(config)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
