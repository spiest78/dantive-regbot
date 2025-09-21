# apps/ui/streamlit_app.py
import os
import json
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://api:8000")

st.set_page_config(page_title="Dantive RegBot", layout="wide")
st.title("Dantive — Regulatory RAG")

# ---------------- Health ----------------
with st.expander("Health", expanded=False):
    if st.button("Ping API /health"):
        try:
            r = requests.get(f"{API_URL}/health", timeout=5)
            r.raise_for_status()
            st.json(r.json())
        except Exception as e:
            st.error(f"Health check failed: {e}")

# ---------------- Mode + RAG knobs ----------------
st.subheader("Mode & RAG knobs")

m1, m2, m3, m4, m5 = st.columns([1.3, 1, 1, 1.2, 1.5])
with m1:
    answer_mode = st.selectbox(
        "Answer mode",
        ["Relaxed (best-effort allowed)", "Strict (sources only)"],
        index=0,
        help="Relaxed = attempt an answer even with thin context; Strict = refuse unless sources suffice.",
    )
with m2:
    top_k = st.slider("top_k", 1, 20, 8)
with m3:
    min_score = st.slider("min_score (client filter)", 0.0, 1.0, 0.0, 0.01)
with m4:
    show_raw = st.toggle("Show raw retrieval", value=True)
with m5:
    use_stream = st.toggle("Stream", value=False, help="Use /ask_stream_rag")

# This flag is what we *request* from the server. Server may ignore if it doesn't support runtime override.
force_answer_wanted = answer_mode.startswith("Relaxed")

st.caption(
    "Note: The server ultimately decides strict vs relaxed. "
    "We send your preference to the API (header X-RAG-Force-Answer and query param force_answer). "
    "The banner below the answer shows what the server actually did."
)

# ---------------- Ask (RAG) ----------------
st.subheader("Ask (RAG)")

c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    prompt = st.text_area(
        "Prompt",
        "What does REACH Article 57(f) say about substances of equivalent concern?",
        height=120
    )
with c2:
    model = st.selectbox("Model", ["mistral:7b-instruct", "llama3:8b-instruct"], index=0)
with c3:
    temperature = st.slider("Temperature", 0.0, 1.0, 0.1, 0.05)

row = st.columns([1, 1, 1])
timeout_s = row[1].number_input("Timeout (s)", min_value=30, max_value=1800, value=120, step=30)
ask_btn = row[2].button("Ask")

def render_server_mode_banner(res: dict):
    policy = res.get("policy", {}) or {}
    answered = policy.get("answered", True)
    reason = policy.get("reason", "")
    req_mode = "Relaxed" if force_answer_wanted else "Strict"

    # Infer server behavior from policy.reason
    if reason in ("best_effort_with_uncertainty",):
        srv_mode = "Relaxed"
    elif reason in ("sufficient_retrieval",):
        # Could be strict or relaxed; if relaxed we still had enough context.
        srv_mode = "Relaxed" if force_answer_wanted else "Strict"
    elif reason in ("no_relevant_documents_above_threshold",):
        srv_mode = "Strict"
    else:
        srv_mode = "Unknown"

    if srv_mode == "Strict":
        st.info(f"Requested: **{req_mode}** · Server acted as: **Strict** (reason: `{reason}`)")
    elif srv_mode == "Relaxed":
        st.success(f"Requested: **{req_mode}** · Server acted as: **Relaxed** (reason: `{reason}`)")
    else:
        st.warning(f"Requested: **{req_mode}** · Server behavior: **Unknown** (reason: `{reason}`)")

def render_answer_payload(res: dict):
    render_server_mode_banner(res)

    st.markdown(f"**Model:** `{res.get('model','')}`")
    st.write("### Answer")
    st.write(res.get("answer", ""))

    st.write("### Citations")
    cits = res.get("citations", [])
    if not cits:
        st.caption("No citations.")
    else:
        shown = [c for c in cits if float(c.get("score", 0)) >= float(min_score)]
        if not shown:
            st.caption(f"No citations above client filter: min_score={min_score:.2f}")
        for c in shown:
            st.markdown(
                f"[^{c.get('ref_num')}] **{c.get('source_name','')}** "
                f"(chunk {c.get('chunk_index')}, score {c.get('score',0):.3f})  \n"
                f"`{c.get('source_path','')}`"
            )
            ex = c.get("excerpt")
            if ex:
                with st.expander(f"Excerpt [^{c.get('ref_num')}]"):
                    st.write(ex)

    st.write("### Retrieval (API)")
    retr = res.get("retrieval", {})
    if retr:
        retr_view = dict(retr)
        if not show_raw and "raw" in retr_view:
            retr_view["raw"] = f"<{len(retr_view['raw'] or [])} hits hidden>"
        st.json(retr_view)

