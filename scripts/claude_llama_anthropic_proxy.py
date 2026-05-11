#!/usr/bin/env python3
"""Small Anthropic-compatible proxy for Claude Code -> llama-server.

llama-server already supports /v1/messages, but Claude Code sends long streaming
requests and the DeepSeek chat template benefits from explicit stop sequences.
This proxy only caps max_tokens and injects stop_sequences, then forwards the
request to the local llama-server.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
import http.client
import json
import os
import sys


UPSTREAM_HOST = os.environ.get("LLAMA_UPSTREAM_HOST", "127.0.0.1")
UPSTREAM_PORT = int(os.environ.get("LLAMA_UPSTREAM_PORT", "8080"))
LISTEN_HOST = os.environ.get("CLAUDE_PROXY_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("CLAUDE_PROXY_PORT", "18082"))
MAX_TOKENS = int(os.environ.get("CLAUDE_PROXY_MAX_TOKENS", "2048"))
STOP_SEQUENCES = [
    "<|im_end|>",
    "<｜end▁of▁sentence｜>",
    "<｜end of sentence｜>",
]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[claude-llama-proxy] " + fmt % args + "\n")
        sys.stderr.flush()

    def _forward(self, method):
        body = None
        base_path = urlsplit(self.path).path

        if method == "POST":
            raw = self.rfile.read(int(self.headers.get("content-length", "0") or "0"))
            try:
                data = json.loads(raw or b"{}")
                if base_path.startswith("/v1/messages"):
                    original = data.get("max_tokens")
                    data["max_tokens"] = min(original, MAX_TOKENS) if isinstance(original, int) else MAX_TOKENS
                    if base_path == "/v1/messages":
                        stops = list(data.get("stop_sequences") or [])
                        for stop in STOP_SEQUENCES:
                            if stop not in stops:
                                stops.append(stop)
                        data["stop_sequences"] = stops

                body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                sys.stderr.write(
                    f"[claude-llama-proxy] {self.path} "
                    f"max_tokens={data.get('max_tokens')} stream={data.get('stream')}\n"
                )
                sys.stderr.flush()
            except Exception as exc:
                body = raw
                sys.stderr.write(f"[claude-llama-proxy] raw forward: {exc}\n")
                sys.stderr.flush()

        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"host", "content-length", "connection", "accept-encoding"}
        }
        if body is not None:
            headers["Content-Length"] = str(len(body))

        conn = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=900)
        try:
            conn.request(method, self.path, body=body, headers=headers)
            resp = conn.getresponse()
            payload = resp.read()

            self.send_response(resp.status)
            for key, value in resp.getheaders():
                if key.lower() not in {"transfer-encoding", "content-length", "connection", "content-encoding"}:
                    self.send_header(key, value)
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except Exception as exc:
            payload = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
            self.send_response(502)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        finally:
            conn.close()

    def do_POST(self):
        self._forward("POST")

    def do_GET(self):
        self._forward("GET")


def main():
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    sys.stderr.write(
        f"[claude-llama-proxy] listening on http://{LISTEN_HOST}:{LISTEN_PORT} "
        f"-> http://{UPSTREAM_HOST}:{UPSTREAM_PORT}, max_tokens={MAX_TOKENS}\n"
    )
    sys.stderr.flush()
    server.serve_forever()


if __name__ == "__main__":
    main()
