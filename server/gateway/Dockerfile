# Gateway: auth, TLS, routing. Build context: the repo root.
FROM python:3.11-slim-bookworm
RUN pip install --no-cache-dir fastapi==0.139.0 uvicorn==0.51.0 httpx==0.28.1
COPY server/catalog.tsv /opt/sow/catalog.tsv
COPY server/gateway/sow_gateway /opt/sow/sow_gateway
WORKDIR /opt/sow
ENV PYTHONUNBUFFERED=1
EXPOSE 8765
CMD ["python", "-m", "sow_gateway"]
