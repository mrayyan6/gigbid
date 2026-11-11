"""Download the Kaggle datasets used to build GigSim data.

Usage:
    python scripts/fetch_datasets.py            # fetch all
    python scripts/fetch_datasets.py --list     # show datasets and status
    python scripts/fetch_datasets.py --only upwork_jobs_50k

Needs a Kaggle API token: put kaggle.json in ~/.kaggle/ (or set KAGGLE_USERNAME and
KAGGLE_KEY). Files land in data/raw/<name>/ (git-ignored). If a download fails, get the
zip manually from the URL and unzip it into that folder. Licences must be recorded in
docs/DATA_CARD.md after checking each dataset page.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"

DATASETS = {
    "upwork_jobs_50k": "asaniczka/upwork-job-postings-dataset-2024-50k-records",
    "upwork_jobs_200k": "asaniczka/all-jobs-on-upwork-200k-plus",
    "upwork_jobs_60k": "ahmedmyalo/upwork-freelance-jobs-60k",
    "freelance_contracts_1_3m": "asaniczka/freelance-contracts-dataset-1-3-million-entries",
    "freelancer_earnings_churn": "sarveshchhetri/freelancer-success-earnings-and-churn-prediction",
    "trial_1": "adityammantri/trial-1",
}


def has_credentials() -> bool:
    if os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY"):
        return True
    return (Path.home() / ".kaggle" / "kaggle.json").exists()


def status(name: str) -> str:
    d = RAW / name
    return "present" if d.exists() and any(d.iterdir()) else "missing"


def fetch(name: str, slug: str) -> bool:
    dest = RAW / name
    dest.mkdir(parents=True, exist_ok=True)
    cmd = ["kaggle", "datasets", "download", "-d", slug, "-p", str(dest), "--unzip"]
    print(f"[fetch] {name}: {' '.join(cmd)}")
    return subprocess.run(cmd).returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", nargs="*", choices=list(DATASETS))
    args = ap.parse_args()

    if args.list:
        for n, s in DATASETS.items():
            print(f"{n:28} {status(n):8} https://www.kaggle.com/datasets/{s}")
        return 0

    if not has_credentials():
        print("No Kaggle credentials. Put kaggle.json in ~/.kaggle/ or set KAGGLE_USERNAME and "
              "KAGGLE_KEY, then rerun.", file=sys.stderr)
        return 2
    if shutil.which("kaggle") is None:
        print("kaggle CLI not found. Run: pip install kaggle", file=sys.stderr)
        return 2

    failed = [n for n, s in DATASETS.items()
              if (not args.only or n in args.only) and not fetch(n, s)]
    if failed:
        print(f"Failed: {failed}. Download manually into data/raw/<name>/", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
