"""Authenticated patient ERP operations; document ingestion stays in main.py."""
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .db import audit, connect
from .erp_access import APPOINTMENT_FIELDS, APPOINTMENT_JOINS, DOCUMENT_FIELDS, patient_user

router = APIRouter(prefix="/api/v1/patient", tags=["patient"])


class Booking(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doctor_id: str = Field(min_length=1, max_length=100)
    scheduled_at: datetime
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("scheduled_at")
    @classmethod
    def future_date(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Include a timezone in the appointment time")
        now = datetime.now(timezone.utc)
        if not now < value <= now + timedelta(days=366):
            raise ValueError("Appointment must be in the future and within one year")
        return value

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Enter an appointment reason")
        return value.strip()


class Cancellation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["CANCELLED"]


class Consent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    records: bool
    clinical: bool
    ai: bool


def own_observations(conn, patient_id):
    return conn.execute(
        "SELECT o.id,o.document_id,o.code,o.value,o.unit,o.reference_low,o.reference_high,o.measured_at "
        "FROM cc_observations o JOIN cc_documents d ON d.id=o.document_id "
        "WHERE o.patient_id=%s AND d.owner_id=%s ORDER BY o.measured_at DESC,o.code",
        (patient_id, patient_id),
    ).fetchall()


@router.get("/dashboard")
def dashboard(request: Request, user=Depends(patient_user)):
    with connect(request.app.state.settings) as conn:
        counts = conn.execute(
            "SELECT count(*) AS reports,count(*) FILTER (WHERE state='READY' AND pipeline=%s) AS indexed_reports "
            "FROM cc_documents WHERE owner_id=%s", (request.app.state.settings.pipeline, user["id"]),
        ).fetchone()
        counts["upcoming_appointments"] = conn.execute(
            "SELECT count(*) AS n FROM cc_appointments WHERE patient_id=%s AND scheduled_at>=now() "
            "AND status IN ('REQUESTED','CONFIRMED')", (user["id"],),
        ).fetchone()["n"]
        counts["assigned_doctors"] = conn.execute(
            "SELECT count(*) AS n FROM cc_assignments WHERE patient_id=%s AND active", (user["id"],),
        ).fetchone()["n"]
        appointments = conn.execute("SELECT " + APPOINTMENT_FIELDS + APPOINTMENT_JOINS +
            "WHERE a.patient_id=%s AND a.scheduled_at>=now() AND a.status IN ('REQUESTED','CONFIRMED') "
            "ORDER BY a.scheduled_at LIMIT 5", (user["id"],)).fetchall()
        documents = conn.execute("SELECT " + DOCUMENT_FIELDS +
            " FROM cc_documents WHERE owner_id=%s ORDER BY created_at DESC LIMIT 5", (user["id"],)).fetchall()
        observations = own_observations(conn, user["id"])[:30]
    return {"stats": counts, "appointments": appointments, "documents": documents, "observations": observations}


@router.get("/doctors")
def doctors(request: Request, q: str = Query("", max_length=100), specialty: str = Query("", max_length=100),
            user=Depends(patient_user)):
    with connect(request.app.state.settings) as conn:
        rows = conn.execute(
            "SELECT d.user_id AS id,d.name,d.specialty,d.department,d.qualifications,d.experience,d.availability,"
            "d.bio,d.is_demo,EXISTS(SELECT 1 FROM cc_assignments a WHERE a.doctor_id=d.user_id "
            "AND a.patient_id=%s AND a.active) AS assigned FROM cc_doctor_profiles d "
            "JOIN cc_users u ON u.id=d.user_id AND u.role='PRACTITIONER' "
            "WHERE (d.name ILIKE %s OR d.specialty ILIKE %s) AND (%s='' OR d.specialty=%s) ORDER BY d.name",
            (user["id"], "%" + q + "%", "%" + q + "%", specialty, specialty),
        ).fetchall()
    return {"doctors": rows}


@router.get("/appointments")
def appointments(request: Request, user=Depends(patient_user)):
    with connect(request.app.state.settings) as conn:
        rows = conn.execute("SELECT " + APPOINTMENT_FIELDS + APPOINTMENT_JOINS +
            "WHERE a.patient_id=%s ORDER BY a.scheduled_at DESC", (user["id"],)).fetchall()
    return {"appointments": rows}


@router.post("/appointments", status_code=201)
def request_appointment(body: Booking, request: Request, user=Depends(patient_user)):
    with connect(request.app.state.settings) as conn:
        doctor = conn.execute(
            "SELECT d.user_id FROM cc_doctor_profiles d JOIN cc_users u ON u.id=d.user_id "
            "WHERE d.user_id=%s AND u.role='PRACTITIONER'", (body.doctor_id,),
        ).fetchone()
        if not doctor:
            raise HTTPException(404, "Doctor not found.")
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,2))", (user["id"],))
        if conn.execute("SELECT 1 FROM cc_appointments WHERE patient_id=%s AND scheduled_at=%s "
                        "AND status IN ('REQUESTED','CONFIRMED')", (user["id"], body.scheduled_at)).fetchone():
            raise HTTPException(409, "You already have an appointment at this time.")
        appointment = conn.execute(
            "INSERT INTO cc_appointments(id,doctor_id,patient_id,scheduled_at,reason,status) "
            "VALUES (%s,%s,%s,%s,%s,'REQUESTED') RETURNING *",
            (str(uuid4()), body.doctor_id, user["id"], body.scheduled_at, body.reason),
        ).fetchone()
        audit(conn, user["id"], "APPOINTMENT_REQUEST")
    return {"appointment": appointment}


