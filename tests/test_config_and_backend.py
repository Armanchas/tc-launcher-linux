import json

from tclauncher.backend import BackendClient, ServerDiscoveryStatus
from tclauncher.config import ConfigManager


def test_config_roundtrip(tmp_path):
    path = str(tmp_path / "config.json")
    config = ConfigManager(config_file=path)
    config.server_discovery_addr = "http://example.com"
    config.session_id = "abc"
    config.run_args = ["-log"]
    config.env_vars = {"A": "1"}
    config.use_mangohud = True
    config.save()

    loaded = ConfigManager(config_file=path)
    loaded.load()
    assert loaded.server_discovery_addr == "http://example.com"
    assert loaded.session_id == "abc"
    assert loaded.run_args == ["-log"]
    assert loaded.env_vars == {"A": "1"}
    assert loaded.use_mangohud is True


def test_config_reads_prospect_og_style_file(tmp_path):
    """A config written by the original Windows launcher must load cleanly."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "backend_data": {"backend_api": "http://api"},
        "server_discovery_addr": "http://server",
        "session_id": "s",
        "refresh_token": "r",
        "exp": 123,
        "run_args": [],
    }))
    config = ConfigManager(config_file=str(path))
    config.load()
    assert config.server_discovery_addr == "http://server"
    assert config.refresh_token == "r"
    assert config.wine_prefix  # Linux default filled in


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.headers = {}
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_discover_handles_426(tmp_path, monkeypatch):
    config = ConfigManager(config_file=str(tmp_path / "c.json"))
    client = BackendClient(config)
    monkeypatch.setattr(client.session, "get", lambda url, timeout=None: _FakeResponse(426))
    assert client.discover("http://x") == ServerDiscoveryStatus.LAUNCHER_OUTDATED


def test_discover_ok_stores_backend_data(tmp_path, monkeypatch):
    config = ConfigManager(config_file=str(tmp_path / "c.json"))
    client = BackendClient(config)
    payload = {"backend_game": "g", "steam_auth": "s", "analytics": "a", "backend_api": "api"}
    monkeypatch.setattr(client.session, "get", lambda url, timeout=None: _FakeResponse(200, payload))
    assert client.discover("http://x") == ServerDiscoveryStatus.OK
    assert config.backend_data == payload


def test_discover_error(tmp_path, monkeypatch):
    config = ConfigManager(config_file=str(tmp_path / "c.json"))
    client = BackendClient(config)

    def boom(url, timeout=None):
        raise ConnectionError("no route")

    monkeypatch.setattr(client.session, "get", boom)
    assert client.discover("http://x") == ServerDiscoveryStatus.UNKNOWN_ERROR


def test_save_replaces_atomically(tmp_path, monkeypatch):
    import os as os_mod
    path = str(tmp_path / "config.json")
    config = ConfigManager(config_file=path)
    config.session_id = "abc"

    replaced = []
    real_replace = os_mod.replace

    def recording_replace(src, dst):
        replaced.append((src, dst))
        real_replace(src, dst)

    monkeypatch.setattr("tclauncher.config.os.replace", recording_replace)
    config.save()

    assert replaced == [(path + ".tmp", path)]
    assert not os_mod.path.exists(path + ".tmp")
    with open(path) as f:
        assert json.load(f)["session_id"] == "abc"


def test_failed_save_preserves_existing_config(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    first = ConfigManager(config_file=str(path))
    first.session_id = "keep-me"
    first.save()

    second = ConfigManager(config_file=str(path))
    second.load()
    second.session_id = "lost-on-crash"

    def exploding_dump(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("tclauncher.config.json.dump", exploding_dump)
    try:
        second.save()
        assert False, "save() should have raised"
    except OSError:
        pass

    assert json.loads(path.read_text())["session_id"] == "keep-me"
    assert not (tmp_path / "config.json.tmp").exists()
