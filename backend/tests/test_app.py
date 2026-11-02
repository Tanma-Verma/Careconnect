import io
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.db import connect
from app.main import create_app
from app.provider import Provider, ProviderError
from app.rag import Vectors
from app.security import COOKIE, digest

HEADERS = {"X-Requested-With": "CareConnect", "Origin": "http://testserver"}
PASSWORD = "Synthetic-Test-Password-2026!"
REPORT = b"SYNTHETIC MEDICAL REPORT. Patient demo alpha. Blood pressure was 122/80 mmHg on 1 November 2026. Follow up with the clinician in two weeks."


def provider_transport(request):
    body = json.loads(request.content)
    if request.url.path.endswith("/embeddings"):
        # Isolated provider fixture only; production has no local/fake embedding mode.
        vectors = [[1.0, 0.0, 0.0] if "blood" in text.lower() else [0.0, 1.0, 0.0] for text in body["input"]]
        return httpx.Response(200, json={"data": [{"index": i, "embedding": v} for i, v in enumerate(vectors)]})
    evidence = json.loads(body["messages"][1]["content"])["evidence"]
    assert evidence and "122/80" in evidence[0]["text"]
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
        "answer": "The report records blood pressure of 122/80 mmHg [1]. Discuss interpretation with your clinician.",
        "sources": [1], "insufficient_evidence": False,
    })}}]})


@pytest.fixture
def client(settings):
    initial_pipeline = settings.pipeline
    provider = Provider(settings, httpx.Client(transport=httpx.MockTransport(provider_transport)))
    app = create_app(settings, provider=provider)
    with TestClient(app, headers=HEADERS) as client:
        with connect(settings) as conn:
            conn.execute("DELETE FROM cc_login_attempts")
        yield client
        vector_client = app.state.vectors.client
        if vector_client is not None:
            names = {collection.name for collection in vector_client.list_collections()}
            for pipeline in {initial_pipeline, settings.pipeline}:
                name = "careconnect-" + pipeline
                if name in names:
                    vector_client.delete_collection(name)


def register(client):
    email = uuid4().hex + "@example.test"
    response = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD, "role": "PATIENT"})
    assert response.status_code == 201, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return email, response


def upload(client, data=REPORT, name="synthetic.txt", media_type="text/plain"):
    return client.post("/api/v1/documents", files={"file": (name, data, media_type)})


def test_auth_sessions_csrf_roles(client, settings):
    assert client.get("/api/v1/documents").status_code == 401
    assert client.post("/api/v1/ai/chat", json={"message": "hello"}).status_code == 401
    for role in ["ADMIN", "PRACTITIONER"]:
        assert client.post("/api/v1/auth/register", json={"email": "blocked@example.test", "password": PASSWORD, "role": role}).status_code == 422
    email, response = register(client)
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    user_id = response.json()["user"]["id"]
    session = client.cookies[COOKIE]
    with connect(settings) as conn:
        user = conn.execute("SELECT password_hash FROM cc_users WHERE id=%s", (user_id,)).fetchone()
        assert PASSWORD not in user["password_hash"] and user["password_hash"].startswith("$argon2id$")
        assert conn.execute("SELECT 1 FROM cc_sessions WHERE token_hash=%s", (digest(session),)).fetchone()
    assert client.get("/api/v1/auth/me").json()["user"]["email"] == email
    csrf = client.headers.pop("X-CSRF-Token")
    assert client.post("/api/v1/auth/logout").status_code == 403
    client.headers["X-CSRF-Token"] = csrf
    assert client.post("/api/v1/auth/logout", headers={"Origin": "https://evil.test"}).status_code == 403
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401
    client.cookies.set(COOKIE, session)
    assert client.get("/api/v1/auth/me").status_code == 401
    client.cookies.clear()
    assert client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password-123"}).status_code == 401
    login = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    assert client.get("/api/v1/audit").status_code == 200
    assert client.get("/api/v1/appointments").status_code == 501
    assert client.get("/patient/").status_code == 200


