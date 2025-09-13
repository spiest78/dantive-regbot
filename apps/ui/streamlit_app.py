import os, requests, streamlit as st

API_URL = os.getenv("API_URL", "http://api:8000")

st.set_page_config(page_title="Dantive RegBot", layout="wide")
st.title("Dantive — Regulatory RAG (skeleton)")

with st.expander("Health", expanded=False):
    if st.button("Ping API /health"):
        try:
            r = requests.get(f"{API_URL}/health", timeout=3)
            st.json(r.json())
        except Exception as e:
            st.error(e)

st.subheader("Chat (runtime model select)")

model = st.selectbox("Model", ["mistral:7b-instruct", "llama3:8b-instruct"], index=0)
prompt = st.text_area("Prompt", "Summarize REACH Article 57 criteria in one sentence.")
temp = st.slider("Temperature", 0.0, 2.0, 0.2, 0.1)
top_p = st.slider("Top-p", 0.0, 1.0, 0.9, 0.05)
max_tokens = st.number_input("Max tokens (optional)", min_value=0, value=0, step=50)

if st.button("Ask"):
    payload = {
        "prompt": prompt,
        "model": model,
        "temperature": temp,
        "top_p": top_p
    }
    if max_tokens and max_tokens > 0:
        payload["max_tokens"] = int(max_tokens)
    try:
        r = requests.post(f"{API_URL}/ask", json=payload, timeout=180)
        r.raise_for_status()
        data = r.json()
        st.write(f"**Model**: {data.get('model')}")
        st.write(data.get("output", ""))
    except Exception as e:
        st.error(e)