@router.patch("/appointments/{appointment_id}")
def cancel_appointment(appointment_id: str, body: Cancellation, request: Request, user=Depends(patient_user)):
    with connect(request.app.state.settings) as conn:
        row = conn.execute("SELECT * FROM cc_appointments WHERE id=%s AND patient_id=%s FOR UPDATE",
                           (appointment_id, user["id"])).fetchone()
        if not row:
            raise HTTPException(404, "Appointment not found.")
        if row["status"] not in {"REQUESTED", "CONFIRMED", "CANCELLED"}:
            raise HTTPException(409, "A completed appointment cannot be cancelled.")
        row = conn.execute("UPDATE cc_appointments SET status='CANCELLED' WHERE id=%s RETURNING *",
                           (appointment_id,)).fetchone()
        audit(conn, user["id"], "APPOINTMENT_CANCEL")
    return {"appointment": row}


@router.get("/history")
def history(request: Request, user=Depends(patient_user)):
    with connect(request.app.state.settings) as conn:
        profile = conn.execute("SELECT history FROM cc_patient_profiles WHERE user_id=%s", (user["id"],)).fetchone()
        notes = conn.execute(
            "SELECT n.*,d.name AS doctor_name FROM cc_notes n JOIN cc_doctor_profiles d ON d.user_id=n.doctor_id "
            "WHERE n.patient_id=%s ORDER BY n.created_at DESC", (user["id"],),
        ).fetchall()
        documents = conn.execute("SELECT " + DOCUMENT_FIELDS +
            " FROM cc_documents WHERE owner_id=%s ORDER BY created_at DESC", (user["id"],)).fetchall()
        observations = own_observations(conn, user["id"])
        audit(conn, user["id"], "PATIENT_HISTORY_VIEW")
    return {"history": profile["history"] if profile else [], "notes": notes, "documents": documents,
            "observations": observations}


@router.get("/observations")
def observations(request: Request, user=Depends(patient_user)):
    with connect(request.app.state.settings) as conn:
        rows = own_observations(conn, user["id"])
    return {"observations": rows}


@router.get("/consents")
def consents(request: Request, user=Depends(patient_user)):
    with connect(request.app.state.settings) as conn:
        rows = conn.execute(
            "SELECT d.user_id AS doctor_id,d.name AS doctor_name,d.specialty,coalesce(a.active,false) AS assigned,"
            "coalesce(c.records,false) AS records,coalesce(c.clinical,false) AS clinical,coalesce(c.ai,false) AS ai,c.updated_at "
            "FROM cc_doctor_profiles d LEFT JOIN cc_assignments a ON a.doctor_id=d.user_id AND a.patient_id=%s "
            "LEFT JOIN cc_consents c ON c.doctor_id=d.user_id AND c.patient_id=%s "
            "WHERE a.patient_id IS NOT NULL OR c.patient_id IS NOT NULL ORDER BY d.name", (user["id"], user["id"]),
        ).fetchall()
    return {"consents": rows}


@router.put("/consents/{doctor_id}")
def change_consent(doctor_id: str, body: Consent, request: Request, user=Depends(patient_user)):
    if body.ai and not body.records:
        raise HTTPException(422, "AI consent also requires medical-record access consent.")
    with connect(request.app.state.settings) as conn:
        if not conn.execute("SELECT 1 FROM cc_doctor_profiles d JOIN cc_users u ON u.id=d.user_id "
                            "WHERE d.user_id=%s AND u.role='PRACTITIONER'", (doctor_id,)).fetchone():
            raise HTTPException(404, "Doctor not found.")
        if not conn.execute("SELECT 1 FROM cc_assignments WHERE doctor_id=%s AND patient_id=%s AND active",
                            (doctor_id, user["id"])).fetchone():
            raise HTTPException(403, "An active doctor assignment is required before sharing records.")
        row = conn.execute(
            "INSERT INTO cc_consents(doctor_id,patient_id,records,clinical,ai) VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT(doctor_id,patient_id) DO UPDATE SET records=EXCLUDED.records,clinical=EXCLUDED.clinical,"
            "ai=EXCLUDED.ai,updated_at=now() RETURNING *",
            (doctor_id, user["id"], body.records, body.clinical, body.ai),
        ).fetchone()
        audit(conn, user["id"], "CONSENT_UPDATE")
    return {"consent": row}


@router.get("/profile")
def profile(request: Request, user=Depends(patient_user)):
    with connect(request.app.state.settings) as conn:
        row = conn.execute("SELECT * FROM cc_patient_profiles WHERE user_id=%s", (user["id"],)).fetchone()
    return {"profile": {**(row or {"user_id": user["id"], "name": "", "history": [], "demographics": {}, "is_demo": False}),
                        "email": user["email"], "role": user["role"]}}