def test_ingest_retrieve_cite_and_duplicate(client, settings):
    register(client)
    response = upload(client)
    assert response.status_code == 200, response.text
    doc = response.json()["document"]
    assert doc["state"] == "READY" and doc["chunk_count"] == 1
    assert (settings.documents_dir / doc["id"]).read_bytes() == REPORT
    assert upload(client).json()["duplicate"] is True
    collection = client.app.state.vectors.collection()
    assert collection.get(where={"document_id": doc["id"]})["ids"] == [doc["id"] + ":0"]
    response = client.post("/api/v1/ai/chat", json={"message": "What was my blood pressure?"})
    assert response.status_code == 200, response.text
    answer = response.json()
    assert set(answer) == {"answer", "citations", "request_id"}
    citation = answer["citations"][0]
    assert citation["document_id"] == doc["id"] and citation["page"] is None
    assert "122/80" in citation["excerpt"]
    assert client.get(citation["url"]).content == REPORT
    assert client.get("/api/v1/documents").json()["documents"][0]["state"] == "READY"


def test_patient_isolation_including_poisoned_vector_candidate(client, settings):
    _, auth_a = register(client)
    doc_a = upload(client).json()["document"]
    client.post("/api/v1/auth/logout")
    _, auth_b = register(client)
    assert auth_a.json()["user"]["id"] != auth_b.json()["user"]["id"]
    assert client.get("/api/v1/documents").json()["documents"] == []
    assert client.get(f"/api/v1/documents/{doc_a['id']}").status_code == 404
    assert client.get(f"/api/v1/documents/{doc_a['id']}/source").status_code == 404
    assert client.post("/api/v1/ai/chat", json={"message": "blood pressure", "owner_id": auth_a.json()["user"]["id"]}).status_code == 422
    own = upload(client, REPORT + b" This is patient beta's independent copy.").json()["document"]
    # Simulate compromised/misconfigured vector metadata. PG authorization must still reject A's chunk.
    client.app.state.vectors.search = lambda owner, embedding: [(doc_a["id"] + ":0", 0.0)]
    response = client.post("/api/v1/ai/chat", json={"message": "blood pressure"})
    assert response.status_code == 200 and response.json()["citations"] == []
    assert "122/80" not in response.json()["answer"]
    assert own["id"] != doc_a["id"]


@pytest.mark.parametrize("name,data,media,status", [
    ("bad.exe", b"hello", "application/octet-stream", 415),
    ("empty.txt", b"", "text/plain", 422),
    ("binary.txt", b"bad\x00text", "text/plain", 422),
    ("latin.txt", b"\xff\xfe", "text/plain", 422),
    ("fake.pdf", b"not a PDF", "application/pdf", 415),
    ("broken.pdf", b"%PDF-1.7\nbroken", "application/pdf", 422),
    ("mismatch.txt", b"%PDF-1.7", "text/plain", 415),
    ("huge.txt", b"x" * (10 * 1024 * 1024 + 1), "text/plain", 413),
    ("long.txt", b"x" * 100001, "text/plain", 422),
])
def test_upload_validation(client, name, data, media, status):
    register(client)
    response = upload(client, data, name, media)
    assert response.status_code == status, response.text
    assert client.get("/api/v1/documents").json()["documents"] == []


def test_pdf_pages_and_overlap(client):
    register(client)
    buffer = io.BytesIO()
    pdf = PdfWriter()
    for text in ["SYNTHETIC report page one. Blood pressure 122/80 mmHg.",
                 "SYNTHETIC report page two. Clinician follow-up in two weeks."]:
        page = pdf.add_blank_page(width=612, height=792)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 30 700 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = stream
    pdf.write(buffer)
    response = upload(client, buffer.getvalue(), "report.pdf", "application/pdf")
    assert response.status_code == 200, response.text
    doc = response.json()["document"]
    assert doc["pages"] == 2 and doc["chunk_count"] == 2
    answer = client.post("/api/v1/ai/chat", json={"message": "What was the blood pressure?"}).json()
    assert answer["citations"][0]["page"] == 1
    assert answer["citations"][0]["url"].endswith("#page=1")
    from app.documents import chunk_pages
    chunks = chunk_pages([(1, "word " * 1000)], "test")
    assert len(chunks) > 2 and chunks[0]["text"][-200:] in chunks[1]["text"]


