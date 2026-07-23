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


# (pid file, install dir, kind) for the native and Flatpak Steam clients, in
# priority order. Drives running_steam() below.
_STEAM_CANDIDATES = [
    ("~/.steam/steam.pid", "~/.steam/steam", "native"),
    (
        "~/.var/app/com.valvesoftware.Steam/.steam/steam.pid",
        "~/.var/app/com.valvesoftware.Steam/data/Steam",
        "flatpak",
    ),
]


def steam_install_kind(path: str) -> str:
    """Classify a Steam install path as 'flatpak' or 'native'."""
    return "flatpak" if "com.valvesoftware.Steam" in path else "native"


def running_steam() -> tuple[str, str] | None:
    """(install_path, kind) of the Steam client that is actually running, else
    None.

    Distinct from find_steam_install_path(): that finds *an* install on disk;
    this finds the one whose pid file points at a live process. When the two
    disagree — Proton bridges to the install we name in
    STEAM_COMPAT_CLIENT_INSTALL_PATH, but the auth ticket must come from the
    client that's actually running — SteamAPI_Init fails "conditions not met".
    """
    for pid_file, install, kind in _STEAM_CANDIDATES:
        try:
            with open(os.path.expanduser(pid_file)) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)  # existence check only
        except (OSError, ValueError):
            continue
        return os.path.realpath(os.path.expanduser(install)), kind
    return None


def runtime_versions() -> list[str]:
    """Best-effort Steam Runtime + pressure-vessel versions from umu's cache.

    These vary between machines (a fresh download vs a stale cache) and the
    pressure-vessel version governs how Steam IPC is bridged into the
    container, so they're worth capturing when Steam auth misbehaves.
    """
    out = []
    base = os.path.expanduser("~/.local/share/umu")
    for rt in ("steamrt3", "steamrt4"):
        try:
            with open(os.path.join(base, rt, "VERSIONS.txt")) as f:
                text = f.read()
        except OSError:
            continue
        depot = pv = ""
        for line in text.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "depot":
                depot = parts[1]
            elif len(parts) >= 2 and parts[0] == "pressure-vessel":
                pv = parts[1]
        out.append(f"{rt}: depot {depot or '?'}, pressure-vessel {pv or '?'}")
    return out


def steam_preflight_issue(config_compat: str = "") -> str | None:
    """A user-facing warning if the Steam setup looks like it will fail
    SteamAPI_Init, else None. `config_compat` is any user-set
    STEAM_COMPAT_CLIENT_INSTALL_PATH (Settings), which overrides detection.
    """
    running = running_steam()
    if running is None:
        if is_steam_running():
            return None  # running but no readable pid file — can't say more
        return (
            "The native Steam client does not appear to be running. The game "
            "authenticates through Steam, so launching without it will fail "
            "with an authentication error."
        )
    run_path, _run_kind = running
    compat = config_compat or (find_steam_install_path() or "")
    if compat and os.path.realpath(os.path.expanduser(compat)) != run_path:
        return (
            f"The Steam install the game will use ({compat}) is not the one "
            f"currently running ({run_path}). Steam auth may fail with "
            "'conditions not met'. Set STEAM_COMPAT_CLIENT_INSTALL_PATH under "
            "Settings to the running install, or start that Steam client."
        )
    return None


# Env keys worth capturing for Steam/Proton/container triage. Prefix-matched
# keys plus a few exact ones. Allowlisted (not a full os.environ dump) so we
# never write unrelated secrets/tokens into a log the user will share.
_DIAG_ENV_PREFIXES = ("STEAM", "PROTON", "PRESSURE_VESSEL", "UMU", "DXVK",
                      "VKD3D", "WINE")
_DIAG_ENV_KEYS = ("GAMEID", "STORE", "XDG_RUNTIME_DIR", "LD_PRELOAD",
                  "MANGOHUD", "ENABLE_GAMEMODE", "LANG")


def relevant_env(env: dict) -> list[str]:
    """Sorted 'KEY=VALUE' lines for the allowlisted Steam/Proton/container env
    vars present in `env`. Allowlisted to avoid leaking unrelated secrets."""
    keys = {k for k in _DIAG_ENV_KEYS if k in env}
    for k in env:
        if any(k.startswith(p) for p in _DIAG_ENV_PREFIXES):
            keys.add(k)
    return [f"{k}={env[k]}" for k in sorted(keys)]


