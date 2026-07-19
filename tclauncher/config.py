"""Launcher configuration, stored as JSON in ~/.tclauncher/config.json.

Keys shared with the original Windows launcher (prospect-og) keep the same
names so a config written by either launcher stays readable by the other.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

# Protocol version we present to servers. Must track prospect-og's VERSION:
# servers answer HTTP 426 on /launcher/discover for versions they reject.
PROTOCOL_VERSION = "1.0.3"
LAUNCHER_USERDIR = os.path.join(os.path.expanduser("~"), ".tclauncher")
CONFIG_FILE = os.path.join(LAUNCHER_USERDIR, "config.json")
DEFAULT_WINE_PREFIX = os.path.join(LAUNCHER_USERDIR, "prefix")

GAME_EXE_RELPATH = os.path.join("Prospect", "Binaries", "Win64", "Prospect-Win64-Shipping.exe")


class ConfigManager:
    def __init__(self, config_file: str = CONFIG_FILE):
        self.config_file = config_file
        # Keys shared with prospect-og
        self.backend_data: dict | None = None
        self.server_discovery_addr: str | None = None
        self.session_id: str = ""
        self.refresh_token: str = ""
        self.exp: int = 0
        self.run_args: list[str] = []
        # Linux-only keys
        self.game_dir: str = ""
        self.proton_path: str = ""
        self.wine_prefix: str = DEFAULT_WINE_PREFIX
        self.umu_path: str = ""
        self.env_vars: dict[str, str] = {}
        self.use_gamemode: bool = False
        self.use_mangohud: bool = False

    def load(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                logger.exception(e)
                return
            self.backend_data = data.get("backend_data", None)
            self.server_discovery_addr = data.get("server_discovery_addr", None)
            self.session_id = data.get("session_id", "")
            self.refresh_token = data.get("refresh_token", "")
            self.exp = data.get("exp", 0)
            self.run_args = data.get("run_args", [])
            self.game_dir = data.get("game_dir", "")
            self.proton_path = data.get("proton_path", "")
            self.wine_prefix = data.get("wine_prefix", DEFAULT_WINE_PREFIX)
            self.umu_path = data.get("umu_path", "")
            self.env_vars = data.get("env_vars", {})
            self.use_gamemode = data.get("use_gamemode", False)
            self.use_mangohud = data.get("use_mangohud", False)
        else:
            self.save()

    def save(self):
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        payload = {
            "backend_data": self.backend_data,
            "server_discovery_addr": self.server_discovery_addr,
            "session_id": self.session_id,
            "refresh_token": self.refresh_token,
            "exp": self.exp,
            "run_args": self.run_args,
            "game_dir": self.game_dir,
            "proton_path": self.proton_path,
            "wine_prefix": self.wine_prefix,
            "umu_path": self.umu_path,
            "env_vars": self.env_vars,
            "use_gamemode": self.use_gamemode,
            "use_mangohud": self.use_mangohud,
        }
        # Write-then-rename so a crash mid-write can't corrupt the config.
        tmp_path = self.config_file + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
        os.replace(tmp_path, self.config_file)

    def game_exe(self) -> str:
        return os.path.join(self.game_dir, GAME_EXE_RELPATH)

    def has_valid_game_dir(self) -> bool:
        return bool(self.game_dir) and os.path.isfile(self.game_exe())
