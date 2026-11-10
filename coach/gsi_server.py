"""Локальный HTTP-сервер, на который Dota 2 сама отправляет состояние игры
(GSI).

Слушает только 127.0.0.1 — снаружи к нему не подключиться.
Принимает данные только с правильным токеном из конфиг-файла.
"""

import json
import logging
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

LOG = logging.getLogger("dota_coach.gsi")


class GSIServer:
    def __init__(
        self,
        port: int,
        token: str,
        on_payload: Callable[[Any], None],
        host: str = "127.0.0.1",
    ) -> None:
        self.host, self.port, self.token = host, port, token
        self.on_payload = on_payload
        self.httpd: ThreadingHTTPServer | None = None
        self.error: str | None = None

    def start(self) -> bool:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    body = self.rfile.read(length) if length else b""
                    data = json.loads(body.decode("utf-8") or "{}")
                except (ValueError, UnicodeDecodeError):
                    self.send_response(400)
                    self.end_headers()
                    return
                token = (
                    ((data.get("auth") or {}).get("token"))
                    if isinstance(data, dict)
                    else None
                )
                if server.token and token != server.token:
                    self.send_response(403)
                    self.end_headers()
                    return
                try:
                    server.on_payload(data)
                except Exception:
                    # Не роняем сервер из-за ошибки обработчика, но и не молчим
                    # о ней.
                    LOG.exception("Ошибка обработки данных от Dota 2")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"OK")

            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write("Dota Coach GSI server работает".encode())

            def log_message(self, *args):
                pass

        try:
            self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        except OSError as e:
            self.error = (
                f"Порт {self.port} занят или недоступен ({e}). Поменяйте "
                "порт в settings.json."
            )
            return False
        self.httpd.daemon_threads = True
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return True

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
