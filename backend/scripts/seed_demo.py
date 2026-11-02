"""Explicitly enabled, deterministic synthetic ERP data; never embeds or deletes data."""
import argparse
import hashlib
import json
import os
import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid5

from psycopg.types.json import Jsonb
from pwdlib import PasswordHash

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.db import connect, initialize
from app.documents import extract

SEED = 20261101
NAMESPACE = UUID("90e66fb5-d034-47c8-a952-650c2a6efcd8")
DEMO_PATIENT_EMAIL = "demo.patient@example.test"
DEMO_DOCTOR_EMAIL = "demo.doctor@example.test"
UNRELATED_DOCTOR_EMAIL = "demo.unrelated@example.test"
AWAITING_INDEX = "Synthetic demo document awaiting real embeddings. Run index_demo.py."
SPECIALTIES = [
    ("General Medicine", "Internal Medicine", "MBBS, MD"),
    ("Cardiology", "Cardiac Care", "MBBS, MD, DM"),
    ("Endocrinology", "Metabolic Care", "MBBS, MD, DM"),
    ("Nephrology", "Renal Medicine", "MBBS, MD, DM"),
    ("Family Medicine", "Primary Care", "MBBS, DNB"),
    ("Hematology", "Laboratory Medicine", "MBBS, MD"),
    ("Gastroenterology", "Digestive Health", "MBBS, MD, DM"),
    ("Geriatric Medicine", "Adult Care", "MBBS, MD"),
]
REPORT_TYPES = ["Complete blood count", "Blood pressure review", "Fasting glucose", "HbA1c",
                "Lipid profile", "Thyroid function", "Kidney function", "Liver function", "Routine examination"]


def stable_id(kind, index):
    return str(uuid5(NAMESPACE, f"careconnect-demo-v1:{kind}:{index}"))


def require_enabled():
    if os.getenv("DEMO_SEED_ENABLED", "").lower() != "true":
        raise ValueError("Demo writes are disabled. Set DEMO_SEED_ENABLED=true explicitly for a local synthetic demo.")


def _measurement(code, value, unit, low=None, high=None):
    return {"code": code, "value": value, "unit": unit, "reference_low": low, "reference_high": high}


