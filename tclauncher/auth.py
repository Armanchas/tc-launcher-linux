"""Steam OpenID login flow.

The browser is sent to {discovery}/steam/openid/login with a redirect back to
a short-lived local HTTP server; the server exchanges the returned code for a
session via the backend's idp endpoints.
"""

import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlparse

from .backend import BackendClient
from .config import ConfigManager
from .desktop import open_url

logger = logging.getLogger(__name__)

SESSION_REQUEST_FAIL = """<html>
    <head><title>The Cycle Launcher authentication</title></head>
    <body>
        <h1>Login failed!</h1>
        <p>Reason: %s</p>
    </body>
</html>
"""
SESSION_REQUEST_SUCCESS = """<html>
    <head><title>The Cycle Launcher authentication</title></head>
    <body>
        <h1>Login complete!</h1>
        <p>You may close this browser tab.</p>
    </body>
</html>
"""


class _CallbackHandler(BaseHTTPRequestHandler):
    session_manager: "SessionManager" = None

    def log_message(self, format, *args):
        logger.info("auth callback: " + format % args)

    def _respond(self, status: int, body: str):
        payload = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/auth_result":
            self._respond(404, SESSION_REQUEST_FAIL % "Unknown path.")
            return
        query = parse_qs(parsed.query)
        if "code" not in query:
            self._respond(400, SESSION_REQUEST_FAIL % "Missing 'code' query parameter.")
            return
        try:
            success, message = self.session_manager._complete_login(query["code"][0])
        except Exception as e:
            logger.exception(e)
            success, message = False, "Unexpected error occurred."
        if success:
            self._respond(200, SESSION_REQUEST_SUCCESS)
        else:
            self._respond(400, SESSION_REQUEST_FAIL % message)


class SessionManager:
    def __init__(self, config: ConfigManager, backend: BackendClient):
        self.config = config
        self.backend = backend
        self.server: HTTPServer | None = None
        self.redirect_url: str | None = None
        self.on_successful_login: Callable | None = None

    def initiate_login(self, on_successful_login: Callable):
        """Open the Steam OpenID page in the browser; on_successful_login is
        called from the callback-server thread once the session is saved."""
        self.on_successful_login = on_successful_login
        if self.server is None:
            self._start_callback_server()
        open_url(
            f"{self.config.server_discovery_addr}/steam/openid/login?launcher_redirect={self.redirect_url}"
        )

    def _start_callback_server(self):
        handler = type("BoundHandler", (_CallbackHandler,), {"session_manager": self})
        self.server = HTTPServer(("localhost", 0), handler)
        port = self.server.server_address[1]
        self.redirect_url = f"http://localhost:{port}/auth_result"
        logger.info(f"Auth callback server on {self.redirect_url}")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _shutdown_server(self):
        if self.server is not None:
            server = self.server
            self.server = None
            self.redirect_url = None
            threading.Thread(target=server.shutdown, daemon=True).start()

    def _complete_login(self, code: str) -> tuple[bool, str]:
        data = self.backend.exchange_code(code)
        if not data.get("success"):
            return False, data.get("message", "Unknown error")
        self.config.session_id = data["session_id"]
        self.config.refresh_token = data["refresh_token"]
        self.config.exp = data["exp"]
        self.config.save()
        self._shutdown_server()
        if self.on_successful_login is not None:
            self.on_successful_login()
        return True, ""

    # --- session state ---

    def has_active_session(self) -> bool:
        return self.config.session_id != "" and self.config.exp > int(time.time())

    def has_refresh_token(self) -> bool:
        return self.config.refresh_token != ""

    def is_valid_backend_session(self) -> bool:
        return self.backend.check_session() or self.backend.refresh_session()

    def invalidate_session(self):
        self.config.session_id = ""
        self.config.refresh_token = ""
        self.config.exp = 0
