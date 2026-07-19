from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..mods import Mod, ModManager, ModStatus
from .theme import ACCENT, OK, TEXT_DIM, WARN
from .workers import run_worker

STATUS_STYLE = {
    ModStatus.UP_TO_DATE: OK,
    ModStatus.UPDATE_AVAILABLE: WARN,
    ModStatus.CORRUPTED_INSTALLATION: "#e5533c",
    ModStatus.NOT_INSTALLED: TEXT_DIM,
}


class ModsDialog(QDialog):
    def __init__(self, mod_manager: ModManager, parent=None):
        super().__init__(parent)
        self.mod_manager = mod_manager

        self.setWindowTitle("Mod manager")
        self.resize(600, 400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        title = QLabel("Installed & available mods")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.addStretch()
        scroll.setWidget(self.list_container)
        layout.addWidget(scroll)

        self.progress_label = QLabel("")
        layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.buttons: list[QPushButton] = []
        self.refresh()

    def refresh(self):
        self.progress_label.setText("Loading mods...")
        run_worker(self.mod_manager.get_mods_with_statuses, on_finished=self._populate,
                   on_failed=lambda e: self.progress_label.setText(f"Failed to load mods: {e}"))

    def _populate(self, mods: list[Mod]):
        self.progress_label.setText("")
        self.buttons = []
        # Clear all rows except the trailing stretch
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not mods:
            empty = QLabel("The selected server does not use any mods.")
            empty.setObjectName("dim")
            self.list_layout.insertWidget(0, empty)
            return

        for mod in mods:
            row = QFrame()
            row.setObjectName("modRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(12, 10, 12, 10)
            row_layout.setSpacing(10)

            name = mod.remote["name"]
            if mod.remote["author"]:
                name += f" by {mod.remote['author']}"
            if mod.local is not None:
                name += f" ({mod.local['version']})"

            text = QVBoxLayout()
            text.setSpacing(2)
            name_label = QLabel(name)
            status_label = QLabel(mod.status.value)
            status_label.setStyleSheet(f"color: {STATUS_STYLE[mod.status]}; font-size: 11px;")
            text.addWidget(name_label)
            text.addWidget(status_label)
            row_layout.addLayout(text)
            row_layout.addStretch()

            if mod.status != ModStatus.UP_TO_DATE:
                action = "Install"
                if mod.status == ModStatus.UPDATE_AVAILABLE:
                    action = f"Update to {mod.remote['version']}"
                elif mod.status == ModStatus.CORRUPTED_INSTALLATION:
                    action = "Reinstall"
                btn = QPushButton(action)
                btn.clicked.connect(lambda checked=False, m=mod: self._install(m))
                row_layout.addWidget(btn)
                self.buttons.append(btn)

            self.list_layout.insertWidget(self.list_layout.count() - 1, row)

    def _install(self, mod: Mod):
        for btn in self.buttons:
            btn.setEnabled(False)
        self.progress_label.setText(f"Installing {mod.remote['name']}...")
        self.progress_bar.setValue(0)
        self.progress_bar.show()

        run_worker(
            self.mod_manager.install_mod, mod,
            on_finished=lambda _: self._install_done(mod, ok=True),
            on_failed=lambda e: self._install_done(mod, ok=False),
            on_progress=lambda p: self.progress_bar.setValue(int(p * 100)),
        )

    def _install_done(self, mod: Mod, ok: bool):
        self.progress_bar.hide()
        if ok:
            self.progress_label.setText(f"{mod.remote['name']} installed.")
        else:
            self.progress_label.setText(f"Failed to install {mod.remote['name']}.")
        self.refresh()
