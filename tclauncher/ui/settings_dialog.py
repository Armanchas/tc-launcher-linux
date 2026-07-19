import shlex

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..config import ConfigManager
from ..runner import find_proton_installs


class SettingsDialog(QDialog):
    def __init__(self, config: ConfigManager, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Settings")
        self.resize(640, 520)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        # Game directory
        self.game_dir_edit = QLineEdit(self.config.game_dir)
        form.addRow("Game directory:", self._with_browse(self.game_dir_edit, directory=True))

        # Proton picker
        proton_row = QHBoxLayout()
        self.proton_combo = QComboBox()
        self.proton_combo.setEditable(False)
        proton_row.addWidget(self.proton_combo, stretch=1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._populate_protons)
        proton_row.addWidget(refresh_btn)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_proton)
        proton_row.addWidget(browse_btn)
        form.addRow("Proton version:", proton_row)

        # Wine prefix
        self.prefix_edit = QLineEdit(self.config.wine_prefix)
        form.addRow("Wine prefix:", self._with_browse(self.prefix_edit, directory=True))

        # umu path override
        self.umu_edit = QLineEdit(self.config.umu_path)
        self.umu_edit.setPlaceholderText("Auto-detect umu-run on PATH")
        form.addRow("umu-run path:", self._with_browse(self.umu_edit, directory=False))

        # Launch flags
        self.args_edit = QLineEdit(shlex.join(self.config.run_args))
        self.args_edit.setPlaceholderText("Extra game command-line flags, e.g. -log -nosplash")
        form.addRow("Launch flags:", self.args_edit)

        # Toggles
        self.gamemode_check = QCheckBox("Run with GameMode (gamemoderun)")
        self.gamemode_check.setChecked(self.config.use_gamemode)
        form.addRow(self.gamemode_check)
        self.mangohud_check = QCheckBox("Enable MangoHud overlay")
        self.mangohud_check.setChecked(self.config.use_mangohud)
        form.addRow(self.mangohud_check)

        # Env vars table
        self.env_table = QTableWidget(0, 2)
        self.env_table.setHorizontalHeaderLabels(["Variable", "Value"])
        self.env_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for name, value in self.config.env_vars.items():
            self._add_env_row(name, value)
        form.addRow("Environment variables:", self.env_table)

        env_btns = QHBoxLayout()
        add_btn = QPushButton("Add variable")
        add_btn.clicked.connect(lambda: self._add_env_row("", ""))
        env_btns.addWidget(add_btn)
        del_btn = QPushButton("Remove selected")
        del_btn.clicked.connect(self._remove_env_row)
        env_btns.addWidget(del_btn)
        env_btns.addStretch()
        form.addRow("", env_btns)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._populate_protons()

    def _with_browse(self, edit: QLineEdit, directory: bool):
        row = QHBoxLayout()
        row.addWidget(edit, stretch=1)
        btn = QPushButton("Browse...")

        def browse():
            if directory:
                path = QFileDialog.getExistingDirectory(self, "Select directory", edit.text())
            else:
                path, _ = QFileDialog.getOpenFileName(self, "Select file", edit.text())
            if path:
                edit.setText(path)

        btn.clicked.connect(browse)
        row.addWidget(btn)
        return row

    def _populate_protons(self):
        self.proton_combo.clear()
        installs = find_proton_installs()
        current_index = 0
        for i, install in enumerate(installs):
            self.proton_combo.addItem(f"{install.name}", install.path)
            if install.path == self.config.proton_path:
                current_index = i
        if self.config.proton_path and self.config.proton_path not in [i.path for i in installs]:
            self.proton_combo.addItem(self.config.proton_path, self.config.proton_path)
            current_index = self.proton_combo.count() - 1
        if self.proton_combo.count() == 0:
            self.proton_combo.addItem("No Proton installations found", "")
        self.proton_combo.setCurrentIndex(current_index)

    def _browse_proton(self):
        path = QFileDialog.getExistingDirectory(self, "Select Proton directory")
        if path:
            self.proton_combo.addItem(path, path)
            self.proton_combo.setCurrentIndex(self.proton_combo.count() - 1)

    def _add_env_row(self, name: str, value: str):
        row = self.env_table.rowCount()
        self.env_table.insertRow(row)
        self.env_table.setItem(row, 0, QTableWidgetItem(name))
        self.env_table.setItem(row, 1, QTableWidgetItem(value))

    def _remove_env_row(self):
        row = self.env_table.currentRow()
        if row >= 0:
            self.env_table.removeRow(row)

    def _save(self):
        try:
            run_args = shlex.split(self.args_edit.text())
        except ValueError as e:
            QMessageBox.critical(self, "Invalid launch flags", str(e))
            return

        env_vars = {}
        for row in range(self.env_table.rowCount()):
            name_item = self.env_table.item(row, 0)
            value_item = self.env_table.item(row, 1)
            name = name_item.text().strip() if name_item else ""
            if name:
                env_vars[name] = value_item.text() if value_item else ""

        self.config.game_dir = self.game_dir_edit.text().strip()
        self.config.proton_path = self.proton_combo.currentData() or ""
        self.config.wine_prefix = self.prefix_edit.text().strip()
        self.config.umu_path = self.umu_edit.text().strip()
        self.config.run_args = run_args
        self.config.use_gamemode = self.gamemode_check.isChecked()
        self.config.use_mangohud = self.mangohud_check.isChecked()
        self.config.env_vars = env_vars
        self.config.save()
        self.accept()
