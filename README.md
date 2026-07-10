# LLM-Powered Banking Analytics Agent (Text-to-SQL)

Natural-language → SQL agent over a 12-table banking warehouse (~200K rows, 80K+ transactions). Schema-aware RAG with curated few-shots, AST-level SQL safety guards, hallucination detection, and retry. FastAPI + Streamlit.

## Stack
Python · FastAPI · PostgreSQL 16 · LangChain · OpenAI GPT-4 · ChromaDB · Streamlit · sqlglot

## Quickstart

```bash
# 1. Setup
cp .env.example .env                        # fill in OPENAI_API_KEY
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Database
docker compose up -d                        # starts postgres on :5433
psql postgresql://banking:banking@localhost:5433/banking -f app/db/schema.sql
python -m app.db.seed                       # ~30s, generates 200K+ rows

# 3. Build the vector store (Phase 2 — coming next)
python -m app.rag.ingest

# 4. Run the API + UI
uvicorn app.main:app --reload --port 8000
streamlit run ui/streamlit_app.py           # in another shell
```

## Layout
```
app/
  agent/      # LLM, retriever, prompt, runner, safety
  db/         # schema.sql, seed.py, connection
  rag/        # schema_docs, few_shots, ingest
  api/        # FastAPI routes
ui/           # Streamlit
evals/        # gold-set runner + results
```

## Verifiable claims (post-eval)
- ✅ 12 tables, 80K+ transactions
- 🧪 SQL accuracy: baseline vs RAG-augmented (run `python -m evals.runner`)
- 🧪 Invalid query rate: guards on vs off
- 🧪 Latency: p50/p95 measured at `/query`
