# One image for the three MCP servers, the command picks which one runs:
#   python -m mcp_servers.marketplace.server --http   (MARKETPLACE_MCP_TOKEN, port 9100)
#   python -m mcp_servers.portfolio.server --http     (FASTMCP_HOST, FASTMCP_PORT, port 9101)
#   python -m mcp_servers.workspace.server --http     (WORKSPACE_MCP_TOKEN, port 9102)
# Build context is the repo root: docker build -f infra/docker/mcp.Dockerfile .
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

ENV AUDIT_LOG_PATH=/var/lib/gigbid/audit.jsonl \
    MCP_HOST=0.0.0.0

CMD ["python", "-m", "mcp_servers.marketplace.server", "--http"]
