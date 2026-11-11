.PHONY: dev worker test eval seed lint demo
PY=.venv/Scripts/python
seed:
	$(PY) -m gigsim.generate
dev:
	$(PY) -m uvicorn gigsim.app:app --port 9000 &
	$(PY) -m apps.api
worker:
	.venv/Scripts/arq worker.main.WorkerSettings
test:
	$(PY) -m pytest -q
eval:
	$(PY) -m evals.runners.rag_eval
	$(PY) -m evals.runners.decision_eval
lint:
	.venv/Scripts/ruff check .
