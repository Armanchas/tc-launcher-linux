import os
import subprocess
import sys
import time

import pytest

from tclauncher.config import GAME_EXE_RELPATH, ConfigManager
from tclauncher.runner import GameRunner, find_umu


@pytest.fixture
def config(tmp_path):
    config = ConfigManager(config_file=str(tmp_path / "config.json"))
    game_dir = tmp_path / "game"
    exe = game_dir / GAME_EXE_RELPATH
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    config.game_dir = str(game_dir)
    config.backend_data = {
        "backend_game": "https://game.example",
        "steam_auth": "https://auth.example",
        "analytics": "https://analytics.example",
        "backend_api": "https://api.example",
    }
    config.proton_path = "/opt/proton-ge"
    config.wine_prefix = str(tmp_path / "prefix")
    fake_umu = tmp_path / "umu-run"
    fake_umu.write_text("#!/bin/sh\n")
    fake_umu.chmod(0o755)
    config.umu_path = str(fake_umu)
    return config


def test_build_command_basic(config):
    runner = GameRunner(config)
    argv, env = runner.build_command()
    assert argv[0] == config.umu_path
    assert argv[1] == config.game_exe()
    assert argv[2:8] == [
        "-backend", "https://game.example",
        "-steam_auth", "https://auth.example",
        "-analytics", "https://analytics.example",
    ]
    assert env["PROTONPATH"] == "/opt/proton-ge"
    assert env["WINEPREFIX"] == config.wine_prefix
    # Steam auth requirements: appid 480 via GAMEID, and no pressure-vessel
    # container so the game can reach the host Steam client.
    assert env["GAMEID"] == "umu-480"
    assert env["SteamAppId"] == "480"
    assert env["UMU_NO_RUNTIME"] == "1"


def test_build_command_sets_steam_client_path_when_detected(config, monkeypatch):
    monkeypatch.setattr("tclauncher.runner.find_steam_install_path", lambda: "/home/u/.steam/steam")
    _, env = GameRunner(config).build_command()
    assert env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] == "/home/u/.steam/steam"


def test_find_steam_install_path_detects_legacycompat(tmp_path, monkeypatch):
    from tclauncher import runner
    steam = tmp_path / "Steam"
    (steam / "legacycompat").mkdir(parents=True)
    monkeypatch.setattr(runner, "STEAM_INSTALL_DIRS", [str(steam)])
    assert runner.find_steam_install_path() == str(steam.resolve())


def test_build_command_includes_run_args_and_env(config):
    config.run_args = ["-log", "-nosplash"]
    config.env_vars = {"DXVK_HUD": "fps"}
    argv, env = GameRunner(config).build_command()
    assert argv[-2:] == ["-log", "-nosplash"]
    assert env["DXVK_HUD"] == "fps"


def test_build_command_requires_server(config):
    config.backend_data = None
    with pytest.raises(RuntimeError, match="No server selected"):
        GameRunner(config).build_command()


def test_build_command_requires_game_dir(config):
    config.game_dir = "/nonexistent"
    with pytest.raises(RuntimeError, match="Game directory"):
        GameRunner(config).build_command()


def test_build_command_requires_proton(config):
    config.proton_path = ""
    with pytest.raises(RuntimeError, match="Proton"):
        GameRunner(config).build_command()


def test_build_command_missing_umu(config):
    config.umu_path = "/nonexistent/umu-run"
    with pytest.raises(RuntimeError, match="umu-run not found"):
        GameRunner(config).build_command()


def test_write_steam_appid(config):
    runner = GameRunner(config)
    runner.write_steam_appid()
    appid_file = os.path.join(os.path.dirname(config.game_exe()), "steam_appid.txt")
    with open(appid_file) as f:
        assert f.read() == "480"


def test_find_umu_override_missing():
    assert find_umu("/nonexistent/umu") is None


def test_launch_validates_before_writing(config, tmp_path):
    config.game_dir = str(tmp_path / "missing")
    runner = GameRunner(config)
    with pytest.raises(RuntimeError, match="Game directory"):
        runner.launch()


