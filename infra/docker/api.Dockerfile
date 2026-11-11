# API image. Build context is the repo root: docker build -f infra/docker/api.Dockerfile .
# worker.Dockerfile and mcp.Dockerfile share every layer before CMD, so Docker builds them once.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    FASTEMBED_CACHE_PATH=/opt/fastembed

WORKDIR /app

# Dependencies first (cached until pyproject.toml changes), read from the pinned list.
COPY pyproject.toml ./
RUN python -c "import tomllib; print(chr(10).join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt

COPY . .

# Fresh clone rule: data/processed is git-ignored, so generate GigSim data at build time.
# Bake the embedding and reranker models so the first request does not download anything.
RUN python -m gigsim.generate \
    && python -c "from rag.index.embed import _model; from rag.index.rerank import _encoder; _model(); print('baked reranker', _encoder()[1])" \
    && mkdir -p /var/lib/gigbid

ENV CHECKPOINT_DB=/var/lib/gigbid/checkpoints.sqlite \
    USERS_DB=/var/lib/gigbid/users.sqlite \
    AUDIT_LOG_PATH=/var/lib/gigbid/audit.jsonl

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
