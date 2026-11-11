# GigBid running notes
- Repo: D:\gigbid (not OneDrive, to avoid sync churn). Brief PDF: OneDrive A2 folder.
- Due 2026-11-12 23:59 PKT. Extension chosen: X2 Proposal experiments.
- Docker Desktop installed via winget (may need restart/WSL setup).
- Done: empty required directory layout, config.yaml, .env.example, git init.
- Next: pyproject, Portfolio MCP server, marketplace port, once kit arrives wire GigSim.
- 2026-11-11: Starter kit v0.1 zip arrived but is scaffold only, no gigsim. Instructor says we build the simulator ourselves from Kaggle datasets plus labelled synthetic data (6 dataset slugs listed in scripts/fetch_datasets.py).
- Added scripts/fetch_datasets.py (needs Kaggle token in ~/.kaggle/kaggle.json), docs/DATA_CARD.md draft, gitignore for data/raw and zips.
- Open: user adds Kaggle token and runs the fetch; then preprocessing, synthetic generators, simulator in gigsim/, merge useful kit files (marketplace_port, handoffs tests, Makefile, pyproject).
