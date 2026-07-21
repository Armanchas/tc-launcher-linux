import os
import subprocess
import sys
import time

import pytest

from tclauncher.config import GAME_EXE_RELPATH, ConfigManager
from tclauncher.runner import (
    GameRunner,
    find_umu,
    format_launch_diagnostics,
    prefix_steam_bridge,
    relevant_env,
    running_steam,
    steam_install_kind,
    steam_login_summary,
    steam_preflight_issue,
)


@pytest.fixture
def config(tmp_path, monkeypatch):
    # Stub Steam detection so build_command() tests don't depend on whether
    # the machine running the tests (dev box vs CI runner) has Steam.
    monkeypatch.setattr(
        "tclauncher.runner.find_steam_install_path", lambda: "/stub/steam"
    )
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
    # Steam auth requirement: appid 480 via GAMEID (umu derives SteamAppId from
    # the text after "umu-"). UMU_NO_RUNTIME is vestigial in umu 1.4.x but kept.
    assert env["GAMEID"] == "umu-480"
    assert env["SteamAppId"] == "480"
    assert env["UMU_NO_RUNTIME"] == "1"


def test_build_command_sets_steam_client_path_when_detected(config, monkeypatch):
    monkeypatch.setattr("tclauncher.runner.find_steam_install_path", lambda: "/home/u/.steam/steam")
    _, env = GameRunner(config).build_command()
    assert env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] == "/home/u/.steam/steam"


def test_build_command_fails_when_steam_install_not_found(config, monkeypatch):
    """Without STEAM_COMPAT_CLIENT_INSTALL_PATH Proton never installs the
    steamclient bridge, so the game boots but Steam login fails. Refuse to
    launch with a precise error instead."""
    monkeypatch.setattr("tclauncher.runner.find_steam_install_path", lambda: None)
    with pytest.raises(RuntimeError, match="STEAM_COMPAT_CLIENT_INSTALL_PATH"):
        GameRunner(config).build_command()


def test_build_command_user_env_var_rescues_failed_detection(config, monkeypatch):
    monkeypatch.setattr("tclauncher.runner.find_steam_install_path", lambda: None)
    config.env_vars = {"STEAM_COMPAT_CLIENT_INSTALL_PATH": "/custom/steam"}
    _, env = GameRunner(config).build_command()
    assert env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] == "/custom/steam"


def test_build_command_user_env_var_overrides_detection(config, monkeypatch):
    """An explicit value from Settings must win over detection — the user set
    it precisely because detection picks the wrong install."""
    monkeypatch.setattr(
        "tclauncher.runner.find_steam_install_path", lambda: "/detected/steam"
    )
    config.env_vars = {"STEAM_COMPAT_CLIENT_INSTALL_PATH": "/custom/steam"}
    _, env = GameRunner(config).build_command()
    assert env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] == "/custom/steam"


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


# --- Steam-auth diagnostics (Track B) ------------------------------------


def test_steam_install_kind_flatpak_vs_native():
    assert steam_install_kind(
        "/home/u/.var/app/com.valvesoftware.Steam/data/Steam"
    ) == "flatpak"
    assert steam_install_kind("/home/u/.local/share/Steam") == "native"


def test_running_steam_returns_live_install(tmp_path, monkeypatch):
    """running_steam() reports the install whose pid file points at a live
    process (unlike find_steam_install_path, which only looks on disk)."""
    pid_file = tmp_path / "steam.pid"
    pid_file.write_text(str(os.getpid()))  # our own pid is guaranteed alive
    install = tmp_path / "Steam"
    install.mkdir()
    monkeypatch.setattr(
        "tclauncher.runner._STEAM_CANDIDATES",
        [(str(pid_file), str(install), "native")],
    )
    assert running_steam() == (str(install.resolve()), "native")


def test_running_steam_none_when_pid_dead(tmp_path, monkeypatch):
    pid_file = tmp_path / "steam.pid"
    pid_file.write_text("999999999")  # not a live pid
    monkeypatch.setattr(
        "tclauncher.runner._STEAM_CANDIDATES",
        [(str(pid_file), str(tmp_path / "Steam"), "native")],
    )
    assert running_steam() is None


def test_format_launch_diagnostics_reports_env_and_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "tclauncher.runner.running_steam",
        lambda: ("/home/u/.local/share/Steam", "native"),
    )
    monkeypatch.setattr(
        "tclauncher.runner.runtime_versions",
        lambda: ["steamrt4: depot 4.0.20260714, pressure-vessel 0.20260714.0"],
    )
    env = {
        "PROTONPATH": "/opt/GE-Proton11-1",
        "WINEPREFIX": "/home/u/.tclauncher/prefix",
        "GAMEID": "umu-480",
        "STEAM_COMPAT_CLIENT_INSTALL_PATH": "/home/u/.local/share/Steam",
    }
    text = format_launch_diagnostics(env, str(tmp_path))
    assert "GE-Proton11-1" in text
    assert "umu-480" in text
    assert "running Steam client: /home/u/.local/share/Steam (native)" in text
    assert "pressure-vessel 0.20260714.0" in text
    assert "steam_appid.txt" in text


def test_format_launch_diagnostics_flags_no_running_steam(tmp_path, monkeypatch):
    monkeypatch.setattr("tclauncher.runner.running_steam", lambda: None)
    monkeypatch.setattr("tclauncher.runner.runtime_versions", lambda: [])
    text = format_launch_diagnostics({}, str(tmp_path))
    assert "NONE DETECTED" in text
    assert "conditions not met" in text


