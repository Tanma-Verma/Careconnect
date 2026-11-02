"""Practitioner operations gated by assignment and explicit patient consent."""
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .db import audit, connect
from .erp_access import (APPOINTMENT_FIELDS, APPOINTMENT_JOINS, DOCUMENT_FIELDS,
                         DOCTOR_APPOINTMENT_SCOPE, doctor_user, require_access)
from .patient_routes import own_observations
from .provider import ProviderError
from .rag import answer_question

router = APIRouter(prefix="/api/v1/doctor", tags=["doctor"])

PATIENT_SCOPE = (
    " FROM cc_patient_profiles p JOIN cc_assignments a ON a.patient_id=p.user_id "
    "JOIN cc_consents c ON c.patient_id=a.patient_id AND c.doctor_id=a.doctor_id "
    "WHERE a.doctor_id=%s AND a.active AND c.records "
)


class Note(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=10000)
    appointment_id: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("content")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Clinical note must not be blank")
        return value.strip()


class AppointmentStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["CONFIRMED", "COMPLETED", "CANCELLED"]


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)

    @field_validator("message")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Question must not be blank")
        return value.strip()


@router.get("/dashboard")
def dashboard(request: Request, user=Depends(doctor_user)):
    with connect(request.app.state.settings) as conn:
        assigned = conn.execute("SELECT count(*) AS n" + PATIENT_SCOPE, (user["id"],)).fetchone()["n"]
        stats = conn.execute(
            "SELECT count(*) FILTER (WHERE a.scheduled_at::date=current_date) AS today_appointments,"
            "count(*) FILTER (WHERE a.scheduled_at>=now() AND a.status IN ('REQUESTED','CONFIRMED')) AS upcoming_appointments,"
            "count(*) FILTER (WHERE a.status='REQUESTED') AS pending_tasks FROM cc_appointments a "
            "WHERE a.doctor_id=%s AND " + DOCTOR_APPOINTMENT_SCOPE, (user["id"],),
        ).fetchone()
        stats["assigned_patients"] = assigned
        stats["recent_reports"] = conn.execute(
            "SELECT count(*) AS n FROM cc_documents d JOIN cc_assignments a ON a.patient_id=d.owner_id "
            "JOIN cc_consents c ON c.patient_id=a.patient_id AND c.doctor_id=a.doctor_id "
            "WHERE a.doctor_id=%s AND a.active AND c.records", (user["id"],),
        ).fetchone()["n"]
        appointments = conn.execute("SELECT " + APPOINTMENT_FIELDS + APPOINTMENT_JOINS +
            "WHERE a.doctor_id=%s AND " + DOCTOR_APPOINTMENT_SCOPE +
            " AND a.scheduled_at>=now() AND a.status IN ('REQUESTED','CONFIRMED') ORDER BY a.scheduled_at LIMIT 5",
            (user["id"],)).fetchall()
        documents = conn.execute(
            "SELECT d.id,d.owner_id AS patient_id,d.filename,d.media_type,d.state,d.chunk_count,d.created_at,p.name AS patient_name "
            "FROM cc_documents d JOIN cc_patient_profiles p ON p.user_id=d.owner_id "
            "JOIN cc_assignments a ON a.patient_id=d.owner_id JOIN cc_consents c "
            "ON c.patient_id=a.patient_id AND c.doctor_id=a.doctor_id "
            "WHERE a.doctor_id=%s AND a.active AND c.records ORDER BY d.created_at DESC LIMIT 5", (user["id"],),
        ).fetchall()
        audit(conn, user["id"], "DOCTOR_DASHBOARD_VIEW")
    return {"stats": stats, "appointments": appointments, "documents": documents}


@router.get("/patients")
def patients(request: Request, q: str = Query("", max_length=100), user=Depends(doctor_user)):
    with connect(request.app.state.settings) as conn:
        rows = conn.execute(
            "SELECT p.user_id AS id,p.name,p.dob,p.sex,p.is_demo,c.records,c.clinical,c.ai" + PATIENT_SCOPE +
            "AND p.name ILIKE %s ORDER BY p.name", (user["id"], "%" + q + "%"),
        ).fetchall()
        audit(conn, user["id"], "DOCTOR_PATIENT_LIST")
    return {"patients": rows}


