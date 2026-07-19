"""Launching the Windows game on Linux via umu-launcher + Proton.

The game obtains its Steam auth ticket through steam_api64.dll, which only
works when Proton can bridge to a running native Steam client — hence the
Steam preflight check and the strong preference for umu/Proton over raw Wine.
"""

import glob
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Callable

from .config import LAUNCHER_USERDIR, ConfigManager
from .desktop import clean_child_env

logger = logging.getLogger(__name__)

GAME_LOG = os.path.join(LAUNCHER_USERDIR, "game.log")

STEAM_APPID = "480"

PROTON_SEARCH_GLOBS = [
    "~/.steam/steam/steamapps/common/Proton*",
    "~/.steam/steam/compatibilitytools.d/*",
    "~/.local/share/Steam/steamapps/common/Proton*",
    "~/.local/share/Steam/compatibilitytools.d/*",
    "~/.var/app/com.valvesoftware.Steam/data/Steam/steamapps/common/Proton*",
    "~/.var/app/com.valvesoftware.Steam/data/Steam/compatibilitytools.d/*",
]

STEAM_PID_FILES = [
    "~/.steam/steam.pid",
    "~/.var/app/com.valvesoftware.Steam/.steam/steam.pid",
]

# Candidate native Steam client install directories, in priority order.
STEAM_INSTALL_DIRS = [
    "~/.steam/steam",
    "~/.local/share/Steam",
    "~/.steam/root",
    "~/.var/app/com.valvesoftware.Steam/data/Steam",
]


def find_steam_install_path() -> str | None:
    """Locate the native Steam client install dir.

    Proton needs this (STEAM_COMPAT_CLIENT_INSTALL_PATH) to install the
    steamclient bridge into the prefix; without it the game's SteamAPI_Init
    fails with "conditions not met" and login returns SteamUnavailable.
    """
    for candidate in STEAM_INSTALL_DIRS:
        path = os.path.expanduser(candidate)
        # 'legacycompat' holds the steamclient DLLs Proton copies into the prefix.
        if os.path.isdir(os.path.join(path, "legacycompat")) or os.path.isfile(
            os.path.join(path, "steam.sh")
        ):
            return os.path.realpath(path)
    return None


@dataclass
class ProtonInstall:
    name: str
    path: str


def find_proton_installs() -> list[ProtonInstall]:
    installs = []
    seen = set()
    for pattern in PROTON_SEARCH_GLOBS:
        for path in sorted(glob.glob(os.path.expanduser(pattern))):
            real = os.path.realpath(path)
            if real in seen:
                continue
            if os.path.isfile(os.path.join(path, "proton")):
                seen.add(real)
                installs.append(ProtonInstall(name=os.path.basename(path), path=path))
    return installs


def find_umu(config_override: str = "") -> str | None:
    if config_override:
        return config_override if os.path.isfile(config_override) else None
    return shutil.which("umu-run")


def is_steam_running() -> bool:
    for pid_file in STEAM_PID_FILES:
        try:
            with open(os.path.expanduser(pid_file)) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)  # existence check only
            return True
        except (OSError, ValueError):
            continue
    # Fallback for setups without a pid file
    return subprocess.run(["pgrep", "-x", "steam"], capture_output=True).returncode == 0


