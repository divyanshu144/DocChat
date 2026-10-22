"""Tiny probe/metrics server for the worker (stdlib only; no dependency on the API app)."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.core.metrics import metrics


def make_server(worker, port: int, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, content_type: str = "text/plain; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802 - stdlib naming
            path = self.path.split("?", 1)[0]
            if path == "/livez":
                self._send(200 if worker.alive else 503, b"ok" if worker.alive else b"stalled")
            elif path == "/readyz":
                self._send(200 if worker.ready else 503, b"ready" if worker.ready else b"not ready")
            elif path == "/metrics":
                self._send(200, generate_latest(metrics.registry), CONTENT_TYPE_LATEST)
            else:
                self._send(404, b"not found")

        def log_message(self, *args):  # request lines are noise and must never reach logs
            pass

    return ThreadingHTTPServer((host, port), Handler)


def serve_in_thread(server: ThreadingHTTPServer) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, name="worker-http", daemon=True)
    thread.start()
    return thread