@router.get("/patients/{patient_id}")
def patient(patient_id: str, request: Request, user=Depends(doctor_user)):
    with connect(request.app.state.settings) as conn:
        consent = require_access(conn, user["id"], patient_id, "records")
        row = conn.execute("SELECT user_id AS id,name,dob,sex,is_demo FROM cc_patient_profiles WHERE user_id=%s",
                           (patient_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Patient profile not found.")
        audit(conn, user["id"], "DOCTOR_PATIENT_VIEW")
    return {"patient": row, "consent": consent}


@router.get("/patients/{patient_id}/documents")
def documents(patient_id: str, request: Request, user=Depends(doctor_user)):
    with connect(request.app.state.settings) as conn:
        require_access(conn, user["id"], patient_id, "records")
        rows = conn.execute("SELECT " + DOCUMENT_FIELDS +
            ",owner_id AS patient_id FROM cc_documents WHERE owner_id=%s ORDER BY created_at DESC", (patient_id,)).fetchall()
        audit(conn, user["id"], "DOCTOR_DOCUMENT_LIST")
    return {"documents": rows}


@router.get("/patients/{patient_id}/history")
def history(patient_id: str, request: Request, user=Depends(doctor_user)):
    with connect(request.app.state.settings) as conn:
        consent = require_access(conn, user["id"], patient_id, "clinical")
        row = conn.execute("SELECT history FROM cc_patient_profiles WHERE user_id=%s", (patient_id,)).fetchone()
        notes = conn.execute(
            "SELECT n.*,d.name AS doctor_name FROM cc_notes n JOIN cc_doctor_profiles d ON d.user_id=n.doctor_id "
            "WHERE n.patient_id=%s ORDER BY n.created_at DESC", (patient_id,),
        ).fetchall()
        documents, observations = [], []
        if consent["records"]:
            documents = conn.execute("SELECT " + DOCUMENT_FIELDS +
                " FROM cc_documents WHERE owner_id=%s ORDER BY created_at DESC", (patient_id,)).fetchall()
            observations = own_observations(conn, patient_id)
        audit(conn, user["id"], "DOCTOR_HISTORY_VIEW")
    return {"history": row["history"] if row else [], "notes": notes, "documents": documents, "observations": observations}


@router.get("/patients/{patient_id}/notes")
def notes(patient_id: str, request: Request, user=Depends(doctor_user)):
    with connect(request.app.state.settings) as conn:
        require_access(conn, user["id"], patient_id, "clinical")
        rows = conn.execute(
            "SELECT n.*,d.name AS doctor_name FROM cc_notes n JOIN cc_doctor_profiles d ON d.user_id=n.doctor_id "
            "WHERE n.patient_id=%s ORDER BY n.created_at DESC", (patient_id,),
        ).fetchall()
        audit(conn, user["id"], "DOCTOR_NOTES_VIEW")
    return {"notes": rows}


@router.post("/patients/{patient_id}/notes", status_code=201)
def create_note(patient_id: str, body: Note, request: Request, user=Depends(doctor_user)):
    with connect(request.app.state.settings) as conn:
        require_access(conn, user["id"], patient_id, "clinical")
        if body.appointment_id and not conn.execute(
            "SELECT 1 FROM cc_appointments WHERE id=%s AND doctor_id=%s AND patient_id=%s",
            (body.appointment_id, user["id"], patient_id),
        ).fetchone():
            raise HTTPException(404, "Matching appointment not found.")
        row = conn.execute(
            "INSERT INTO cc_notes(id,doctor_id,patient_id,appointment_id,content) VALUES (%s,%s,%s,%s,%s) RETURNING *",
            (str(uuid4()), user["id"], patient_id, body.appointment_id, body.content),
        ).fetchone()
        audit(conn, user["id"], "DOCTOR_NOTE_CREATE")
    return {"note": row}


@router.get("/patients/{patient_id}/documents/{document_id}/source")
def source(patient_id: str, document_id: str, request: Request, user=Depends(doctor_user)):
    settings = request.app.state.settings
    with connect(settings) as conn:
        require_access(conn, user["id"], patient_id, "records")
        row = conn.execute("SELECT id,filename,media_type FROM cc_documents WHERE id=%s AND owner_id=%s",
                           (document_id, patient_id)).fetchone()
        if not row:
            raise HTTPException(404, "Document not found.")
        path = settings.documents_dir / row["id"]
        if not path.resolve().is_relative_to(settings.documents_dir.resolve()) or not path.is_file():
            raise HTTPException(404, "Original file is unavailable.")
        audit(conn, user["id"], "DOCTOR_DOCUMENT_VIEW")
    return FileResponse(path, media_type=row["media_type"], filename=row["filename"], content_disposition_type="inline")


@router.post("/patients/{patient_id}/ai/chat")
def chat(patient_id: str, body: Question, request: Request, user=Depends(doctor_user)):
    settings = request.app.state.settings

    def current_access():
        with connect(settings) as conn:
            require_access(conn, user["id"], patient_id, "records", "ai")

    current_access()
    try:
        result = answer_question(settings, request.app.state.provider, request.app.state.vectors,
                                 patient_id, body.message, authorization_check=current_access)
    except (HTTPException, ProviderError):
        raise
    except Exception:
        raise HTTPException(503, "Retrieval is unavailable. Check Chroma connectivity and embedding configuration.") from None
    current_access()
    for citation in result["citations"]:
        citation["url"] = f"/api/v1/doctor/patients/{patient_id}/documents/{citation['document_id']}/source"
        if citation["page"]:
            citation["url"] += f"#page={citation['page']}"
    result["request_id"] = request.state.request_id
    with connect(settings) as conn:
        audit(conn, user["id"], "DOCTOR_AI_CHAT")
    return result


@router.get("/appointments")
def appointments(request: Request, user=Depends(doctor_user)):
    with connect(request.app.state.settings) as conn:
        rows = conn.execute("SELECT " + APPOINTMENT_FIELDS + APPOINTMENT_JOINS +
            "WHERE a.doctor_id=%s AND " + DOCTOR_APPOINTMENT_SCOPE +
            " ORDER BY a.scheduled_at DESC", (user["id"],)).fetchall()
        audit(conn, user["id"], "DOCTOR_APPOINTMENT_LIST")
    return {"appointments": rows}


@router.patch("/appointments/{appointment_id}")
def update_appointment(appointment_id: str, body: AppointmentStatus, request: Request, user=Depends(doctor_user)):
    with connect(request.app.state.settings) as conn:
        row = conn.execute("SELECT * FROM cc_appointments WHERE id=%s AND doctor_id=%s FOR UPDATE",
                           (appointment_id, user["id"])).fetchone()
        if not row:
            raise HTTPException(404, "Appointment not found.")
        require_access(conn, user["id"], row["patient_id"], "clinical")
        allowed = {"REQUESTED": {"CONFIRMED", "CANCELLED"}, "CONFIRMED": {"COMPLETED", "CANCELLED"},
                   "COMPLETED": set(), "CANCELLED": set()}
        if body.status != row["status"] and body.status not in allowed[row["status"]]:
            raise HTTPException(409, "This appointment status transition is not allowed.")
        row = conn.execute("UPDATE cc_appointments SET status=%s WHERE id=%s RETURNING *",
                           (body.status, appointment_id)).fetchone()
        audit(conn, user["id"], "DOCTOR_APPOINTMENT_UPDATE")
    return {"appointment": row}


@router.get("/profile")
def profile(request: Request, user=Depends(doctor_user)):
    with connect(request.app.state.settings) as conn:
        row = conn.execute("SELECT * FROM cc_doctor_profiles WHERE user_id=%s", (user["id"],)).fetchone()
    if not row:
        raise HTTPException(404, "Practitioner profile not found.")
    return {"profile": {**row, "email": user["email"], "role": user["role"]}}