def report_content(index, patient_index):
    """Stable one-page originals with explicit units, dates and reference intervals."""
    rng = random.Random(SEED + index)
    male = patient_index % 2 == 0
    kind = REPORT_TYPES[index % len(REPORT_TYPES)]
    if patient_index == 0:
        visit = min(index, 4)
        measured = [date(2026, 7, 1), date(2026, 8, 1), date(2026, 9, 1), date(2026, 10, 1), date(2026, 11, 1)][visit]
        systolic, diastolic, glucose = [(142, 92, 126), (138, 88, 118), (134, 86, 112), (128, 82, 108), (124, 80, 102)][visit]
        kind = "Longitudinal routine examination and blood count"
        values = [_measurement("systolic_bp", systolic, "mmHg"), _measurement("diastolic_bp", diastolic, "mmHg"),
                  _measurement("fasting_glucose", glucose, "mg/dL", 70, 99),
                  _measurement("hemoglobin", round(14.2 + visit / 10, 1), "g/dL", 13, 17),
                  _measurement("white_blood_cells", 6.4, "10^9/L", 4, 11),
                  _measurement("platelets", 245, "10^9/L", 150, 400),
                  _measurement("hba1c", round(6.1 - visit / 10, 1), "%", 4, 5.6)]
    else:
        measured = date(2026, 9, 1) + timedelta(days=index % 61)
        values = {
            "Complete blood count": [_measurement("hemoglobin", round(rng.uniform(13.2, 15.2), 1), "g/dL", 13 if male else 12, 17 if male else 15.5),
                _measurement("white_blood_cells", round(rng.uniform(4.8, 9.2), 1), "10^9/L", 4, 11), _measurement("platelets", rng.randint(180, 310), "10^9/L", 150, 400)],
            "Blood pressure review": [_measurement("systolic_bp", rng.randint(112, 145), "mmHg"), _measurement("diastolic_bp", rng.randint(72, 92), "mmHg")],
            "Fasting glucose": [_measurement("fasting_glucose", rng.randint(82, 132), "mg/dL", 70, 99)],
            "HbA1c": [_measurement("hba1c", round(rng.uniform(5.1, 7.2), 1), "%", 4, 5.6)],
            "Lipid profile": [_measurement("total_cholesterol", rng.randint(150, 225), "mg/dL", 0, 199), _measurement("ldl_cholesterol", rng.randint(75, 145), "mg/dL", 0, 99),
                _measurement("hdl_cholesterol", rng.randint(42, 65), "mg/dL", 40 if male else 50, None), _measurement("triglycerides", rng.randint(95, 170), "mg/dL", 0, 149)],
            "Thyroid function": [_measurement("tsh", round(rng.uniform(1.1, 4.8), 2), "mIU/L", 0.4, 4), _measurement("free_t4", round(rng.uniform(0.9, 1.6), 2), "ng/dL", 0.8, 1.8)],
            "Kidney function": [_measurement("creatinine", round(rng.uniform(0.7, 1.2), 2), "mg/dL", 0.7 if male else 0.6, 1.3 if male else 1.1),
                _measurement("urea_nitrogen", rng.randint(10, 21), "mg/dL", 7, 20)],
            "Liver function": [_measurement("alt", rng.randint(16, 48), "U/L", 7, 56), _measurement("ast", rng.randint(16, 38), "U/L", 10, 40),
                _measurement("total_bilirubin", round(rng.uniform(0.4, 1.1), 1), "mg/dL", 0.2, 1.2)],
            "Routine examination": [_measurement("systolic_bp", rng.randint(112, 136), "mmHg"), _measurement("diastolic_bp", rng.randint(72, 86), "mmHg"),
                _measurement("pulse", rng.randint(62, 88), "beats/min", 60, 100), _measurement("oxygen_saturation", rng.randint(96, 99), "%", 95, 100)],
        }[kind]
        if kind == "Lipid profile":
            # Keep the synthetic components internally coherent (Friedewald-style total).
            values[0]["value"] = round(values[1]["value"] + values[2]["value"] + values[3]["value"] / 5, 1)
    labels = {"systolic_bp": "Systolic blood pressure", "diastolic_bp": "Diastolic blood pressure", "fasting_glucose": "Fasting blood glucose", "hba1c": "HbA1c"}
    lines = ["SYNTHETIC MEDICAL REPORT - FICTIONAL DEMONSTRATION DATA ONLY",
             f"Fictional patient: Demo Patient {patient_index + 1:03d}", f"Synthetic report number: {index + 1:05d}", f"Report date: {measured.isoformat()}", f"Report type: {kind}",
             "Laboratory intervals below are synthetic adult reference intervals; interpretation requires a clinician."]
    for item in values:
        label = labels.get(item["code"], item["code"].replace("_", " ").capitalize())
        low, high = item["reference_low"], item["reference_high"]
        interval = f"; reference interval {low} to {high} {item['unit']}" if low is not None and high is not None else (f"; reference lower bound {low} {item['unit']}" if low is not None else "; no reference interval specified")
        flag = "below" if low is not None and item["value"] < low else "above" if high is not None and item["value"] > high else "within" if low is not None or high is not None else "not classified against a reference interval"
        lines.append(f"{label}: {item['value']} {item['unit']}{interval}; {flag}{' supplied interval' if flag in {'below','above','within'} else ''}.")
    if patient_index == 0:
        lines.append(f"Blood pressure on {measured.isoformat()}: {systolic}/{diastolic} mmHg. Fasting sample followed an eight-hour fast.")
    lines.extend(["These are observations, not a diagnosis or treatment recommendation.",
                  "Clinical appointment notes are stored separately and are not included in this report. Review results with a healthcare professional."])
    return ("\n".join(lines) + "\n").encode(), measured, values, kind


