# All services in one image (web, API, worker, three MCP servers, GigSim). For single container hosts.
# Build context is the repo root:
#   docker build -f infra/docker/all-in-one.Dockerfile -t gigbid-all .
#   docker run --rm -p 7860:7860 -e REVIEWER_PASSWORD=change-me gigbid-all
# Hugging Face Spaces use infra/hf_space/Dockerfile, which clones the repo and then does the same.

# == web: Next.js standalone build ==
FROM node:24-slim AS web-build
WORKDIR /web
ENV API_URL=http://127.0.0.1:8000 \
    NEXT_TELEMETRY_DISABLED=1
COPY apps/web/package.json apps/web/package-lock.json ./
# npm ci fails on Linux with a lockfile written on Windows (missing nested picomatch), so use install
RUN npm install -g npm@11.6.1 && npm install --no-audit --no-fund
COPY apps/web ./
RUN mkdir -p public && npm run build

# == runtime: Python 3.13 plus the node binary (the standalone server only needs node) ==
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    FASTEMBED_CACHE_PATH=/opt/fastembed \
    STATE_DIR=/home/user/state \
    PORT=7860

COPY --from=web-build /usr/local/bin/node /usr/local/bin/node

RUN useradd -m -u 1000 user
WORKDIR /app

COPY pyproject.toml ./
RUN python -c "import tomllib; print(chr(10).join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt

COPY . .
COPY --from=web-build /web/.next/standalone /app/web
COPY --from=web-build /web/.next/static /app/web/.next/static
COPY --from=web-build /web/public /app/web/public

# Generate GigSim data at build time, bake the embedding and reranker models, fix line endings.
RUN python -m gigsim.generate \
    && python -c "from rag.index.embed import _model; from rag.index.rerank import _encoder; _model(); print('baked reranker', _encoder()[1])" \
    && sed -i 's/\r$//' infra/docker/start.sh \
    && chmod +x infra/docker/start.sh \
    && mkdir -p /home/user/state \
    && chown -R user:user /app /opt/fastembed /home/user

USER user
EXPOSE 7860
CMD ["bash", "infra/docker/start.sh"]
