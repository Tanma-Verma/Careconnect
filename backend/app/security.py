import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response
from pwdlib import PasswordHash

from .db import audit, connect
from .timing import timed

COOKIE = "careconnect_session"
passwords = PasswordHash.recommended()
DUMMY_HASH = passwords.hash("unusable-dummy-password-for-timing")


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


@timed("authentication")
def session_user(request: Request):
    token = request.cookies.get(COOKIE, "")
    if not token or len(token) > 128:
        raise HTTPException(401, "Sign in to continue.")
    with connect(request.app.state.settings) as conn:
        user = conn.execute(
            "SELECT u.id,u.email,u.role,s.csrf FROM cc_sessions s JOIN cc_users u ON u.id=s.user_id "
            "WHERE s.token_hash=%s AND s.expires_at>now()", (digest(token),)
        ).fetchone()
    if not user:
        raise HTTPException(401, "Your session has expired. Sign in again.")
    if user["role"] not in {"PATIENT", "PRACTITIONER", "ADMIN"}:
        raise HTTPException(403, "Unsupported account role.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if not secrets.compare_digest(request.headers.get("x-csrf-token", "").encode(), user["csrf"].encode()):
            raise HTTPException(403, "Invalid CSRF token. Reload the page.")
    return user


def patient_user(user=Depends(session_user)):
    if user["role"] != "PATIENT":
        raise HTTPException(403, "A patient account is required.")
    return user


def practitioner_user(user=Depends(session_user)):
    if user["role"] != "PRACTITIONER":
        raise HTTPException(403, "A practitioner account is required.")
    return user


def create_session(conn, settings, user, response: Response, request: Request):
    old = request.cookies.get(COOKIE)
    if old:
        conn.execute("DELETE FROM cc_sessions WHERE token_hash=%s", (digest(old),))
    conn.execute("DELETE FROM cc_sessions WHERE expires_at<=now()")
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO cc_sessions(token_hash,user_id,csrf,expires_at) VALUES (%s,%s,%s,%s)",
        (digest(token), user["id"], csrf, datetime.now(timezone.utc) + timedelta(hours=settings.session_hours)),
    )
    response.set_cookie(COOKIE, token, max_age=settings.session_hours * 3600,
                        httponly=True, secure=settings.cookie_secure, samesite="strict", path="/")
    return {"user": {key: user[key] for key in ("id", "email", "role")}, "csrf_token": csrf}


def check_auth_rate(conn, address):
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,1))", (address,))
    conn.execute("DELETE FROM cc_login_attempts WHERE created_at < now()-interval '15 minutes'")
    count = conn.execute("SELECT count(*) AS n FROM cc_login_attempts WHERE address=%s", (address,)).fetchone()["n"]
    if count >= 20:
        raise HTTPException(429, "Too many authentication attempts. Try again in 15 minutes.")
    conn.execute("INSERT INTO cc_login_attempts(address) VALUES (%s)", (address,))
