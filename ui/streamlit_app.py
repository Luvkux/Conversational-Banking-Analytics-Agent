"""
Streamlit UI for the Banking Analytics Agent.

Run:
    streamlit run ui/streamlit_app.py

Talks to the FastAPI backend at http://localhost:8000 by default.
Override with API_BASE env var.
"""
from __future__ import annotations

import os

import httpx
import pandas as pd
import streamlit as st


API_BASE = os.environ.get("API_BASE", "http://localhost:8000")
TIMEOUT = 60.0


# -------------------------------------------------------------
# API helpers
# -------------------------------------------------------------
def call_api(question: str, mode: str, use_cache: bool) -> dict:
    payload = {"question": question, "mode": mode, "use_cache": use_cache}
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.post(f"{API_BASE}/query", json=payload)
        r.raise_for_status()
        return r.json()


def fetch_schema() -> list[dict]:
    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(f"{API_BASE}/schema")
            r.raise_for_status()
            return r.json().get("tables", [])
    except Exception:
        return []


def fetch_health() -> dict:
    try:
        with httpx.Client(timeout=5) as client:
            return client.get(f"{API_BASE}/health").json()
    except Exception as e:
        return {"status": f"unreachable: {e}"}


# -------------------------------------------------------------
# Renderers
# -------------------------------------------------------------
def render_explainability(expl: dict) -> None:
    with st.expander("🧠 Explainability", expanded=False):
        ca, cb = st.columns(2)
        with ca:
            st.markdown("**Retrieved tables**")
            tabs = expl.get("retrieved_tables") or []
            st.write(", ".join(tabs) if tabs else "_none_")
        with cb:
            st.markdown("**Few-shot examples used**")
            exs = expl.get("retrieved_examples") or []
            if exs:
                for e in exs:
                    st.caption(f"• {e}")
            else:
                st.caption("_none_")

        attempts = expl.get("attempts") or []
        if attempts:
            st.markdown("**Attempts**")
            st.dataframe(pd.DataFrame(attempts), hide_index=True, use_container_width=True)

        bits = [
            f"mode: `{expl.get('mode', 'rag')}`",
            f"cache_hit: {'yes' if expl.get('cache_hit') else 'no'}",
            f"hallucination_caught: {'⚠️ yes' if expl.get('hallucination_detected') else '✓ no'}",
        ]
        st.caption(" · ".join(bits))


def render_response(resp: dict) -> None:
    expl = resp.get("explainability", {})

    if not resp.get("success"):
        st.error(f"**{resp.get('error_kind') or 'error'}**: "
                 f"{resp.get('error') or 'no SQL produced'}")
        render_explainability(expl)
        return

    sql = resp.get("sql") or ""
    rows = resp.get("rows") or []
    n = resp.get("row_count", 0)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Latency", f"{resp.get('latency_ms', 0)} ms")
    m2.metric("Rows", f"{n}{' (truncated)' if resp.get('truncated') else ''}")
    m3.metric("Attempts", expl.get("attempt_count", 1))
    m4.metric("Cache hit", "yes" if expl.get("cache_hit") else "no")

    with st.expander("🔍 Generated SQL", expanded=False):
        st.code(sql, language="sql")

    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("Query executed successfully — 0 rows returned.")

    render_explainability(expl)


# -------------------------------------------------------------
# Page setup
# -------------------------------------------------------------
st.set_page_config(page_title="Banking Analytics Agent", page_icon="🏦", layout="wide")

if "history" not in st.session_state:
    st.session_state.history = []
if "settings" not in st.session_state:
    st.session_state.settings = {"mode": "rag", "use_cache": True}


# Sidebar
with st.sidebar:
    st.header("⚙️ Settings")
    st.session_state.settings["mode"] = st.radio(
        "Generation mode", ["rag", "baseline"], index=0,
        help="`rag` uses schema-aware retrieval + few-shots. "
             "`baseline` dumps the full schema (used for measuring RAG lift).",
    )
    st.session_state.settings["use_cache"] = st.checkbox(
        "Use cache", value=True,
        help="Cache the question → SQL mapping. SQL is still re-executed for fresh data.",
    )

    if st.button("Clear conversation"):
        st.session_state.history = []
        st.rerun()

    st.divider()
    st.header("🩺 Health")
    h = fetch_health()
    if h.get("status") == "ok":
        st.success(f"All systems operational · cache: {h.get('cache_size', 0)} entries")
    else:
        st.error(str(h))

    st.divider()
    with st.expander("📚 Warehouse schema", expanded=False):
        for t in fetch_schema():
            st.caption(f"**{t['table']}** ({len(t['columns'])} cols)")
            st.code(", ".join(t["columns"]), language="text")


# Main
st.title("🏦 Banking Analytics Agent")
st.caption("Natural-language → SQL over a 12-table banking warehouse")

# Render existing history
for entry in st.session_state.history:
    with st.chat_message("user"):
        st.write(entry["q"])
    with st.chat_message("assistant"):
        render_response(entry["response"])

# Input
q = st.chat_input("Ask a banking question — e.g. 'top branches by AUM' or 'conversion rate by campaign channel'")
if q:
    with st.chat_message("user"):
        st.write(q)
    with st.chat_message("assistant"):
        with st.spinner("Generating SQL and executing..."):
            try:
                resp = call_api(q, st.session_state.settings["mode"],
                                st.session_state.settings["use_cache"])
            except httpx.HTTPError as e:
                resp = {"success": False, "error": f"API error: {e}",
                        "error_kind": "api", "latency_ms": 0,
                        "explainability": {}}
        render_response(resp)
        st.session_state.history.append({"q": q, "response": resp})
