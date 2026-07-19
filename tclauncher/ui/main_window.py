import logging
import time

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..auth import SessionManager
from ..backend import BackendClient, ServerDiscoveryStatus
from ..config import LAUNCHER_USERDIR, PROTOCOL_VERSION, ConfigManager
from ..desktop import open_path
from ..mods import ModManager
from ..runner import GAME_LOG, GameRunner, is_steam_running
from ..version import APP_VERSION
from .mods_dialog import ModsDialog
from .server_dialog import ServerDialog
from .settings_dialog import SettingsDialog
from .theme import STATUS_COLORS, TEXT_DIM
from .workers import run_worker

logger = logging.getLogger(__name__)


def primary_action(account_state: str, game_dir_ok: bool) -> str:
    """What the primary button does: 'login', 'locate' or 'play'.

    Logging in never requires game files, so a missing game directory only
    changes the action once the user is signed in and would otherwise Play.
    """
    if account_state != "signed_in":
        return "login"
    return "play" if game_dir_ok else "locate"


class MainWindow(QMainWindow):
    login_succeeded = Signal()
    game_exited = Signal()

    def __init__(self, config: ConfigManager):
        super().__init__()
        self.config = config
        self.backend = BackendClient(config)
        self.session_manager = SessionManager(config, self.backend)
        self.mod_manager = ModManager(config, self.backend)
        self.runner = GameRunner(config)

        self._logged_in = False
        self._server_online = False
        self._status_hold = False

        self.setWindowTitle("The Cycle Launcher")
        self.setMinimumSize(460, 500)
        self.resize(480, 520)

        self._build_ui()

        self.login_succeeded.connect(self._on_login_success)
        self.game_exited.connect(self._on_game_exit)

        self._refresh_account_ui()
        self._set_status("Select a server to begin", "offline")

        self.status_timer = QTimer(self)
        self.status_timer.setInterval(5000)
        self.status_timer.timeout.connect(self._poll_status)
        self.status_timer.start()

        self._startup_checks()

    # --- layout ---

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(28, 24, 28, 16)
        root.setSpacing(18)

        # Header
        header = QVBoxLayout()
        header.setSpacing(2)
        title = QLabel("THE CYCLE")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignHCenter)
        subtitle = QLabel("Community Launcher")
        subtitle.setObjectName("subtitle")
        subtitle.setAlignment(Qt.AlignHCenter)
        header.addWidget(title)
        header.addWidget(subtitle)
        root.addLayout(header)

        # Account card
        card = QFrame()
        card.setObjectName("card")
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 12, 12)
        card_layout.setSpacing(10)
        self.account_dot = QLabel("●")
        card_layout.addWidget(self.account_dot)
        self.account_label = QLabel("Not signed in")
        card_layout.addWidget(self.account_label)
        card_layout.addStretch()
        self.btn_logout = QPushButton("Log out")
        self.btn_logout.setObjectName("link")
        self.btn_logout.setCursor(Qt.PointingHandCursor)
        self.btn_logout.clicked.connect(self.log_out)
        card_layout.addWidget(self.btn_logout)
        root.addWidget(card)

        # Game files notice — visible while no valid game directory is set
        self.game_notice = QFrame()
        self.game_notice.setObjectName("card")
        notice_layout = QHBoxLayout(self.game_notice)
        notice_layout.setContentsMargins(14, 12, 12, 12)
        notice_layout.setSpacing(10)
        notice_dot = QLabel("●")
        notice_dot.setStyleSheet(f"color: {STATUS_COLORS['waiting']}; font-size: 13px;")
        notice_layout.addWidget(notice_dot)
        notice_text = QLabel("Game files not set — the install folder is usually named 'Release'")
        notice_text.setWordWrap(True)
        notice_layout.addWidget(notice_text, 1)
        self.btn_locate = QPushButton("Locate…")
        self.btn_locate.setObjectName("link")
        self.btn_locate.setCursor(Qt.PointingHandCursor)
        self.btn_locate.clicked.connect(self.locate_game_files)
        notice_layout.addWidget(self.btn_locate)
        self.game_notice.hide()
        root.addWidget(self.game_notice)

        root.addStretch()

        # Primary action
        self.btn_play = QPushButton()
        self.btn_play.setObjectName("primary")
        self.btn_play.setMinimumHeight(52)
        self.btn_play.setCursor(Qt.PointingHandCursor)
        self.btn_play.clicked.connect(self.on_primary_clicked)
        root.addWidget(self.btn_play)

        # Secondary actions
        secondary = QHBoxLayout()
        secondary.setSpacing(10)
        for text, slot in (
            ("Select server", self.open_server_dialog),
            ("Manage mods", self.open_mods_dialog),
            ("Settings", self.open_settings_dialog),
        ):
            btn = QPushButton(text)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(slot)
            secondary.addWidget(btn)
        root.addLayout(secondary)

        root.addStretch()

        # Status bar
        status = QHBoxLayout()
        status.setSpacing(8)
        self.status_dot = QLabel("●")
        status.addWidget(self.status_dot)
        self.status_label = QLabel("Select a server to begin")
        status.addWidget(self.status_label)
        status.addStretch()
        btn_logs = QPushButton("Logs")
        btn_logs.setObjectName("link")
        btn_logs.setCursor(Qt.PointingHandCursor)
        btn_logs.clicked.connect(lambda: self._open_host_path(LAUNCHER_USERDIR))
        status.addWidget(btn_logs)
        version = QLabel(f"v{APP_VERSION}")
        version.setObjectName("dim")
        status.addWidget(version)
        root.addLayout(status)

    # --- startup ---

    def _startup_checks(self):
        if self.config.server_discovery_addr:
            def on_discovered(status):
                if status == ServerDiscoveryStatus.LAUNCHER_OUTDATED:
                    self._set_status("This server requires a newer launcher", "offline")
                    self._status_hold = True
                else:
                    self._poll_status()
                    self._validate_session_async()

            run_worker(self.backend.discover, self.config.server_discovery_addr,
                       on_finished=on_discovered)
        self._check_launcher_update()

    def _check_launcher_update(self):
        if not self.config.server_discovery_addr:
            return

        def check():
            manifest = self.backend.launcher_update_manifest()
            if manifest and manifest.get("version") not in (None, PROTOCOL_VERSION):
                return manifest["version"]
            return None

        def notify(version):
            if version and not self._status_hold:
                self._set_status(f"Server expects launcher {version} (protocol may differ)", "waiting")

        run_worker(check, on_finished=notify)

    # --- account / session ---

    def _account_state(self) -> str:
        if self.session_manager.has_active_session():
            return "signed_in"
        if self.session_manager.has_refresh_token():
            return "expired"
        return "signed_out"

    def _refresh_account_ui(self):
        state = self._account_state()
        game_dir_ok = self.config.has_valid_game_dir()
        self._primary_action = primary_action(state, game_dir_ok)
        self.game_notice.setVisible(not game_dir_ok)
        if state == "signed_in":
            self._logged_in = True
            self.account_dot.setStyleSheet(f"color: {STATUS_COLORS['online']}; font-size: 13px;")
            self.account_label.setText("Signed in with Steam")
            self.btn_logout.show()
            self.btn_play.setText("Play" if self._primary_action == "play"
                                  else "Locate game files…")
        elif state == "expired":
            self._logged_in = False
            self.account_dot.setStyleSheet(f"color: {STATUS_COLORS['waiting']}; font-size: 13px;")
            self.account_label.setText("Session expired — sign in again")
            self.btn_logout.hide()
            self.btn_play.setText("Log in with Steam")
        else:
            self._logged_in = False
            self.account_dot.setStyleSheet(f"color: {TEXT_DIM}; font-size: 13px;")
            self.account_label.setText("Not signed in")
            self.btn_logout.hide()
            self.btn_play.setText("Log in with Steam")
        self._update_primary_enabled()

    def _validate_session_async(self):
        """Confirm a locally-valid session is still accepted by the server, so
        the button never shows 'Play' for a session the backend has expired."""
        if self._account_state() != "signed_in":
            return

        def check():
            return self.session_manager.is_valid_backend_session()

        def apply(valid):
            # Only downgrade on a definite rejection; is_valid_backend_session
            # also refreshes the token when it can, so a True keeps us signed in.
            if not valid:
                self.session_manager.invalidate_session()
                self.config.save()
                self._refresh_account_ui()

        run_worker(check, on_finished=apply)

    def _on_login_success(self):
        self._status_hold = False
        self._refresh_account_ui()
        self._poll_status()

    def _release_login_hold(self):
        """Recovery if the browser login is abandoned: resume status polling."""
        if self._status_hold and not self._logged_in:
            self._status_hold = False
            self._poll_status()

    def log_out(self):
        self.session_manager.invalidate_session()
        self.config.save()
        self._refresh_account_ui()

    # --- status bar ---

    def _set_status(self, text: str, state: str):
        self.status_label.setText(text)
        self.status_dot.setStyleSheet(f"color: {STATUS_COLORS.get(state, STATUS_COLORS['offline'])}; font-size: 13px;")
        self._server_online = state == "online"
        self._update_primary_enabled()

    def _update_primary_enabled(self):
        if self.runner.is_running():
            self.btn_play.setText("Stop game")
            self.btn_play.setEnabled(True)
            return
        action = getattr(self, "_primary_action", "login")
        if action == "locate":
            # Picking a folder needs neither a server nor a session.
            self.btn_play.setEnabled(True)
        elif action == "play":
            self.btn_play.setEnabled(self._server_online)
        else:
            # Login needs a server (its OpenID URL comes from the discovery addr).
            self.btn_play.setEnabled(bool(self.config.server_discovery_addr))

    def _poll_status(self):
        if self._status_hold or self.runner.is_running():
            return
        if self.config.backend_data is None:
            self._set_status("Select a server to begin", "offline")
            return

        def apply(data):
            if data is None:
                self._set_status("Server offline", "offline")
            else:
                self._set_status(f"{data['online']} players online", "online")

        run_worker(self.backend.server_status, on_finished=apply)

    # --- login / play ---

    def on_primary_clicked(self):
        if self.runner.is_running():
            answer = QMessageBox.question(
                self, "Stop game", "Stop the game process?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer == QMessageBox.Yes:
                self.runner.stop()
            return
        action = getattr(self, "_primary_action", "login")
        if action == "login":
            self._start_login()
        elif action == "locate":
            self.locate_game_files()
        else:
            self._start_play()

    def locate_game_files(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select game directory — usually a folder named 'Release'")
        if not path:
            return
        previous = self.config.game_dir
        self.config.game_dir = path
        if not self.config.has_valid_game_dir():
            self.config.game_dir = previous
            QMessageBox.warning(
                self, "The Cycle not found",
                "That folder does not contain The Cycle game files.\n\n"
                "Pick the game folder as distributed (usually named 'Release') — "
                "it contains Prospect/Binaries/Win64/Prospect-Win64-Shipping.exe.",
            )
            return
        self.config.save()
        self._refresh_account_ui()

    def _start_login(self):
        if not self.config.server_discovery_addr:
            QMessageBox.information(self, "Select a server first",
                                    "Choose a server, then log in with Steam.")
            return
        self._status_hold = True
        self._set_status("Waiting for browser sign-in…", "waiting")
        QTimer.singleShot(120_000, self._release_login_hold)
        self.session_manager.initiate_login(self.login_succeeded.emit)

    def _start_play(self):
        if not is_steam_running():
            answer = QMessageBox.warning(
                self, "Steam is not running",
                "The native Steam client does not appear to be running.\n\n"
                "The game authenticates through Steam, so launching without it "
                "will fail with an authentication error. Launch anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return

        self.btn_play.setEnabled(False)
        self._status_hold = True
        self._set_status("Checking mods and session…", "waiting")

        def preflight():
            if not self.mod_manager.are_mods_installed():
                return "mods"
            if not self.session_manager.is_valid_backend_session():
                return "session"
            return "ok"

        run_worker(preflight, on_finished=self._on_preflight_done,
                   on_failed=lambda e: self._launch_failed(str(e)))

    def _on_preflight_done(self, result: str):
        self._status_hold = False
        if result == "mods":
            self._launch_failed(None)
            QMessageBox.critical(self, "Mods verification failed",
                                 "Failed to verify mod installations. Open 'Manage mods' and install "
                                 "missing mods or reinstall corrupted mods.")
            return
        if result == "session":
            self.session_manager.invalidate_session()
            self.config.save()
            self._refresh_account_ui()
            self._launch_failed(None)
            QMessageBox.warning(self, "Session expired",
                                "Your game session is no longer valid. Log in with Steam again to play.")
            return

        first_run = not self.runner.prefix_initialized()
        try:
            self.runner.launch(on_exit=self.game_exited.emit)
        except Exception as e:
            logger.exception(e)
            self._launch_failed(str(e))
            return
        self._launch_started_at = time.monotonic()
        self._update_primary_enabled()
        if first_run:
            self._set_status(
                "First launch: Proton is downloading its runtime — this can take several minutes…",
                "waiting",
            )
        else:
            self._set_status("Game running…", "online")

    def _launch_failed(self, message: str | None):
        self._status_hold = False
        self._update_primary_enabled()
        self._poll_status()
        if message:
            QMessageBox.critical(self, "Launch Error", message)

    def _open_host_path(self, path: str):
        """Open a file/folder on the host, working around the frozen build's
        environment (see desktop.open_path); QDesktopServices as fallback."""
        if not open_path(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _on_game_exit(self):
        self.showNormal()
        elapsed = time.monotonic() - getattr(self, "_launch_started_at", 0.0)
        self._status_hold = False
        self._poll_status()
        self._refresh_account_ui()
        # A very short session usually means the game never really started
        # (Proton/asset error) or failed Steam auth immediately.
        if elapsed < 25 and not self.runner.user_stopped:
            box = QMessageBox(
                QMessageBox.Warning, "Game closed quickly",
                f"The game exited after about {elapsed:.0f} seconds.\n\n"
                "If no game window appeared, check the log at:\n"
                f"{GAME_LOG}\n\n"
                "The most common cause is that the native Steam client was not "
                "running and logged in — the game needs it to authenticate.",
                QMessageBox.Close, self,
            )
            open_btn = box.addButton("Open log", QMessageBox.ActionRole)
            box.exec()
            if box.clickedButton() is open_btn:
                self._open_host_path(GAME_LOG)

    # --- dialogs ---

    def open_server_dialog(self):
        dialog = ServerDialog(self.config, self.backend, self)
        dialog.exec()
        if dialog.accepted_new_server:
            # Match prospect-og: a new server means a new identity provider.
            self.session_manager.invalidate_session()
            self.config.save()
            self._refresh_account_ui()
            run_worker(self.mod_manager.load_mods)
            self._status_hold = False
            self._poll_status()

    def open_mods_dialog(self):
        if not self.config.has_valid_game_dir():
            QMessageBox.critical(self, "Game directory not set",
                                 "Locate your game files first — use the notice on the "
                                 "main screen or set the directory in Settings.")
            return
        ModsDialog(self.mod_manager, self).exec()

    def open_settings_dialog(self):
        dialog = SettingsDialog(self.config, self)
        dialog.exec()
        # Settings can change the game directory; re-derive notice/button state.
        self._refresh_account_ui()
