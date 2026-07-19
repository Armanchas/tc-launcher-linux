"""HTTP client for the server-discovery backend.

Endpoint shapes mirror prospect-og's launcher.py so this launcher is
protocol-compatible with existing community servers.
"""

import logging
from enum import IntEnum

import requests

from .config import PROTOCOL_VERSION, ConfigManager

logger = logging.getLogger(__name__)

USER_AGENT = f"TCL/{PROTOCOL_VERSION}"
REQUEST_TIMEOUT = 3


class ServerDiscoveryStatus(IntEnum):
    OK = 0
    LAUNCHER_OUTDATED = 1
    UNKNOWN_ERROR = 2


class BackendClient:
    def __init__(self, config: ConfigManager):
        self.config = config
        self.session = requests.Session()
        self.session.headers = {"User-Agent": USER_AGENT}

    def _discovery(self) -> str:
        if self.config.server_discovery_addr is None:
            raise RuntimeError("Server discovery address not specified")
        return self.config.server_discovery_addr

    # --- discovery / status ---

    def discover(self, server_addr: str) -> ServerDiscoveryStatus:
        try:
            res = self.session.get(f"{server_addr}/launcher/discover", timeout=REQUEST_TIMEOUT)
            if res.status_code == 426:
                return ServerDiscoveryStatus.LAUNCHER_OUTDATED
            res.raise_for_status()
            self.config.backend_data = res.json()
            return ServerDiscoveryStatus.OK
        except Exception as e:
            logger.exception(e)
            return ServerDiscoveryStatus.UNKNOWN_ERROR

    def server_status(self) -> dict | None:
        """Population poll. Returns e.g. {'online': 3} or None if unreachable."""
        if self.config.backend_data is None:
            return None
        try:
            res = self.session.get(f"{self.config.backend_data['backend_api']}/status", timeout=REQUEST_TIMEOUT)
            res.raise_for_status()
            return res.json()
        except Exception:
            return None

    # --- session (idp) ---

    def exchange_code(self, code: str) -> dict:
        res = self.session.post(f"{self._discovery()}/idp/exchange_code", json={"code": code},
                                timeout=REQUEST_TIMEOUT)
        return res.json()

    def check_session(self) -> bool:
        if not self.config.session_id:
            logger.warning("Session ID is missing from config.")
            return False
        try:
            payload = {"session_id": self.config.session_id}
            res = self.session.post(f"{self._discovery()}/idp/check_session", json=payload, timeout=REQUEST_TIMEOUT)
            res.raise_for_status()
            return True
        except Exception as e:
            logger.exception(e)
            return False

    def refresh_session(self) -> bool:
        if not self.config.refresh_token:
            logger.warning("Refresh token is missing from config.")
            return False
        try:
            payload = {
                "session_id": self.config.session_id,
                "refresh_token": self.config.refresh_token,
            }
            res = self.session.post(f"{self._discovery()}/idp/refresh_session", json=payload, timeout=REQUEST_TIMEOUT)
            data = res.json()
            res.raise_for_status()
            self.config.refresh_token = data["refresh_token"]
            self.config.save()
            return True
        except Exception as e:
            logger.exception(e)
            return False

    # --- mods / launcher update ---

    def remote_mods(self) -> dict:
        try:
            res = self.session.get(f"{self._discovery()}/launcher/mods", timeout=REQUEST_TIMEOUT)
            return res.json()["items"]
        except Exception as e:
            logger.exception(e)
            return {}

    def launcher_update_manifest(self) -> dict | None:
        try:
            res = self.session.get(f"{self._discovery()}/launcher/check_update", timeout=REQUEST_TIMEOUT)
            res.raise_for_status()
            return res.json()
        except Exception as e:
            logger.exception(e)
            return None

    def download(self, url: str, dest_path: str, on_progress=None):
        """Stream a file to dest_path, calling on_progress(fraction) if given."""
        res = self.session.get(url, stream=True, timeout=(REQUEST_TIMEOUT, 30))
        res.raise_for_status()
        downloaded = 0
        total_size = int(res.headers.get("content-length", 0))
        with open(dest_path, "wb") as f:
            for chunk in res.iter_content(1024 * 1024):
                f.write(chunk)
                if total_size > 0 and on_progress is not None:
                    downloaded += len(chunk)
                    on_progress(downloaded / total_size)