class GameRunner:
    def __init__(self, config: ConfigManager):
        self.config = config
        self.process: subprocess.Popen | None = None
        self.user_stopped = False

    def is_running(self) -> bool:
        return self.process is not None

    def prefix_initialized(self) -> bool:
        """True once Proton has built the prefix. When False, the next launch
        is a slow first run (runtime download + prefix creation)."""
        prefix = os.path.expanduser(self.config.wine_prefix)
        return os.path.exists(os.path.join(prefix, "system.reg"))

    def write_steam_appid(self):
        appid_path = os.path.join(os.path.dirname(self.config.game_exe()), "steam_appid.txt")
        try:
            with open(appid_path, "w") as f:
                f.write(STEAM_APPID)
        except OSError as e:
            raise RuntimeError(f"Game directory is not writable: {appid_path} ({e})") from e

    def build_command(self) -> tuple[list[str], dict[str, str]]:
        """Returns (argv, env) for the game launch. Raises RuntimeError on
        missing prerequisites so the UI can show a precise message."""
        if self.config.backend_data is None:
            raise RuntimeError("No server selected. Use 'Select server' first.")
        if not self.config.has_valid_game_dir():
            raise RuntimeError("Game directory is not set or does not contain the game executable.")

        umu = find_umu(self.config.umu_path)
        if umu is None:
            raise RuntimeError(
                "umu-run not found. Install umu-launcher (https://github.com/Open-Wine-Components/umu-launcher) "
                "or set its path in Settings."
            )
        if not self.config.proton_path:
            raise RuntimeError("No Proton version selected. Pick one in Settings.")

        env = dict(os.environ)
        if getattr(sys, "frozen", False):
            # The whole launch chain (gamemoderun/mangohud are bash scripts,
            # umu-run is host Python) must use HOST libraries, not the frozen
            # bundle's: PyInstaller's LD_LIBRARY_PATH makes host bash resolve
            # symbols against the bundled (older) libreadline and crash.
            env = clean_child_env(env)
        env.update(self.config.env_vars)
        env["WINEPREFIX"] = os.path.expanduser(self.config.wine_prefix)
        env["PROTONPATH"] = self.config.proton_path
        env["STORE"] = "none"
        # GAMEID drives the appid umu passes to the game: umu parses the part
        # after "umu-", so "umu-480" yields SteamAppId 480 (Spacewar). The
        # default "umu-default" yields an invalid appid and Steam init fails.
        env["GAMEID"] = f"umu-{STEAM_APPID}"
        env["SteamAppId"] = STEAM_APPID
        env["SteamGameId"] = STEAM_APPID
        # Skip umu's pressure-vessel container: inside it the game cannot reach
        # the host Steam client's IPC sockets, so SteamAPI_Init fails with
        # "conditions not met" and login returns SteamUnavailable. Running
        # Proton directly on the host lets Steam auth succeed.
        env["UMU_NO_RUNTIME"] = "1"
        # Point Proton at the Steam client so it installs the steamclient bridge
        # DLLs into the prefix. Fall back to the configured value if detection
        # fails (e.g. an unusual install location).
        steam_path = find_steam_install_path()
        if steam_path:
            env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = steam_path

        argv = []
        if self.config.use_gamemode:
            if shutil.which("gamemoderun") is None:
                raise RuntimeError("gamemoderun not found but the GameMode option is enabled.")
            argv.append("gamemoderun")
        if self.config.use_mangohud:
            if shutil.which("mangohud") is None:
                raise RuntimeError("mangohud not found but the MangoHud option is enabled.")
            argv.append("mangohud")

        argv += [
            umu,
            self.config.game_exe(),
            "-backend", self.config.backend_data["backend_game"],
            "-steam_auth", self.config.backend_data["steam_auth"],
            "-analytics", self.config.backend_data["analytics"],
        ]
        argv += self.config.run_args
        return argv, env

    def launch(self, on_exit: Callable | None = None):
        """Start the game and watch it on a background thread.

        Child stdout/stderr go to GAME_LOG. This is essential on the first
        launch: umu downloads the Steam Linux Runtime and builds the Proton
        prefix, which takes minutes with no game window — without a captured
        log the launcher looks frozen and failures are invisible.
        """
        argv, env = self.build_command()
        os.makedirs(os.path.expanduser(self.config.wine_prefix), exist_ok=True)
        self.write_steam_appid()
        logger.info(f"Launching (output -> {GAME_LOG}): {argv}")

        log_file = open(GAME_LOG, "w")
        log_file.write("Launching: " + " ".join(argv) + "\n\n")
        log_file.flush()
        self.user_stopped = False
        self.process = subprocess.Popen(
            argv, env=env, cwd=self.config.game_dir,
            stdout=log_file, stderr=subprocess.STDOUT,
            start_new_session=True,
        )

        def watch():
            self.process.wait()
            returncode = self.process.returncode
            self.process = None
            log_file.close()
            logger.info(f"Game process exited with code {returncode}")
            if on_exit is not None:
                on_exit()

        threading.Thread(target=watch, daemon=True).start()

    def stop(self):
        """User-requested stop: terminate, and kill after a grace period.
        Signals the whole process group — self.process is the umu wrapper;
        the game lives in grandchildren (proton → wine). The watch() thread
        still delivers the exit notification."""
        process = self.process
        if process is None:
            return
        self.user_stopped = True
        logger.info("Stopping game process group on user request")
        self._signal_tree(process, signal.SIGTERM)

        def enforce():
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("Game did not exit after terminate; killing")
                self._signal_tree(process, signal.SIGKILL)

        threading.Thread(target=enforce, daemon=True).start()

    @staticmethod
    def _signal_tree(process: subprocess.Popen, sig: int):
        try:
            os.killpg(os.getpgid(process.pid), sig)
        except (ProcessLookupError, PermissionError):
            # Group gone or not ours (already reaped, or start_new_session
            # unavailable): fall back to the process itself.
            try:
                process.send_signal(sig)
            except ProcessLookupError:
                pass