def test_provider_failure_failed_state_retry(client):
    register(client)
    provider = client.app.state.provider
    original = provider.client
    provider.client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(401, text="secret-provider-body")))
    response = upload(client)
    assert response.status_code == 502
    doc = response.json()["document"]
    assert doc["state"] == "FAILED" and "401" in doc["error"] and "secret-provider-body" not in response.text
    provider.client.close()
    provider.client = original
    retry = upload(client)
    assert retry.status_code == 200 and retry.json()["document"]["id"] == doc["id"]
    assert retry.json()["document"]["state"] == "READY"


def test_insufficient_and_invalid_citations(client):
    register(client)
    empty = client.post("/api/v1/ai/chat", json={"message": "blood pressure"})
    assert empty.status_code == 200 and empty.json()["citations"] == []
    assert upload(client).status_code == 200
    unrelated = client.post("/api/v1/ai/chat", json={"message": "What is the weather?"})
    assert unrelated.status_code == 200 and unrelated.json()["citations"] == []
    client.app.state.provider.generate = lambda question, evidence: {"answer": "Invented [99]", "sources": [99], "insufficient_evidence": False}
    assert client.post("/api/v1/ai/chat", json={"message": "blood pressure"}).status_code == 502
    client.app.state.provider.generate = lambda question, evidence: {"answer": "Not found", "sources": [], "insufficient_evidence": True}
    assert client.post("/api/v1/ai/chat", json={"message": "blood pressure"}).json()["citations"] == []
    client.app.state.provider.generate = lambda question, evidence: {"answer": "Not found [1]", "sources": [], "insufficient_evidence": True}
    assert client.post("/api/v1/ai/chat", json={"message": "blood pressure"}).status_code == 502
    client.app.state.provider.generate = lambda question, evidence: {"answer": "Not found", "sources": [1], "insufficient_evidence": True}
    assert client.post("/api/v1/ai/chat", json={"message": "blood pressure"}).status_code == 502


def test_missing_configuration_and_timeout(client):
    register(client)
    client.app.state.provider.settings.embedding_key = ""
    response = upload(client)
    assert response.status_code == 502 and "EMBEDDING_API_KEY" in response.text
    client.app.state.provider.settings.embedding_key = "test-only"
    assert upload(client).status_code == 200
    def timeout(request):
        raise httpx.ReadTimeout("private details")
    client.app.state.provider.client = httpx.Client(transport=httpx.MockTransport(timeout))
    response = client.post("/api/v1/ai/chat", json={"message": "blood pressure"})
    assert response.status_code == 502 and "timed out" in response.text and "private details" not in response.text


def test_provider_rejects_bad_payloads(settings):
    for data in [{"data": []}, {"data": [{"index": 0, "embedding": [0, 0]}]}, {"data": [{"index": 3, "embedding": [1, 2]}]}]:
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=data))) as http:
            with pytest.raises(ProviderError):
                Provider(settings, http).embed(["hello"])
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "not JSON"}}]}))) as http:
        with pytest.raises(ProviderError):
            Provider(settings, http).generate("question", [{"text": "data"}])


def test_expiration_rotation_and_request_bounds(client, settings):
    email, auth = register(client)
    old_token = client.cookies[COOKIE]
    login = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200
    with connect(settings) as conn:
        assert not conn.execute("SELECT 1 FROM cc_sessions WHERE token_hash=%s", (digest(old_token),)).fetchone()
        conn.execute("UPDATE cc_sessions SET expires_at=now()-interval '1 second' WHERE user_id=%s", (auth.json()["user"]["id"],))
    assert client.get("/api/v1/documents").status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": email, "password": "x" * 20000}).status_code == 413
    assert client.post("/api/v1/auth/login", headers={"Sec-Fetch-Site": "cross-site"}, json={"email": email, "password": PASSWORD}).status_code == 403
    assert client.get("/.env").status_code == 404
    assert client.get("/backend/app/schema.sql").status_code == 404
    assert client.get("/CareConnect_Prototype.html").status_code == 404


def test_restart_preserves_session_source_vectors_and_ready_state(client, settings):
    email, _ = register(client)
    doc = upload(client).json()["document"]
    token = client.cookies[COOKIE]
    from app.db import initialize
    initialize(settings)  # startup schema is idempotent
    provider = Provider(settings, httpx.Client(transport=httpx.MockTransport(provider_transport)))
    with TestClient(create_app(settings, provider=provider), headers=HEADERS) as restarted:
        restarted.cookies.set(COOKIE, token)
        me = restarted.get("/api/v1/auth/me")
        assert me.status_code == 200 and me.json()["user"]["email"] == email
        restarted.headers["X-CSRF-Token"] = me.json()["csrf_token"]
        assert restarted.get(f"/api/v1/documents/{doc['id']}").json()["document"]["state"] == "READY"
        assert restarted.get(f"/api/v1/documents/{doc['id']}/source").content == REPORT
        result = restarted.post("/api/v1/ai/chat", json={"message": "blood pressure"})
        assert result.status_code == 200 and result.json()["citations"]