def test_write_steam_appid_unwritable_dir_friendly_error(config):
    exe_dir = os.path.dirname(config.game_exe())
    os.chmod(exe_dir, 0o555)
    try:
        runner = GameRunner(config)
        with pytest.raises(RuntimeError, match="not writable"):
            runner.write_steam_appid()
    finally:
        os.chmod(exe_dir, 0o755)


def test_stop_terminates_running_process(config):
    runner = GameRunner(config)
    # start_new_session=True: without it, os.getpgid(pid) inside stop() would
    # resolve to the *test runner's own* process group (a plain Popen call
    # inherits the parent's group), and os.killpg would signal pytest itself.
    runner.process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
    )
    process = runner.process
    runner.stop()
    assert process.wait(timeout=5) != 0
    assert runner.user_stopped is True


def test_stop_kills_whole_process_tree(config, tmp_path):
    """stop() must reach grandchildren (umu -> proton -> wine -> game), not
    just the direct child, or the Wine tree is orphaned when the UI reports
    the game as stopped."""
    pidfile = tmp_path / "child.pid"
    parent_code = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen(['sleep', '60'])\n"
        "with open(sys.argv[1], 'w') as f:\n"
        "    f.write(str(child.pid))\n"
        "child.wait()\n"
    )
    runner = GameRunner(config)
    runner.process = subprocess.Popen(
        [sys.executable, "-c", parent_code, str(pidfile)],
        start_new_session=True,
    )
    parent_pid = runner.process.pid

    deadline = time.time() + 5
    while not pidfile.exists() and time.time() < deadline:
        time.sleep(0.1)
    assert pidfile.exists(), "child never reported its pid"
    child_pid = int(pidfile.read_text())

    runner.stop()

    deadline = time.time() + 5
    parent_gone = child_gone = False
    while time.time() < deadline and not (parent_gone and child_gone):
        if not parent_gone:
            try:
                os.kill(parent_pid, 0)
            except ProcessLookupError:
                parent_gone = True
        if not child_gone:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                child_gone = True
        if not (parent_gone and child_gone):
            time.sleep(0.1)

    assert parent_gone, "parent (umu-wrapper stand-in) survived stop()"
    assert child_gone, "child (game stand-in) survived stop() - tree leak"


def test_stop_is_noop_when_idle(config):
    runner = GameRunner(config)
    runner.stop()
    assert runner.user_stopped is False


def test_build_command_scrubs_frozen_env(config, monkeypatch):
    """In the frozen (AppImage) build, PyInstaller's LD_LIBRARY_PATH must not
    leak into the game launch chain: gamemoderun is a bash script, and host
    bash crashes resolving symbols against the bundle's older libreadline."""
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEIxyz/_internal")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    _, env = GameRunner(config).build_command()
    assert "LD_LIBRARY_PATH" not in env


def test_build_command_frozen_env_restores_original(config, monkeypatch):
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEIxyz/_internal")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/opt/custom/lib")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    _, env = GameRunner(config).build_command()
    assert env["LD_LIBRARY_PATH"] == "/opt/custom/lib"


def test_build_command_keeps_env_when_not_frozen(config, monkeypatch):
    monkeypatch.setenv("LD_LIBRARY_PATH", "/opt/dev/lib")
    monkeypatch.delattr(sys, "frozen", raising=False)
    _, env = GameRunner(config).build_command()
    assert env["LD_LIBRARY_PATH"] == "/opt/dev/lib"


def test_build_command_config_env_vars_survive_frozen_scrub(config, monkeypatch):
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEIxyz/_internal")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    config.env_vars = {"LD_LIBRARY_PATH": "/from/settings", "DXVK_HUD": "fps"}
    _, env = GameRunner(config).build_command()
    assert env["LD_LIBRARY_PATH"] == "/from/settings"
    assert env["DXVK_HUD"] == "fps"
