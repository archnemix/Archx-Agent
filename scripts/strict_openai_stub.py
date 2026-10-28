"""A strict stand-in for llama-server, so `remote_model.sh` can be rehearsed without one.

It serves exactly the routes llama.cpp serves (`/health`, `/v1/models`,
`POST /v1/chat/completions`, with and without streaming) and answers 404 to everything else.
That strictness is the point: an earlier stub replied to any path, which let a wrong base URL
pass - groq given `/openai/v1` asked for `/openai/v1/openai/v1/chat/completions` and the stub
said 200 while a real server said 404.

    python scripts/strict_openai_stub.py 8477 &
    ./scripts/remote_model.sh http://127.0.0.1:8477
"""
import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def _json(self, code, payload):
        raw = json.dumps(payload).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def _404(self):
        self._json(404, {"error": {"message": "File Not Found", "type": "not_found_error", "code": 404}})
    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/health": return self._json(200, {"status": "ok"})
        if p == "/v1/models": return self._json(200, {"object": "list", "data": [{"id": "local", "object": "model"}]})
        # llama.cpp serves neither of these; a stub that pretends otherwise hides real bugs

        return self._404()
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        p = self.path.split("?")[0]
        if p != "/v1/chat/completions":
            return self._404()
        if body.get("stream"):
            frames = [{"id": "c", "object": "chat.completion.chunk", "model": "local",
                       "choices": [{"index": 0, "delta": {"content": "Hello "}, "finish_reason": None}]},
                      {"id": "c", "object": "chat.completion.chunk", "model": "local",
                       "choices": [{"index": 0, "delta": {"content": "there."}, "finish_reason": "stop"}]}]
            raw = "".join(f"data: {json.dumps(f)}\n\n" for f in frames).encode() + b"data: [DONE]\n\n"
            self.send_response(200); self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
            return
        # `created` is required by the mistralai client's response model, and llama.cpp sends it
        return self._json(200, {"id": "x", "object": "chat.completion", "created": 1, "model": "local",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello there, friend."}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 6, "completion_tokens": 4}})

ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
