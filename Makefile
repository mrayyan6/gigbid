.PHONY: dev worker test eval eval-llm tables graphs seed lint demo
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
	$(PY) -m evals.runners.ablation
	$(PY) -m evals.runners.tool_design
	$(PY) -m evals.runners.smoke_eval
	$(PY) scripts/render_tables.py

# LLM runs: set GIGBID_PROFILE=open_hosted (Groq) or open (local Ollama). Slow and rate limited.
eval-llm:
	$(PY) -m evals.runners.injection_eval
	$(PY) -m evals.runners.proposal_eval
	$(PY) -m evals.runners.x2_experiment
	$(PY) -m evals.runners.arch_compare
	$(PY) scripts/render_tables.py

tables:
	$(PY) scripts/render_tables.py

graphs:
	$(PY) scripts/render_graphs.py
lint:
	.venv/Scripts/ruff check .
