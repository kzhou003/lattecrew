#!/usr/bin/env python3
"""Logging reverse proxy: records each chat request body, then forwards to llama-swap. Streams the reply back."""
import http.server, json, os, sys, time, urllib.request as u
UP = "http://127.0.0.1:8100"; OUT = sys.argv[1]
class H(http.server.BaseHTTPRequestHandler):
    def _go(self, body=None):
        if body is not None and self.path.endswith("/chat/completions"):
            b = json.loads(body)
            if os.environ.get("REORDER") and b.get("tools"):
                # Keep the cacheable prefix stable: tools whose text changes per session go last.
                vol = lambda t: "/scratch/" in json.dumps(t)
                b["tools"] = [t for t in b["tools"] if not vol(t)] + [t for t in b["tools"] if vol(t)]
                body = json.dumps(b).encode()
            with open(OUT, "a") as f: f.write(json.dumps({"t": time.time(), "body": b}) + "\n")
        req = u.Request(UP + self.path, data=body, method=self.command, headers={k: v for k, v in self.headers.items() if k.lower() not in ("host", "content-length")})
        try:
            r = u.urlopen(req, timeout=900)
        except u.HTTPError as e:
            r = e
        self.send_response(r.status if hasattr(r, "status") else r.code)
        for k, v in r.headers.items():
            if k.lower() not in ("transfer-encoding", "connection", "content-length"): self.send_header(k, v)
        self.send_header("Connection", "close"); self.end_headers()
        while True:
            chunk = r.read1(65536) if hasattr(r, "read1") else r.read(65536)
            if not chunk: break
            self.wfile.write(chunk); self.wfile.flush()
    def do_GET(self): self._go()
    def do_POST(self): self._go(self.rfile.read(int(self.headers.get("Content-Length", 0))))
    def log_message(self, *a): pass
http.server.ThreadingHTTPServer(("127.0.0.1", 8110), H).serve_forever()
