# Hugging Face Docker Space. This file and README.md are the ONLY files in the Space repo.
# It clones the public GigBid repo at a pinned commit, so a redeploy is: bump GIGBID_COMMIT, push.
# Secrets (JWT_SECRET, TOKEN_ENCRYPTION_KEY, MARKETPLACE_MCP_TOKEN, WORKSPACE_MCP_TOKEN,
# REVIEWER_EMAIL, REVIEWER_PASSWORD, REVIEWER_PERSONA, DATABASE_URL, REDIS_URL, GROQ_API_KEY,
# LANGSMITH_API_KEY) are set in the Space settings and arrive as environment variables at run time.
# Keep both ARGs in sync with the Space "Variables" if you build the same file elsewhere.
ARG GIGBID_REPO=https://github.com/mrayyan6/gigbid
ARG GIGBID_COMMIT=main

# == source: clone at the pinned commit ==
FROM python:3.13-slim AS src
ARG GIGBID_REPO
ARG GIGBID_COMMIT
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN git clone "$GIGBID_REPO" /src && cd /src && git checkout "$GIGBID_COMMIT" && rm -rf .git

# == web: Next.js standalone build ==
FROM node:20-slim AS web-build
WORKDIR /web
ENV API_URL=http://127.0.0.1:8000 \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=src /src/apps/web/package.json /src/apps/web/package-lock.json ./
RUN npm install -g npm@11.6.1 && npm ci
COPY --from=src /src/apps/web ./
RUN mkdir -p public && npm run build

# == runtime ==
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

COPY --from=src /src/pyproject.toml ./
RUN python -c "import tomllib; print(chr(10).join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt

COPY --from=src /src/ ./
COPY --from=web-build /web/.next/standalone /app/web
COPY --from=web-build /web/.next/static /app/web/.next/static
COPY --from=web-build /web/public /app/web/public

RUN python -m gigsim.generate \
    && python -c "from rag.index.embed import _model; from rag.index.rerank import _encoder; _model(); print('baked reranker', _encoder()[1])" \
    && sed -i 's/\r$//' infra/docker/start.sh \
    && chmod +x infra/docker/start.sh \
    && mkdir -p /home/user/state \
    && chown -R user:user /app /opt/fastembed /home/user

USER user
EXPOSE 7860
CMD ["bash", "infra/docker/start.sh"]