def test_format_launch_diagnostics_warns_on_compat_mismatch(tmp_path, monkeypatch):
    """If the compat path we hand Proton is a different install than the one
    actually running, the ticket won't be issued — surface it loudly."""
    monkeypatch.setattr(
        "tclauncher.runner.running_steam",
        lambda: ("/home/u/.var/app/com.valvesoftware.Steam/data/Steam", "flatpak"),
    )
    monkeypatch.setattr("tclauncher.runner.runtime_versions", lambda: [])
    env = {"STEAM_COMPAT_CLIENT_INSTALL_PATH": "/home/u/.local/share/Steam"}
    text = format_launch_diagnostics(env, str(tmp_path))
    assert "WARNING" in text
    assert "not the" in text


def test_steam_preflight_issue_none_when_running_matches(monkeypatch):
    monkeypatch.setattr(
        "tclauncher.runner.running_steam",
        lambda: ("/home/u/.local/share/Steam", "native"),
    )
    assert steam_preflight_issue("/home/u/.local/share/Steam") is None


def test_steam_preflight_issue_warns_when_not_running(monkeypatch):
    monkeypatch.setattr("tclauncher.runner.running_steam", lambda: None)
    monkeypatch.setattr("tclauncher.runner.is_steam_running", lambda: False)
    msg = steam_preflight_issue("")
    assert msg is not None
    assert "not appear to be running" in msg


def test_steam_preflight_issue_warns_on_mismatch(monkeypatch):
    monkeypatch.setattr(
        "tclauncher.runner.running_steam",
        lambda: ("/home/u/.var/app/com.valvesoftware.Steam/data/Steam", "flatpak"),
    )
    msg = steam_preflight_issue("/home/u/.local/share/Steam")
    assert msg is not None
    assert "not the one currently running" in msg


def test_relevant_env_allowlists_steam_proton_container_keys():
    env = {
        "PROTONPATH": "/opt/proton",
        "STEAM_COMPAT_CLIENT_INSTALL_PATH": "/home/u/.steam",
        "PRESSURE_VESSEL_FILESYSTEMS_RW": "/foo",
        "XDG_RUNTIME_DIR": "/run/user/1000",
        "LD_PRELOAD": "/x/mangohud.so",
        "SECRET_TOKEN": "hunter2",  # must NOT appear
        "HOME": "/home/u",  # must NOT appear
    }
    lines = relevant_env(env)
    joined = "\n".join(lines)
    assert "PROTONPATH=/opt/proton" in joined
    assert "PRESSURE_VESSEL_FILESYSTEMS_RW=/foo" in joined
    assert "XDG_RUNTIME_DIR=/run/user/1000" in joined
    assert "LD_PRELOAD=/x/mangohud.so" in joined
    assert "SECRET_TOKEN" not in joined
    assert "HOME=" not in joined
    assert lines == sorted(lines)  # stable ordering


def test_prefix_steam_bridge_present(tmp_path):
    (tmp_path / "system.reg").write_text("")
    steam = tmp_path / "drive_c" / "Program Files (x86)" / "Steam"
    steam.mkdir(parents=True)
    (steam / "steamclient64.dll").write_bytes(b"MZ")
    assert prefix_steam_bridge(str(tmp_path)) == "present"


def test_prefix_steam_bridge_missing(tmp_path):
    (tmp_path / "system.reg").write_text("")  # prefix built, but no bridge dll
    assert "MISSING" in prefix_steam_bridge(str(tmp_path))


def test_prefix_steam_bridge_not_built(tmp_path):
    assert "not built" in prefix_steam_bridge(str(tmp_path))


def test_steam_login_summary_reports_offline_flag(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "loginusers.vdf").write_text(
        '"users"\n{\n\t"76561190000000000"\n\t{\n'
        '\t\t"AccountName"\t\t"someone"\n'
        '\t\t"MostRecent"\t\t"1"\n'
        '\t\t"WantsOfflineMode"\t\t"1"\n\t}\n}\n'
    )
    summary = steam_login_summary(str(tmp_path))
    assert "1 account" in summary
    assert "most-recent set: yes" in summary
    assert "WantsOfflineMode" in summary
    assert "someone" not in summary  # no PII


def test_steam_login_summary_no_file(tmp_path):
    assert "never logged in" in steam_login_summary(str(tmp_path))


def test_format_launch_diagnostics_includes_system_and_env(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "tclauncher.runner.running_steam",
        lambda: ("/home/u/.local/share/Steam", "native"),
    )
    monkeypatch.setattr("tclauncher.runner.runtime_versions", lambda: [])
    monkeypatch.setattr(
        "tclauncher.runner.steam_login_summary", lambda p: "1 account(s)"
    )
    env = {
        "PROTONPATH": "/opt/GE-Proton11-1",
        "WINEPREFIX": str(tmp_path / "prefix"),
        "GAMEID": "umu-480",
        "STEAM_COMPAT_CLIENT_INSTALL_PATH": "/home/u/.local/share/Steam",
        "XDG_RUNTIME_DIR": "/run/user/1000",
    }
    text = format_launch_diagnostics(env, str(tmp_path))
    assert "launcher = TCLauncher" in text
    assert "system =" in text
    assert "prefix Steam bridge:" in text
    assert "Steam login (on-disk): 1 account(s)" in text
    assert "relevant env:" in text
    assert "XDG_RUNTIME_DIR=/run/user/1000" in text
