# apps/ui/streamlit_app.py
import os
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://api:8000")

st.set_page_config(page_title="Dantive RegBot", layout="wide")
st.title("Dantive — Regulatory RAG (skeleton)")

# ---------------- Health ----------------
with st.expander("Health", expanded=False):
    if st.button("Ping API /health"):
        try:
            r = requests.get(f"{API_URL}/health", timeout=5)
            r.raise_for_status()
            st.json(r.json())
        except Exception as e:
            st.error(f"Health check failed: {e}")

# ---------------- Controls ----------------
st.subheader("Chat (runtime model select)")

cols = st.columns([1, 1, 1, 1])
with cols[0]:
    model = st.selectbox("Model", ["mistral:7b-instruct", "llama3:8b-instruct"], index=0)
with cols[1]:
    temp = st.slider("Temperature", 0.0, 2.0, 0.2, 0.1)
with cols[2]:
    top_p = st.slider("Top-p", 0.0, 1.0, 0.9, 0.05)
with cols[3]:
    max_tokens = st.number_input("Max tokens", min_value=64, max_value=2048, value=400, step=64)

prompt = st.text_area("Prompt", "Summarize REACH Article 57 criteria in one sentence.", height=120)

opt_cols = st.columns([1, 1, 4])
with opt_cols[0]:
    stream_mode = st.toggle("Stream answer", value=True)
with opt_cols[1]:
    timeout_s = st.number_input("Timeout (s)", min_value=60, max_value=1800, value=600, step=60)

# ---------------- Ask ----------------
if st.button("Ask"):
    if not prompt.strip():
        st.warning("Please enter a prompt.")
    else:
        # payload compatible with your FastAPI models
        payload = {
            "prompt": prompt,
            "model": model,
            "temperature": float(temp),
            "top_p": float(top_p),
            "max_tokens": int(max_tokens),
        }

        if stream_mode:
            # ---- Streaming via /ask_stream ----
            with st.spinner("Thinking…"):
                try:
                    r = requests.post(
                        f"{API_URL}/ask_stream",
                        json=payload,
                        stream=True,
                        timeout=(10, int(timeout_s)),   # (connect, read)
                    )
                    r.raise_for_status()
                    # live render
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
            # ---- Non-streaming via /ask ----
            with st.spinner("Thinking…"):
                try:
                    r = requests.post(
                        f"{API_URL}/ask",
                        json=payload,
                        timeout=int(timeout_s),
                    )
                    r.raise_for_status()
                    data = r.json()
                    st.write(f"**Model**: {data.get('model','')}")
                    st.markdown(data.get("output", ""))
                except Exception as e:
                    st.error(f"Request error: {e}")

# ---------------- Small UX niceties ----------------
st.caption(
    "Tip: If long answers time out, lower **Max tokens** or enable **Stream answer**. "
    "Timeout can be adjusted above."
)