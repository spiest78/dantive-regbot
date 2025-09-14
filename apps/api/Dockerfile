FROM python:3.11-slim

WORKDIR /app
RUN apt-get update && apt-get install -y curl build-essential && rm -rf /var/lib/apt/lists/*

COPY apps/api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
RUN pip install --no-cache-dir pypdf

# Code is bind-mounted by compose at /workspace; this image only needs deps.
CMD ["bash", "-lc", "uvicorn main:app --host 0.0.0.0 --port 8000"]