def seed(settings, doctors=100, patients=100, reports=100, appointments=150, notes=60):
    require_enabled()
    password = os.getenv("DEMO_PASSWORD", "")
    if not 12 <= len(password) <= 128:
        raise ValueError("Set DEMO_PASSWORD to a local password of 12-128 characters; it is never printed or stored as plaintext.")
    if doctors < 2 or patients < 1 or reports < 1 or min(appointments, notes) < 0:
        raise ValueError("Need at least two doctors, one patient, one report; appointment/note counts cannot be negative.")
    if max(doctors, patients, reports, appointments, notes) > 10000:
        raise ValueError("Demo counts are limited to 10,000 each.")
    initialize(settings)
    settings.documents_dir.mkdir(parents=True, exist_ok=True)
    hashed = PasswordHash.recommended().hash(password)
    with connect(settings) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(714226)")
        # Verify reserved identities before inserting anything; never adopt an existing real account.
        accounts = []
        for role, count in [("PRACTITIONER", doctors), ("PATIENT", patients)]:
            kind = "doctor" if role == "PRACTITIONER" else "patient"
            for i in range(count):
                uid = stable_id(kind, i)
                email = (DEMO_PATIENT_EMAIL if kind == "patient" and i == 0 else DEMO_DOCTOR_EMAIL if kind == "doctor" and i == 0 else UNRELATED_DOCTOR_EMAIL if kind == "doctor" and i == 1 else f"{kind}{i+1:03d}@careconnect.example.test")
                existing = conn.execute("SELECT u.id,u.email,u.role,coalesce(p.is_demo,d.is_demo,false) AS is_demo FROM cc_users u LEFT JOIN cc_patient_profiles p ON p.user_id=u.id LEFT JOIN cc_doctor_profiles d ON d.user_id=u.id WHERE u.id=%s OR u.email=%s", (uid, email)).fetchall()
                if existing and (len(existing) != 1 or existing[0] != {"id": uid, "email": email, "role": role, "is_demo": True}):
                    raise ValueError("A reserved demo identifier conflicts with existing data. No existing account will be overwritten.")
                accounts.append((kind, i, uid, email, role))
        for kind, i, uid, email, role in accounts:
            conn.execute("INSERT INTO cc_users(id,email,password_hash,role) VALUES (%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING", (uid, email, hashed, role))
            if kind == "doctor":
                specialty, department, qualifications = SPECIALTIES[i % len(SPECIALTIES)]
                conn.execute("INSERT INTO cc_doctor_profiles(user_id,name,specialty,department,qualifications,experience,availability,bio,is_demo) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,true) ON CONFLICT(user_id) DO NOTHING",
                             (uid, f"Dr. Demo Clinician {i+1:03d}", specialty, department, qualifications, 3 + i % 26, Jsonb([{"day": day, "start": "09:00", "end": "16:00", "timezone": "Asia/Kolkata"} for day in ["Monday", "Wednesday", "Friday"]]), "Fictional practitioner profile for the CareConnect synthetic demonstration."))
            else:
                history = [{"date": "2026-06-01", "summary": "Synthetic routine follow-up; longitudinal readings available in reports." if i == 0 else "Fictional preventive care review; no diagnosis inferred from laboratory values."}]
                conn.execute("INSERT INTO cc_patient_profiles(user_id,name,dob,sex,history,demographics,is_demo) VALUES (%s,%s,%s,%s,%s,%s,true) ON CONFLICT(user_id) DO NOTHING",
                             (uid, f"Demo Patient {i+1:03d}", date(1970 + i % 32, 1 + i % 12, 1 + i % 27), "M" if i % 2 == 0 else "F", Jsonb(history), Jsonb({"city": f"Fictional City {1+i%8}", "country": "Synthetic demo", "synthetic": True})))
        for i in range(patients):
            patient, doctor = stable_id("patient", i), stable_id("doctor", i % doctors)
            conn.execute("INSERT INTO cc_assignments(doctor_id,patient_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (doctor, patient))
            conn.execute("INSERT INTO cc_consents(doctor_id,patient_id,records,clinical,ai) VALUES (%s,%s,true,true,true) ON CONFLICT DO NOTHING", (doctor, patient))
            if i and i % 4 == 0:
                conn.execute("INSERT INTO cc_assignments(doctor_id,patient_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (stable_id("doctor", (i+1) % doctors), patient))
        for i in range(appointments):
            patient_index = i % patients
            scheduled = datetime(2026, 10, 25, 10, tzinfo=timezone.utc) + timedelta(days=i // patients * 11, minutes=patient_index * 30)
            status = "COMPLETED" if scheduled < datetime(2026, 11, 2, tzinfo=timezone.utc) else "CONFIRMED"
            conn.execute("INSERT INTO cc_appointments(id,doctor_id,patient_id,scheduled_at,reason,status) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
                         (stable_id("appointment", i), stable_id("doctor", patient_index % doctors), stable_id("patient", patient_index), scheduled, "Synthetic routine review of recorded measurements", status))
        for i in range(notes):
            patient_index = i % patients
            appt = stable_id("appointment", patient_index) if patient_index < appointments else None
            conn.execute("INSERT INTO cc_notes(id,doctor_id,patient_id,appointment_id,content,created_at) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
                         (stable_id("note", i), stable_id("doctor", patient_index % doctors), stable_id("patient", patient_index), appt,
                          "SYNTHETIC CLINICAL NOTE: Reviewed available measurements at the fictional routine visit. Discussed maintaining a dated home blood-pressure log and bringing laboratory reports to the next review. No treatment was prescribed. This structured note is not indexed in the AI assistant.",
                          datetime(2026, 10, 25, 10, tzinfo=timezone.utc) + timedelta(minutes=patient_index * 30)))
        for i in range(reports):
            patient_index = 0 if i < min(5, reports) else (1 + (i - 5) % (patients - 1) if patients > 1 else 0)
            original, measured, values, kind = report_content(i, patient_index)
            uid, document_id = stable_id("patient", patient_index), stable_id("document", i)
            filename = f"synthetic-{measured.isoformat()}-{kind.lower().replace(' ', '-')}-{i+1:03d}.txt"
            pages, media_type = extract(filename, "text/plain", original, settings)
            digest = hashlib.sha256(original).hexdigest()
            row = conn.execute("SELECT id,owner_id,sha256 FROM cc_documents WHERE id=%s OR (owner_id=%s AND sha256=%s)", (document_id, uid, digest)).fetchone()
            if row and row != {"id": document_id, "owner_id": uid, "sha256": digest}:
                raise ValueError("Reserved demo document conflicts with existing data; existing documents are preserved.")
            path = settings.documents_dir / document_id
            if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("Existing demo original has a different hash; refusing to overwrite it.")
            if not path.exists():
                with path.open("xb") as handle:
                    handle.write(original)
            conn.execute("INSERT INTO cc_documents(id,owner_id,sha256,filename,media_type,size_bytes,pages,pipeline,state,error,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'FAILED',%s,%s) ON CONFLICT(id) DO NOTHING",
                         (document_id, uid, digest, filename, media_type, len(original), len(pages), settings.pipeline, AWAITING_INDEX, datetime.combine(measured, datetime.min.time(), timezone.utc)))
            for j, item in enumerate(values):
                conn.execute("INSERT INTO cc_observations(id,patient_id,document_id,code,value,unit,reference_low,reference_high,measured_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
                             (stable_id("observation", f"{i}:{j}"), uid, document_id, item["code"], item["value"], item["unit"], item["reference_low"], item["reference_high"], datetime.combine(measured, datetime.min.time(), timezone.utc)))
    return {"doctors": doctors, "patients": patients, "reports": reports, "appointments": appointments, "notes": notes,
            "demo_patient_email": DEMO_PATIENT_EMAIL, "demo_doctor_email": DEMO_DOCTOR_EMAIL,
            "unrelated_doctor_email": UNRELATED_DOCTOR_EMAIL, "password": "supplied through DEMO_PASSWORD; existing account passwords unchanged",
            "indexing": "Originals and metadata created; only index_demo.py can mark successful real indexing READY."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name, default in [("doctors",100),("patients",100),("reports",100),("appointments",150),("notes",60)]:
        parser.add_argument("--"+name, type=int, default=default)
    args = parser.parse_args()
    try:
        print(json.dumps(seed(Settings(), **vars(args))))
    except ValueError as exc:
        parser.exit(2, str(exc) + "\n")


if __name__ == "__main__":
    main()
