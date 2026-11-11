# Arq worker image. Same layers as api.Dockerfile, different command.
# Build context is the repo root: docker build -f infra/docker/worker.Dockerfile .
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    FASTEMBED_CACHE_PATH=/opt/fastembed

WORKDIR /app

COPY pyproject.toml ./
RUN python -c "import tomllib; print(chr(10).join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt

COPY . .

RUN python -m gigsim.generate \
    && python -c "from rag.index.embed import _model; from rag.index.rerank import _encoder; _model(); print('baked reranker', _encoder()[1])" \
    && mkdir -p /var/lib/gigbid

ENV CHECKPOINT_DB=/var/lib/gigbid/checkpoints.sqlite \
    USERS_DB=/var/lib/gigbid/users.sqlite \
    AUDIT_LOG_PATH=/var/lib/gigbid/audit.jsonl

CMD ["arq", "worker.main.WorkerSettings"]
