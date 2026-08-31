from __future__ import annotations
import os, threading, time
from collections import defaultdict, deque
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

class SimpleRateLimitMiddleware(BaseHTTPMiddleware):
    RULES = {
        "/login": (10, 300), "/register": (8, 600),
        "/forgot-password": (5, 900), "/reset-password": (8, 900), "/checkout": (20, 300),
    }
    def __init__(self, app):
        super().__init__(app)
        self.events = defaultdict(deque)
        self.lock = threading.Lock()
    def _client_ip(self, request) -> str:
        if os.getenv("TRUST_PROXY", "0") == "1":
            forwarded = request.headers.get("x-forwarded-for", "")
            if forwarded:
                return forwarded.split(",", 1)[0].strip()
        return request.client.host if request.client else "unknown"
    async def dispatch(self, request, call_next):
        if request.method != "POST" or request.url.path not in self.RULES:
            return await call_next(request)
        max_requests, window = self.RULES[request.url.path]
        key, now = (self._client_ip(request), request.url.path), time.monotonic()
        with self.lock:
            bucket = self.events[key]
            cutoff = now - window
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= max_requests:
                return JSONResponse({"detail": "Забагато спроб. Спробуйте пізніше."}, status_code=429,
                                    headers={"Retry-After": str(window)})
            bucket.append(now)
        return await call_next(request)
