"""Infrastructure persistence probe, not an AI demo. Never inserts into user tables."""
import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

import chromadb
from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.db import connect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["seed", "verify"])
    args = parser.parse_args()
    settings = Settings()
    marker = settings.documents_dir / ".persistence-probe.json"
    client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
    if args.action == "seed":
        value = uuid4().hex
        name = "cc_persistence_probe_" + value[:12]
        with connect(settings) as conn:
            conn.execute(sql.SQL("CREATE TABLE {} (marker text PRIMARY KEY)").format(sql.Identifier(name)))
            conn.execute(sql.SQL("INSERT INTO {} VALUES (%s)").format(sql.Identifier(name)), (value,))
        collection = client.create_collection(name=name, embedding_function=None)
        collection.add(ids=[value], embeddings=[[1.0, 0.0, 0.0]], documents=["Synthetic storage probe; not patient data or a model embedding."])
        marker.write_text(json.dumps({"value": value, "name": name}))
        print("SEEDED: isolated DB row, private file and Chroma storage probe (not AI).")
    else:
        info = json.loads(marker.read_text())
        name, value = info["name"], info["value"]
        if not name.startswith("cc_persistence_probe_") or len(value) != 32:
            raise ValueError("Invalid probe metadata")
        with connect(settings) as conn:
            row = conn.execute(sql.SQL("SELECT marker FROM {} WHERE marker=%s").format(sql.Identifier(name)), (value,)).fetchone()
            assert row and row["marker"] == value
        collection = client.get_collection(name, embedding_function=None)
        assert collection.get(ids=[value])["ids"] == [value]
        assert collection.query(query_embeddings=[[1.0, 0.0, 0.0]], n_results=1)["ids"][0] == [value]
        print("VERIFIED: PostgreSQL row, private file and Chroma index survived restart; similarity query works.")


if __name__ == "__main__":
    main()
