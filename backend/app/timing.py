"""Content-free request timings. Never pass payloads, identities or headers here."""
import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import perf_counter
from uuid import uuid4

current = ContextVar("rag_timing", default=None)
STAGES = ("authentication", "question_embedding", "chroma_retrieval", "ownership_validation",
          "context_construction", "generation", "json_citation_validation", "audit")


class Timings:
    def __init__(self, request_id=None):
        self.request_id = request_id or str(uuid4())
        self.started = perf_counter()
        self.stages = dict.fromkeys(STAGES, 0.0)
        self.attempts = []

    def summary(self, status):
        total = (perf_counter() - self.started) * 1000
        return {"request_id": self.request_id, "status": status,
                "stages_ms": {k: round(v, 3) for k, v in self.stages.items()},
                "request_overhead_ms": round(max(0, total - sum(self.stages.values())), 3),
                "total_ms": round(total, 3), "provider_attempts": self.attempts}


@contextmanager
def measure(name):
    trace = current.get()
    start = perf_counter()
    try:
        yield
    finally:
        if trace is not None:
            trace.stages[name] += (perf_counter() - start) * 1000


def timed(name):
    def decorate(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            with measure(name):
                return function(*args, **kwargs)
        return wrapper
    return decorate


class TimingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/api/v1/ai/chat" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        trace = Timings()
        scope.setdefault("state", {})["request_id"] = trace.request_id
        token = current.set(trace)
        status = 500
        async def capture(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)
        try:
            await self.app(scope, receive, capture)
        finally:
            logging.getLogger("careconnect.performance").warning("rag_timing %s", json.dumps(trace.summary(status)))
            current.reset(token)
