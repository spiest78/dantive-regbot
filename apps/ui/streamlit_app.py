# apps/ui/streamlit_app.py
import os
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

# ---------------- Chat (STRICT RAG) ----------------
st.subheader("Ask (strict RAG — no hallucinations)")

c1, c2, c3 = st.columns([2, 1, 1])
with c1:
    prompt = st.text_area("Prompt", "What does REACH Article 57(f) say about substances of equivalent concern?", height=120)
with c2:
    model = st.selectbox("Model", ["mistral:7b-instruct", "llama3:8b-instruct"], index=0)
with c3:
    temperature = st.slider("Temperature", 0.0, 1.0, 0.1, 0.05)

col_btns = st.columns([1, 1])
use_stream = col_btns[0].toggle("Stream (strict)", value=False, help="Uses /ask_stream_rag if available")
timeout_s = col_btns[1].number_input("Timeout (s)", min_value=30, max_value=1800, value=120, step=30)

if st.button("Ask (strict)"):
    if not prompt.strip():
        st.warning("Please enter a prompt.")
    else:
        if use_stream:
            # Streaming STRICT endpoint (requires /ask_stream_rag on API)
            try:
                with st.spinner("Thinking…"):
                    r = requests.post(
                        f"{API_URL}/ask_stream_rag",
                        json={"prompt": prompt, "model": model},
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
            except Exception as e:
                st.error(f"Streaming error: {e}")
        else:
            # Non-streaming STRICT endpoint
            try:
                with st.spinner("Thinking…"):
                    r = requests.post(
                        f"{API_URL}/ask",
                        json={"prompt": prompt, "model": model},
                        timeout=int(timeout_s),
                    )
                    r.raise_for_status()
                    res = r.json()

                # Render strict response
                st.markdown(f"**Model:** `{res.get('model','')}`")
                st.write("### Answer")
                st.write(res.get("answer", ""))

                policy = res.get("policy", {})
                if not policy.get("answered", True):
                    st.warning("No relevant documents above the threshold. Answer withheld.")

                st.write("### Citations")
                cits = res.get("citations", [])
                if not cits:
                    st.caption("No citations.")
                else:
                    for c in cits:
                        st.markdown(
                            f"[^{c.get('ref_num')}] **{c.get('source_name','')}** "
                            f"(chunk {c.get('chunk_index')}, score {c.get('score',0):.3f})  \n"
                            f"`{c.get('source_path','')}`"
                        )
                        ex = c.get("excerpt")
                        if ex:
                            with st.expander(f"Excerpt [^{c.get('ref_num')}]"):
                                st.write(ex)

                st.write("### Retrieval")
                st.json(res.get("retrieval", {}))

            except Exception as e:
                st.error(f"Request error: {e}")

st.caption("Strict mode answers ONLY from retrieved sources; otherwise it says “I don't know based on the provided sources.”")

# ---------------- Inspect Qdrant ----------------
st.subheader("Inspect Qdrant collection")

i1, i2 = st.columns([1, 3])
with i1:
    sample_n = st.number_input("Sample points", min_value=1, max_value=100, value=5)
    filename_filter = st.text_input("Filter by source_name (optional)", value="")
run_inspect = st.button("Show sample")

if run_inspect:
    try:
        # Backend helper endpoint (see API patch below)
        payload = {"limit": int(sample_n), "with_payload": True, "with_vectors": False}
        if filename_filter.strip():
            payload["filter"] = {
                "must": [{"key": "source_name", "match": {"value": filename_filter.strip()}}]
            }
        r = requests.post(f"{API_URL}/qdrant_scroll", json=payload, timeout=30)
        if r.status_code == 404:
            st.error("`/qdrant_scroll` not found on API. Add the small helper endpoint in the API.")
        else:
            r.raise_for_status()
            data = r.json()
            st.write("### Sample payloads")
            st.json(data)
    except Exception as e:
        st.error(e)

# ---------------- (Optional) Per-file counts ----------------
st.subheader("Per-file counts (top 20)")
if st.button("Compute counts"):
    try:
        r = requests.post(f"{API_URL}/qdrant_counts_by_source", json={}, timeout=120)
        if r.status_code == 404:
            st.error("`/qdrant_counts_by_source` not found on API. Add the helper endpoint in the API.")
        else:
            r.raise_for_status()
            data = r.json()
            st.dataframe(data)
    except Exception as e:
        st.error(e)