import re
from uuid import uuid4

import chromadb
from chromadb.config import Settings as ChromaSettings

from .db import audit, connect
from .provider import ProviderError
from .timing import measure, timed

INSUFFICIENT = "I could not find enough relevant evidence in your ready documents to answer this question. Upload a relevant report or ask about a documented finding. A healthcare professional can help interpret your results."


class Vectors:
    def __init__(self, settings):
        self.settings = settings
        self.client = None

    def collection(self):
        if self.client is None:
            self.client = chromadb.HttpClient(host=self.settings.chroma_host, port=self.settings.chroma_port,
                                             settings=ChromaSettings(anonymized_telemetry=False))
        return self.client.get_or_create_collection(
            name="careconnect-" + self.settings.pipeline, embedding_function=None,
            configuration={"hnsw": {"space": "cosine"}},
        )

    def heartbeat(self):
        self.collection()
        self.client.heartbeat()

    def index(self, owner_id, document_id, chunks, provider):
        collection = self.collection()
        # A retry replaces this document's vectors; IDs remain deterministic.
        collection.delete(where={"$and": [{"owner_id": owner_id}, {"document_id": document_id}]})
        for offset in range(0, len(chunks), 32):
            batch = chunks[offset:offset + 32]
            embeddings = provider.embed([chunk["text"] for chunk in batch])
            collection.upsert(
                ids=[chunk["id"] for chunk in batch], embeddings=embeddings,
                documents=[chunk["text"] for chunk in batch],
                metadatas=[{"owner_id": owner_id, "document_id": document_id, "chunk_id": chunk["id"],
                            "page": chunk["page"] or 0} for chunk in batch],
            )

    def search(self, owner_id, embedding):
        result = self.collection().query(query_embeddings=[embedding], n_results=8,
                                         where={"owner_id": owner_id}, include=["distances"])
        return list(zip(result["ids"][0], result["distances"][0]))


def answer_question(settings, provider, vectors, owner_id, question, authorization_check=None):
    # Delegated access is checked with fresh PostgreSQL state, never vector metadata.
    if authorization_check:
        authorization_check()
    request_id = str(uuid4())
    def insufficient():
        return {"answer": INSUFFICIENT, "citations": [], "request_id": request_id}

    with measure("ownership_validation"), connect(settings) as conn:
        ready = conn.execute("SELECT id FROM cc_documents WHERE owner_id=%s AND state='READY' AND pipeline=%s",
                             (owner_id, settings.pipeline)).fetchall()
    if not ready:
        return insufficient()
    with measure("question_embedding"):
        embedding = provider.embed([question])[0]
    with measure("chroma_retrieval"):
        candidates = vectors.search(owner_id, embedding)
    evidence, citations = [], []
    authorized = []
    with measure("ownership_validation"), connect(settings) as conn:
        for chunk_id, distance in candidates:
            if distance is None or not -0.00001 <= distance <= settings.max_distance:
                continue
            # PostgreSQL is authoritative for ownership, readiness, page and exact source text.
            row = conn.execute(
                "SELECT c.id,c.page,c.source_text,d.id AS document_id,d.filename,d.pages "
                "FROM cc_chunks c JOIN cc_documents d ON d.id=c.document_id "
                "WHERE c.id=%s AND d.owner_id=%s AND d.state='READY' AND d.pipeline=%s",
                (chunk_id, owner_id, settings.pipeline),
            ).fetchone()
            if not row or (row["page"] is not None and not 1 <= row["page"] <= row["pages"]):
                continue
            authorized.append(row)
            if len(authorized) == 5:
                break
    with measure("context_construction"):
        for row in authorized:
            label = len(evidence) + 1
            evidence.append({"label": label, "title": row["filename"], "page": row["page"], "text": row["source_text"]})
            url = f"/api/v1/documents/{row['document_id']}/source"
            if row["page"]:
                url += f"#page={row['page']}"
            citations.append({"label": label, "document_id": row["document_id"], "chunk_id": row["id"],
                              "title": row["filename"], "page": row["page"], "excerpt": row["source_text"], "url": url})
    if not evidence:
        return insufficient()
    if authorization_check:
        authorization_check()
    result = provider.generate(question, evidence)
    if authorization_check:
        authorization_check()
    response = _validated_response(result, citations, request_id)
    if response["citations"]:
        with measure("audit"), connect(settings) as conn:
            audit(conn, owner_id, "AI_CHAT")
    return response


@timed("json_citation_validation")
def _validated_response(result, citations, request_id):
    sources = result["sources"]
    markers = [int(i) for i in re.findall(r"\[(\d+)\]", result["answer"])]
    if result["insufficient_evidence"]:
        if sources or markers:
            raise ProviderError("LLM returned conflicting evidence/citation fields. Please retry.")
        return {"answer": INSUFFICIENT, "citations": [], "request_id": request_id}
    if not sources or set(sources) != set(markers) or any(i < 1 or i > len(citations) for i in sources):
        raise ProviderError("LLM returned unsupported citations. No answer was accepted; please retry.")
    return {"answer": result["answer"], "citations": [citations[i - 1] for i in sorted(set(sources))], "request_id": request_id}