def system_summary() -> str:
    """Distro + kernel — CachyOS vs other, and kernel matters for
    pressure-vessel / ntsync behaviour."""
    pretty = "?"
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    pretty = line.split("=", 1)[1].strip().strip('"')
                    break
    except OSError:
        pass
    try:
        release = os.uname().release
    except OSError:
        release = "?"
    return f"{pretty}, kernel {release}"


def prefix_steam_bridge(wineprefix: str) -> str:
    """Whether Proton installed the steamclient bridge DLL into the prefix.
    If it's MISSING on a built prefix, SteamAPI_Init can't reach Steam at all —
    that alone explains 'conditions not met'."""
    if not wineprefix or not os.path.exists(os.path.join(wineprefix, "system.reg")):
        return "prefix not built yet (first run)"
    dll = os.path.join(
        wineprefix, "drive_c", "Program Files (x86)", "Steam", "steamclient64.dll"
    )
    if os.path.isfile(dll):
        return "present"
    return "MISSING (Proton did not install the steamclient bridge)"


# (source name in <steam>/legacycompat/, dest name in the prefix Steam dir).
# Mirrors what GE-Proton's `proton` setup_prefix copies; SteamService.exe is
# installed as steam.exe. install_steam_bridge() below does this copy ourselves
# because umu drops STEAM_COMPAT_CLIENT_INSTALL_PATH before Proton runs.
_STEAM_BRIDGE_FILES = [
    ("steamclient.dll", "steamclient.dll"),
    ("steamclient64.dll", "steamclient64.dll"),
    ("GameOverlayRenderer64.dll", "GameOverlayRenderer64.dll"),
    ("SteamService.exe", "steam.exe"),
    ("Steam.dll", "Steam.dll"),
]


def install_steam_bridge(steam_path: str, wineprefix: str) -> str:
    """Copy the Windows steamclient bridge DLLs from the host Steam client's
    legacycompat/ dir into the prefix's Program Files (x86)/Steam/, so the
    game's SteamAPI_Init can reach the running Steam client.

    Proton's setup_prefix is supposed to do this, but umu never forwards our
    STEAM_COMPAT_CLIENT_INSTALL_PATH to Proton — it seeds the value empty and
    overwrites ours (umu_run.py) — so Proton's copy silently no-ops and the
    prefix Steam dir is left empty (-> 'conditions not met' -> SteamUnavailable).
    We do the copy ourselves, dereferencing symlinks (wine can't follow a
    host-absolute symlink from inside the prefix) and overwriting each launch so
    host Steam client updates are picked up. Returns a one-line summary for the
    launch log.
    """
    src_dir = os.path.join(os.path.expanduser(steam_path), "legacycompat")
    dest_dir = os.path.join(
        os.path.expanduser(wineprefix), "drive_c", "Program Files (x86)", "Steam"
    )
    if not os.path.isdir(src_dir):
        return (
            f"legacycompat not found at {src_dir}; steamclient bridge not "
            "installed (update/restart Steam so it downloads its Proton files)"
        )
    os.makedirs(dest_dir, exist_ok=True)
    installed, missing = [], []
    for src_name, dest_name in _STEAM_BRIDGE_FILES:
        src = os.path.join(src_dir, src_name)
        if not os.path.isfile(src):  # isfile() follows symlinks
            missing.append(src_name)
            continue
        # copyfile() dereferences symlinks, producing a real file in the prefix.
        shutil.copyfile(src, os.path.join(dest_dir, dest_name))
        installed.append(dest_name)
    summary = f"installed {len(installed)}/{len(_STEAM_BRIDGE_FILES)} into {dest_dir}"
    if missing:
        summary += f" (missing sources: {', '.join(missing)})"
    return summary


def steam_login_summary(steam_path: str) -> str:
    """Best-effort read of loginusers.vdf: account count, most-recent flag, and
    a warning if any account has WantsOfflineMode=1 (offline mode blocks auth).
    Deliberately logs no account/persona names (PII)."""
    if not steam_path:
        return "unknown (no Steam path)"
    vdf = os.path.join(steam_path, "config", "loginusers.vdf")
    try:
        with open(vdf) as f:
            text = f.read()
    except OSError:
        return "no loginusers.vdf (Steam never logged in on this install?)"
    import re

    compact = re.sub(r"\s+", "", text)
    n = len(re.findall(r'"\d{17}"', text))
    most_recent = "yes" if '"MostRecent""1"' in compact else "no"
    parts = [f"{n} account(s)", f"most-recent set: {most_recent}"]
    if '"WantsOfflineMode""1"' in compact:
        parts.append("WARNING: an account has WantsOfflineMode=1 (blocks auth)")
    return ", ".join(parts)


