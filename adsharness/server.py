"""Loopback-only HTTP UI with same-origin and session-token protection."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
from urllib.parse import urlsplit, parse_qs

from .core import Catalog, MAX_FILE
from .agents import AgentManager

STATIC = Path(__file__).parent / "static"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass  # Never log document contents, paths, or request parameters.

    def reply(self, status, data, content_type="application/json; charset=utf-8"):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(data)

    def allowed(self):
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        origin = self.headers.get("Origin")
        return (self.headers.get("Host") in hosts and
                (origin is None or origin in {f"http://{h}" for h in hosts}) and
                self.headers.get("Sec-Fetch-Site") not in ("cross-site", "same-site"))

    def do_GET(self):
        if not self.allowed():
            return self.reply(403, {"error": "Origin not allowed"})
        url = urlsplit(self.path)
        try:
            if url.path == "/api/session":
                return self.reply(200, {"token": self.server.token})
            if url.path.startswith("/api/"):
                if not secrets.compare_digest(self.headers.get("X-adsharness-token", ""), self.server.token):
                    return self.reply(403, {"error": "Invalid session; reload the page"})
                if url.path == "/api/inventory":
                    return self.reply(200, self.server.catalog.inventory())
                if url.path == "/api/document":
                    return self.reply(200, self.server.catalog.document(parse_qs(url.query).get("id", [""])[0], reveal=parse_qs(url.query).get("reveal", ["0"])[0] == "1"))
                if url.path == "/api/agents":
                    return self.reply(200, self.server.agents.status())
                if url.path == "/api/job":
                    return self.reply(200, self.server.agents.get(parse_qs(url.query).get("id", [""])[0]))
            assets = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css")}
            if url.path in assets:
                file, kind = assets[url.path]
                return self.reply(200, (STATIC / file).read_bytes(), kind + "; charset=utf-8")
            self.reply(404, {"error": "Not found"})
        except (ValueError, OSError, UnicodeError):
            self.reply(400, {"error": "Could not read the requested data"})

    def do_POST(self):
        if not self.allowed() or not secrets.compare_digest(self.headers.get("X-adsharness-token", ""), self.server.token):
            return self.reply(403, {"error": "Invalid session or origin"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= MAX_FILE * 2:
                raise ValueError("Request is too large or empty")
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError("Invalid request")
            if self.path == "/api/organize":
                result = self.server.catalog.organize(body["id"], body["favorite"], body["tags"])
            elif self.path == "/api/document":
                result = self.server.catalog.save_document(body["id"], body["revision"], body["content"], reveal=body.get("reveal") is True)
            elif self.path == "/api/agents/check":
                result = self.server.agents.check(body["provider"])
            elif self.path == "/api/agents/login":
                result = self.server.agents.login(body["provider"])
            elif self.path == "/api/agents/propose":
                result = self.server.agents.propose(body["provider"], body["id"], body["revision"], body["instruction"], body.get("model", ""))
            elif self.path == "/api/agents/apply":
                result = self.server.agents.apply(body["job_id"])
            elif self.path == "/api/agents/cancel":
                result = self.server.agents.cancel(body["job_id"])
            else:
                return self.reply(404, {"error": "Not found"})
            self.reply(200, result)
        except (ValueError, KeyError, TypeError) as exc:
            self.reply(400, {"error": str(exc) if isinstance(exc, ValueError) else "Invalid request"})
        except (OSError, subprocess.SubprocessError):
            self.reply(500, {"error": "Could not save. Check local permissions."})


class LocalServer(ThreadingHTTPServer):
    def server_close(self):
        if hasattr(self, "agents"):
            self.agents.close()
        super().server_close()


def create_server(catalog, port=4317):
    server = LocalServer(("127.0.0.1", port), Handler)
    server.catalog = catalog
    server.agents = AgentManager(catalog)
    server.token = secrets.token_urlsafe(32)
    return server


def main():
    parser = argparse.ArgumentParser(prog="adsharness", description="MCPs, skills, and harnesses in one place")
    parser.add_argument("--port", type=int, default=4317)
    parser.add_argument("--workspace", type=Path, help="Specific project to include in the inventory")
    args = parser.parse_args()
    if args.workspace and not args.workspace.is_dir():
        parser.error("The workspace must be an existing directory")
    state = Path(os.environ.get("ADSHARNESS_DATA_DIR") or Path.home() / ".local/share/adsharness")
    server = create_server(Catalog(Path.home(), state, args.workspace), args.port)
    print(f"adsharness → http://localhost:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