def api_headers():
    # Informative header—supported by future API versions; ignored safely otherwise.
    return {
        "X-RAG-Force-Answer": "true" if force_answer_wanted else "false",
        "Content-Type": "application/json",
    }

def api_params():
    # Informative query param—safe no-op if server ignores it.
    return {"force_answer": "true" if force_answer_wanted else "false"}

if ask_btn:
    if not prompt.strip():
        st.warning("Please enter a prompt.")
    else:
        try:
            if use_stream:
                with st.spinner("Thinking…"):
                    r = requests.post(
                        f"{API_URL}/ask_stream_rag",
                        params=api_params(),
                        headers=api_headers(),
                        json={"prompt": prompt, "model": model, "temperature": temperature},
                        stream=True,
                        timeout=(10, int(timeout_s)),
                    )
                    if r.status_code == 404:
                        st.error("`/ask_stream_rag` not found on API. Disable Stream or update API.")
                    else:
                        r.raise_for_status()
                        ph = st.empty()
                        buf = []
                        for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
                            if not chunk:
                                continue
                            buf.append(chunk)
                            ph.markdown("".join(buf))
            else:
                with st.spinner("Thinking…"):
                    r = requests.post(
                        f"{API_URL}/ask",
                        params=api_params(),
                        headers=api_headers(),
                        json={"prompt": prompt, "model": model, "temperature": temperature},
                        timeout=int(timeout_s),
                    )
                    r.raise_for_status()
                    res = r.json()
                render_answer_payload(res)
        except Exception as e:
            st.error(f"Request error: {e}")

st.caption("In strict server mode, answers are given ONLY from retrieved sources; otherwise the server replies “I don't know based on the provided sources.” In relaxed mode, the server may answer with uncertainty if context is thin.")

# ---------------- Retrieve-only probe ----------------
st.subheader("Retrieve-only probe (/debug/retrieve)")
rq1, rq2, rq3 = st.columns([2, 1, 1])
with rq1:
    probe_q = st.text_input("Query", "REACH Article 57 criteria")
with rq2:
    probe_k = st.slider("probe top_k", 1, 20, 10)
with rq3:
    run_probe = st.button("Run probe")

if run_probe:
    try:
        r = requests.get(
            f"{API_URL}/debug/retrieve",
            params={"qtext": probe_q, "top_k": int(probe_k)},
            timeout=60
        )
        if r.status_code == 404:
            st.error("`/debug/retrieve` not found on API. Update API to the latest drop-in.")
        else:
            r.raise_for_status()
            data = r.json()
            st.write("### Retrieval results")
            results = data.get("results", [])
            if min_score > 0.0:
                results = [h for h in results if float(h.get("score", 0)) >= float(min_score)]
            st.json({**data, "results": results})
    except Exception as e:
        st.error(e)

# ---------------- Inspect Qdrant ----------------
st.subheader("Inspect Qdrant collection")
i1, i2 = st.columns([1, 3])
with i1:
    sample_n = st.number_input("Sample points", min_value=1, max_value=100, value=5)
    filename_filter = st.text_input("Filter by source_name (optional)", value="")
run_inspect = st.button("Show sample")

if run_inspect:
    try:
        payload = {"limit": int(sample_n), "with_payload": True, "with_vectors": False}
        if filename_filter.strip():
            payload["filter"] = {
                "must": [{"key": "source_name", "match": {"value": filename_filter.strip()}}]
            }
        r = requests.post(f"{API_URL}/qdrant_scroll", json=payload, timeout=30)
        if r.status_code == 404:
            st.error("`/qdrant_scroll` not found on API. Add the helper endpoint in the API.")
        else:
            r.raise_for_status()
            st.write("### Sample payloads")
            st.json(r.json())
    except Exception as e:
        st.error(e)

# ---------------- Per-file counts ----------------
st.subheader("Per-file counts (top 20)")
if st.button("Compute counts"):
    try:
        r = requests.post(f"{API_URL}/qdrant_counts_by_source", json={}, timeout=120)
        if r.status_code == 404:
            st.error("`/qdrant_counts_by_source` not found on API.")
        else:
            r.raise_for_status()
            st.dataframe(r.json())
    except Exception as e:
        st.error(e)