def steam_process_hint() -> str | None:
    """When no Steam pid file is readable, locate a running steam via pgrep +
    /proc so the log still shows which binary is running."""
    try:
        out = subprocess.run(
            ["pgrep", "-x", "steam"], capture_output=True, text=True
        )
    except OSError:
        return None
    for pid in out.stdout.split():
        try:
            return f"pid {pid} -> {os.readlink(f'/proc/{pid}/exe')}"
        except OSError:
            continue
    return None


def format_launch_diagnostics(env: dict, game_exe_dir: str) -> str:
    """A human-readable env snapshot for the top of game.log, so a failing
    tester's log alone pins down Steam-auth problems instead of needing a
    second machine to diff against.
    """
    from .version import APP_VERSION

    build = "AppImage" if getattr(sys, "frozen", False) else "source"
    lines = ["=== launch diagnostics ==="]
    lines.append(f"launcher = TCLauncher {APP_VERSION} ({build})")
    lines.append(f"system = {system_summary()}")
    lines.append(f"PROTONPATH = {env.get('PROTONPATH', '(unset)')}")
    lines.append(f"WINEPREFIX = {env.get('WINEPREFIX', '(unset)')}")
    lines.append(f"GAMEID = {env.get('GAMEID', '(unset)')}")

    compat = env.get("STEAM_COMPAT_CLIENT_INSTALL_PATH", "")
    if compat:
        lines.append(
            f"STEAM_COMPAT_CLIENT_INSTALL_PATH = {compat} "
            f"({steam_install_kind(compat)})"
        )
    else:
        lines.append("STEAM_COMPAT_CLIENT_INSTALL_PATH = (unset)")

    running = running_steam()
    steam_path_for_login = compat
    if running is None:
        lines.append(
            "running Steam client: NONE DETECTED — Steamworks auth will fail "
            "with 'conditions not met'. Start Steam and log in."
        )
        hint = steam_process_hint()
        if hint:
            lines.append(f"  (but a steam process is alive: {hint})")
    else:
        run_path, run_kind = running
        steam_path_for_login = run_path
        lines.append(f"running Steam client: {run_path} ({run_kind})")
        if compat and os.path.realpath(os.path.expanduser(compat)) != run_path:
            lines.append(
                f"  WARNING: compat path ({os.path.realpath(compat)}) is not the "
                f"running Steam install ({run_path}); the auth ticket comes from "
                "the running client — set STEAM_COMPAT_CLIENT_INSTALL_PATH to "
                "match it."
            )

    lines.append(f"Steam login (on-disk): {steam_login_summary(steam_path_for_login)}")
    lines.append(
        f"prefix Steam bridge: {prefix_steam_bridge(env.get('WINEPREFIX', ''))}"
    )

    appid_file = os.path.join(game_exe_dir, "steam_appid.txt")
    lines.append(
        f"steam_appid.txt: {appid_file} "
        f"({'present' if os.path.isfile(appid_file) else 'MISSING'})"
    )

    for rv in runtime_versions():
        lines.append(rv)

    lines.append("relevant env:")
    for line in relevant_env(env):
        lines.append(f"  {line}")

    lines.append("=== end diagnostics ===")
    return "\n".join(lines)


