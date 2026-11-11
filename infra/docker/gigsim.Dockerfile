# GigSim simulator image (small: it only needs FastAPI). State is in memory and regenerates from
# the seed on boot. Build context is the repo root: docker build -f infra/docker/gigsim.Dockerfile .
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY pyproject.toml ./
RUN python -c "import tomllib; d=tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']; print(chr(10).join(x for x in d if x.split('==')[0].split('[')[0] in ('fastapi','uvicorn','pydantic','pyyaml')))" > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt

COPY gigsim ./gigsim
COPY data/policy_pack ./data/policy_pack
COPY evals/datasets ./evals/datasets

RUN python -m gigsim.generate

EXPOSE 9000
CMD ["python", "-m", "uvicorn", "gigsim.app:app", "--host", "0.0.0.0", "--port", "9000"]
