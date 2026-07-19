from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from ..backend import BackendClient, ServerDiscoveryStatus
from ..config import ConfigManager
from .workers import run_worker


class ServerDialog(QDialog):
    """Enter a server discovery URL; on save, run discovery and persist it."""

    def __init__(self, config: ConfigManager, backend: BackendClient, parent=None):
        super().__init__(parent)
        self.config = config
        self.backend = backend
        self.accepted_new_server = False

        self.setWindowTitle("Select server")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Enter server URL:"))
        self.url_edit = QLineEdit(self.config.server_discovery_addr or "http://127.0.0.1:8080")
        layout.addWidget(self.url_edit)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _save(self):
        url = self.url_edit.text().strip()
        if not url.startswith("http"):
            QMessageBox.critical(self, "Invalid server URL", "Server URL must start with 'http'.")
            return
        url = url.rstrip("/")
        self.buttons.setEnabled(False)
        run_worker(
            self.backend.discover, url,
            on_finished=lambda status: self._on_discovered(url, status),
        )

    def _on_discovered(self, url: str, status: ServerDiscoveryStatus):
        self.buttons.setEnabled(True)
        if status == ServerDiscoveryStatus.LAUNCHER_OUTDATED:
            QMessageBox.critical(self, "Incompatible launcher",
                                 "Your launcher version is incompatible with this server.")
            return
        if status == ServerDiscoveryStatus.UNKNOWN_ERROR:
            QMessageBox.critical(self, "Server discovery failed",
                                 "Failed to fetch server information. Make sure that the specified server URL is correct.")
            return
        self.config.server_discovery_addr = url
        self.config.save()
        self.accepted_new_server = True
        self.accept()
