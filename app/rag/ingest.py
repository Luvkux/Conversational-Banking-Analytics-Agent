"""
Build the ChromaDB vector store with two collections:
  - schema_docs : one chunk per table description
  - few_shots   : one chunk per curated NL-SQL example

Run: python -m app.rag.ingest
Idempotent — wipes and rebuilds both collections each time.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings
from openai import OpenAI

from app.config import settings
from app.rag.schema_docs import all_docs


# -------------------------------------------------------------
_oai = OpenAI(api_key=settings.openai_api_key)


def embed(texts: list[str], batch_size: int = 100) -> list[list[float]]:
    """Embed a list of texts with the configured OpenAI model."""
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        chunk = texts[i : i + batch_size]
        resp = _oai.embeddings.create(
            model=settings.openai_embedding_model,
            input=chunk,
        )
        out.extend([d.embedding for d in resp.data])
    return out


def _client() -> chromadb.PersistentClient:
    Path(settings.chroma_dir).mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(
        path=settings.chroma_dir,
        settings=ChromaSettings(anonymized_telemetry=False),
    )


# -------------------------------------------------------------
def ingest_schema_docs(client: chromadb.PersistentClient) -> int:
    name = "schema_docs"
    if name in [c.name for c in client.list_collections()]:
        client.delete_collection(name)
    coll = client.create_collection(name, metadata={"hnsw:space": "cosine"})

    docs = all_docs()
    texts = [d.doc.strip() for d in docs]
    ids = [d.table for d in docs]
    metas = [{"table": d.table} for d in docs]

    print(f"Embedding {len(texts)} schema docs...")
    embeddings = embed(texts)
    coll.add(ids=ids, documents=texts, metadatas=metas, embeddings=embeddings)
    return len(texts)


def ingest_few_shots(client: chromadb.PersistentClient) -> int:
    name = "few_shots"
    if name in [c.name for c in client.list_collections()]:
        client.delete_collection(name)
    coll = client.create_collection(name, metadata={"hnsw:space": "cosine"})

    path = Path(__file__).parent / "few_shots.json"
    examples = json.loads(path.read_text())

    # We embed the question text (that's what the user query will match against);
    # we keep the SQL in metadata so we can reconstruct the prompt examples.
    ids = [e["id"] for e in examples]
    texts = [e["question"] for e in examples]
    metas = [{"sql": e["sql"], "category": e["category"]} for e in examples]

    print(f"Embedding {len(texts)} few-shot questions...")
    embeddings = embed(texts)
    coll.add(ids=ids, documents=texts, metadatas=metas, embeddings=embeddings)
    return len(texts)


# -------------------------------------------------------------
def main():
    t0 = time.time()
    client = _client()

    n_schema = ingest_schema_docs(client)
    n_fs = ingest_few_shots(client)

    print(f"\nIngest complete in {time.time()-t0:.1f}s")
    print(f"  schema_docs: {n_schema}")
    print(f"  few_shots:   {n_fs}")
    print(f"  storage:     {settings.chroma_dir}")


if __name__ == "__main__":
    main()
