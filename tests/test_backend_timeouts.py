"""Every backend request must carry a timeout so a stalled network can't
hang the login exchange or a mod download forever."""

from tclauncher.backend import REQUEST_TIMEOUT, BackendClient
from tclauncher.config import ConfigManager


class _FakeResponse:
    def __init__(self, payload=None):
        self._payload = payload or {}
        self.headers = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        return iter([b"data"])


class _RecordingSession:
    def __init__(self):
        self.headers = {}
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse({"success": True})

    def get(self, url, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse()


def _client(tmp_path):
    config = ConfigManager(config_file=str(tmp_path / "config.json"))
    config.server_discovery_addr = "http://server.example"
    client = BackendClient(config)
    client.session = _RecordingSession()
    return client


def test_exchange_code_has_timeout(tmp_path):
    client = _client(tmp_path)
    client.exchange_code("somecode")
    assert client.session.calls[0].get("timeout") == REQUEST_TIMEOUT


def test_download_has_connect_and_read_timeout(tmp_path):
    client = _client(tmp_path)
    client.download("http://server.example/file.zip", str(tmp_path / "file.zip"))
    call = client.session.calls[0]
    assert call.get("stream") is True
    assert call.get("timeout") == (REQUEST_TIMEOUT, 30)
