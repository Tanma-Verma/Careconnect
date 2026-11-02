import asyncio
import hashlib
import logging
import re
from contextlib import asynccontextmanager
from typing import Literal
from uuid import uuid4

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware
from urllib.parse import urlparse

from .config import Settings
from .db import audit, connect, initialize
from .documents import chunk_pages, extract
from .provider import Provider, ProviderError
from .rag import Vectors, answer_question
from .security import COOKIE, DUMMY_HASH, check_auth_rate, create_session, digest, passwords, session_user, patient_user
from .timing import TimingMiddleware

logger = logging.getLogger("careconnect")


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address")
        return value


class Registration(Credentials):
    role: Literal["PATIENT"] = "PATIENT"


class Chat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)

    @field_validator("message")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("Message is empty")
        return value.strip()


class RequestGuard:
    """Bound request bodies before multipart parsing; require same-origin browser writes."""
    def __init__(self, app, settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        if scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
            if (headers.get("origin", self.settings.origin) != self.settings.origin
                    or headers.get("sec-fetch-site", "same-origin") not in {"same-origin", "none"}
                    or headers.get("x-requested-with") != "CareConnect"):
                return await JSONResponse({"error": "Same-origin CareConnect requests are required."}, 403)(scope, receive, send)
            limit = self.settings.max_upload + 65536 if scope["path"] == "/api/v1/documents" else 16384
            body = bytearray()
            try:
                while True:
                    message = await asyncio.wait_for(receive(), timeout=20)
                    if message["type"] == "http.disconnect":
                        return
                    body.extend(message.get("body", b""))
                    if len(body) > limit:
                        return await JSONResponse({"error": "Request is too large."}, 413)(scope, receive, send)
                    if not message.get("more_body", False):
                        break
            except TimeoutError:
                return await JSONResponse({"error": "Upload timed out."}, 408)(scope, receive, send)
            delivered = False
            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()
            return await self.app(scope, replay, send)
        return await self.app(scope, receive, send)


def public_document(row):
    return {key: row[key] for key in ("id", "filename", "media_type", "size_bytes", "pages", "state", "error", "chunk_count", "created_at")}


def create_app(settings=None, provider=None, vectors=None):
    settings = settings or Settings()
    settings.validate()

    @asynccontextmanager
    async def lifespan(app):
        initialize(settings)
        settings.documents_dir.mkdir(parents=True, exist_ok=True)
        # ponytail: one Uvicorn worker, synchronous bounded ingestion; use a durable job queue before scaling workers.
        with connect(settings) as conn:
            conn.execute("UPDATE cc_documents SET state='FAILED',error='Ingestion interrupted by restart. Upload the same file to retry.' WHERE state='PROCESSING'")
        logger.warning("CareConnect started. Embeddings configured=%s; LLM configured=%s. No credentials are logged.",
                       all((settings.embedding_url, settings.embedding_key, settings.embedding_model)),
                       all((settings.llm_url, settings.llm_key, settings.llm_model)))
        yield
        app.state.provider.close()

    app = FastAPI(title="CareConnect patient document assistant", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.provider = provider or Provider(settings)
    app.state.vectors = vectors or Vectors(settings)
    app.add_middleware(RequestGuard, settings=settings)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list({urlparse(settings.origin).hostname, "localhost", "127.0.0.1"}))

    @app.middleware("http")
    async def response_security(request, call_next):
        request.state.request_id = getattr(request.state, "request_id", str(uuid4()))
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse({"error": str(exc.detail), "request_id": request.state.request_id}, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        errors = [".".join(str(x) for x in e["loc"][1:]) + ": " + e["msg"] for e in exc.errors()]
        return JSONResponse({"error": "; ".join(errors), "request_id": request.state.request_id}, 422)

    @app.exception_handler(ProviderError)
    async def provider_error(request, exc):
        return JSONResponse({"error": str(exc), "request_id": request.state.request_id}, 502)

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        logger.error("Request %s failed (%s)", request.state.request_id, type(exc).__name__)
        return JSONResponse({"error": "Service unavailable. Retry or check backend diagnostics.", "request_id": request.state.request_id}, 503)

    @app.get("/health")
    def health():
        try:
            with connect(settings) as conn:
                conn.execute("SELECT 1")
            app.state.vectors.heartbeat()
        except Exception:
            return JSONResponse({"status": "unhealthy", "error": "PostgreSQL or Chroma is unreachable."}, 503)
        return {"status": "ok", "database": "ok", "chroma": "ok", "providers": {
            "embeddings_configured": bool(settings.embedding_url and settings.embedding_key and settings.embedding_model),
            "llm_configured": bool(settings.llm_url and settings.llm_key and settings.llm_model),
            "connectivity": "not_checked_by_health",
        }}

    def rate_limit(request):
        with connect(settings) as conn:
            check_auth_rate(conn, request.client.host if request.client else "unknown")

    @app.post("/api/v1/auth/register", status_code=201)
    def register(body: Registration, request: Request, response: Response):
        rate_limit(request)
        user = {"id": str(uuid4()), "email": body.email, "role": "PATIENT"}
        hashed = passwords.hash(body.password)
        try:
            with connect(settings) as conn:
                conn.execute("INSERT INTO cc_users(id,email,password_hash) VALUES (%s,%s,%s)", (user["id"], body.email, hashed))
                audit(conn, user["id"], "AUTH_REGISTER")
                return create_session(conn, settings, user, response, request)
        except psycopg.errors.UniqueViolation:
            raise HTTPException(409, "An account with this email already exists.") from None

    @app.post("/api/v1/auth/login")
    def login(body: Credentials, request: Request, response: Response):
        rate_limit(request)
        with connect(settings) as conn:
            user = conn.execute("SELECT * FROM cc_users WHERE email=%s", (body.email,)).fetchone()
            valid = passwords.verify(body.password, user["password_hash"] if user else DUMMY_HASH)
            if not user or not valid:
                raise HTTPException(401, "Invalid email or password.")
            audit(conn, user["id"], "AUTH_LOGIN")
            return create_session(conn, settings, user, response, request)

    @app.get("/api/v1/auth/me")
    def me(user=Depends(session_user)):
        return {"user": {k: user[k] for k in ("id", "email", "role")}, "csrf_token": user["csrf"]}

    @app.post("/api/v1/auth/logout")
    def logout(request: Request, response: Response, user=Depends(session_user)):
        with connect(settings) as conn:
            conn.execute("DELETE FROM cc_sessions WHERE token_hash=%s", (digest(request.cookies[COOKIE]),))
            audit(conn, user["id"], "AUTH_LOGOUT")
        response.delete_cookie(COOKIE, path="/", httponly=True, secure=settings.cookie_secure, samesite="strict")
        return {"ok": True}

    @app.get("/api/v1/records")
    @app.get("/api/v1/documents")
    def documents(user=Depends(patient_user)):
        with connect(settings) as conn:
            rows = conn.execute("SELECT * FROM cc_documents WHERE owner_id=%s ORDER BY created_at DESC", (user["id"],)).fetchall()
        return {"documents": [public_document(row) for row in rows]}

    @app.post("/api/v1/documents")
    def upload(file: UploadFile, response: Response, user=Depends(patient_user)):
        filename = (file.filename or "document").replace("\\", "/").split("/")[-1]
        filename = "".join(c for c in filename if c.isprintable())[:180]
        data = file.file.read(settings.max_upload + 1)
        pages, media_type = extract(filename, file.content_type or "", data, settings)
        sha = hashlib.sha256(data).hexdigest()
        with connect(settings) as conn:
            # Session advisory lock prevents concurrent retries for the same patient, including across requests.
            locked = conn.execute("SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS locked", (user["id"],)).fetchone()["locked"]
            if not locked:
                raise HTTPException(409, "Another document is being processed. Wait and retry.")
            row = conn.execute("SELECT * FROM cc_documents WHERE owner_id=%s AND sha256=%s", (user["id"], sha)).fetchone()
            if row and row["state"] == "READY" and row["pipeline"] == settings.pipeline:
                return {"document": public_document(row), "duplicate": True}
            document_id = row["id"] if row else str(uuid4())
            chunks = chunk_pages(pages, document_id)
            path = settings.documents_dir / document_id
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(data)
            temporary.replace(path)
            conn.execute(
                "INSERT INTO cc_documents(id,owner_id,sha256,filename,media_type,size_bytes,pages,pipeline,state) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'PROCESSING') "
                "ON CONFLICT(owner_id,sha256) DO UPDATE SET state='PROCESSING',error=NULL,pipeline=EXCLUDED.pipeline,updated_at=now()",
                (document_id, user["id"], sha, filename, media_type, len(data), len(pages), settings.pipeline),
            )
            conn.commit()
            try:
                app.state.vectors.index(user["id"], document_id, chunks, app.state.provider)
                conn.execute("DELETE FROM cc_chunks WHERE document_id=%s", (document_id,))
                with conn.cursor() as cursor:
                    cursor.executemany("INSERT INTO cc_chunks(id,document_id,page,source_text) VALUES (%s,%s,%s,%s)",
                                       [(c["id"], document_id, c["page"], c["text"]) for c in chunks])
                conn.execute("UPDATE cc_documents SET state='READY',error=NULL,chunk_count=%s,updated_at=now() WHERE id=%s", (len(chunks), document_id))
                audit(conn, user["id"], "DOCUMENT_INGEST")
                conn.commit()
            except Exception as exc:
                conn.rollback()
                error = str(exc) if isinstance(exc, ProviderError) else "Vector indexing failed. Check Chroma connectivity and retry the same file."
                conn.execute("UPDATE cc_documents SET state='FAILED',error=%s,updated_at=now() WHERE id=%s", (error, document_id))
                conn.commit()
                logger.warning("Document ingestion failed (%s)", type(exc).__name__)
            row = conn.execute("SELECT * FROM cc_documents WHERE id=%s", (document_id,)).fetchone()
            if row["state"] == "FAILED":
                response.status_code = 502
            return {"document": public_document(row), "duplicate": False, "error": row["error"]}

    @app.get("/api/v1/documents/{document_id}")
    def document(document_id: str, user=Depends(patient_user)):
        with connect(settings) as conn:
            row = conn.execute("SELECT * FROM cc_documents WHERE id=%s AND owner_id=%s", (document_id, user["id"])).fetchone()
        if not row:
            raise HTTPException(404, "Document not found.")
        return {"document": public_document(row)}

    @app.get("/api/v1/documents/{document_id}/source")
    def source(document_id: str, user=Depends(patient_user)):
        with connect(settings) as conn:
            row = conn.execute("SELECT * FROM cc_documents WHERE id=%s AND owner_id=%s", (document_id, user["id"])).fetchone()
            if not row:
                raise HTTPException(404, "Document not found.")
            audit(conn, user["id"], "DOCUMENT_VIEW")
        path = settings.documents_dir / row["id"]
        if not path.is_file():
            raise HTTPException(404, "Original file is unavailable.")
        return FileResponse(path, media_type=row["media_type"], filename=row["filename"], content_disposition_type="inline")

    @app.post("/api/v1/ai/chat")
    def chat(body: Chat, request: Request, user=Depends(patient_user)):
        try:
            result = answer_question(settings, app.state.provider, app.state.vectors, user["id"], body.message)
            result["request_id"] = request.state.request_id
            return result
        except ProviderError:
            raise
        except Exception:
            raise HTTPException(503, "Retrieval is unavailable. Check Chroma connectivity and embedding configuration.") from None

    @app.get("/api/v1/audit")
    def audit_events(user=Depends(session_user)):
        with connect(settings) as conn:
            events = conn.execute("SELECT action,created_at AS \"createdAt\",'SUCCESS' AS outcome FROM cc_audit WHERE user_id=%s ORDER BY id DESC LIMIT 50", (user["id"],)).fetchall()
        return {"events": events}

    from .doctor_routes import router as doctor_router
    from .patient_routes import router as patient_router
    app.include_router(doctor_router)
    app.include_router(patient_router)

    @app.api_route("/api/{unimplemented:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def unavailable(unimplemented: str, user=Depends(session_user)):
        raise HTTPException(501, "This feature is outside the patient document assistant demo.")

    app.add_middleware(TimingMiddleware)
    app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
    return app


app = create_app()
