"""Resume sequential REAL indexing of seeded synthetic originals; no generated vectors."""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.db import audit, connect
from app.documents import chunk_pages, extract
from app.provider import Provider, ProviderError
from app.rag import Vectors
from scripts.seed_demo import require_enabled, stable_id


def candidate_documents(settings):
    # Only IDs in our deterministic seed namespace are eligible, not arbitrary patient uploads.
    seeded_ids = {stable_id("document", i) for i in range(10000)}
    with connect(settings) as conn:
        rows = conn.execute("SELECT d.* FROM cc_documents d JOIN cc_patient_profiles p ON p.user_id=d.owner_id WHERE p.is_demo=true ORDER BY (d.owner_id=%s) DESC,d.created_at,d.id", (stable_id("patient", 0),)).fetchall()
    return [row for row in rows if row["id"] in seeded_ids]


def progress(settings):
    rows = candidate_documents(settings)
    return {"total": len(rows), "ready": sum(row["state"] == "READY" and row["pipeline"] == settings.pipeline for row in rows),
            "processing": sum(row["state"] == "PROCESSING" for row in rows),
            "remaining": sum(row["state"] != "READY" or row["pipeline"] != settings.pipeline for row in rows),
            "demo_patient_ready": sum(row["owner_id"] == stable_id("patient", 0) and row["state"] == "READY" and row["pipeline"] == settings.pipeline for row in rows)}


def index_one(settings, row, provider, vectors):
    with connect(settings) as conn:
        locked = conn.execute("SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS locked", (row["owner_id"],)).fetchone()["locked"]
        if not locked:
            raise ProviderError("Another document for this demo patient is being processed. Retry later.")
        current = conn.execute("SELECT * FROM cc_documents WHERE id=%s AND owner_id=%s", (row["id"], row["owner_id"])).fetchone()
        if not current:
            raise ValueError("Synthetic document metadata is unavailable.")
        if current["state"] == "READY" and current["pipeline"] == settings.pipeline:
            return False
        original = (settings.documents_dir / row["id"]).read_bytes()
        if hashlib.sha256(original).hexdigest() != current["sha256"]:
            raise ValueError("Synthetic original hash does not match its saved metadata. Indexing refused.")
        pages, _ = extract(current["filename"], current["media_type"], original, settings)
        chunks = chunk_pages(pages, current["id"])
        conn.execute("UPDATE cc_documents SET state='PROCESSING',error=NULL,updated_at=now() WHERE id=%s", (row["id"],))
        conn.commit()
        try:
            vectors.index(row["owner_id"], row["id"], chunks, provider)
            actual = vectors.collection().get(ids=[chunk["id"] for chunk in chunks])["ids"]
            if set(actual) != {chunk["id"] for chunk in chunks}:
                raise ProviderError("Chroma did not retain all expected synthetic document chunks.")
            conn.execute("DELETE FROM cc_chunks WHERE document_id=%s", (row["id"],))
            with conn.cursor() as cursor:
                cursor.executemany("INSERT INTO cc_chunks(id,document_id,page,source_text) VALUES (%s,%s,%s,%s)",
                                   [(chunk["id"], row["id"], chunk["page"], chunk["text"]) for chunk in chunks])
            conn.execute("UPDATE cc_documents SET state='READY',error=NULL,pipeline=%s,chunk_count=%s,updated_at=now() WHERE id=%s", (settings.pipeline, len(chunks), row["id"]))
            audit(conn, row["owner_id"], "DEMO_DOCUMENT_INGEST")
            conn.commit()
            return True
        except Exception as exc:
            conn.rollback()
            safe_error = str(exc) if isinstance(exc, ProviderError) else "Synthetic document indexing failed. Check backend diagnostics and retry."
            conn.execute("UPDATE cc_documents SET state='FAILED',error=%s,updated_at=now() WHERE id=%s", (safe_error, row["id"]))
            conn.commit()
            raise


def run(settings, max_documents=100, max_seconds=600, delay=1.0, attempts=2, status_only=False):
    require_enabled()
    if max_documents < 1 or not 1 <= max_seconds <= 7200 or not 0 <= delay <= 60 or not 1 <= attempts <= 3:
        raise ValueError("Use positive max-documents, max-seconds 1-7200, delay 0-60, attempts 1-3.")
    if status_only:
        result = progress(settings)
        print(json.dumps({"progress": result}), flush=True)
        return result
    settings.validate()
    provider, vectors = Provider(settings), Vectors(settings)
    started = time.monotonic()
    indexed = failed = attempted = 0
    stop_reason = "completed"
    try:
        rows = candidate_documents(settings)
        for row in rows:
            if row["state"] == "READY" and row["pipeline"] == settings.pipeline:
                continue
            if attempted >= max_documents or time.monotonic() - started >= max_seconds:
                stop_reason = "configured_run_limit"
                break
            attempted += 1
            succeeded = False
            for attempt in range(attempts):
                try:
                    if index_one(settings, row, provider, vectors):
                        indexed += 1
                    succeeded = True
                    print(json.dumps({"event": "indexed", "document_id": row["id"], "attempt": attempt + 1}), flush=True)
                    break
                except Exception as exc:
                    safe_error = str(exc) if isinstance(exc, (ProviderError, ValueError)) else "Indexing operation failed (" + type(exc).__name__ + ")."
                    print(json.dumps({"event": "index_error", "document_id": row["id"], "attempt": attempt + 1, "error": safe_error}), flush=True)
                    if isinstance(exc, ProviderError) and any(code in str(exc) for code in ("HTTP 429", "HTTP 401", "HTTP 403", "HTTP 404", "HTTP 400", "must be configured")):
                        stop_reason = "provider_quota_auth_or_configuration"
                        break
                    if not isinstance(exc, ProviderError) or attempt + 1 == attempts:
                        break
                    if time.monotonic() - started + 2 >= max_seconds:
                        stop_reason = "configured_run_limit"
                        break
                    time.sleep(2)
            if not succeeded:
                failed += 1
            print(json.dumps({"progress": progress(settings)}), flush=True)
            if stop_reason != "completed":
                break
            if time.monotonic() - started + delay >= max_seconds:
                stop_reason = "configured_run_limit"
                break
            time.sleep(delay)
    finally:
        provider.close()
    result = {"indexed_this_run": indexed, "failed_this_run": failed, "attempted_this_run": attempted,
              "stop_reason": stop_reason, **progress(settings)}
    print(json.dumps({"summary": result}), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-documents", type=int, default=100)
    parser.add_argument("--max-seconds", type=float, default=600)
    parser.add_argument("--delay", type=float, default=1)
    parser.add_argument("--attempts", type=int, default=2)
    parser.add_argument("--status-only", action="store_true")
    args = parser.parse_args()
    try:
        run(Settings(), **vars(args))
    except ValueError as exc:
        parser.exit(2, str(exc) + "\n")


if __name__ == "__main__":
    main()
