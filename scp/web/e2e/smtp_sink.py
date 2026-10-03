"""A mail server for the browser tests (N143): takes every message over plain SMTP on port 2525 and keeps it, and
lists what it took as JSON on http://127.0.0.1:2526/messages (DELETE empties the list). Standard library only."""
from __future__ import annotations

import json
import socketserver
import threading
from email import message_from_bytes, policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SMTP_PORT, HTTP_PORT = 2525, 2526
taken: list[dict] = []
lock = threading.Lock()


class Smtp(socketserver.StreamRequestHandler):
    def reply(self, line: str) -> None:
        self.wfile.write((line + "\r\n").encode())

    def handle(self) -> None:
        self.reply("220 sink ESMTP")
        sender, rcpts = "", []
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            cmd = raw.decode("utf-8", "replace").strip()
            verb = cmd.split(" ", 1)[0].upper()
            if verb in ("EHLO", "HELO"):
                self.reply("250 sink")
            elif verb == "MAIL":
                sender, rcpts = cmd.split(":", 1)[1].strip().strip("<>").split(">")[0], []
                self.reply("250 OK")
            elif verb == "RCPT":
                rcpts.append(cmd.split(":", 1)[1].strip().strip("<>").split(">")[0])
                self.reply("250 OK")
            elif verb == "DATA":
                self.reply("354 go on")
                lines = []
                while (ln := self.rfile.readline()) not in (b".\r\n", b".\n", b""):
                    lines.append(ln[1:] if ln.startswith(b"..") else ln)
                msg = message_from_bytes(b"".join(lines), policy=policy.default)
                body = msg.get_body(preferencelist=("plain",))
                with lock:
                    taken.append({"from": sender, "to": rcpts, "subject": str(msg["Subject"] or ""),
                                  "reply_to": str(msg["Reply-To"] or ""), "text": body.get_content() if body else "",
                                  "attachments": [a.get_filename() for a in msg.iter_attachments()],
                                  "pdf": [a.get_content()[:8].decode("latin-1") for a in msg.iter_attachments()
                                          if a.get_content_type() == "application/pdf"]})
                self.reply("250 taken")
            elif verb == "RSET":
                sender, rcpts = "", []
                self.reply("250 OK")
            elif verb == "QUIT":
                self.reply("221 bye")
                return
            else:
                self.reply("250 OK")


class Http(BaseHTTPRequestHandler):
    def _send(self, data: object) -> None:
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        with lock:
            self._send(list(taken))

    def do_DELETE(self) -> None:  # noqa: N802
        with lock:
            taken.clear()
        self._send([])

    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    smtp = socketserver.ThreadingTCPServer(("127.0.0.1", SMTP_PORT), Smtp)
    threading.Thread(target=smtp.serve_forever, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", HTTP_PORT), Http).serve_forever()
