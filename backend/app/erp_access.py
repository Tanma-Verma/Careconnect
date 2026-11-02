"""Role and current-consent checks shared by the two ERP routers."""
from fastapi import Depends, HTTPException

from .security import session_user


def patient_user(user=Depends(session_user)):
    if user["role"] != "PATIENT":
        raise HTTPException(403, "This operation requires a patient account.")
    return user


def doctor_user(user=Depends(session_user)):
    if user["role"] != "PRACTITIONER":
        raise HTTPException(403, "This operation requires a practitioner account.")
    return user


def require_access(conn, doctor_id, patient_id, *scopes):
    """A role alone never grants access. Scope names come only from server code."""
    if not scopes or any(scope not in {"records", "clinical", "ai"} for scope in scopes):
        raise ValueError("An explicit supported consent scope is required")
    row = conn.execute(
        "SELECT c.records,c.clinical,c.ai FROM cc_assignments a "
        "JOIN cc_consents c ON c.doctor_id=a.doctor_id AND c.patient_id=a.patient_id "
        "JOIN cc_users u ON u.id=a.patient_id AND u.role='PATIENT' "
        "WHERE a.doctor_id=%s AND a.patient_id=%s AND a.active",
        (doctor_id, patient_id),
    ).fetchone()
    if not row or not all(row[scope] for scope in scopes):
        raise HTTPException(403, "An active patient assignment and current consent for this operation are required.")
    return row


DOCUMENT_FIELDS = "id,filename,media_type,size_bytes,pages,state,error,chunk_count,created_at"
APPOINTMENT_FIELDS = (
    "a.id,a.patient_id,a.doctor_id,a.scheduled_at,a.reason,a.status,a.created_at,"
    "p.name AS patient_name,d.name AS doctor_name,d.specialty"
)
APPOINTMENT_JOINS = (
    " FROM cc_appointments a LEFT JOIN cc_patient_profiles p ON p.user_id=a.patient_id "
    "JOIN cc_doctor_profiles d ON d.user_id=a.doctor_id "
)
DOCTOR_APPOINTMENT_SCOPE = (
    "EXISTS (SELECT 1 FROM cc_assignments x JOIN cc_consents c "
    "ON c.doctor_id=x.doctor_id AND c.patient_id=x.patient_id "
    "WHERE x.doctor_id=a.doctor_id AND x.patient_id=a.patient_id AND x.active AND c.clinical)"
)
