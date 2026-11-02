"""ERP integration tests: real isolated PostgreSQL/Chroma, mocked external HTTP only."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.db import connect
from app.main import create_app
from app.provider import Provider, ProviderError
from scripts.index_demo import candidate_documents, index_one, progress
from scripts.seed_demo import (DEMO_DOCTOR_EMAIL, DEMO_PATIENT_EMAIL,
                               UNRELATED_DOCTOR_EMAIL, report_content, seed, stable_id)

PASSWORD = "Synthetic-ERP-Isolated-Test-2026!"
HEADERS = {"X-Requested-With": "CareConnect", "Origin": "http://testserver"}
PATIENT = stable_id("patient", 0)
DOCTOR = stable_id("doctor", 0)
DOCTOR_BASE = f"/api/v1/doctor/patients/{PATIENT}"


@pytest.fixture
def erp(settings, monkeypatch):
    # Stable seed IDs need their own database, not the suite's shared session DB.
    original_dsn = settings.database_url
    database = "cc_erp_test_" + uuid4().hex[:12]
    with psycopg.connect(original_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    settings.database_url = make_conninfo(original_dsn, dbname=database)
    monkeypatch.setenv("DEMO_SEED_ENABLED", "true")
    monkeypatch.setenv("DEMO_PASSWORD", PASSWORD)
    calls = []

    def provider_http(request):
        calls.append(request.url.path)
        body = json.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [
                {"index": i, "embedding": [1.0, 0.0, 0.0]} for i, _ in enumerate(body["input"])]})
        evidence = json.loads(body["messages"][1]["content"])["evidence"]
        assert evidence and all(isinstance(item["text"], str) and item["text"] for item in evidence)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "answer": "The synthetic report records observations [1]. Review them with your clinician.",
            "sources": [1], "insufficient_evidence": False,
        })}}]})

    provider = Provider(settings, httpx.Client(transport=httpx.MockTransport(provider_http)))
    app = create_app(settings, provider=provider)
    try:
        with TestClient(app, headers=HEADERS) as client:
            client.erp_calls = calls
            yield client, settings
    finally:
        if app.state.vectors.client is not None:
            app.state.vectors.client.delete_collection("careconnect-" + settings.pipeline)
        with psycopg.connect(original_dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database)))


@pytest.fixture
def seeded(erp):
    client, settings = erp
    seed(settings, doctors=4, patients=4, reports=8, appointments=6, notes=4)
    return client, settings


def login(client, email=DEMO_PATIENT_EMAIL):
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response.json()["user"]


def indexed_demo(client, settings):
    row = candidate_documents(settings)[0]
    assert row["owner_id"] == PATIENT
    assert index_one(settings, row, client.app.state.provider, client.app.state.vectors)
    return row


def test_default_seed_counts_relations_and_idempotency(erp, monkeypatch):
    client, settings = erp
    seed(settings)
    expected = {"cc_doctor_profiles": 100, "cc_patient_profiles": 100, "cc_documents": 100,
                "cc_appointments": 150, "cc_assignments": 124, "cc_notes": 60}
    with connect(settings) as conn:
        for table, count in expected.items():
            assert conn.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(table))).fetchone()["n"] == count
        assert conn.execute("SELECT count(*) AS n FROM cc_documents WHERE state='READY'").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM cc_chunks").fetchone()["n"] == 0
        docs = conn.execute("SELECT * FROM cc_documents").fetchall()
        for doc in docs:
            data = (settings.documents_dir / doc["id"]).read_bytes()
            assert b"FICTIONAL DEMONSTRATION" in data
            assert hashlib.sha256(data).hexdigest() == doc["sha256"]
        assert not conn.execute("SELECT 1 FROM cc_notes n LEFT JOIN cc_assignments a ON a.doctor_id=n.doctor_id AND a.patient_id=n.patient_id WHERE a.patient_id IS NULL").fetchone()
        assert not conn.execute("SELECT 1 FROM cc_observations o JOIN cc_documents d ON d.id=o.document_id WHERE o.patient_id<>d.owner_id").fetchone()
        old_password = conn.execute("SELECT password_hash FROM cc_users WHERE id=%s", (PATIENT,)).fetchone()["password_hash"]
        conn.execute("UPDATE cc_consents SET records=false,ai=false WHERE doctor_id=%s AND patient_id=%s", (DOCTOR, PATIENT))
        conn.execute("UPDATE cc_appointments SET status='CANCELLED' WHERE id=%s", (stable_id("appointment", 0),))
    monkeypatch.setenv("DEMO_PASSWORD", "Different-Synthetic-Password-2026!")
    seed(settings)
    with connect(settings) as conn:
        for table, count in expected.items():
            assert conn.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(table))).fetchone()["n"] == count
        assert conn.execute("SELECT password_hash FROM cc_users WHERE id=%s", (PATIENT,)).fetchone()["password_hash"] == old_password
        assert not conn.execute("SELECT records FROM cc_consents WHERE doctor_id=%s AND patient_id=%s", (DOCTOR, PATIENT)).fetchone()["records"]
        assert conn.execute("SELECT status FROM cc_appointments WHERE id=%s", (stable_id("appointment", 0),)).fetchone()["status"] == "CANCELLED"


def test_seed_is_explicitly_enabled_and_reports_deterministic(erp, monkeypatch):
    _, settings = erp
    monkeypatch.delenv("DEMO_SEED_ENABLED")
    with pytest.raises(ValueError, match="disabled"):
        seed(settings)
    first = report_content(4, 0)
    assert first == report_content(4, 0)
    assert b"124/80 mmHg" in first[0] and b"2026-11-01" in first[0]
    assert b"Fasting blood glucose: 102 mg/dL" in first[0]
    assert b"Hemoglobin: 14.6 g/dL" in first[0]


def test_roles_authentication_dashboards_and_private_directory(seeded):
    client, _ = seeded
    assert client.get("/api/v1/doctor/dashboard").status_code == 401
    assert login(client)["role"] == "PATIENT"
    patient = client.get("/api/v1/patient/dashboard").json()
    assert patient["stats"]["reports"] == 5 and patient["stats"]["indexed_reports"] == 0
    assert patient["stats"]["assigned_doctors"] == 1
    directory = client.get("/api/v1/patient/doctors").json()["doctors"]
    assert len(directory) == 4 and all("password_hash" not in row and "email" not in row for row in directory)
    assert client.get("/api/v1/doctor/dashboard").status_code == 403
    assert login(client, DEMO_DOCTOR_EMAIL)["role"] == "PRACTITIONER"
    dashboard = client.get("/api/v1/doctor/dashboard").json()
    assert dashboard["stats"]["assigned_patients"] == 1 and dashboard["stats"]["recent_reports"] == 5
    assert client.get("/api/v1/doctor/profile").json()["profile"]["is_demo"] is True
    for path in ["/api/v1/patient/dashboard", "/api/v1/documents", "/api/v1/records"]:
        assert client.get(path).status_code == 403
    assert client.post("/api/v1/ai/chat", json={"message": "blood pressure"}).status_code == 403
    assert client.get("/api/v1/audit").status_code == 200
    assert client.get("/doctor/").status_code == 200
    for role in ["ADMIN", "PRACTITIONER"]:
        assert client.post("/api/v1/auth/register", json={"email": "blocked@example.test", "password": PASSWORD, "role": role}).status_code == 422


def test_assigned_scope_and_search_do_not_expose_other_patients(seeded):
    client, settings = seeded
    login(client, DEMO_DOCTOR_EMAIL)
    rows = client.get("/api/v1/doctor/patients").json()["patients"]
    assert [row["id"] for row in rows] == [PATIENT]
    assert client.get("/api/v1/doctor/patients", params={"q": "' OR 1=1 --"}).json()["patients"] == []
    assert client.get(f"/api/v1/doctor/patients/{stable_id('patient', 1)}").status_code == 403
    login(client, UNRELATED_DOCTOR_EMAIL)
    assert client.get(DOCTOR_BASE).status_code == 403
    assert client.get(DOCTOR_BASE + "/documents").status_code == 403
    assert client.post(DOCTOR_BASE + "/ai/chat", json={"message": "blood pressure"}).status_code == 403
    with connect(settings) as conn:
        conn.execute("INSERT INTO cc_assignments(doctor_id,patient_id) VALUES (%s,%s)", (stable_id("doctor", 1), PATIENT))
    assert client.get(DOCTOR_BASE).status_code == 403  # assignment alone is insufficient


def test_consent_grant_revoke_and_distinct_scopes(seeded):
    client, _ = seeded
    login(client)
    assert client.put(f"/api/v1/patient/consents/{stable_id('doctor', 1)}", json={"records": True, "clinical": True, "ai": True}).status_code == 403
    assert client.put(f"/api/v1/patient/consents/{DOCTOR}", json={"records": False, "clinical": True, "ai": True}).status_code == 422
    endpoint = f"/api/v1/patient/consents/{DOCTOR}"
    assert client.put(endpoint, json={"records": True, "clinical": False, "ai": False}).status_code == 200
    login(client, DEMO_DOCTOR_EMAIL)
    assert client.get(DOCTOR_BASE + "/documents").status_code == 200
    assert client.get(DOCTOR_BASE + "/history").status_code == 403
    assert client.post(DOCTOR_BASE + "/notes", json={"content": "Synthetic note"}).status_code == 403
    assert client.post(DOCTOR_BASE + "/ai/chat", json={"message": "blood pressure"}).status_code == 403
    login(client)
    assert client.put(endpoint, json={"records": False, "clinical": False, "ai": False}).status_code == 200
    login(client, DEMO_DOCTOR_EMAIL)
    assert client.get("/api/v1/doctor/patients").json()["patients"] == []
    assert client.get(DOCTOR_BASE + "/documents").status_code == 403


def test_notes_appointments_csrf_and_patient_history(seeded):
    client, settings = seeded
    login(client)
    when = (datetime.now(timezone.utc) + timedelta(days=20)).isoformat()
    body = {"doctor_id": DOCTOR, "scheduled_at": when, "reason": "Synthetic follow-up"}
    created = client.post("/api/v1/patient/appointments", json=body)
    assert created.status_code == 201
    appointment = created.json()["appointment"]
    assert client.post("/api/v1/patient/appointments", json=body).status_code == 409
    assert client.post("/api/v1/patient/appointments", json={**body, "patient_id": stable_id("patient", 1)}).status_code == 422
    login(client, "patient002@careconnect.example.test")
    assert client.patch(f"/api/v1/patient/appointments/{appointment['id']}", json={"status": "CANCELLED"}).status_code == 404
    login(client, DEMO_DOCTOR_EMAIL)
    endpoint = f"/api/v1/doctor/appointments/{appointment['id']}"
    assert client.patch(endpoint, json={"status": "CONFIRMED"}).status_code == 200
    assert client.patch(endpoint, json={"status": "COMPLETED"}).status_code == 200
    assert client.patch(endpoint, json={"status": "CONFIRMED"}).status_code == 409
    token = client.headers.pop("X-CSRF-Token")
    assert client.post(DOCTOR_BASE + "/notes", json={"content": "SYNTHETIC note"}).status_code == 403
    client.headers["X-CSRF-Token"] = token
    note = "SYNTHETIC note containing literal <script>alert('fixture')</script> text."
    response = client.post(DOCTOR_BASE + "/notes", json={"content": note, "appointment_id": appointment["id"]})
    assert response.status_code == 201 and response.json()["note"]["content"] == note
    assert client.post(DOCTOR_BASE + "/notes", json={"content": "SYNTHETIC", "appointment_id": stable_id("appointment", 1)}).status_code == 404
    login(client)
    assert client.patch(f"/api/v1/patient/appointments/{appointment['id']}", json={"status": "CANCELLED"}).status_code == 409
    history = client.get("/api/v1/patient/history").json()
    assert any(row["content"] == note for row in history["notes"])
    assert len(history["observations"]) == 35 and len(history["documents"]) == 5


def test_real_storage_index_retry_and_hash_check(seeded):
    client, settings = seeded
    row = indexed_demo(client, settings)
    assert index_one(settings, row, client.app.state.provider, client.app.state.vectors) is False
    with connect(settings) as conn:
        saved = conn.execute("SELECT * FROM cc_documents WHERE id=%s", (row["id"],)).fetchone()
        count = conn.execute("SELECT count(*) AS n FROM cc_chunks WHERE document_id=%s", (row["id"],)).fetchone()["n"]
    assert saved["state"] == "READY" and saved["chunk_count"] == count
    assert len(client.app.state.vectors.collection().get(where={"document_id": row["id"]})["ids"]) == count
    pending = next(doc for doc in candidate_documents(settings) if doc["state"] != "READY")
    (settings.documents_dir / pending["id"]).write_bytes(b"SYNTHETIC altered fixture")
    with pytest.raises(ValueError, match="hash"):
        index_one(settings, pending, client.app.state.provider, client.app.state.vectors)
    assert progress(settings)["ready"] == 1


def test_doctor_rag_citations_and_cross_patient_vectors(seeded):
    client, settings = seeded
    row = indexed_demo(client, settings)
    login(client, DEMO_DOCTOR_EMAIL)
    response = client.post(DOCTOR_BASE + "/ai/chat", json={"message": "blood pressure"})
    assert response.status_code == 200, response.text
    citation = response.json()["citations"][0]
    assert citation["document_id"] == row["id"] and citation["url"].startswith(DOCTOR_BASE + "/documents/")
    assert client.get(citation["url"]).status_code == 200
    assert client.get(f"/api/v1/documents/{row['id']}/source").status_code == 403
    foreign = next(doc for doc in candidate_documents(settings) if doc["owner_id"] != PATIENT)
    index_one(settings, foreign, client.app.state.provider, client.app.state.vectors)
    client.app.state.vectors.search = lambda owner, embedding: [(foreign["id"] + ":0", 0.0)]
    bad = client.post(DOCTOR_BASE + "/ai/chat", json={"message": "blood pressure"})
    assert bad.status_code == 200 and bad.json()["citations"] == []
    assert client.get(DOCTOR_BASE + f"/documents/{foreign['id']}/source").status_code == 404
    login(client, UNRELATED_DOCTOR_EMAIL)
    assert client.get(citation["url"]).status_code == 403


@pytest.mark.parametrize("revocation_stage", ["embedding", "generation"])
def test_revocation_during_rag_blocks_response(seeded, revocation_stage):
    client, settings = seeded
    indexed_demo(client, settings)
    login(client, DEMO_DOCTOR_EMAIL)
    provider = client.app.state.provider
    original = provider.embed if revocation_stage == "embedding" else provider.generate

    def revoked(*args):
        result = original(*args)
        with connect(settings) as conn:
            conn.execute("UPDATE cc_consents SET records=false,ai=false WHERE doctor_id=%s AND patient_id=%s", (DOCTOR, PATIENT))
        return result

    if revocation_stage == "embedding":
        provider.embed = revoked
    else:
        provider.generate = revoked
    response = client.post(DOCTOR_BASE + "/ai/chat", json={"message": "blood pressure"})
    assert response.status_code == 403 and "answer" not in response.json()
    if revocation_stage == "embedding":
        assert not any(path.endswith("/chat/completions") for path in client.erp_calls)


def test_provider_failure_never_marks_seeded_report_ready(seeded):
    client, settings = seeded
    provider = client.app.state.provider
    provider.client.close()
    provider.client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(429, text="PRIVATE_PROVIDER_DETAIL")))
    row = candidate_documents(settings)[0]
    with pytest.raises(ProviderError, match="429"):
        index_one(settings, row, provider, client.app.state.vectors)
    with connect(settings) as conn:
        failed = conn.execute("SELECT state,error FROM cc_documents WHERE id=%s", (row["id"],)).fetchone()
    assert failed["state"] == "FAILED" and "PRIVATE_PROVIDER_DETAIL" not in failed["error"]
    assert progress(settings)["ready"] == 0


def test_erp_restart_retains_session_data_and_source(seeded):
    client, settings = seeded
    row = indexed_demo(client, settings)
    login(client, DEMO_DOCTOR_EMAIL)
    from app.security import COOKIE
    token = client.cookies[COOKIE]
    # Same mock HTTP boundary, fresh application startup; storage is retained.
    provider = Provider(settings, httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500))))
    with TestClient(create_app(settings, provider=provider), headers=HEADERS) as restarted:
        restarted.cookies.set(COOKIE, token)
        assert restarted.get("/api/v1/auth/me").status_code == 200
        assert restarted.get("/api/v1/doctor/dashboard").json()["stats"]["assigned_patients"] == 1
        source = restarted.get(DOCTOR_BASE + f"/documents/{row['id']}/source")
        assert source.status_code == 200 and hashlib.sha256(source.content).hexdigest() == row["sha256"]
        assert restarted.app.state.vectors.collection().get(where={"document_id": row["id"]})["ids"]