class GameRunner:
    def __init__(self, config: ConfigManager):
        self.config = config
        self.process: subprocess.Popen | None = None
        self.user_stopped = False
        # True from launch() until the game process exits. Distinct from
        # `process`, which is briefly None during the first-run createprefix
        # pass (and between it and the game start) — is_running() must stay
        # true across that gap so the UI keeps showing "Stop game".
        self._starting = False

    def is_running(self) -> bool:
        return self._starting or self.process is not None

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
        # Historically believed to skip umu's pressure-vessel container so the
        # game could reach the host Steam client's IPC. In umu 1.4.x this var is
        # vestigial: umu writes it into the env but never consumes it, and the
        # container always runs. Steam auth works fine *through* the container
        # (verified: GE-Proton11-1/steamrt4 succeeds here). When it fails with
        # "conditions not met" the cause is the host Steam client being
        # unreachable (not running, not logged in, or a compat-path/running-
        # install mismatch), which the launch diagnostics below surface. Kept
        # because it's harmless. See CLAUDE.md "Steam auth is a Steam-client
        # reachability problem".
        env["UMU_NO_RUNTIME"] = "1"
        # Point Proton at the Steam client so it installs the steamclient bridge
        # DLLs into the prefix. An explicit value (Settings env vars, or the
        # launcher's own environment) wins over detection; without either, the
        # game would boot but Steam login would fail — refuse to launch.
        if not env.get("STEAM_COMPAT_CLIENT_INSTALL_PATH"):
            steam_path = find_steam_install_path()
            if steam_path is None:
                raise RuntimeError(
                    "Steam client installation not found (looked in ~/.steam, "
                    "~/.local/share/Steam and the Flatpak data dir). The game needs it "
                    "for Steam login. If Steam is installed somewhere unusual, set "
                    "STEAM_COMPAT_CLIENT_INSTALL_PATH under Settings → Environment "
                    "variables."
                )
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

    def _run_createprefix(self, umu: str, env: dict, log_file) -> bool:
        """Build the Proton prefix without launching the game (umu's
        'createprefix' verb), so install_steam_bridge() can drop the steamclient
        DLLs in before the game calls SteamAPI_Init. A normal launch builds the
        prefix and starts the game in one umu invocation, leaving no such window.
        Returns True if the prefix is ready, False if stopped or it failed."""
        log_file.write("First run: building Proton prefix (umu createprefix)…\n\n")
        log_file.flush()
        self.process = subprocess.Popen(
            [umu, "createprefix"], env=env, cwd=self.config.game_dir,
            stdout=log_file, stderr=subprocess.STDOUT, start_new_session=True,
        )
        self.process.wait()
        rc = self.process.returncode
        self.process = None
        if self.user_stopped:
            return False
        if rc != 0:
            log_file.write(f"(umu createprefix exited {rc})\n\n")
            log_file.flush()
        return self.prefix_initialized()

    def launch(self, on_exit: Callable | None = None):
        """Start the game and watch it on a background thread.

        Child stdout/stderr go to GAME_LOG. This is essential on the first
        launch: umu downloads the Steam Linux Runtime and builds the Proton
        prefix, which takes minutes with no game window — without a captured
        log the launcher looks frozen and failures are invisible.

        The whole sequence — first-run prefix build, steamclient bridge
        install, then the game — runs on a background thread so the slow
        createprefix pass never blocks the GUI.
        """
        argv, env = self.build_command()
        os.makedirs(os.path.expanduser(self.config.wine_prefix), exist_ok=True)
        self.write_steam_appid()
        umu = find_umu(self.config.umu_path)
        logger.info(f"Launching (output -> {GAME_LOG}): {argv}")

        log_file = open(GAME_LOG, "w")
        log_file.write("Launching: " + " ".join(argv) + "\n\n")
        try:
            log_file.write(
                format_launch_diagnostics(
                    env, os.path.dirname(self.config.game_exe())
                )
                + "\n\n"
            )
        except Exception as e:  # diagnostics must never block a launch
            log_file.write(f"(launch diagnostics failed: {e})\n\n")
        log_file.flush()
        self.user_stopped = False
        self._starting = True

        def run():
            try:
                if not self.prefix_initialized():
                    if not self._run_createprefix(umu, env, log_file):
                        return  # stopped or failed before the game could start
                # Every launch: (re)install the steamclient bridge into the
                # prefix. umu never forwards STEAM_COMPAT_CLIENT_INSTALL_PATH to
                # Proton, so Proton's own copy no-ops; without this the prefix
                # Steam dir stays empty and Steam auth fails "conditions not
                # met". Refreshing each launch also picks up client updates.
                steam_path = env.get("STEAM_COMPAT_CLIENT_INSTALL_PATH", "")
                if steam_path:
                    summary = install_steam_bridge(steam_path, env["WINEPREFIX"])
                    log_file.write(f"steam bridge: {summary}\n\n")
                    log_file.flush()
                if self.user_stopped:
                    return
                self.process = subprocess.Popen(
                    argv, env=env, cwd=self.config.game_dir,
                    stdout=log_file, stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                self.process.wait()
            except Exception:
                logger.exception("Game launch failed")
            finally:
                returncode = self.process.returncode if self.process else None
                self.process = None
                self._starting = False
                log_file.close()
                logger.info(f"Game process exited with code {returncode}")
                if on_exit is not None:
                    on_exit()

        threading.Thread(target=run, daemon=True).start()

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