def test_llm_failure_does_not_fabricate_success(client):
    register(client)
    assert upload(client).status_code == 200
    client.app.state.provider.settings.llm_key = ""
    response = client.post("/api/v1/ai/chat", json={"message": "blood pressure"})
    assert response.status_code == 502 and "LLM_API_KEY" in response.text
    assert "answer" not in response.json()


def test_embedding_configuration_changes_require_reingestion(client):
    register(client)
    doc = upload(client).json()["document"]
    client.app.state.settings.embedding_model += "-new-version"
    result = client.post("/api/v1/ai/chat", json={"message": "blood pressure"})
    assert result.status_code == 200 and result.json()["citations"] == []
    retry = upload(client)
    assert retry.status_code == 200 and not retry.json()["duplicate"]
    assert retry.json()["document"]["id"] == doc["id"]
    assert client.post("/api/v1/ai/chat", json={"message": "blood pressure"}).json()["citations"]


def test_processing_state_concurrent_retry_and_recovery(client, settings):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    register(client)
    started, finish = Event(), Event()
    provider = client.app.state.provider
    embed = provider.embed
    def paused(texts):
        started.set()
        assert finish.wait(10)
        return embed(texts)
    provider.embed = paused
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(upload, client)
        try:
            assert started.wait(10)
            assert client.get("/api/v1/documents").json()["documents"][0]["state"] == "PROCESSING"
            assert upload(client).status_code == 409
        finally:
            finish.set()
        assert future.result().json()["document"]["state"] == "READY"
    provider.embed = embed
    doc = client.get("/api/v1/documents").json()["documents"][0]
    with connect(settings) as conn:
        conn.execute("UPDATE cc_documents SET state='PROCESSING' WHERE id=%s", (doc["id"],))
    next_provider = Provider(settings, httpx.Client(transport=httpx.MockTransport(provider_transport)))
    with TestClient(create_app(settings, provider=next_provider), headers=HEADERS):
        with connect(settings) as conn:
            row = conn.execute("SELECT state,error FROM cc_documents WHERE id=%s", (doc["id"],)).fetchone()
            assert row["state"] == "FAILED" and "interrupted" in row["error"]


def test_encrypted_and_scanned_pdf_rejected(client):
    register(client)
    for encrypted in (False, True):
        pdf = PdfWriter()
        pdf.add_blank_page(width=612, height=792)
        if encrypted:
            pdf.encrypt("test-only")
        buffer = io.BytesIO()
        pdf.write(buffer)
        response = upload(client, buffer.getvalue(), "unreadable.pdf", "application/pdf")
        assert response.status_code == 422
        assert ("Encrypted" if encrypted else "No text") in response.text


def test_request_timings_are_complete_and_content_free(client, caplog):
    email, _ = register(client)
    assert upload(client).status_code == 200
    response = client.post("/api/v1/ai/chat", json={"message": "blood pressure SECRET_QUESTION_MARKER"})
    assert response.status_code == 200
    records = [record.message for record in caplog.records if record.name == "careconnect.performance"]
    metrics = json.loads(records[-1].split("rag_timing ", 1)[1])
    assert metrics["request_id"] == response.json()["request_id"]
    assert metrics["status"] == 200 and metrics["total_ms"] > 0
    assert set(metrics["stages_ms"]) == {"authentication", "question_embedding", "chroma_retrieval",
        "ownership_validation", "context_construction", "generation", "json_citation_validation", "audit"}
    assert all(value > 0 for value in metrics["stages_ms"].values())
    assert metrics["total_ms"] >= sum(metrics["stages_ms"].values())
    assert len(metrics["provider_attempts"]) == 2
    for private in [email, PASSWORD, "SECRET_QUESTION_MARKER", "122/80", "test-only", "synthetic.txt"]:
        assert private not in records[-1]
